"""Tester för säkerhetskopior, versionsvisning och admins sidor för dem."""
import os
import re
import sqlite3
import time
import zipfile
from datetime import datetime
from io import BytesIO

import pytest

from app import backup, main, version
from app import db as database

from .conftest import login
from .test_features import PNG, _conn, _make_student


def _users(path):
    c = sqlite3.connect(path)
    try:
        return [r[0] for r in c.execute("SELECT username FROM users ORDER BY id")]
    finally:
        c.close()


def _at(day, hour=4):
    return datetime(2026, 11, day, hour, 30, 0)


# ------------------------------------------------------------------ modulen

def test_make_creates_a_single_valid_file_with_the_data(client):
    _make_student(client)
    dest = backup.make("manuell", _at(12))
    assert dest.name == "hemskola-manuell-2026-11-12-043000.db" and backup.NAME_RE.match(dest.name)
    assert sorted(_users(dest)) == ["admin", "mia"]
    assert not list(dest.parent.glob("*-wal")) and not list(dest.parent.glob("*-shm")) and not list(dest.parent.glob("*.tmp"))
    c = sqlite3.connect(dest)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"      # går att kopiera som en enda fil
    c.close()


def test_backup_contains_committed_data_only_and_does_not_block_the_app(client):
    live = _conn()
    live.execute("INSERT INTO users(username, display_name, password_hash, role) VALUES ('sen','Sen','x','student')")
    live.commit()
    live.execute("INSERT INTO users(username, display_name, password_hash, role) VALUES ('ocommittad','O','x','student')")
    dest = backup.make("manuell", _at(12))                                   # medan en annan anslutning har en öppen transaktion
    assert "sen" in _users(dest) and "ocommittad" not in _users(dest)
    live.commit()
    live.close()


def test_kinds_and_names(client):
    assert backup.make("natt", _at(5)).name == "hemskola-natt-2026-11-05.db"
    assert backup.make("fore", _at(5), "abc1234").name == "hemskola-fore-2026-11-05-043000-abc1234.db"
    with pytest.raises(ValueError):
        backup.make("okänd")
    for bad in ("../x.db", "hemskola-natt-../../etc.db", "hemskola-annat-1.db", "hemskola-natt-1.db.tmp", "x.db",
                "hemskola-natt-a/b.db", "hemskola-natt-.db"):
        assert not backup.NAME_RE.match(bad), bad


def test_prune_keeps_the_newest_of_each_kind(client):
    for day in range(1, 21):                                                 # 20 nattliga
        backup.make("natt", datetime(2026, 10, day, 4))
    for sec in range(8):                                                     # 8 före uppdatering
        backup.make("fore", datetime(2026, 11, 1, 5, 0, sec), "sig")
    for sec in range(12):                                                    # 12 manuella
        backup.make("manuell", datetime(2026, 11, 2, 6, 0, sec))
    names = [b["name"] for b in backup.listing()]
    nights = sorted(n for n in names if "-natt-" in n)
    assert len(nights) == backup.KEEP["natt"] == 14 and nights[0] == "hemskola-natt-2026-10-07.db" and nights[-1] == "hemskola-natt-2026-10-20.db"
    assert sum("-fore-" in n for n in names) == 5 and sum("-manuell-" in n for n in names) == 10
    assert "hemskola-fore-2026-11-01-050007-sig.db" in names and "hemskola-fore-2026-11-01-050002-sig.db" not in names


def test_listing_is_newest_first_and_ignores_other_files(client):
    old = backup.make("manuell", _at(1))
    new = backup.make("manuell", _at(2))
    os.utime(old, (1_700_000_000, 1_700_000_000))
    (backup.backup_dir() / "anteckningar.txt").write_text("x")
    (backup.backup_dir() / "hemskola-natt-2026-11-03.db.tmp").write_text("x")
    (backup.backup_dir() / backup.VERSION_FILE).write_text("abc")
    items = backup.listing()
    assert [b["name"] for b in items] == [new.name, old.name]
    assert items[0]["kind"] == "manuell" and items[0]["kind_label"] == "Manuell" and items[0]["size"] > 0


def test_nightly_due_rules(client):
    assert backup.nightly_due(_at(12, 2)) is False                           # före kl 03
    assert backup.nightly_due(_at(12, 3)) is True
    assert backup.run_due(_at(12, 9)).name == "hemskola-natt-2026-11-12.db"
    assert backup.nightly_due(_at(12, 23)) is False and backup.run_due(_at(12, 23)) is None   # redan tagen idag
    assert backup.nightly_due(_at(13, 4)) is True                            # nästa dygn


def test_no_nightly_backup_of_an_empty_database(client):
    conn = _conn()
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    assert backup.nightly_due(_at(12)) is False


def test_stale_warning(client, monkeypatch):
    monkeypatch.setenv("BACKUPS", "1")
    assert backup.stale() is True                                            # inga kopior alls
    dest = backup.make("manuell")
    assert backup.stale() is False
    two_days_ago = time.time() - 2 * 86400
    os.utime(dest, (two_days_ago, two_days_ago))
    assert backup.stale() is True
    monkeypatch.setenv("BACKUPS", "0")
    assert backup.stale() is False                                           # avstängt: ingen varning


