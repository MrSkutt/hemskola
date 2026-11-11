"""Faktasidor: korta texter med grunder, formler, tabeller och bilder, en fil per ämne.

Filerna ligger i app/facts/<ämne>.md. Lägger man en fil med samma namn i mappen "facts" bredvid databasen
(t.ex. data/facts/matte.md) används den i stället, så att innehållet kan ändras utan att bygga om containern.

Formatet är en liten delmängd av markdown:

    # Rubrik för sidan
    Ingress (första stycket).

    ## Rubrik för ett avsnitt          (### ger en underrubrik)
    Vanlig text. Rader utan tomrad emellan blir ett stycke. **Fet text**, *kursiv* och `kod` fungerar.
    - punktlista            1. numrerad lista
    | Kolumn 1 | Kolumn 2 |   (första raden är rubrikrad, en rad med |---|---| ignoreras)
    = A = b · h | Rektangelns area   (formel, flera efter varandra grupperas)
    ![solsystemet.svg](Bildtext)    (bild från mediamappen)
    @diagram {"type": "angle", "degrees": 60}   (diagram, samma format som i övningarna)
    > Tips eller extra viktig information
"""
import json
import os
import re
from pathlib import Path

from markupsafe import Markup, escape

from . import db as database
from . import diagrams

BUILTIN_DIR = Path(__file__).parent / "facts"
NAME = re.compile(r"^[a-z0-9_]{1,40}$")
MEDIA_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

_cache: dict = {}


def custom_dir() -> Path:
    return Path(database.DB_PATH).parent / "facts"


def _path(subject: str):
    if not NAME.match(subject or ""):
        return None
    for d in (custom_dir(), BUILTIN_DIR):
        p = d / f"{subject}.md"
        if p.is_file():
            return p
    return None


def available() -> set:
    out = set()
    for d in (BUILTIN_DIR, custom_dir()):
        if d.is_dir():
            out.update(p.stem for p in d.glob("*.md") if NAME.match(p.stem))
    return out


def exists(subject: str) -> bool:
    return _path(subject) is not None


# ---------------------------------------------------------------- inline

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\s](?:[^*]*[^*\s])?)\*(?![\w*])")
_CODE = re.compile(r"`(.+?)`")


def fmt(text) -> Markup:
    """Escapar texten och gör **fet** och `kod` till HTML."""
    s = str(escape(str(text)))
    s = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", s)
    s = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", s)
    return Markup(s)


# ---------------------------------------------------------------- tolkning

def slug(text: str, used: set) -> str:
    base = re.sub(r"[^a-z0-9åäö]+", "-", text.lower()).strip("-") or "avsnitt"
    base = base.replace("å", "a").replace("ä", "a").replace("ö", "o")
    out, n = base, 2
    while out in used:
        out, n = f"{base}-{n}", n + 1
    used.add(out)
    return out


def _is_separator(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return any(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c)


def _table(lines):
    rows = []
    for ln in lines:
        if _is_separator(ln):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return {"type": "table", "head": rows[0], "rows": rows[1:]}


def parse(text: str):
    """Returnerar (sida, fel). sida = {"title", "intro", "sections": [{"id", "title", "blocks"}]}."""
    errors = []
    page = {"title": "", "intro": [], "sections": []}
    used = set()
    target = page["intro"]          # block-lista som just nu fylls på
    para, lst, tbl, formulas = [], None, [], []

    def flush():
        nonlocal para, lst, tbl, formulas
        if para:
            target.append({"type": "p", "text": " ".join(para)})
            para = []
        if lst:
            target.append(lst)
            lst = None
        if tbl:
            t = _table(tbl)
            if t:
                target.append(t)
            tbl = []
        if formulas:
            target.append({"type": "formulas", "items": formulas})
            formulas = []

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            flush()
            continue
        if s.startswith("## "):
            flush()
            sec = {"id": slug(s[3:].strip(), used), "title": s[3:].strip(), "blocks": []}
            page["sections"].append(sec)
            target = sec["blocks"]
            continue
        if s.startswith("### "):
            flush()
            target.append({"type": "h3", "text": s[4:].strip()})
            continue
        if s.startswith("# ") and not page["title"]:
            flush()
            page["title"] = s[2:].strip()
            continue
        if s.startswith("|"):
            if not tbl:
                flush()
            elif len(tbl) >= 2 and _is_separator(s):
                # en ny tabell börjar direkt efter den förra: raden före avgränsaren är den nya tabellens rubrikrad
                header = tbl.pop()
                flush()
                tbl.append(header)
            tbl.append(s)
            continue
        if s.startswith("= "):
            if not formulas:
                flush()
            f, _, expl = s[2:].partition(" | ")
            formulas.append({"formula": f.strip(), "text": expl.strip()})
            continue
        m = re.fullmatch(r"!\[([A-Za-z0-9._-]{1,100})\]\((.*)\)", s)
        if m:
            flush()
            if not MEDIA_NAME.match(m.group(1)):
                errors.append((n, "ogiltigt bildnamn"))
            else:
                target.append({"type": "image", "name": m.group(1), "caption": m.group(2).strip()})
            continue
        if s.startswith("@diagram "):
            flush()
            try:
                spec = json.loads(s[len("@diagram "):])
                problem = diagrams.validate(spec)
                if problem:
                    errors.append((n, f"diagram: {problem}"))
                else:
                    target.append({"type": "diagram", "svg": diagrams.render(spec)})
            except ValueError as e:
                errors.append((n, f"diagram: {e}"))
            continue
        if s.startswith("> "):
            flush()
            target.append({"type": "note", "text": s[2:].strip()})
            continue
        m = re.match(r"^(?:[-*]|(\d+)[.)])\s+(.*)$", s)
        if m:
            kind = "ol" if m.group(1) else "ul"
            if lst and lst["type"] != kind:
                flush()
            if para or tbl or formulas:
                flush()
            if not lst:
                lst = {"type": kind, "items": []}
            lst["items"].append(m.group(2).strip())
            continue
        if lst or tbl or formulas:
            flush()
        para.append(s)
    flush()
    page["intro"] = " ".join(b["text"] for b in page["intro"] if b["type"] == "p")
    return page, errors


def load(subject: str):
    """Läser och tolkar en faktafil (cachad tills filen ändras). None om den saknas."""
    p = _path(subject)
    if not p:
        return None
    mtime = p.stat().st_mtime_ns
    hit = _cache.get(str(p))
    if not hit or hit[0] != mtime:
        hit = _cache[str(p)] = (mtime, parse(p.read_text(encoding="utf-8"))[0])
    return hit[1]
