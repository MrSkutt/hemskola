"""Tester för övningsredigeraren: formulär, spara, ta bort, sök och förhandsvisning."""
import json
import re

import pytest

from app import db as database
from app import diagrams, exercise_editor as ed
from app import logic, main

from .conftest import login
from .test_features import PNG, _conn, _make_student


def _mc(**kw):
    f = ed.blank_form(subject="matte", level=2, typ="mc", topic="Bråk")
    f.update(question="Vilket är störst?", options=["1/2", "1/3", "1/4", "", "", ""], correct=[0], explanation="Halv är störst.")
    f.update(kw)
    return f


def _txt(**kw):
    f = ed.blank_form(subject="matte", level=2, typ="text", topic="Procent")
    f.update(question="Hur mycket är 10 % av 350?", answers_text="35", explanation="Dela med 10.")
    f.update(kw)
    return f


def _post(**kw):
    """Formulärdata som webbläsaren skickar för en flervalsövning."""
    d = {"subject": "matte", "topic": "Bråk", "level": "2", "type": "mc", "question": "Vilket är störst?",
         "option": ["1/2", "1/3", "1/4", "", "", ""], "correct": "0", "explanation": "Halv är störst.",
         "active": "1"}
    d.update(kw)
    return d


def _admin(client):
    login(client, "admin", "adminpass1")


def _ex(conn, subject="matte", question="Fråga?", typ="text", answers='["x"]', **kw):
    cols = {"subject": subject, "topic": kw.get("topic", "Eget"), "level": kw.get("level", 2), "type": typ,
            "question": question, "answers": answers, "options": kw.get("options"), "active": kw.get("active", 1),
            "image": kw.get("image"), "diagram": kw.get("diagram"), "explanation": kw.get("explanation", "")}
    cur = conn.execute(
        "INSERT INTO exercises(subject, topic, level, type, question, options, answers, active, image, diagram, explanation) "
        "VALUES (:subject,:topic,:level,:type,:question,:options,:answers,:active,:image,:diagram,:explanation)", cols)
    conn.commit()
    return cur.lastrowid


# ------------------------------------------------------------------ ren logik

def test_clean_subject():
    assert ed.clean_subject("  Franska ") == "franska"
    assert ed.clean_subject("Data kunskap") == "data-kunskap"
    assert ed.clean_subject("å") == ""                      # för kort
    for bad in ("", "a/b", "../x", "x" * 31, "-x", "a b!", None):
        assert ed.clean_subject(bad) == ""


def test_build_valid_mc_maps_correct_slot_to_text_even_with_blank_slots():
    form = _mc(options=["", "grön", "", "röd", "blå", ""], correct=[3])
    row, errors = ed.build(form, {"matte"})
    assert errors == []
    assert json.loads(row["options"]) == ["grön", "röd", "blå"]
    assert json.loads(row["answers"]) == ["röd"]
    assert (row["subject"], row["level"], row["type"], row["topic"]) == ("matte", 2, "mc", "Bråk")


def test_build_valid_text_with_several_answers_and_cleanup():
    row, errors = ed.build(_txt(answers_text="20:15\n  20.15 \n\n20:15\n"), {"matte"})
    assert errors == [] and json.loads(row["answers"]) == ["20:15", "20.15"]
    assert row["options"] is None


@pytest.mark.parametrize("change,message", [
    ({"options": ["bara en", "", "", "", "", ""], "correct": [0]}, "minst två alternativ"),
    ({"options": ["Katt", "katt", "", "", "", ""], "correct": [0]}, "likadana"),
    ({"correct": []}, "Markera vilket alternativ"),
    ({"correct": [5]}, "Markera vilket alternativ"),               # pekar på en tom ruta
    ({"options": ["a", "b", "c", "d", "e", "f", "g", "h", "i"], "correct": [0]}, "Högst 8"),
    ({"question": "   "}, "Skriv frågan"),
    ({"question": "x" * 1501}, "högst 1500"),
    ({"topic": " "}, "Skriv vilket område"),
    ({"topic": "x" * 61}, "högst 60"),
    ({"level": 0}, "nivå mellan 1 och 5"),
    ({"level": 6}, "nivå mellan 1 och 5"),
    ({"type": ""}, "flerval eller fritext"),
    ({"subject": ""}, "Välj ett ämne"),
    ({"subject": "a/b"}, "Ämnet finns inte"),
    ({"subject": ed.NEW_SUBJECT, "new_subject": "x"}, "nytt ämnesnamn"),
    ({"explanation": "x" * 2001}, "Förklaringen"),
    ({"image": "../hemlig.png"}, "Bildens filnamn"),
])
def test_build_rejects_bad_forms_with_swedish_messages(change, message):
    row, errors = ed.build(_mc(**change), {"matte"})
    assert row is None and any(message in e for e in errors), errors


def test_build_text_errors():
    assert "minst ett godkänt svar" in ed.build(_txt(answers_text=" \n "), {"matte"})[1][0]
    assert "Högst 20" in ed.build(_txt(answers_text="\n".join(str(i) for i in range(21))), {"matte"})[1][0]
    assert "högst 200" in ed.build(_txt(answers_text="x" * 201), {"matte"})[1][0]


def test_build_collects_every_error_at_once():
    row, errors = ed.build(_mc(question="", topic="", correct=[]), {"matte"})
    assert row is None and len(errors) == 3


def test_build_new_subject_is_cleaned():
    row, errors = ed.build(_mc(subject=ed.NEW_SUBJECT, new_subject=" Franska "), {"matte"})
    assert errors == [] and row["subject"] == "franska"
    row, errors = ed.build(_mc(subject="Matte "), {"matte"})                    # versaler och mellanslag rättas
    assert errors == [] and row["subject"] == "matte"


