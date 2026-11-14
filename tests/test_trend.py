"""Tester för utveckling över tid: andel rätt per vecka och ämne, och sidorna som visar den."""
import re
from datetime import datetime, time, timedelta, timezone

from app import logic, trend

from .conftest import login
from .test_features import _conn, _make_student


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


def _monday(weeks_ago=0):
    return trend.week_start(logic.today()) - timedelta(weeks=weeks_ago)


def _add(conn, uid, subject, correct, day, at=time(12, 0)):
    """Ett svar i ett ämne, vid en lokal tidpunkt."""
    ex = conn.execute("SELECT id FROM exercises WHERE subject=? AND generator IS NULL AND active=1 LIMIT 1", (subject,)).fetchone()["id"]
    when = datetime.combine(day, at, logic.TZ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO attempts (user_id, exercise_id, given, correct, created_at) VALUES (?,?,?,?,?)",
                 (uid, ex, "x", correct, when))


def _fill(conn, uid, subject, weeks_ago, n, right):
    """n svar (varav right rätta) under en vecka, spridda över veckans dagar."""
    for i in range(n):
        _add(conn, uid, subject, 1 if i < right else 0, _monday(weeks_ago) + timedelta(days=i % 5))
    conn.commit()


def _student(client, name="mia"):
    _make_student(client, name)
    conn = _conn()
    return conn, _uid(conn, name)


# ------------------------------------------------------------------ uträkning

def test_weeks_are_local_monday_to_sunday(client):
    conn, uid = _student(client)
    _add(conn, uid, "matte", 1, _monday(1) + timedelta(days=6), time(23, 30))      # söndag kväll, förra veckan
    _add(conn, uid, "matte", 0, _monday(0), time(0, 10))                            # måndag natt, den här veckan
    conn.commit()
    series = trend.build(conn, uid, ["matte"], None, 8)["all"]["series"]
    assert (series[-2]["n"], series[-2]["correct"]) == (1, 1)
    assert (series[-1]["n"], series[-1]["correct"]) == (1, 0)
    conn.close()


def test_percentage_per_week_and_subject_with_gaps(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 4, 10, 5)
    _fill(conn, uid, "matte", 3, 8, 6)
    _fill(conn, uid, "matte", 1, 6, 6)
    _fill(conn, uid, "svenska", 3, 4, 1)
    data = trend.build(conn, uid, ["matte", "svenska"], None, 8)
    matte = next(e for e in data["subjects"] if e["key"] == "matte")
    assert [p["pct"] for p in matte["series"][-5:]] == [50, 75, None, 100, None]
    assert matte["n"] == 24
    assert [e["key"] for e in data["subjects"]] == ["matte", "svenska"]               # flest svar först
    assert data["all"]["series"][-4]["n"] == 12 and data["all"]["series"][-4]["pct"] == 58   # 7 av 12
    # veckor utan svar bryter linjen: två skilda linjer, inte en som påstår något om veckan emellan
    assert str(matte["svg"]).count('class="tr-seg"') == 1                               # bara 50 -> 75 hänger ihop
    assert str(data["all"]["svg"]).count('class="tr-seg"') == 1
    conn.close()


def test_axis_starts_at_the_first_answer_but_never_shows_fewer_than_four_weeks(client):
    conn, uid = _student(client)
    assert trend.build(conn, uid, ["matte"], None, 12)["count"] == 4                  # inga svar än
    assert trend.build(conn, uid, ["matte"], None, 12)["ever"] is False
    _fill(conn, uid, "matte", 1, 3, 2)
    assert trend.build(conn, uid, ["matte"], None, 12)["count"] == 4
    _fill(conn, uid, "matte", 6, 3, 2)
    assert trend.build(conn, uid, ["matte"], None, 12)["count"] == 7
    _fill(conn, uid, "matte", 20, 3, 2)
    assert trend.build(conn, uid, ["matte"], None, 12)["count"] == 12
    assert trend.build(conn, uid, ["matte"], None, 8)["count"] == 8
    assert trend.build(conn, uid, ["matte"], None, 26)["count"] == 21
    conn.close()


