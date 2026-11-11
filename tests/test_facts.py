"""Tester för fliken Fakta: tolkning av faktafiler, sidor, behörighet och länkar."""
import os
import time
from pathlib import Path

from app import facts, logic

from .conftest import login
from .test_features import _conn, _make_student

SEED_MEDIA = Path(facts.BUILTIN_DIR).parent / "seed" / "media"


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


# ------------------------------------------------------------------ tolkning

SAMPLE = """# Testsida
Första stycket är ingressen.

## Första avsnittet
Text med **fet**, *kursiv* och `kod`.
Fortsättning på samma stycke.

### Underrubrik
- punkt ett
- punkt två

1. steg ett
2. steg två

| Namn | Värde |
|---|---|
| a | 1 |
| b | 2 |

= A = b · h | Rektangelns area
= O = 2(b + h) | Omkrets

![atom.svg](En atom)
@diagram {"type": "angle", "degrees": 60}
> Tips till läsaren

## Andra avsnittet
Bara en rad.
"""


def test_parse_builds_blocks_in_order():
    page, errors = facts.parse(SAMPLE)
    assert errors == []
    assert page["title"] == "Testsida" and page["intro"] == "Första stycket är ingressen."
    assert [s["title"] for s in page["sections"]] == ["Första avsnittet", "Andra avsnittet"]
    assert [s["id"] for s in page["sections"]] == ["forsta-avsnittet", "andra-avsnittet"]
    blocks = page["sections"][0]["blocks"]
    assert [b["type"] for b in blocks] == ["p", "h3", "ul", "ol", "table", "formulas", "image", "diagram", "note"]
    assert blocks[0]["text"].endswith("Fortsättning på samma stycke.")
    assert blocks[2]["items"] == ["punkt ett", "punkt två"] and blocks[3]["items"] == ["steg ett", "steg två"]
    assert blocks[4]["head"] == ["Namn", "Värde"] and blocks[4]["rows"] == [["a", "1"], ["b", "2"]]
    assert blocks[5]["items"][0] == {"formula": "A = b · h", "text": "Rektangelns area"}
    assert len(blocks[5]["items"]) == 2
    assert blocks[6] == {"type": "image", "name": "atom.svg", "caption": "En atom"}
    assert blocks[7]["svg"].lstrip().startswith("<svg")
    assert blocks[8]["text"] == "Tips till läsaren"


def test_parse_reports_bad_diagrams_and_keeps_going():
    page, errors = facts.parse("# T\n\n## A\n@diagram {inte json}\n@diagram {\"type\": \"finns_inte\"}\nText efter.\n")
    assert len(errors) == 2 and all("diagram" in e[1] for e in errors)
    assert [b["type"] for b in page["sections"][0]["blocks"]] == ["p"]


def test_table_pads_short_rows_and_ignores_separator():
    page, _ = facts.parse("# T\n\n## A\n| a | b | c |\n|:--|---|--:|\n| 1 | 2 |\n")
    t = page["sections"][0]["blocks"][0]
    assert t["head"] == ["a", "b", "c"] and t["rows"] == [["1", "2", ""]]


def test_adjacent_tables_are_split_into_two():
    page, errors = facts.parse("# T\n\n## A\n| a | b |\n|---|---|\n| 1 | 2 |\n| c | d | e |\n|---|---|---|\n| 3 | 4 | 5 |\n")
    assert errors == []
    t1, t2 = page["sections"][0]["blocks"]
    assert t1["head"] == ["a", "b"] and t1["rows"] == [["1", "2"]]
    assert t2["head"] == ["c", "d", "e"] and t2["rows"] == [["3", "4", "5"]]


def test_duplicate_section_titles_get_unique_ids():
    page, _ = facts.parse("# T\n\n## Likadan\nA\n\n## Likadan\nB\n")
    assert [s["id"] for s in page["sections"]] == ["likadan", "likadan-2"]


def test_fmt_escapes_html_and_formats_inline():
    out = str(facts.fmt("<script>alert(1)</script> **fet** *kursiv* `a < b` 2*3*4"))
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "<strong>fet</strong>" in out and "<em>kursiv</em>" in out and "<code>a &lt; b</code>" in out
    assert "2*3*4" in out        # gånger-tecken i matte ska inte bli kursivt


def test_subject_name_is_validated(client):
    for bad in ("../app/main", "a/b", "", "MATTE", "x" * 50, "matte.md"):
        assert facts.exists(bad) is False
        assert facts.load(bad) is None


# ------------------------------------------------------------------ innehåll

