"""Tester för granskning av importerade övningar: de läggs in dolda och syns för eleverna först när admin godkänt dem."""
import json
import re

from app import db as database
from app import exercise_editor as ed
from app import logic

from .conftest import login
from .test_editor import _admin, _ex, _post
from .test_features import _conn, _make_student


def _items(n=3, subject="franska", level=2):
    return [{"subject": subject, "topic": "Hälsningar", "level": level, "type": "text",
             "question": f"Hur säger man hej på franska? ({i})", "answer": "bonjour",
             "explanation": f"Bonjour betyder hej. {i}"} for i in range(n)]


def _review_ids(conn):
    return [r[0] for r in conn.execute("SELECT id FROM exercises WHERE review=1 ORDER BY id")]


def _row(conn, ex_id):
    return conn.execute("SELECT active, review FROM exercises WHERE id=?", (ex_id,)).fetchone()


# ------------------------------------------------------------------ importen

def test_import_for_review_hides_and_marks(client):
    conn = _conn()
    res = logic.import_exercises(conn, _items(3), review=True)
    assert res["added"] == 3 and res["review"] is True
    rows = conn.execute("SELECT active, review FROM exercises WHERE subject='franska'").fetchall()
    assert len(rows) == 3 and all(r["active"] == 0 and r["review"] == 1 for r in rows)
    conn.close()


def test_import_default_is_visible_as_before(client):
    conn = _conn()
    res = logic.import_exercises(conn, _items(2, subject="tyska"))
    assert res["added"] == 2 and res["review"] is False
    rows = conn.execute("SELECT active, review FROM exercises WHERE subject='tyska'").fetchall()
    assert all(r["active"] == 1 and r["review"] == 0 for r in rows)
    conn.close()


def test_review_flag_not_set_when_nothing_was_added(client):
    conn = _conn()
    logic.import_exercises(conn, _items(2))
    res = logic.import_exercises(conn, _items(2), review=True)       # samma frågor igen: alla dubbletter
    assert res["added"] == 0 and res["skipped"] == 2 and res["review"] is False
    conn.close()


def test_review_import_never_touches_an_existing_visible_exercise(client):
    conn = _conn()
    ex_id = _ex(conn, subject="franska", question="Hur säger man hej på franska? (0)")
    res = logic.import_exercises(conn, _items(2), review=True)
    assert res["added"] == 1 and res["skipped"] == 1
    assert tuple(_row(conn, ex_id)) == (1, 0)                         # den gamla är kvar, synlig och ogranskad
    conn.close()


def test_review_import_works_for_a_bundle_and_leaves_words_alone(client):
    conn = _conn()
    res = logic.import_bundle(conn, {"exercises": _items(2),
                                     "words": [{"word": "klättra", "pos": "verb", "level": 2,
                                                "forms": {"presens": "klättrar", "preteritum": "klättrade",
                                                          "supinum": "klättrat", "imperativ": "klättra"}}]},
                              review=True)
    assert res["added"] == 2 and res["words_added"] == 1 and res["review"] is True
    conn.close()


def test_seed_exercises_are_not_marked_for_review(client):
    conn = _conn()
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE review=1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE active=1").fetchone()[0] > 100
    conn.close()


def test_migration_adds_the_column_to_an_old_database(client):
    conn = _conn()
    conn.execute("ALTER TABLE exercises DROP COLUMN review")
    conn.commit()
    assert "review" not in [r[1] for r in conn.execute("PRAGMA table_info(exercises)")]
    database.migrate(conn)
    conn.commit()
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(exercises)")}
    assert "review" in cols and cols["review"]["dflt_value"] == "0"
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE review<>0").fetchone()[0] == 0   # befintliga är ogranskade
    database.migrate(conn)                                           # och går att köra igen
    conn.close()


# ------------------------------------------------------------------ eleven ser dem inte