def test_weeks_with_few_answers_are_drawn_as_hollow_rings(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 2, trend.UNSURE_BELOW - 1, 4)
    _fill(conn, uid, "matte", 1, trend.UNSURE_BELOW, 4)
    svg = str(trend.build(conn, uid, ["matte"], None, 8)["subjects"][0]["svg"])
    assert svg.count('class="tr-dot low"') == 1 and svg.count('class="tr-dot"') == 1
    assert svg.count('class="tr-seg low"') == 1 and svg.count('class="tr-seg"') == 0       # linjen mot en osäker vecka är streckad
    assert "få svar så det är osäkert" in svg
    conn.close()


def test_the_headline_week_is_the_latest_one_with_enough_answers(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 1, 10, 8)
    _fill(conn, uid, "matte", 0, 2, 0)                                                  # två svar i veckan som pågår
    latest = trend.build(conn, uid, ["matte"], None, 8)["subjects"][0]["latest"]
    assert latest["pct"] == 80 and latest["n"] == 10 and latest["current"] is False and latest["unsure"] is False
    conn.execute("DELETE FROM attempts WHERE user_id=?", (uid,))
    _fill(conn, uid, "matte", 0, 2, 2)                                                  # bara en osäker vecka finns
    latest = trend.build(conn, uid, ["matte"], None, 8)["subjects"][0]["latest"]
    assert latest["unsure"] is True and latest["current"] is True
    conn.close()


def test_comparison_needs_enough_answers_in_both_halves(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 7, 12, 6)                                                 # första halvan: 50 %
    _fill(conn, uid, "matte", 1, 12, 9)                                                 # sista halvan: 75 %
    change = trend.build(conn, uid, ["matte"], None, 8)["all"]["change"]
    assert (change["first"], change["last"], change["diff"], change["direction"]) == (50, 75, 25, 1)
    assert change["first_weeks"].count("v") == 2 and change["last_weeks"].count("v") == 2     # t.ex. v36–v39
    conn.execute("DELETE FROM attempts WHERE user_id=?", (uid,))
    _fill(conn, uid, "matte", 7, 9, 5)                                                  # bara 9 svar i första halvan
    _fill(conn, uid, "matte", 1, 12, 9)
    assert trend.build(conn, uid, ["matte"], None, 8)["all"]["change"] is None
    conn.execute("DELETE FROM attempts WHERE user_id=?", (uid,))
    _fill(conn, uid, "matte", 7, 20, 10)
    _fill(conn, uid, "matte", 1, 20, 11)                                                # 50 -> 55: uppåt
    assert trend.build(conn, uid, ["matte"], None, 8)["all"]["change"]["direction"] == 1
    conn.execute("DELETE FROM attempts WHERE user_id=?", (uid,))
    _fill(conn, uid, "matte", 7, 100, 50)
    _fill(conn, uid, "matte", 1, 100, 51)                                               # 50 -> 51
    assert trend.build(conn, uid, ["matte"], None, 8)["all"]["change"]["direction"] == 0
    conn.execute("DELETE FROM attempts WHERE user_id=?", (uid,))
    _fill(conn, uid, "matte", 7, 100, 80)
    _fill(conn, uid, "matte", 1, 100, 60)
    assert trend.build(conn, uid, ["matte"], None, 8)["all"]["change"]["direction"] == -1
    conn.close()


def test_all_subjects_counts_only_the_ones_in_the_report(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 1, 10, 8)
    _fill(conn, uid, "kpop", 1, 10, 2)
    data = trend.for_student(conn, uid, 8)
    assert data["all"]["series"][-2] == {"n": 10, "correct": 8, "pct": 80}             # K-pop är inte med
    assert data["left_out"] == ["K-pop"]
    assert [e["key"] for e in data["subjects"]] == ["kpop", "matte"]                  # lika många svar: i bokstavsordning
    conn.close()


def test_student_sees_only_enabled_subjects_but_admin_sees_all(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 1, 6, 3)
    _fill(conn, uid, "fysik", 1, 6, 3)
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, [s for s in subjects if s != "fysik"], subjects, subjects)
    conn.commit()
    assert {e["key"] for e in trend.for_student(conn, uid, 8)["subjects"]} == {"matte"}
    assert {e["key"] for e in trend.for_student(conn, uid, 8, only_enabled=False)["subjects"]} == {"matte", "fysik"}
    conn.close()