def test_every_subject_has_a_valid_fact_page():
    have = facts.available()
    subjects = set(logic.SUBJECT_LABELS) - {"no", "so"}
    assert subjects <= have, subjects - have
    for name in sorted(have):
        text = (facts.BUILTIN_DIR / f"{name}.md").read_text(encoding="utf-8")
        page, errors = facts.parse(text)
        assert errors == [], (name, errors)
        assert page["title"] and len(page["intro"]) > 20, name
        assert len(page["sections"]) >= 4, name
        ids = [s["id"] for s in page["sections"]]
        assert len(ids) == len(set(ids)), name
        for sec in page["sections"]:
            assert sec["blocks"], (name, sec["title"])
            for b in sec["blocks"]:
                if b["type"] == "image":
                    assert (SEED_MEDIA / b["name"]).is_file(), (name, b["name"])
                if b["type"] == "table":
                    assert b["rows"] and all(len(r) == len(b["head"]) for r in b["rows"]), (name, sec["title"])
                    assert all(c for r in b["rows"] for c in r[:1]), (name, sec["title"])      # första kolumnen är aldrig tom


def test_periodic_table_image_has_all_118_elements():
    svg = (SEED_MEDIA / "periodiska_hela.svg").read_text(encoding="utf-8")
    for sym in ("H", "He", "Fe", "Au", "Og", "Lr", "La", "U"):
        assert f">{sym}</text>" in svg
    import re
    nums = {int(n) for n in re.findall(r"font-size='9' fill='#374151'>(\d+)</text>", svg)}
    assert nums == set(range(1, 119))


# ------------------------------------------------------------------ sidor och behörighet

def test_requires_login(client):
    assert client.get("/fakta").status_code in (302, 303, 401)
    assert client.get("/fakta/matte").status_code in (302, 303, 401)


def test_student_nav_and_pages(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    home = client.get("/home").text
    assert ">Övningar<" in home and ">Fakta<" in home and ">Hem<" not in home
    assert "<title>Övningar – Hemskola</title>" in home
    assert "📖 Fakta om matematik" in home and "/fakta/kpop" in home

    idx = client.get("/fakta")
    assert idx.status_code == 200
    assert "Grundämnen" in idx.text and "Fritid och skoj" in idx.text
    for s in ("matte", "kemi", "kpop"):
        assert f'href="/fakta/{s}"' in idx.text

    page = client.get("/fakta/matte")
    assert page.status_code == 200
    assert "Räkneordning och negativa tal" in page.text and 'id="delbarhet-och-primtal"' in page.text
    assert "<svg" in page.text and "<table" in page.text
    assert "Till övningarna" in page.text

    kemi = client.get("/fakta/kemi").text
    assert "/media/periodiska_hela.svg" in kemi and "H₂O" in kemi

    assert client.get("/fakta/finns_inte").status_code == 404
    assert client.get("/fakta/..%2Fmain").status_code == 404


def test_student_cannot_open_facts_for_hidden_subjects(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, [s for s in subjects if s != "kpop"], [], subjects)
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    assert client.get("/fakta/kpop").status_code == 404
    assert "/fakta/kpop" not in client.get("/fakta").text and "/fakta/kpop" not in client.get("/home").text
    assert client.get("/fakta/matte").status_code == 200


def test_admin_sees_all_fact_pages(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, ["matte"], [], subjects)       # påverkar bara eleven
    conn.commit()
    conn.close()
    login(client, "admin", "adminpass1")
    idx = client.get("/fakta")
    assert idx.status_code == 200 and 'href="/fakta/kpop"' in idx.text and 'href="/fakta/historia"' in idx.text
    assert client.get("/fakta/kpop").status_code == 200
    assert "Till övningarna" not in client.get("/fakta/kpop").text
    assert ">Fakta<" in client.get("/admin").text


def test_fact_link_in_practice_but_not_in_tests(client):
    _make_student(client)
    conn = _conn()
    logic.set_level(conn, _uid(conn), "matte", 1)
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    practice = client.get("/practice/matte")
    assert practice.status_code == 200
    assert 'href="/fakta/matte"' in practice.text and 'target="_blank"' in practice.text
    url = client.post("/test/start/fysik").headers["location"]
    test_page = client.get(url).text
    assert "📖" not in test_page and "/fakta/fysik" not in test_page


# ------------------------------------------------------------------ egna filer

def test_custom_directory_overrides_builtin_and_reloads(client, tmp_path):
    folder = tmp_path / "facts"
    folder.mkdir()
    f = folder / "matte.md"
    f.write_text("# Egen matte\nMin egen ingress som är lång nog.\n\n## Bara det här\nHej **världen**.\n", encoding="utf-8")
    _make_student(client)
    login(client, "mia", "hemligt1")
    page = client.get("/fakta/matte").text
    assert "Bara det här" in page and "<strong>världen</strong>" in page and "Räkneordning" not in page
    # ändrad fil läses om (cachen följer ändringstiden)
    f.write_text("# Egen matte\nMin egen ingress som är lång nog.\n\n## Nytt avsnitt\nNy text.\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(f, (later, later))
    page = client.get("/fakta/matte").text
    assert "Nytt avsnitt" in page and "Bara det här" not in page
    # övriga ämnen använder fortfarande de inbyggda
    assert "Atomnummer" in client.get("/fakta/kemi").text
    # tar man bort den egna filen gäller den inbyggda igen
    f.unlink()
    assert "Räkneordning" in client.get("/fakta/matte").text
