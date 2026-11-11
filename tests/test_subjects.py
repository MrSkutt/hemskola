"""Tester för ämnesgrupper, ämnesval per elev och vilka ämnen som tas med i rapporten."""
import re

from app import db as database
from app import logic, report

from .conftest import login
from .test_features import _conn, _make_student


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


def _answer(conn, uid, subject, correct=1):
    ex = conn.execute("SELECT id FROM exercises WHERE subject=? AND generator IS NULL AND active=1 LIMIT 1", (subject,)).fetchone()
    conn.execute("INSERT INTO attempts (user_id, exercise_id, given, correct) VALUES (?,?,?,?)", (uid, ex["id"], "x", correct))
    conn.commit()


def test_groups_follow_fixed_order_and_unknown_subjects_go_last():
    groups = logic.group_subjects(["kpop", "fysik", "matte", "geografi", "ritkonst", "svenska"])
    assert [g["key"] for g in groups] == ["grund", "no", "so", "fritid", "ovrigt"]
    assert groups[0]["subjects"] == ["matte", "svenska"]
    assert groups[-1]["subjects"] == ["ritkonst"]
    assert logic.ordered_subjects(["kpop", "matte", "kemi"]) == ["matte", "kemi", "kpop"]
    covered = {s for _, _, members in logic.SUBJECT_GROUPS for s in members}
    assert covered == set(logic.SUBJECT_LABELS) - {"no", "so"}      # varje riktigt ämne ligger i en grupp