def test_snapshot_before_update(client, capsys):
    folder = backup.backup_dir()
    first = backup.snapshot_before_update("aaaaaaa")
    assert first and first.name.endswith("-aaaaaaa.db") and "-fore-" in first.name
    assert (folder / backup.VERSION_FILE).read_text() == "aaaaaaa"
    assert backup.snapshot_before_update("aaaaaaa") is None                  # samma kod: ingen ny kopia
    second = backup.snapshot_before_update("bbbbbbb")                        # ny kod: ny kopia
    assert second and second != first and (folder / backup.VERSION_FILE).read_text() == "bbbbbbb"
    assert "Säkerhetskopia före uppdatering" in capsys.readouterr().out


def test_new_installation_gets_no_pre_update_copy_but_remembers_the_code(client):
    conn = _conn()
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    assert backup.snapshot_before_update("ccccccc") is None
    assert (backup.backup_dir() / backup.VERSION_FILE).read_text() == "ccccccc"
    assert backup.listing() == []


def test_failed_pre_update_copy_does_not_stop_startup_and_is_retried(client, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disken är full")
    real_make = backup.make
    monkeypatch.setattr(backup, "make", boom)
    assert backup.snapshot_before_update("ddddddd") is None
    assert "VARNING" in capsys.readouterr().out
    assert not (backup.backup_dir() / backup.VERSION_FILE).exists()          # inte markerad som klar
    monkeypatch.setattr(backup, "make", real_make)                           # disken har blivit ledig igen
    assert backup.snapshot_before_update("ddddddd") is not None              # nästa start försöker igen


def test_bootstrap_takes_the_copy_before_migrating_the_database(client, monkeypatch):
    """Kopian ska visa databasen som den var, innan den nya koden har ändrat något i den."""
    conn = _conn()
    conn.execute("DROP TABLE reward_requests")                               # som en databas från en äldre version
    conn.commit()
    conn.close()
    monkeypatch.setenv("BACKUPS", "1")
    main.bootstrap()
    (copy,) = [b for b in backup.listing() if b["kind"] == "fore"]
    c = sqlite3.connect(backup.backup_dir() / copy["name"])
    old_tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    assert "reward_requests" not in old_tables and "users" in old_tables
    live = _conn()
    assert live.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 0    # den levande databasen är uppgraderad
    live.close()
    main.bootstrap()
    assert len([b for b in backup.listing() if b["kind"] == "fore"]) == 1    # samma kod: ingen ny kopia


def test_bootstrap_makes_no_copies_when_backups_are_off(client):
    main.bootstrap()                                                         # BACKUPS=0 i testerna
    assert backup.listing() == []


def test_full_zip_has_database_and_images(client, tmp_path):
    _make_student(client)
    media = main.media_dir()
    (media / "a.png").write_bytes(PNG)
    (media / "undermapp").mkdir(exist_ok=True)
    out = tmp_path / "allt.zip"
    backup.full_zip(out, media)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "hemskola.db" in names and "media/a.png" in names and not any("undermapp" in n for n in names)
        assert z.read("media/a.png") == PNG
        db_bytes = z.read("hemskola.db")
    p = tmp_path / "ur-zip.db"
    p.write_bytes(db_bytes)
    assert sorted(_users(p)) == ["admin", "mia"]


def test_scheduler_runs_checks_and_stops(client, monkeypatch):
    assert backup.start_scheduler() is None                                  # BACKUPS=0
    monkeypatch.setenv("BACKUPS", "1")
    calls = []
    monkeypatch.setattr(backup, "run_due", lambda: calls.append(1))
    monkeypatch.setattr(backup, "CHECK_EVERY", 0.01)
    t = backup.start_scheduler()
    assert t.daemon
    deadline = time.time() + 3
    while len(calls) < 3 and time.time() < deadline:
        time.sleep(0.01)
    backup.stop_scheduler(t)
    assert len(calls) >= 3 and not t.is_alive()


def test_scheduler_survives_a_failing_backup(client, monkeypatch, capsys):
    monkeypatch.setenv("BACKUPS", "1")
    n = []
    def flaky():
        n.append(1)
        raise OSError("tillfälligt fel")
    monkeypatch.setattr(backup, "run_due", flaky)
    monkeypatch.setattr(backup, "CHECK_EVERY", 0.01)
    t = backup.start_scheduler()
    deadline = time.time() + 3
    while len(n) < 3 and time.time() < deadline:
        time.sleep(0.01)
    backup.stop_scheduler(t)
    assert len(n) >= 3 and "Nattlig säkerhetskopia misslyckades" in capsys.readouterr().out


# ------------------------------------------------------------------ version

def test_release_label_and_signature_format():
    assert re.match(r"^\d{4}\.\d{2}\.\d{2}(\.\d+)?$", version.RELEASE)
    info = version.info()
    assert re.match(r"^[0-9a-f]{7}$", info["signature"]) and info["label"] == f"{info['release']} ({info['signature']})"


def test_code_signature_changes_with_the_code_only(tmp_path):
    (tmp_path / "a.py").write_text("print(1)")
    (tmp_path / "t.html").write_text("<p>x</p>")
    first = version.code_signature(tmp_path)
    assert version.code_signature(tmp_path) == first                         # stabil
    (tmp_path / "anteckning.txt").write_text("spelar ingen roll")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.pyc.py").write_text("spelar ingen roll")
    assert version.code_signature(tmp_path) == first                         # andra filer och cache räknas inte
    (tmp_path / "a.py").write_text("print(2)")
    changed = version.code_signature(tmp_path)
    assert changed != first
    (tmp_path / "ny.css").write_text("a{}")
    assert version.code_signature(tmp_path) != changed                       # ny fil
    (tmp_path / "ny.css").rename(tmp_path / "ny2.css")
    assert version.code_signature(tmp_path) not in (first, changed)


def test_healthz_reports_the_version(client):
    r = client.get("/healthz").json()
    assert r["ok"] is True and r["version"] == version.RELEASE and r["signature"] == version.info()["signature"]


def test_footer_shows_version_to_admin_only(client):
    _make_student(client)
    assert version.info()["signature"] not in client.get("/login").text
    login(client, "mia", "hemligt1")
    assert version.RELEASE not in client.get("/home").text
    client.post("/logout")
    login(client, "admin", "adminpass1")
    page = client.get("/admin").text
    assert f"version {version.info()['label']}" in page and 'href="/admin/backups"' in page


# ------------------------------------------------------------------ admin

def test_backup_pages_need_admin(client):
    for method, url in (("get", "/admin/backups"), ("post", "/admin/backups/now"), ("get", "/admin/backups/helt.zip"),
                        ("get", "/admin/backups/hemskola-natt-2026-11-12.db")):
        assert getattr(client, method)(url).status_code in (303, 401, 403), url
    _make_student(client)
    login(client, "mia", "hemligt1")
    for method, url in (("get", "/admin/backups"), ("post", "/admin/backups/now"), ("get", "/admin/backups/helt.zip")):
        assert getattr(client, method)(url).status_code == 403, url


def test_backup_page_states(client, monkeypatch):
    login(client, "admin", "adminpass1")
    page = client.get("/admin/backups").text
    assert "Automatiska säkerhetskopior är avstängda" in page and "Inga kopior än" in page    # BACKUPS=0 i testet
    monkeypatch.setenv("BACKUPS", "1")
    page = client.get("/admin/backups").text
    assert "Ingen säkerhetskopia har tagits de senaste 36 timmarna" in page
    assert "Ingen säkerhetskopia" in client.get("/admin").text                # och en varning på startsidan
    backup.make("manuell")
    page = client.get("/admin/backups").text
    assert "tas automatiskt varje natt" in page and "Manuell" in page and "Ladda ner" in page
    assert "Så här återställer du" in page and "Ingen säkerhetskopia har tagits" not in client.get("/admin").text


def test_take_a_copy_now_and_download_it(client):
    login(client, "admin", "adminpass1")
    r = client.post("/admin/backups/now")
    assert r.status_code == 303 and r.headers["location"] == "/admin/backups"
    (item,) = backup.listing()
    assert item["kind"] == "manuell"
    page = client.get("/admin/backups").text
    assert f"Säkerhetskopian {item['name']} är tagen." in page
    r = client.get(f"/admin/backups/{item['name']}")
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3\x00")
    assert "attachment" in r.headers["content-disposition"] and item["name"] in r.headers["content-disposition"]


def test_download_refuses_other_files(client):
    login(client, "admin", "adminpass1")
    (backup.backup_dir().parent / "secret.key").write_text("hemlig")
    for url in ("/admin/backups/secret.key", "/admin/backups/..%2Fsecret.key", "/admin/backups/hemskola-natt-2026-01-01.db",
                "/admin/backups/hemskola-natt-..%2Fsecret.key", "/admin/backups/.senaste-version"):
        assert client.get(url).status_code == 404, url


def test_failed_manual_backup_is_reported_not_crashing(client, monkeypatch):
    login(client, "admin", "adminpass1")
    def boom(*a, **k):
        raise OSError("disken är full")
    monkeypatch.setattr(backup, "make", boom)
    assert client.post("/admin/backups/now").status_code == 303
    assert "Det gick inte att ta någon säkerhetskopia: disken är full" in client.get("/admin/backups").text


def test_zip_download_contains_database_and_images_and_cleans_up(client, tmp_path, monkeypatch):
    _make_student(client)
    (main.media_dir() / "bild.png").write_bytes(PNG)
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    login(client, "admin", "adminpass1")
    r = client.get("/admin/backups/helt.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert re.search(r'filename="hemskola-allt-\d{4}-\d{2}-\d{2}\.zip"', r.headers["content-disposition"])
    z = zipfile.ZipFile(BytesIO(r.content))
    assert "hemskola.db" in z.namelist() and "media/bild.png" in z.namelist()
    assert not list((tmp_path / "tmp").iterdir())                            # den tillfälliga filen är borttagen
