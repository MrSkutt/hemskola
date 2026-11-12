"""Säkerhetskopior av databasen.

* natt   – en per dygn (efter kl 03), de 14 senaste sparas.
* fore   – en precis innan appen startar med ny kod, så att en uppdatering alltid kan backas. De 5 senaste sparas.
* manuell – den du själv tar från admin. De 10 senaste sparas.

Kopiorna tas med SQLites egen backup-funktion, så de är hela och konsekventa även medan appen används. Varje kopia är
en enda fil som kontrollerats efteråt. Bilderna i media-mappen ingår inte i kopiorna (de ändras aldrig efter att de lagts
in), men finns med i zip-filen från full_zip()."""
import os
import re
import sqlite3
import tempfile
import threading
import time
import traceback
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from . import db as database

KEEP = {"natt": 14, "fore": 5, "manuell": 10}
KIND_LABELS = {"natt": "Nattlig", "fore": "Före uppdatering", "manuell": "Manuell"}
NAME_RE = re.compile(r"^hemskola-(natt|fore|manuell)-[A-Za-z0-9._-]+\.db$")
NIGHT_HOUR = 3                 # tidigast när nattkopian tas
STALE_AFTER = timedelta(hours=36)
CHECK_EVERY = 300              # sekunder mellan kontroller i bakgrundstråden
VERSION_FILE = ".senaste-version"
_stop = threading.Event()


def enabled() -> bool:
    return os.environ.get("BACKUPS", "1") != "0"


def backup_dir() -> Path:
    d = Path(os.environ.get("BACKUP_DIR") or Path(database.DB_PATH).parent / "backups")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _snapshot(dest: Path) -> None:
    """Skriver en konsekvent kopia av databasen till dest (atomiskt) och kontrollerar den."""
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(database.DB_PATH, timeout=30)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")     # en enda fil, utan -wal och -shm
        finally:
            dst.close()
    finally:
        src.close()
    chk = sqlite3.connect(tmp)
    try:
        result = chk.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        chk.close()
    if result != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Säkerhetskopian klarade inte kontrollen: {result}")
    os.replace(tmp, dest)


def make(kind: str = "manuell", now: datetime | None = None, label: str = "") -> Path:
    if kind not in KEEP:
        raise ValueError(kind)
    now = now or datetime.now()
    stamp = now.strftime("%Y-%m-%d") if kind == "natt" else now.strftime("%Y-%m-%d-%H%M%S")
    name = f"hemskola-{kind}-{stamp}{'-' + label if label else ''}.db"
    dest = backup_dir() / name
    _snapshot(dest)
    prune()
    return dest


def prune() -> None:
    """Behåller de senaste av varje slag. Namnen börjar med datum, så sorterade namn är sorterade i tid."""
    names = sorted((p.name for p in backup_dir().glob("hemskola-*.db") if NAME_RE.match(p.name)), reverse=True)
    for kind, keep in KEEP.items():
        for old in [n for n in names if n.startswith(f"hemskola-{kind}-")][keep:]:
            (backup_dir() / old).unlink(missing_ok=True)


def listing() -> list:
    """Alla kopior, nyast först."""
    out = []
    for p in backup_dir().glob("hemskola-*.db"):
        m = NAME_RE.match(p.name)
        if not m:
            continue
        st = p.stat()
        out.append({"name": p.name, "kind": m.group(1), "kind_label": KIND_LABELS[m.group(1)], "size": st.st_size,
                    "time": datetime.fromtimestamp(st.st_mtime)})
    return sorted(out, key=lambda b: b["time"], reverse=True)


def stale(now: datetime | None = None) -> bool:
    """Sant om det är dags att varna: kopior är på, men ingen har tagits på över 36 timmar."""
    if not enabled() or not Path(database.DB_PATH).exists():
        return False
    items = listing()
    return not items or (now or datetime.now()) - items[0]["time"] > STALE_AFTER


def _has_data() -> bool:
    """Finns det en databas med användare? En tom eller ny databas behöver ingen kopia."""
    if not Path(database.DB_PATH).exists():
        return False
    try:
        conn = sqlite3.connect(database.DB_PATH, timeout=10)
        try:
            return conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def nightly_due(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.hour < NIGHT_HOUR or not _has_data():
        return False
    return not (backup_dir() / f"hemskola-natt-{now.strftime('%Y-%m-%d')}.db").exists()


def run_due(now: datetime | None = None) -> Path | None:
    return make("natt", now) if nightly_due(now) else None


def snapshot_before_update(signature: str) -> Path | None:
    """Tar en kopia om koden har ändrats sedan förra starten. Ska anropas innan databasen uppgraderas.
    Misslyckas kopian skrivs det ut en varning och appen startar ändå (eleven ska inte stå utan), och försöket upprepas
    nästa start."""
    marker = backup_dir() / VERSION_FILE
    last = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    if last == signature:
        return None
    if not _has_data():            # ny installation: inget att kopiera, men minns koden så att nästa ändring märks
        note_version(signature)
        return None
    try:
        dest = make("fore", label=signature)
    except Exception:
        print("*** VARNING: kunde inte ta säkerhetskopia före uppdateringen ***\n" + traceback.format_exc(), flush=True)
        return None
    marker.write_text(signature, encoding="utf-8")
    print(f"Säkerhetskopia före uppdatering: {dest.name}", flush=True)
    return dest


def note_version(signature: str) -> None:
    """Minns vilken kod som körs."""
    try:
        (backup_dir() / VERSION_FILE).write_text(signature, encoding="utf-8")
    except OSError:
        pass


def full_zip(dest: Path, media_dir: Path) -> None:
    """Databasen (en konsekvent kopia) och alla bilder i en zip-fil, till exempel för att flytta systemet eller fylla
    en testmiljö."""
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "hemskola.db"
        _snapshot(snap)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "hemskola.db")
            if media_dir.is_dir():
                for f in sorted(media_dir.iterdir()):
                    if f.is_file():
                        z.write(f, f"media/{f.name}")


def _loop() -> None:
    while not _stop.is_set():
        try:
            run_due()
        except Exception:
            print("*** Nattlig säkerhetskopia misslyckades ***\n" + traceback.format_exc(), flush=True)
        _stop.wait(CHECK_EVERY)


def start_scheduler() -> threading.Thread | None:
    """Startar tråden som tar nattkopian. Den kontrollerar direkt vid start (så att en kopia som missats medan appen
    stod still tas så fort det går) och sedan var femte minut."""
    if not enabled():
        return None
    _stop.clear()
    t = threading.Thread(target=_loop, name="backup", daemon=True)
    t.start()
    return t


def stop_scheduler(thread: threading.Thread | None = None) -> None:
    _stop.set()
    if thread:
        thread.join(timeout=5)