def test_table_has_one_row_per_week_newest_first(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 1, 12, 9)
    data = trend.build(conn, uid, ["matte"], None, 8)
    assert len(data["table"]) == data["count"] == len(data["weeks"])
    assert data["table"][0]["week"].endswith("(pågår)") and data["table"][1]["cells"] == ["75 % (12)", "75 % (12)"]
    assert data["table"][2]["cells"] == ["–", "–"]
    assert data["table_head"] == ["Vecka", "Alla ämnen", "Matematik"]
    conn.close()


def test_clean_weeks_only_allows_the_offered_choices():
    assert [trend.clean_weeks(v) for v in ("8", "12", "26", "52", 26)] == [8, 12, 26, 52, 26]
    assert [trend.clean_weeks(v) for v in ("", None, "7", "banan", "-1", "999", "12.5")] == [12] * 7


def test_chart_text_is_escaped():
    series = [{"n": 6, "correct": 3, "pct": 50}] * 4
    weeks = [{"start": datetime(2026, 11, 2).date(), "num": 45, "label": "v45", "current": False}] * 4
    svg = str(trend._svg('<script>alert(1)</script>', series, weeks, big=True, mark=3))
    assert "<script" not in svg and "&lt;script&gt;" in svg


# ------------------------------------------------------------------ sidorna

def test_student_page_shows_the_charts(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 2, 10, 5)
    _fill(conn, uid, "matte", 1, 10, 8)
    conn.close()
    login(client, "mia", "hemligt1")
    page = client.get("/utveckling")
    assert page.status_code == 200
    assert "Din utveckling" in page.text and "Alla ämnen tillsammans" in page.text and "Matematik" in page.text
    assert page.text.count("<svg") >= 2 and "Visa siffrorna" in page.text
    assert 'href="/utveckling" class=active' in page.text
    assert "<strong>12 veckor</strong>" in page.text and "?veckor=26#utveckling" in page.text
    assert "<strong>26 veckor</strong>" in client.get("/utveckling?veckor=26").text
    assert "<strong>12 veckor</strong>" in client.get("/utveckling?veckor=banan").text    # okänt val ger standard
    assert client.get("/home").text.count('class=active') == 1 and 'href="/utveckling"' in client.get("/home").text


def test_student_without_answers_gets_a_friendly_page_without_period_links(client):
    _student(client)[0].close()
    login(client, "mia", "hemligt1")
    page = client.get("/utveckling")
    assert page.status_code == 200 and "Inga svar än" in page.text and "?veckor=" not in page.text and "<svg" not in page.text


def test_old_answers_outside_the_period_suggest_a_longer_one(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 30, 8, 4)
    conn.close()
    login(client, "mia", "hemligt1")
    page = client.get("/utveckling?veckor=8")
    assert "Välj en längre period" in page.text and "?veckor=52#utveckling" in page.text
    assert "<svg" in client.get("/utveckling?veckor=52").text


def test_only_students_have_the_page(client):
    r = client.get("/utveckling")
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    login(client, "admin", "adminpass1")
    assert client.get("/utveckling").status_code == 403
    assert 'href="/utveckling"' not in client.get("/admin").text


def test_admin_sees_the_same_charts_on_the_student_page_and_a_link_from_the_overview(client):
    conn, uid = _student(client)
    _fill(conn, uid, "matte", 2, 10, 5)
    _fill(conn, uid, "matte", 1, 10, 8)
    _fill(conn, uid, "fysik", 1, 10, 8)
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, [s for s in subjects if s != "fysik"], subjects, subjects)   # avstängt för eleven
    conn.commit()
    conn.close()
    login(client, "admin", "adminpass1")
    page = client.get(f"/admin/student/{uid}")
    assert "Utveckling över tid" in page.text and 'id="utveckling"' in page.text
    assert "Matematik" in page.text and "Fysik" in page.text and page.text.count("<svg") >= 3
    assert f"/admin/student/{uid}?veckor=26#utveckling" in page.text
    assert "<strong>26 veckor</strong>" in client.get(f"/admin/student/{uid}?veckor=26").text
    assert client.get(f"/admin/student/{uid}?veckor=oj").status_code == 200
    assert f'/admin/student/{uid}#utveckling' in client.get("/admin").text
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert "Fysik" not in client.get("/utveckling").text                                    # eleven ser bara sina ämnen