def test_defaults_everything_visible_but_kpop_not_in_report(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    settings = logic.subject_settings(conn, uid)
    assert all(v["enabled"] for v in settings.values())
    assert settings["kpop"]["in_report"] is False
    assert settings["matte"]["in_report"] is True and settings["biologi"]["in_report"] is True
    assert "kpop" in logic.enabled_subjects(conn, uid) and "kpop" not in logic.report_subjects(conn, uid)
    conn.close()


def test_save_and_read_subject_settings(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, enabled=["matte", "kpop"], in_report=["matte", "kpop"], subjects=subjects)
    conn.commit()
    s = logic.subject_settings(conn, uid)
    assert s["matte"] == {"enabled": True, "in_report": True}
    assert s["kpop"] == {"enabled": True, "in_report": True}
    assert s["fysik"] == {"enabled": False, "in_report": False}
    assert logic.enabled_subjects(conn, uid) == ["matte", "kpop"]
    assert logic.subject_enabled(conn, uid, "fysik") is False and logic.subject_enabled(conn, uid, "nytt") is True
    # ett ämne som tillkommer senare får standardvärden
    conn.execute("DELETE FROM user_subjects WHERE subject='kpop'")
    assert logic.subject_settings(conn, uid)["kpop"] == {"enabled": True, "in_report": False}
    conn.close()


def test_settings_are_per_student(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    conn = _conn()
    a, b = _uid(conn, "mia"), _uid(conn, "ben")
    logic.save_subject_settings(conn, a, [], [], logic.active_subjects(conn))
    conn.commit()
    assert logic.enabled_subjects(conn, a) == [] and len(logic.enabled_subjects(conn, b)) == len(logic.active_subjects(conn))
    conn.close()


def test_home_is_grouped_and_hides_disabled_subjects(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    page = client.get("/home").text
    for title in ("Grundämnen", "Naturorienterande ämnen (NO)", "Samhällsorienterande ämnen (SO)", "Fritid och skoj"):
        assert title in page
    assert page.index("Grundämnen") < page.index("Naturorienterande") < page.index("Samhällsorienterande") < page.index("Fritid och skoj")
    client.post("/logout")

    conn = _conn()
    logic.save_subject_settings(conn, _uid(conn), [x for x in logic.active_subjects(conn) if x not in ("kpop", "fysik")], [],
                                logic.active_subjects(conn))
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    page = client.get("/home").text
    assert "K-pop" not in page and "Fysik" not in page and "Fritid och skoj" not in page
    assert "Matematik" in page and "Kemi" in page


def test_disabled_subject_cannot_be_practised_or_tested(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.set_level(conn, uid, "kpop", 2)
    logic.save_subject_settings(conn, uid, [x for x in logic.active_subjects(conn) if x != "kpop"], [], logic.active_subjects(conn))
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    r = client.get("/practice/kpop")
    assert r.status_code == 303 and r.headers["location"] == "/home"
    assert client.post("/test/start/kpop").headers["location"] == "/home"
    ex_id = _conn().execute("SELECT id FROM exercises WHERE subject='kpop' AND generator IS NULL LIMIT 1").fetchone()["id"]
    assert client.post("/practice/kpop", data={"exercise_id": ex_id, "given": "x"}).headers["location"] == "/home"
    conn = _conn()
    assert conn.execute("SELECT COUNT(*) FROM tests WHERE user_id=? AND subject='kpop'", (uid,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id=?", (uid,)).fetchone()[0] == 0
    conn.close()
    # andra ämnen fungerar som vanligt
    logic.set_level(c := _conn(), uid, "matte", 1)
    c.commit()
    c.close()
    assert client.get("/practice/matte").status_code == 200


def test_open_test_in_disabled_subject_is_not_offered(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    client.post("/test/start/fysik")
    assert "påbörjat prov i Fysik" in client.get("/home").text
    client.post("/logout")
    conn = _conn()
    uid = _uid(conn)
    logic.save_subject_settings(conn, uid, [x for x in logic.active_subjects(conn) if x != "fysik"], [], logic.active_subjects(conn))
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    assert "påbörjat prov" not in client.get("/home").text


def test_report_defaults_exclude_kpop_and_filter_totals(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    student = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    logic.set_level(conn, uid, "matte", 2)
    logic.set_level(conn, uid, "kpop", 3)
    for _ in range(3):
        _answer(conn, uid, "matte")
    for _ in range(5):
        _answer(conn, uid, "kpop")
    data = report.collect(conn, student, 30)
    assert [s["subject"] for s in data["subjects"]] == ["matte"]
    assert len(data["rows"]) == 3
    both = report.collect(conn, student, 30, ["matte", "kpop"])
    assert [s["subject"] for s in both["subjects"]] == ["matte", "kpop"] and len(both["rows"]) == 8
    only_kpop = report.collect(conn, student, 30, ["kpop"])
    assert len(only_kpop["rows"]) == 5 and [s["subject"] for s in only_kpop["subjects"]] == ["kpop"]
    # elev som bara övat K-pop: rapporten visar ingen aktivitet och ingen streak
    conn.execute("DELETE FROM attempts WHERE exercise_id IN (SELECT id FROM exercises WHERE subject='matte')")
    conn.commit()
    quiet = report.collect(conn, student, 30)
    assert quiet["rows"] == [] and quiet["streak"] == 0 and quiet["active_days"] == 0
    conn.close()


def test_report_pdf_route_uses_stored_choice_or_form_choice(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.set_level(conn, uid, "matte", 1)
    conn.commit()
    conn.close()
    login(client, "admin", "adminpass1")
    for url in (f"/admin/student/{uid}/report.pdf", f"/admin/student/{uid}/report.pdf?subjects=matte&subjects=kpop",
                f"/admin/student/{uid}/report.pdf?subjects=finns_inte"):
        r = client.get(url)
        assert r.status_code == 200 and r.content.startswith(b"%PDF"), url


def test_admin_can_save_subject_choices_in_the_ui(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    conn.close()
    login(client, "admin", "adminpass1")
    page = client.get(f"/admin/student/{uid}").text
    assert "Ämnen för Mia" in page and "Fritid och skoj" in page
    kpop_report = re.search(r'<input type="checkbox" name="report" value="kpop"[^>]*>', page).group(0)
    assert "checked" not in kpop_report                                 # standard: inte med i rapporten
    assert "checked" in re.search(r'<input type="checkbox" name="enabled" value="kpop"[^>]*>', page).group(0)

    r = client.post(f"/admin/student/{uid}/subjects",
                    data={"enabled": ["matte", "svenska", "kpop"], "report": ["matte", "kpop"]})
    assert r.status_code == 303
    page = client.get(f"/admin/student/{uid}").text
    assert "checked" in re.search(r'<input type="checkbox" name="report" value="kpop"[^>]*>', page).group(0)
    assert "checked" not in re.search(r'<input type="checkbox" name="report" value="svenska"[^>]*>', page).group(0)
    assert "checked" not in re.search(r'<input type="checkbox" name="enabled" value="fysik"[^>]*>', page).group(0)
    assert "avstängt för eleven" in page
    overview = client.get("/admin").text
    assert "Avstängda för eleven" in overview and "Fysik" in overview
    assert client.post("/admin/student/9999/subjects", data={}).status_code == 404
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert client.post(f"/admin/student/{uid}/subjects", data={}).status_code in (303, 403)   # elever får inte ändra
    assert "Fysik" not in client.get("/home").text


def test_upgrade_adds_the_table_without_losing_data(client):
    _make_student(client)
    conn = _conn()
    conn.execute("DROP TABLE user_subjects")
    conn.commit()
    conn.close()
    database.init_db()                                                   # som vid start efter en uppgradering
    conn = _conn()
    assert conn.execute("SELECT COUNT(*) FROM users WHERE username='mia'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM user_subjects").fetchone()[0] == 0
    assert all(v["enabled"] for v in logic.subject_settings(conn, _uid(conn)).values())
    conn.close()