def test_student_cannot_get_exercises_awaiting_review(client):
    _make_student(client)
    conn = _conn()
    logic.import_exercises(conn, _items(3), review=True)
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()[0]
    assert "franska" not in logic.active_subjects(conn)
    assert logic.pick_exercise(conn, uid, "franska") is None
    # i ett ämne som redan finns: den hittepå-fråga som väntar på granskning dyker aldrig upp
    wait = _ex(conn, subject="matte", question="Väntande fråga", level=1, active=0)
    conn.execute("UPDATE exercises SET review=1 WHERE id=?", (wait,))
    conn.commit()
    for _ in range(300):
        picked = logic.pick_exercise(conn, uid, "matte")
        assert picked is None or picked != wait
    conn.close()
    login(client, "mia", "hemligt1")
    home = client.get("/home").text
    assert "Franska" not in home
    r = client.get("/practice/franska", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/home"


def test_exercises_show_up_for_the_student_after_approval(client):
    _make_student(client)
    conn = _conn()
    logic.import_exercises(conn, _items(3), review=True)
    conn.close()
    _admin(client)
    client.post("/admin/exercises/approve-all", data={"back": "/admin/exercises"})
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert "Franska" in client.get("/home").text


# ------------------------------------------------------------------ importformuläret

def test_import_page_has_review_checked_and_a_prompt_for_claude(client):
    _admin(client)
    page = client.get("/admin/import").text
    assert re.search(r'<input type="checkbox" name="review" value="1" checked>', page)
    assert "Be Claude skriva nya övningar" in page and "Skriv 30 nya övningar" in page
    assert "/static/import.js" in page
    assert client.get("/static/import.js").status_code == 200


def test_import_with_review_checked_hides_and_links_to_the_list(client):
    _admin(client)
    r = client.post("/admin/import", data={"pasted": json.dumps(_items(3)), "review": "1"})
    assert r.status_code == 200
    assert "3 nya övningar" in r.text and "dolda för eleverna" in r.text
    assert 'href="/admin/exercises?state=review"' in r.text
    conn = _conn()
    assert len(_review_ids(conn)) == 3
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE subject='franska' AND active=1").fetchone()[0] == 0
    conn.close()
    assert 'class="pill wait" title="Importerade övningar som väntar på ditt godkännande">3<' in r.text  # siffran i menyn


def test_import_without_review_is_visible_straight_away(client):
    _admin(client)
    r = client.post("/admin/import", data={"pasted": json.dumps(_items(2, subject="tyska"))})
    assert "2 nya övningar" in r.text and "dolda för eleverna" not in r.text
    conn = _conn()
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE subject='tyska' AND active=1").fetchone()[0] == 2
    assert _review_ids(conn) == []
    conn.close()


def test_import_of_only_duplicates_does_not_promise_a_review(client):
    _admin(client)
    client.post("/admin/import", data={"pasted": json.dumps(_items(2))})
    r = client.post("/admin/import", data={"pasted": json.dumps(_items(2)), "review": "1"})
    assert "0 nya övningar" in r.text and "Granska och godkänn" not in r.text


# ------------------------------------------------------------------ listan och menyn

def _import_review(client, items=None):
    _admin(client)
    client.post("/admin/import", data={"pasted": json.dumps(items or _items(3)), "review": "1"})


def test_menu_pill_and_banner_show_the_waiting_count(client):
    _import_review(client)
    page = client.get("/admin/exercises").text
    assert 'title="Importerade övningar som väntar på ditt godkännande">3<' in page
    assert "3 importerade övningar väntar på ditt godkännande" in page and "Granska dem" in page
    start = client.get("/admin").text
    assert 'title="Importerade övningar som väntar på ditt godkännande">3<' in start
    review = client.get("/admin/exercises?state=review").text
    assert "importerade övningar väntar på ditt godkännande och syns inte" not in review   # ingen banner i granskningslistan


def test_no_pill_when_nothing_waits_and_students_never_see_it(client):
    _make_student(client)
    _admin(client)
    assert "väntar på ditt godkännande" not in client.get("/admin/exercises").text
    client.post("/admin/import", data={"pasted": json.dumps(_items(2)), "review": "1"})
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert "Importerade övningar" not in client.get("/home").text


def test_review_list_shows_answers_and_explanations(client):
    _import_review(client)
    page = client.get("/admin/exercises?state=review").text
    assert page.count("väntar på godkännande</span>") == 3
    assert "Godkända svar: <strong>bonjour</strong>" in page
    assert "Förklaring: Bonjour betyder hej. 1" in page
    assert page.count(">Godkänn</button>") == 3 and "Godkänn alla 3" in page
    assert page.count("Ta bort</button>") == 3


def test_review_list_shows_options_of_multiple_choice(client):
    _admin(client)
    item = {"subject": "franska", "topic": "Färger", "level": 1, "type": "mc", "question": "Vad är rouge?",
            "options": ["röd", "blå", "grön"], "answer": "röd", "explanation": "Rouge är röd."}
    client.post("/admin/import", data={"pasted": json.dumps([item]), "review": "1"})
    page = client.get("/admin/exercises?state=review").text
    assert "Alternativ: <strong>✔ röd</strong> · blå · grön" in page


def test_state_filters_keep_review_apart_from_hidden(client):
    _import_review(client)
    conn = _conn()
    hidden = _ex(conn, subject="matte", question="Dold av mig", active=0)
    visible = _ex(conn, subject="matte", question="Synlig fråga")
    conn.close()
    big = 10 ** 6
    on = ed.search(_conn(), state="on", page_size=big)["rows"]
    off = ed.search(_conn(), state="off", page_size=big)["rows"]
    rev = ed.search(_conn(), state="review", page_size=big)["rows"]
    assert {r["id"] for r in rev} == set(_review_ids(_conn()))
    assert hidden in {r["id"] for r in off} and not ({r["id"] for r in off} & {r["id"] for r in rev})
    assert visible in {r["id"] for r in on} and not ({r["id"] for r in on} & {r["id"] for r in rev})
    page = client.get("/admin/exercises?state=off&subject=franska").text
    assert "Inga övningar matchar" in page


def test_review_list_can_be_filtered_by_subject_and_text(client):
    _import_review(client, _items(2, subject="franska") + _items(2, subject="tyska"))
    only = ed.search(_conn(), state="review", subject="tyska")
    assert only["total"] == 2 and {r["subject"] for r in only["rows"]} == {"tyska"}
    hit = ed.search(_conn(), state="review", q="(1)")
    assert hit["total"] == 2
    empty = client.get("/admin/exercises?state=review&subject=matte").text
    assert "Inget väntar på granskning just nu" in empty


# ------------------------------------------------------------------ godkänna

def test_approve_one_makes_it_visible(client):
    _import_review(client)
    conn = _conn()
    a, b, c = _review_ids(conn)
    r = client.post(f"/admin/exercises/{a}/approve", data={"back": "/admin/exercises?state=review"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/exercises?state=review"
    assert tuple(_row(conn, a)) == (1, 0)
    assert tuple(_row(conn, b)) == (0, 1) and tuple(_row(conn, c)) == (0, 1)
    assert ed.review_count(conn) == 2
    conn.close()


def test_approve_does_not_unhide_something_the_admin_hid_herself(client):
    _admin(client)
    conn = _conn()
    hidden = _ex(conn, subject="matte", question="Dold av mig", active=0)
    r = client.post(f"/admin/exercises/{hidden}/approve")
    assert r.status_code == 303
    assert tuple(_row(conn, hidden)) == (0, 0)
    assert ed.approve(conn, hidden) is False
    assert ed.approve(conn, 999999) is False
    conn.close()


def test_approve_back_is_not_an_open_redirect(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    r = client.post(f"/admin/exercises/{a}/approve", data={"back": "https://evil.example/x"})
    assert r.headers["location"] == "/admin/exercises?state=review"
    r = client.post(f"/admin/exercises/{a}/approve", data={"back": "//evil.example"})
    assert r.headers["location"] == "/admin/exercises?state=review"


def test_approve_all_covers_every_page_and_only_the_filter(client):
    _admin(client)
    many = [{"subject": "franska", "topic": "Ord", "level": 1, "type": "text", "question": f"Fråga nummer {i}?",
             "answer": "x"} for i in range(ed.PAGE_SIZE + 10)]
    client.post("/admin/import", data={"pasted": json.dumps(many + _items(2, subject="tyska")), "review": "1"})
    conn = _conn()
    assert ed.review_count(conn) == ed.PAGE_SIZE + 12
    r = client.post("/admin/exercises/approve-all", data={"subject": "franska", "back": "/admin/exercises?state=review"})
    assert r.status_code == 303
    assert ed.review_count(conn) == 2                                # bara tyskan väntar kvar
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE subject='franska' AND active=1 AND review=0"
                        ).fetchone()[0] == ed.PAGE_SIZE + 10
    assert "60 övningar är godkända" in client.get("/admin/exercises?state=review").text
    conn.close()


def test_approve_all_without_filter_takes_everything_that_waits(client):
    _import_review(client, _items(3) + _items(2, subject="tyska"))
    client.post("/admin/exercises/approve-all", data={})
    conn = _conn()
    assert ed.review_count(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE subject IN ('franska','tyska') AND active=1").fetchone()[0] == 5
    conn.close()
    assert "Inget att godkänna" not in client.get("/admin/exercises").text
    client.post("/admin/exercises/approve-all", data={})
    assert "Inget att godkänna" in client.get("/admin/exercises").text


def test_approve_all_leaves_exercises_the_admin_hid_herself(client):
    _import_review(client)
    conn = _conn()
    hidden = _ex(conn, subject="franska", question="Dold av mig", active=0)
    client.post("/admin/exercises/approve-all", data={})
    assert tuple(_row(conn, hidden)) == (0, 0)
    conn.close()


def test_show_button_on_a_waiting_exercise_also_clears_the_mark(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    client.post(f"/admin/exercises/{a}/active", data={"back": "/admin/exercises"})
    assert tuple(_row(_conn(), a)) == (1, 0)
    client.post(f"/admin/exercises/{a}/active", data={"back": "/admin/exercises"})        # dölj igen
    assert tuple(_row(_conn(), a)) == (0, 0)                          # dold av admin, inte "väntar"


def test_waiting_exercise_can_be_deleted(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    client.post(f"/admin/exercises/{a}/delete", data={"back": "/admin/exercises?state=review"})
    assert _conn().execute("SELECT 1 FROM exercises WHERE id=?", (a,)).fetchone() is None
    assert ed.review_count(_conn()) == 2


def test_only_admin_can_approve(client):
    _make_student(client)
    _admin(client)
    client.post("/admin/import", data={"pasted": json.dumps(_items(2)), "review": "1"})
    a = _review_ids(_conn())[0]
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert client.post(f"/admin/exercises/{a}/approve").status_code == 403
    assert client.post("/admin/exercises/approve-all").status_code == 403
    assert ed.review_count(_conn()) == 2


# ------------------------------------------------------------------ redigeraren

def test_editor_shows_banner_and_approve_button_for_a_waiting_exercise(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    page = client.get(f"/admin/exercises/{a}/edit").text
    assert "Den här övningen är importerad och väntar på ditt godkännande" in page
    assert "väntar på godkännande</span>" in page
    assert "Spara och godkänn" in page and "Spara utan att godkänna" in page
    ok = _ex(_conn(), subject="matte", question="Vanlig")
    normal = client.get(f"/admin/exercises/{ok}/edit").text
    assert "Spara och godkänn" not in normal and "Den här övningen är importerad" not in normal


def _edit_post(a, **kw):
    d = {"subject": "franska", "topic": "Hälsningar", "level": "2", "type": "text",
         "question": "Hur säger man hej på franska? (0)", "answers_text": "bonjour\nsalut", "explanation": "Hej."}
    d.update(kw)
    return d


def test_save_and_approve_in_the_editor(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    r = client.post(f"/admin/exercises/{a}/edit", data=_edit_post(a, approve="1"))
    assert r.status_code == 303, r.text
    assert tuple(_row(_conn(), a)) == (1, 0)
    answers = json.loads(_conn().execute("SELECT answers FROM exercises WHERE id=?", (a,)).fetchone()[0])
    assert answers == ["bonjour", "salut"]


def test_plain_save_keeps_it_waiting(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    r = client.post(f"/admin/exercises/{a}/edit", data=_edit_post(a, explanation="Ändrad."))
    assert r.status_code == 303, r.text
    assert tuple(_row(_conn(), a)) == (0, 1)
    assert _conn().execute("SELECT explanation FROM exercises WHERE id=?", (a,)).fetchone()[0] == "Ändrad."


def test_saving_with_visible_checked_clears_the_mark(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    client.post(f"/admin/exercises/{a}/edit", data=_edit_post(a, active="1"))
    assert tuple(_row(_conn(), a)) == (1, 0)


def test_failed_save_leaves_the_exercise_waiting(client):
    _import_review(client)
    a = _review_ids(_conn())[0]
    r = client.post(f"/admin/exercises/{a}/edit", data=_edit_post(a, approve="1", answers_text=""))
    assert r.status_code == 400
    assert tuple(_row(_conn(), a)) == (0, 1)


def test_editor_preview_loads_automatically_for_an_existing_exercise():
    js = open("app/static/editor.js", encoding="utf-8").read()
    assert "form.elements.question.value.trim()) preview();" in js


def test_new_exercises_from_the_editor_are_not_marked(client):
    _admin(client)
    r = client.post("/admin/exercises/new", data=_post(question="Helt ny fråga?"))
    assert r.status_code == 303
    row = _conn().execute("SELECT active, review FROM exercises WHERE question='Helt ny fråga?'").fetchone()
    assert tuple(row) == (1, 0)