def test_build_diagram():
    ok = _mc(diagram_type="clock", diagram=json.dumps({"type": "clock", "time": "2:10"}))
    row, errors = ed.build(ok, {"matte"})
    assert errors == [] and json.loads(row["diagram"]) == {"type": "clock", "time": "2:10"}
    assert "inte giltig JSON" in ed.build(_mc(diagram="{oj"), {"matte"})[1][0]
    assert "Du valde en diagramtyp" in ed.build(_mc(diagram_type="clock"), {"matte"})[1][0]
    assert "okänd diagramtyp" in ed.build(_mc(diagram='{"type": "tårta"}'), {"matte"})[1][0].lower()
    assert "kunde inte ritas" in ed.build(_mc(diagram='{"type": "clock", "time": "x"}'), {"matte"})[1][0]
    assert "objekt med en" in ed.build(_mc(diagram="[1, 2]"), {"matte"})[1][0]
    assert "för långa" in ed.build(_mc(diagram=" " * 10 + "{" + "1" * 5000), {"matte"})[1][0]


def test_every_diagram_template_is_valid_and_named():
    assert set(diagrams.EXAMPLES) == set(diagrams.TYPES) == set(diagrams.TYPE_LABELS)
    for kind, spec in diagrams.EXAMPLES.items():
        assert spec["type"] == kind and diagrams.validate(spec) is None, kind


def test_form_round_trip_from_database_row(client):
    conn = _conn()
    mc = _ex(conn, typ="mc", question="Färg?", options='["röd","grön","blå"]', answers='["grön"]',
             explanation="Gräs.", image="k.png", diagram=json.dumps({"type": "angle", "degrees": 90}))
    tx = _ex(conn, typ="text", question="2+2?", answers='["4","fyra"]')
    f = ed.form_from_row(conn.execute("SELECT * FROM exercises WHERE id=?", (mc,)).fetchone())
    assert f["options"][:3] == ["röd", "grön", "blå"] and len(f["options"]) == ed.OPTION_SLOTS
    assert f["correct"] == [1] and f["image"] == "k.png" and f["diagram_type"] == "angle"
    assert json.loads(f["diagram"]) == {"type": "angle", "degrees": 90}
    row, errors = ed.build(f, {"matte"})
    assert errors == []
    old = conn.execute("SELECT * FROM exercises WHERE id=?", (mc,)).fetchone()
    for col in ("subject", "topic", "level", "type", "question", "explanation", "image"):
        assert row[col] == old[col], col
    assert json.loads(row["options"]) == json.loads(old["options"])           # samma innehåll (JSON kan ha olika mellanrum)
    assert json.loads(row["answers"]) == json.loads(old["answers"])
    t = ed.form_from_row(conn.execute("SELECT * FROM exercises WHERE id=?", (tx,)).fetchone())
    assert t["answers_text"] == "4\nfyra" and t["correct"] == []
    conn.close()


def test_form_from_post_reads_lists_and_defaults():
    class Data(dict):
        def getlist(self, k):
            v = self.get(k, [])
            return v if isinstance(v, list) else [v]
    f = ed.form_from_post(Data(subject=" matte ", level="x", type="mc", option=["a", "b"], correct=["1", "oj", "0"],
                               image_current=" a.png ", active="1"))
    assert f["subject"] == "matte" and f["level"] == 0 and f["correct"] == [1, 0]
    assert f["options"][:2] == ["a", "b"] and len(f["options"]) == ed.OPTION_SLOTS
    assert f["image"] == "a.png" and f["active"] is True
    assert ed.form_from_post(Data())["active"] is False


def test_create_update_and_duplicates(client):
    conn = _conn()
    row, _ = ed.build(_mc(), {"matte"})
    new_id, err, dup = ed.create_exercise(conn, row)
    assert new_id and err == "" and dup is None
    conn.commit()
    again, err, dup = ed.create_exercise(conn, row)
    assert again is None and "exakt samma fråga" in err and dup == new_id
    other, _ = ed.build(_mc(question="Vilket är minst?"), {"matte"})
    o_id, _, _ = ed.create_exercise(conn, other, active=False)
    assert conn.execute("SELECT active FROM exercises WHERE id=?", (o_id,)).fetchone()[0] == 0
    # ändra den ena till den andras fråga ger dubblett, men en övning krockar inte med sig själv
    assert ed.update_exercise(conn, o_id, row)[0].startswith("Det finns redan")
    assert ed.update_exercise(conn, new_id, row, active=False) == ("", None)
    assert conn.execute("SELECT active FROM exercises WHERE id=?", (new_id,)).fetchone()[0] == 0
    assert ed.update_exercise(conn, 9999, row)[0] == "Övningen finns inte."
    conn.close()


def test_same_question_is_fine_in_another_subject(client):
    conn = _conn()
    a, _ = ed.build(_mc(), {"matte", "svenska"})
    b, _ = ed.build(_mc(subject="svenska"), {"matte", "svenska"})
    assert ed.create_exercise(conn, a)[1] == "" and ed.create_exercise(conn, b)[1] == ""
    conn.close()


def test_generators_cannot_be_edited_replaced_or_deleted(client):
    conn = _conn()
    g = conn.execute("SELECT id FROM exercises WHERE generator IS NOT NULL LIMIT 1").fetchone()["id"]
    row, _ = ed.build(_mc(), {"matte"})
    assert "kan inte redigeras" in ed.update_exercise(conn, g, row)[0]
    assert "kan inte redigeras" in ed.replace_exercise(conn, g, row)[1]
    assert "kan inte tas bort" in ed.delete_exercise(conn, g)
    conn.close()


def test_replace_hides_old_and_needs_a_different_question(client):
    conn = _conn()
    old = _ex(conn, question="Gammal fråga?")
    row, _ = ed.build(_txt(question="Gammal fråga?"), {"matte"})
    new_id, err, dup = ed.replace_exercise(conn, old, row)
    assert new_id is None and dup == old and "annan frågetext" in err
    assert conn.execute("SELECT active FROM exercises WHERE id=?", (old,)).fetchone()[0] == 1   # orörd
    row, _ = ed.build(_txt(question="Ny fråga?"), {"matte"})
    new_id, err, _ = ed.replace_exercise(conn, old, row)
    assert err == "" and new_id != old
    assert conn.execute("SELECT active FROM exercises WHERE id=?", (old,)).fetchone()[0] == 0
    assert conn.execute("SELECT active FROM exercises WHERE id=?", (new_id,)).fetchone()[0] == 1
    assert "finns inte" in ed.replace_exercise(conn, 9999, row)[1]
    conn.close()


def test_delete_rules(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    free, answered, intest = _ex(conn, question="a?"), _ex(conn, question="b?"), _ex(conn, question="c?")
    conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,1)", (uid, answered, "x"))
    tid = conn.execute("INSERT INTO tests(user_id, subject, kind) VALUES (?, 'matte', 'status')", (uid,)).lastrowid
    conn.execute("INSERT INTO test_items(test_id, position, exercise_id) VALUES (?,1,?)", (tid, intest))
    conn.commit()
    assert "1 svar" in ed.delete_exercise(conn, answered)
    assert "ingår i ett prov" in ed.delete_exercise(conn, intest)
    assert ed.delete_exercise(conn, free) == ""
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE id IN (?,?,?)", (free, answered, intest)).fetchone()[0] == 2
    assert ed.delete_exercise(conn, free) == "Övningen finns inte."
    conn.close()


def test_search_filters_pages_and_swedish_letters(client):
    conn = _conn()
    conn.execute("DELETE FROM exercises WHERE generator IS NULL")
    conn.commit()
    _ex(conn, "svenska", "Vad betyder ÖGA?", topic="Ord", level=1, typ="text", answers='["syn"]')
    _ex(conn, "svenska", "Andra frågan", topic="Ord", level=2, typ="mc", options='["a","b"]', answers='["a"]', active=0)
    _ex(conn, "matte", "Räkna åäö 2+2", topic="Addition", level=1, typ="text", answers='["fyra"]', explanation="Plus")
    total = lambda **kw: ed.search(conn, **kw)["total"]
    allgen = total()
    assert total(subject="svenska") == 2 + conn.execute("SELECT COUNT(*) FROM exercises WHERE subject='svenska' AND generator IS NOT NULL").fetchone()[0]
    assert total(subject="svenska", kind="mc") == 1 and total(subject="svenska", kind="text") == 1
    assert total(kind="gen") == conn.execute("SELECT COUNT(*) FROM exercises WHERE generator IS NOT NULL").fetchone()[0]
    assert total(subject="svenska", kind="mc", state="off") == 1 and total(subject="svenska", kind="mc", state="on") == 0
    assert total(subject="svenska", topic="Ord", level=2) == 1
    assert total(q="öga") == 1 and total(q="  ÖGA  ") == 1                     # versaler, åäö och mellanslag
    assert total(q="ÅÄÖ") == 1 and total(q="fyra") == 1 and total(q="plus") == 1  # svar och förklaring söks också
    assert total(q="addition", subject="matte") >= 1                            # området söks
    assert total(q="finns-inte-alls") == 0 and total(q="öga", level=2) == 0
    res = ed.search(conn, q="finns-inte-alls")
    assert (res["rows"], res["page"], res["pages"], res["first"], res["last"]) == ([], 1, 1, 0, 0)
    # sidor
    for i in range(ed.PAGE_SIZE + 5):
        _ex(conn, "historia", f"Sidfråga {i}?", topic="Sida", level=3)
    r1 = ed.search(conn, subject="historia", topic="Sida")
    assert (r1["total"], r1["pages"], len(r1["rows"]), r1["first"], r1["last"]) == (ed.PAGE_SIZE + 5, 2, ed.PAGE_SIZE, 1, ed.PAGE_SIZE)
    r2 = ed.search(conn, subject="historia", topic="Sida", page=2)
    assert (len(r2["rows"]), r2["first"], r2["last"]) == (5, ed.PAGE_SIZE + 1, ed.PAGE_SIZE + 5)
    assert not {r["id"] for r in r1["rows"]} & {r["id"] for r in r2["rows"]}
    assert ed.search(conn, subject="historia", topic="Sida", page=99)["page"] == 2     # för högt sidnummer rättas
    assert ed.search(conn, subject="historia", topic="Sida", page=-3)["page"] == 1
    assert allgen >= 3
    conn.close()


def test_search_counts_answers(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    e = _ex(conn, question="Svarad?")
    for ok in (1, 1, 0):
        conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,?)", (uid, e, "x", ok))
    conn.commit()
    row = [r for r in ed.search(conn, q="Svarad?")["rows"] if r["id"] == e][0]
    assert (row["n"], row["c"]) == (3, 2)
    conn.close()


def test_topics_by_subject(client):
    conn = _conn()
    _ex(conn, "franska", "Bonjour?", topic="Hälsningar")
    _ex(conn, "franska", "Merci?", topic="Artighet", active=0)
    t = ed.topics_by_subject(conn)
    assert t["franska"] == ["Artighet", "Hälsningar"] and "matte" in t
    conn.close()


def test_preview_item_flags_unknown_area():
    row, _ = ed.build(_mc(topic="Helt påhittat"), {"matte"})
    item = ed.preview_item(row)
    assert item["area_unknown"] and item["options"] == ["1/2", "1/3", "1/4"] and item["answers"] == ["1/2"]
    row, _ = ed.build(_mc(diagram=json.dumps({"type": "angle", "degrees": 90})), {"matte"})
    assert "<svg" in ed.preview_item(row)["svg"]


# ------------------------------------------------------------------ sidor och rutter

def test_pages_need_admin(client):
    for method, url in (("get", "/admin/exercises/new"), ("get", "/admin/exercises/1/edit"),
                        ("post", "/admin/exercises/new"), ("post", "/admin/exercises/1/edit"),
                        ("post", "/admin/exercises/1/delete"), ("post", "/admin/exercises/preview")):
        assert getattr(client, method)(url).status_code in (303, 401, 403), url
    _make_student(client)
    login(client, "mia", "hemligt1")
    for method, url in (("get", "/admin/exercises/new"), ("post", "/admin/exercises/new"),
                        ("post", "/admin/exercises/preview"), ("post", "/admin/exercises/1/delete")):
        assert getattr(client, method)(url).status_code == 403, url


def test_list_has_search_filters_edit_buttons_and_pager(client):
    conn = _conn()
    for i in range(ed.PAGE_SIZE + 3):
        _ex(conn, "historia", f"Lista {i}?", topic="Listan", level=4)
    g = conn.execute("SELECT id FROM exercises WHERE generator IS NOT NULL LIMIT 1").fetchone()["id"]
    _admin(client)
    page = client.get("/admin/exercises?subject=historia&topic=Listan&level=4").text
    assert "Visar 1–50 av 53 övningar" in page and "Sida 1 av 2" in page and "Nästa →" in page
    assert "page=2" in page and "subject=historia" in page                   # filtren följer med mellan sidorna
    assert page.count("/edit?back=") == ed.PAGE_SIZE and 'name="q"' in page
    page2 = client.get("/admin/exercises?subject=historia&topic=Listan&level=4&page=2").text
    assert "Visar 51–53 av 53" in page2 and "← Föregående" in page2 and "Nästa →" not in page2
    assert "Inga övningar matchar" in client.get("/admin/exercises?q=finns-inte-alls").text
    gen_page = client.get("/admin/exercises?kind=gen").text
    assert f"/admin/exercises/{g}/edit" not in gen_page                      # inga redigera-knappar på generatorer
    assert "Rensa" in gen_page
    assert "Rensa" not in client.get("/admin/exercises").text
    assert 'name="topic"' in page and 'name="topic"' not in client.get("/admin/exercises").text
    conn.close()


def test_list_hide_button_returns_to_the_same_filtered_page(client):
    conn = _conn()
    e = _ex(conn, "historia", "Dölj mig?", topic="Dold")
    _admin(client)
    page = client.get("/admin/exercises?subject=historia&q=Dölj").text
    assert 'name="back" value="/admin/exercises?subject=historia&amp;q=D%C3%B6lj"' in page   # tillbaka till samma filter
    r = client.post(f"/admin/exercises/{e}/active", data={"back": "/admin/exercises?subject=historia&q=D"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/exercises?subject=historia&q=D"
    assert conn.execute("SELECT active FROM exercises WHERE id=?", (e,)).fetchone()[0] == 0
    r = client.post(f"/admin/exercises/{e}/active", data={"back": "https://evil.example/"})
    assert r.headers["location"] == "/admin/exercises"                        # extern adress ignoreras
    assert conn.execute("SELECT active FROM exercises WHERE id=?", (e,)).fetchone()[0] == 1
    conn.close()


def test_new_form_is_blank_and_similar_prefills(client):
    conn = _conn()
    e = _ex(conn, "historia", "Förebild?", topic="Vikingar", level=4, typ="text")
    _admin(client)
    page = client.get("/admin/exercises/new").text
    assert "Ny övning" in page and "Välj ämne…" in page and 'name="option"' in page
    assert 'name="subject"' in page and "Nytt ämne…" in page and "Spara och skapa nästa" in page
    assert "Ta bort övningen" not in page and "Förhandsgranska" in page
    sim = client.get(f"/admin/exercises/new?similar={e}").text
    assert 'value="Vikingar"' in sim and re.search(r'<option value="historia" selected>', sim)
    assert re.search(r'<option value="4" selected>', sim) and re.search(r'value="text"\s+checked', sim)
    assert "Förebild?" not in sim                                            # frågan kopieras inte
    assert client.get("/admin/exercises/new?similar=99999").status_code == 200   # okänd förebild ger tomt formulär
    conn.close()


def test_edit_form_shows_the_exercise(client):
    conn = _conn()
    e = _ex(conn, "matte", "Färg?", typ="mc", options='["röd","grön","blå"]', answers='["grön"]', explanation="Gräs.",
            topic="Färger")
    _admin(client)
    page = client.get(f"/admin/exercises/{e}/edit?back=/admin/exercises%3Fsubject%3Dmatte").text
    assert "Redigera övning" in page and "Färg?" in page and 'value="grön"' in page and "Gräs." in page
    assert re.search(r'name="correct" value="1"[^>]*checked', page)
    assert 'href="/admin/exercises?subject=matte"' in page and "Ta bort övningen" in page
    assert "Skapa en liknande övning" in page and "Spara som ny övning" not in page   # ingen har svarat
    assert client.get("/admin/exercises/99999/edit").status_code == 404
    conn.close()


def test_edit_of_generator_redirects_with_message(client):
    conn = _conn()
    g = conn.execute("SELECT id FROM exercises WHERE generator IS NOT NULL LIMIT 1").fetchone()["id"]
    _admin(client)
    r = client.get(f"/admin/exercises/{g}/edit")
    assert r.status_code == 303 and r.headers["location"] == "/admin/exercises"
    assert "kan inte redigeras" in client.get("/admin/exercises").text
    assert client.post(f"/admin/exercises/{g}/edit", data=_post()).status_code == 400
    conn.close()


def test_create_mc_via_form(client):
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Skapad via formulär?"))
    assert r.status_code == 303 and r.headers["location"] == "/admin/exercises?subject=matte&level=2"
    conn = _conn()
    row = conn.execute("SELECT * FROM exercises WHERE question='Skapad via formulär?'").fetchone()
    assert (row["subject"], row["topic"], row["level"], row["type"], row["active"]) == ("matte", "Bråk", 2, "mc", 1)
    assert json.loads(row["options"]) == ["1/2", "1/3", "1/4"] and json.loads(row["answers"]) == ["1/2"]
    assert "Övningen är sparad" in client.get("/admin/exercises").text
    conn.close()


def test_create_text_exercise_and_unchecked_active_hides_it(client):
    _admin(client)
    data = _post(type="text", question="Skriv svaret", answers_text="a\nb")
    del data["active"]
    data.pop("option")
    data.pop("correct")
    assert client.post("/admin/exercises/new", data=data).status_code == 303
    conn = _conn()
    row = conn.execute("SELECT * FROM exercises WHERE question='Skriv svaret'").fetchone()
    assert row["type"] == "text" and json.loads(row["answers"]) == ["a", "b"] and row["options"] is None
    assert row["active"] == 0
    conn.close()


def test_create_in_a_new_subject(client):
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(subject=ed.NEW_SUBJECT, new_subject="Franska", question="Bonjour?"))
    assert r.status_code == 303 and "subject=franska" in r.headers["location"]
    conn = _conn()
    assert conn.execute("SELECT subject FROM exercises WHERE question='Bonjour?'").fetchone()[0] == "franska"
    assert "franska" in logic.active_subjects(conn)
    page = client.get("/admin/exercises/new").text
    assert '<option value="franska"' in page and ">Franska<" in page
    conn.close()


def test_save_and_create_next_prefills_the_next_form(client):
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Första?", after="next", back="/admin/exercises?q=x"))
    assert r.status_code == 303
    loc = r.headers["location"]
    conn = _conn()
    first = conn.execute("SELECT id FROM exercises WHERE question='Första?'").fetchone()["id"]
    assert loc.startswith(f"/admin/exercises/new?similar={first}") and "back=" in loc
    page = client.get(loc).text
    assert "Här är nästa" in page and 'value="Bråk"' in page
    conn.close()


def test_validation_errors_keep_the_form_filled_and_save_nothing(client):
    _admin(client)
    before = _count()
    r = client.post("/admin/exercises/new", data=_post(question="Behåll mig", correct=[], topic=""))
    assert r.status_code == 400
    assert "Det gick inte att spara" in r.text and "Markera vilket alternativ" in r.text and "Skriv vilket område" in r.text
    assert "Behåll mig" in r.text and 'value="1/3"' in r.text              # formuläret är kvar ifyllt
    assert _count() == before


def _count():
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    conn.close()
    return n


def test_duplicate_shows_link_to_the_existing_exercise(client):
    conn = _conn()
    e = _ex(conn, "matte", "Finns redan?", typ="text")
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Finns redan?", type="text", answers_text="1"))
    assert r.status_code == 400 and "exakt samma fråga" in r.text and f"/admin/exercises/{e}/edit" in r.text
    conn.close()


def test_edit_updates_in_place_and_keeps_history(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    e = _ex(conn, "matte", "Gammal text?", typ="text", answers='["4"]')
    conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,1)", (uid, e, "4"))
    conn.commit()
    created = conn.execute("SELECT created_at FROM exercises WHERE id=?", (e,)).fetchone()[0]
    _admin(client)
    page = client.get(f"/admin/exercises/{e}/edit").text
    assert "Elever har svarat 1 gång" in page and "Spara som ny övning" in page
    assert re.search(r"<button[^>]*disabled[^>]*>Ta bort övningen</button>", page)    # kan inte tas bort
    data = _post(type="text", question="Ny text?", answers_text="5\nfem", level="3", topic="Andra")
    data.pop("option"), data.pop("correct")
    r = client.post(f"/admin/exercises/{e}/edit", data={**data, "back": "/admin/exercises?q=Ny"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/exercises?q=Ny"
    conn = _conn()
    row = conn.execute("SELECT * FROM exercises WHERE id=?", (e,)).fetchone()
    assert (row["question"], row["level"], row["topic"], json.loads(row["answers"])) == ("Ny text?", 3, "Andra", ["5", "fem"])
    assert row["created_at"] == created and _count() == conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    assert conn.execute("SELECT correct FROM attempts WHERE exercise_id=?", (e,)).fetchone()[0] == 1   # gamla svar orörda
    assert "Ändringarna är sparade" in client.get("/admin/exercises").text
    conn.close()


def test_edit_can_change_type_from_text_to_mc(client):
    conn = _conn()
    e = _ex(conn, "matte", "Typbyte?", typ="text")
    _admin(client)
    assert client.post(f"/admin/exercises/{e}/edit", data=_post(question="Typbyte?")).status_code == 303
    row = conn.execute("SELECT type, options, answers FROM exercises WHERE id=?", (e,)).fetchone()
    assert row["type"] == "mc" and json.loads(row["options"]) == ["1/2", "1/3", "1/4"] and json.loads(row["answers"]) == ["1/2"]
    data = _post(type="text", question="Typbyte?", answers_text="svar")
    client.post(f"/admin/exercises/{e}/edit", data=data)
    row = conn.execute("SELECT type, options FROM exercises WHERE id=?", (e,)).fetchone()
    assert row["type"] == "text" and row["options"] is None             # gamla alternativ följer inte med
    conn.close()


def test_edit_save_as_new_hides_the_old_exercise(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    e = _ex(conn, "matte", "Gammal?", typ="text")
    conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,0)", (uid, e, "x"))
    conn.commit()
    _admin(client)
    r = client.post(f"/admin/exercises/{e}/edit", data=_post(question="Gammal?", replace="1"))
    assert r.status_code == 400 and "annan frågetext" in r.text            # samma text går inte
    r = client.post(f"/admin/exercises/{e}/edit", data=_post(question="Helt ny?", replace="1"))
    assert r.status_code == 303
    assert conn.execute("SELECT question, active FROM exercises WHERE id=?", (e,)).fetchone()[:] == ("Gammal?", 0)
    new = conn.execute("SELECT * FROM exercises WHERE question='Helt ny?'").fetchone()
    assert new["active"] == 1 and new["type"] == "mc"
    assert conn.execute("SELECT COUNT(*) FROM attempts WHERE exercise_id=?", (e,)).fetchone()[0] == 1   # historiken stannar
    assert "den gamla är dold" in client.get("/admin/exercises").text
    conn.close()


def test_replace_flag_is_ignored_when_nobody_has_answered(client):
    conn = _conn()
    e = _ex(conn, "matte", "Ingen svarat?", typ="text")
    _admin(client)
    client.post(f"/admin/exercises/{e}/edit", data=_post(question="Ingen svarat nu?", replace="1"))
    assert conn.execute("SELECT question FROM exercises WHERE id=?", (e,)).fetchone()[0] == "Ingen svarat nu?"
    assert _count() == conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
    conn.close()


def test_edit_moving_legacy_exercise_moves_levels_when_old_subject_is_empty(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    e = _ex(conn, "no", "Gammal NO-fråga?", typ="text")
    conn.execute("INSERT INTO user_levels(user_id, subject, level) VALUES (?, 'no', 3)", (uid,))
    conn.commit()
    _admin(client)
    client.post(f"/admin/exercises/{e}/edit", data=_post(subject="fysik", question="Gammal NO-fråga?"))
    conn = _conn()
    assert conn.execute("SELECT subject FROM exercises WHERE id=?", (e,)).fetchone()[0] == "fysik"
    assert logic.get_level(conn, uid, "no") is None and logic.get_level(conn, uid, "fysik") == 3
    conn.close()


def test_delete_route(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    free, used = _ex(conn, question="Ta bort?"), _ex(conn, question="Använd?")
    conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,1)", (uid, used, "x"))
    conn.commit()
    _admin(client)
    r = client.post(f"/admin/exercises/{free}/delete", data={"back": "/admin/exercises?q=Ta"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/exercises?q=Ta"
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE id=?", (free,)).fetchone()[0] == 0
    assert "Övningen är borttagen" in client.get("/admin/exercises").text
    r = client.post(f"/admin/exercises/{used}/delete")
    assert r.status_code == 303 and conn.execute("SELECT COUNT(*) FROM exercises WHERE id=?", (used,)).fetchone()[0] == 1
    assert "Elever har svarat på den" in client.get("/admin/exercises").text
    assert client.post("/admin/exercises/99999/delete").status_code == 303        # ingen krasch
    conn.close()


def test_back_parameter_never_leaves_the_admin_area(client):
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Back?", back="https://evil.example/x"))
    assert r.headers["location"] == "/admin/exercises?subject=matte&level=2"
    r = client.post("/admin/exercises/new", data=_post(question="Back2?", back="//evil.example/x"))
    assert r.headers["location"].startswith("/admin/exercises?subject=")
    assert "evil" not in client.get("/admin/exercises/new?back=https://evil.example/").text


# --- bilder

def test_choose_existing_image_and_keep_or_remove_it(client):
    (main.media_dir() / "bild.png").write_bytes(PNG)
    _admin(client)
    client.post("/admin/exercises/new", data=_post(question="Bild?", image_existing="bild.png"))
    conn = _conn()
    e = conn.execute("SELECT id, image FROM exercises WHERE question='Bild?'").fetchone()
    assert e["image"] == "bild.png"
    assert 'src="/media/bild.png"' in client.get(f"/admin/exercises/{e['id']}/edit").text
    client.post(f"/admin/exercises/{e['id']}/edit", data=_post(question="Bild?", image_current="bild.png", explanation="ny"))
    assert conn.execute("SELECT image FROM exercises WHERE id=?", (e["id"],)).fetchone()[0] == "bild.png"   # behålls
    client.post(f"/admin/exercises/{e['id']}/edit", data=_post(question="Bild?", image_current="bild.png", remove_image="1"))
    assert conn.execute("SELECT image FROM exercises WHERE id=?", (e["id"],)).fetchone()[0] is None
    assert (main.media_dir() / "bild.png").exists()                          # filen är kvar i biblioteket
    conn.close()


def test_missing_image_file_does_not_block_other_edits_but_new_pick_is_checked(client):
    conn = _conn()
    e = _ex(conn, "matte", "Trasig bild?", typ="text", image="borta.png")
    _admin(client)
    r = client.post(f"/admin/exercises/{e}/edit", data=_post(question="Trasig bild?", type="text", answers_text="1",
                                                              image_current="borta.png"))
    assert r.status_code == 303                                              # övriga ändringar går att spara
    r = client.post(f"/admin/exercises/{e}/edit", data=_post(question="Trasig bild?", image_existing="finns-inte.png"))
    assert r.status_code == 400 and "finns inte längre" in r.text
    conn.close()


def test_upload_image_is_stored_with_its_own_prefix_and_shared(client):
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Uppladdad?"),
                    files={"image_file": ("hund.png", PNG, "image/png")})
    assert r.status_code == 303
    conn = _conn()
    name = conn.execute("SELECT image FROM exercises WHERE question='Uppladdad?'").fetchone()[0]
    assert re.match(r"^ovning-[0-9a-f]{10}\.png$", name) and (main.media_dir() / name).read_bytes() == PNG
    assert name in client.get("/admin/media").text                           # syns i bildbiblioteket
    conn.close()


def test_bad_upload_is_refused_and_nothing_is_saved(client):
    _admin(client)
    before = _count()
    r = client.post("/admin/exercises/new", data=_post(question="Dålig bild?"),
                    files={"image_file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400 and "filtyp stöds inte" in r.text and _count() == before
    r = client.post("/admin/exercises/new", data=_post(question="Dålig bild 2?"),
                    files={"image_file": ("x.png", b"inte en bild", "image/png")})
    assert r.status_code == 400 and "ser inte ut som" in r.text and _count() == before


def test_uploaded_image_survives_a_validation_error_in_the_form(client):
    """Bilden sparas direkt och följer med formuläret, så man slipper ladda upp den igen efter ett fel."""
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Fel men bild?", correct=[]),
                    files={"image_file": ("hund.png", PNG, "image/png")})
    assert r.status_code == 400
    name = re.search(r'name="image_current" value="(ovning-[0-9a-f]+\.png)"', r.text).group(1)
    r = client.post("/admin/exercises/new", data=_post(question="Fel men bild?", image_current=name))
    assert r.status_code == 303
    conn = _conn()
    assert conn.execute("SELECT image FROM exercises WHERE question='Fel men bild?'").fetchone()[0] == name
    conn.close()


def test_image_url_goes_through_the_safe_fetcher(client):
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Url?", image_url="http://127.0.0.1/x.png"))
    assert r.status_code == 400 and "Url?" in r.text                          # privata adresser nekas
    conn = _conn()
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE question='Url?'").fetchone()[0] == 0
    conn.close()


# --- diagram och förhandsvisning

def test_diagram_is_saved_and_shown_in_preview(client):
    _admin(client)
    spec = json.dumps({"type": "bar_chart", "labels": ["A", "B"], "values": [3, 5]})
    r = client.post("/admin/exercises/new", data=_post(question="Diagram?", diagram_type="bar_chart", diagram=spec))
    assert r.status_code == 303
    conn = _conn()
    e = conn.execute("SELECT id, diagram FROM exercises WHERE question='Diagram?'").fetchone()
    assert json.loads(e["diagram"])["values"] == [3, 5]
    page = client.get(f"/admin/exercises/{e['id']}/edit").text
    assert 'value="bar_chart" selected' in page and "&#34;values&#34;" in page
    assert 'data-examples=' in page and "Stapeldiagram" in page
    bad = client.post("/admin/exercises/new", data=_post(question="Diagram2?", diagram='{"type": "bar_chart"}'))
    assert bad.status_code == 400 and "kunde inte ritas" in bad.text
    conn.close()


def test_preview_shows_question_correct_answer_and_changes_nothing(client):
    _admin(client)
    before = _count()
    r = client.post("/admin/exercises/preview", data=_post(question="Förhandsvisa mig?"))
    assert r.status_code == 200 and "Förhandsvisa mig?" in r.text and "✔ rätt" in r.text
    assert "Område:" in r.text and "Halv är störst." in r.text and "<html" not in r.text      # bara en bit
    assert _count() == before


def test_preview_text_exercise_and_errors_and_unknown_area(client):
    _admin(client)
    data = _post(type="text", answers_text="a\nb", topic="Uppdiktat område")
    data.pop("option"), data.pop("correct")
    r = client.post("/admin/exercises/preview", data=data)
    assert "Godkända svar:" in r.text and "a  ·  b" in r.text and "visas under Övrigt" in r.text
    r = client.post("/admin/exercises/preview", data=_post(question="", correct=[]))
    assert "Det går inte att spara än" in r.text and "Skriv frågan" in r.text and "✔ rätt" not in r.text
    r = client.post("/admin/exercises/preview", data=_post(diagram=json.dumps({"type": "clock", "time": "3:30"})))
    assert "<svg" in r.text


def test_preview_does_not_swallow_the_flash_message(client):
    _admin(client)
    client.post("/admin/exercises/new", data=_post(question="Flash?"))          # sätter meddelandet
    client.post("/admin/exercises/preview", data=_post())
    assert "Övningen är sparad" in client.get("/admin/exercises").text


def test_preview_mentions_a_chosen_but_unsaved_image(client):
    _admin(client)
    r = client.post("/admin/exercises/preview", data=_post(image_url="https://example.com/a.png"))
    assert "visas här när du sparat" in r.text
    r = client.post("/admin/exercises/preview", data=_post(), files={"image_file": ("a.png", PNG, "image/png")})
    assert "visas här när du sparat" in r.text
    assert not list(main.media_dir().glob("ovning-*"))                       # förhandsvisningen sparar inget


def test_student_sees_a_new_exercise_but_not_a_hidden_one(client):
    _make_student(client)
    _admin(client)
    client.post("/admin/exercises/new", data=_post(subject=ed.NEW_SUBJECT, new_subject="latin", question="Salve?",
                                                   type="text", answers_text="hej"))
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert "Latin" in client.get("/home").text
    client.post("/logout")
    _admin(client)
    conn = _conn()
    e = conn.execute("SELECT id FROM exercises WHERE question='Salve?'").fetchone()["id"]
    client.post(f"/admin/exercises/{e}/active")
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert "Latin" not in client.get("/home").text
    conn.close()


# ------------------------------------------------------------------ övningar som behöver ses över

def _answers(conn, uid, ex_id, results):
    for ok in results:
        conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,?)",
                     (uid, ex_id, "svar" if ok else "fel", ok))
    conn.commit()


def _review_set(client):
    """Fem övningar i ett eget ämne: A 1 av 5 rätt, B 3 av 3, C 1 av 3, D 0 av 2, E obesvarad."""
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    ids = {k: _ex(conn, "granska", f"Fråga {k}?", topic="Granska") for k in "ABCDE"}
    _answers(conn, uid, ids["A"], [1, 0, 0, 0, 0])
    _answers(conn, uid, ids["B"], [1, 1, 1])
    _answers(conn, uid, ids["C"], [0, 1, 0])
    _answers(conn, uid, ids["D"], [0, 0])
    return conn, uid, ids


def test_is_hard_boundaries():
    assert ed.is_hard(3, 0) and ed.is_hard(3, 1) and ed.is_hard(6, 2) and ed.is_hard(30, 10)
    assert not ed.is_hard(3, 2) and not ed.is_hard(2, 0) and not ed.is_hard(0, 0) and not ed.is_hard(6, 3)


def test_search_by_answer_statistics(client):
    conn, uid, ids = _review_set(client)
    names = lambda **kw: sorted(r["question"][-2] for r in ed.search(conn, subject="granska", **kw)["rows"])
    assert names() == list("ABCDE")
    assert names(stat="answered") == list("ABCD") and names(stat="unanswered") == ["E"]
    assert names(stat="hard") == ["A", "C"]                                  # D har för få svar för att räknas
    assert names(stat="nonsens") == list("ABCDE")                            # okänt värde ger inget filter


def test_search_sorting_by_share_correct_and_number_of_answers(client):
    conn, uid, ids = _review_set(client)
    order = lambda sort, **kw: [r["question"][-2] for r in ed.search(conn, subject="granska", sort=sort, **kw)["rows"]]
    assert order("low") == ["D", "A", "C", "B", "E"]                         # 0 %, 20 %, 33 %, 100 %, obesvarad sist
    assert order("many") == ["A", "B", "C", "D", "E"]                        # 5, 3, 3, 2, 0 svar (lika: i vanlig ordning)
    assert order("") == list("ABCDE")
    assert order("low", stat="hard") == ["A", "C"]                           # filter och sortering går att kombinera


def test_list_page_filters_sorts_and_flags_hard_exercises(client):
    conn, uid, ids = _review_set(client)
    _admin(client)
    page = client.get("/admin/exercises?subject=granska&stat=hard&sort=low").text
    assert "Visar 1–2 av 2" in page and "Fråga A?" in page and "Fråga C?" in page and "Fråga B?" not in page
    assert page.index("Fråga A?") < page.index("Fråga C?")                  # 20 % före 33 %
    assert page.count('class="pill redo"') == 2                              # varning på båda raderna
    assert 'value="hard" selected' in page and 'value="low" selected' in page
    full = client.get("/admin/exercises?subject=granska").text
    assert full.count('class="pill redo"') == 2                              # A och C, inte B eller D
    assert "20 % rätt" in full and "100 % rätt" in full
    assert "Lägst andel rätt" in full and "Aldrig besvarade" in full and "Flest svar" in full


def test_pager_keeps_the_statistics_filters(client):
    conn = _conn()
    _make_student(client)
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    for i in range(ed.PAGE_SIZE + 2):
        _answers(conn, uid, _ex(conn, "granska", f"Många {i}?", topic="G"), [0, 0, 0])
    _admin(client)
    page = client.get("/admin/exercises?subject=granska&stat=hard&sort=low").text
    assert "stat=hard" in page and "sort=low" in page and "page=2" in page
    link = re.search(r'href="(/admin/exercises\?[^"]*page=2)"', page).group(1).replace("&amp;", "&")
    assert "Visar 51–52 av 52" in client.get(link).text


def test_edit_page_shows_recent_answers_and_a_button_to_approve_wrong_text_answers(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    e = _ex(conn, "matte", "Hur mycket är 2+2?", typ="text", answers='["4"]')
    for given, ok in (("fyra", 0), ("4", 1), ("  ", 0)):
        conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,?)", (uid, e, given, ok))
    conn.commit()
    _admin(client)
    page = client.get(f"/admin/exercises/{e}/edit").text
    assert "Elevernas senaste svar" in page and "Mia" in page
    assert page.count('class="small ghost addans"') == 1 and 'data-answer="fyra"' in page   # inte vid rätt eller tomt svar
    assert page.index("✖ fel") < page.index("✔ rätt") < page.rindex("✖ fel")   # nyast först: fel (tomt), rätt (4), fel (fyra)
    assert "Med <em>Godkänn</em>" in page


def test_edit_page_for_multiple_choice_has_no_approve_buttons_and_no_history_when_unanswered(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    mc = _ex(conn, "matte", "Färg?", typ="mc", options='["röd","grön"]', answers='["grön"]')
    fresh = _ex(conn, "matte", "Ny?", typ="text")
    conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,0)", (uid, mc, "röd"))
    conn.commit()
    _admin(client)
    page = client.get(f"/admin/exercises/{mc}/edit").text
    assert "Elevernas senaste svar" in page and "röd" in page and "addans" not in page.split("Elevernas senaste svar")[1].split("</table>")[0]
    assert "Elevernas senaste svar" not in client.get(f"/admin/exercises/{fresh}/edit").text
    assert "Elevernas senaste svar" not in client.get("/admin/exercises/new").text


def test_recent_attempts_are_limited_and_newest_first(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    e = _ex(conn, "matte", "Många svar?", typ="text")
    for i in range(20):
        conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,0)", (uid, e, f"svar{i}"))
    conn.commit()
    rows = ed.recent_attempts(conn, e)
    assert len(rows) == 15 and rows[0]["given"] == "svar19" and rows[-1]["given"] == "svar5"
    assert rows[0]["display_name"] == "Mia"
    assert ed.recent_attempts(conn, e, limit=2)[1]["given"] == "svar18"
