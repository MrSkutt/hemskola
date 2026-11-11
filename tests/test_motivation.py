"""Tester för val av område, dagsmål, poäng, märken och belöningar."""
import glob
import json
from datetime import date, timedelta
from pathlib import Path

from app import areas, generators, logic, motivation

from .conftest import login
from .test_features import _conn, _make_student


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


def _ins(conn, uid, subject, n, correct=1, test_id=None, created=None, topic=None):
    """Lägger in n svar direkt i databasen (utan nivåbyte och dagsmål)."""
    q = "SELECT id FROM exercises WHERE subject=? AND active=1" + (" AND topic=?" if topic else "") + " LIMIT 1"
    ex = conn.execute(q, (subject, topic) if topic else (subject,)).fetchone()["id"]
    for _ in range(n):
        conn.execute(
            "INSERT INTO attempts(user_id, exercise_id, test_id, given, correct, created_at) "
            "VALUES (?,?,?,?,?,COALESCE(?, datetime('now')))", (uid, ex, test_id, "x", correct, created))
    conn.commit()


def _answer(conn, uid, subject, right=True):
    item = logic.next_item(conn, uid, subject)
    return logic.record_attempt(conn, uid, item, item["answers"][0] if right else "fel-svar-zzz")


def _student(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    return conn, uid


# ------------------------------------------------------------------ områden

def test_all_builtin_topics_belong_to_an_area():
    topics = {}
    for f in glob.glob(str(Path(areas.__file__).parent / "seed" / "*.json")):
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        for e in data.get("exercises", []) if isinstance(data, dict) else data:
            if isinstance(e, dict) and e.get("subject") and e.get("topic"):
                topics.setdefault(e["subject"], set()).add(e["topic"])
    for g in generators.REGISTRY.values():
        topics.setdefault(g.subject, set()).add(g.topic)
    missing = [(s, t) for s, ts in topics.items() for t in ts if areas.area_of(s, t) == areas.OVRIGT]
    assert missing == []


def test_area_table_has_no_duplicate_topics_within_a_subject():
    for subject, groups in areas.AREAS.items():
        seen = {}
        for name, topics in groups.items():
            for t in topics:
                assert t not in seen, (subject, t, seen[t], name)
                seen[t] = name


def test_subject_areas_and_picking_stay_inside_the_chosen_area(client):
    conn, uid = _student(client)
    offered = logic.subject_areas(conn, "matte")
    names = [a["name"] for a in offered]
    assert "Geometri" in names and "Bråk, decimaltal och procent" in names
    assert all(a["n"] >= 1 for a in offered)
    logic.set_level(conn, uid, "matte", 2)
    for _ in range(40):
        ex = logic.exercise_row(conn, logic.pick_exercise(conn, uid, "matte", area="Geometri"))
        assert areas.area_of("matte", ex["topic"]) == "Geometri"
    conn.close()


def test_weakest_area(client):
    conn, uid = _student(client)
    assert logic.weakest_area(conn, uid, "matte") is None            # inga svar än
    _ins(conn, uid, "matte", 6, correct=0, topic="Area")             # Geometri: alla fel
    _ins(conn, uid, "matte", 6, correct=1, topic="Bråk")             # Bråk: alla rätt
    assert logic.weakest_area(conn, uid, "matte") == "Geometri"
    conn.close()


def test_practice_keeps_the_area_through_the_loop(client):
    _make_student(client)
    conn = _conn()
    logic.set_level(conn, _uid(conn), "matte", 2)
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    home = client.get("/home").text
    assert 'name="omrade"' in home and "Mitt svagaste område" in home and "Geometri" in home

    page = client.get("/practice/matte?omrade=Geometri")
    assert page.status_code == 200 and "Område: <strong>Geometri</strong>" in page.text
    assert 'action="/practice/matte?omrade=Geometri"' in page.text
    ex_id = page.text.split('name="exercise_id" value="')[1].split('"')[0]
    gen = page.text.split('name="generated_id" value="')[1].split('"')[0]
    r = client.post("/practice/matte?omrade=Geometri", data={"exercise_id": ex_id, "generated_id": gen, "given": "9999"})
    assert r.status_code == 303 and "omrade=Geometri" in r.headers["location"]
    answer = client.get(r.headers["location"]).text
    assert 'href="/practice/matte?omrade=Geometri"' in answer


def test_unknown_area_is_ignored_and_can_be_switched_off(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.set_level(conn, uid, "matte", 1)
    conn.commit()
    login(client, "mia", "hemligt1")
    page = client.get("/practice/matte?omrade=Finns+inte").text
    assert "Område:" not in page
    assert "Område: <strong>Geometri</strong>" in client.get("/practice/matte?omrade=Geometri").text
    logic.save_prefs(conn, uid, False, 15, True, True)
    conn.commit()
    conn.close()
    assert "Område:" not in client.get("/practice/matte?omrade=Geometri").text
    home = client.get("/home").text
    assert 'name="omrade"' not in home and 'href="/practice/matte"' in home


def test_weakest_area_choice_without_answers_falls_back_with_a_message(client):
    _make_student(client)
    conn = _conn()
    logic.set_level(conn, _uid(conn), "matte", 1)
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    page = client.get("/practice/matte?omrade=svagast")
    assert page.status_code == 200 and "svagaste område" in page.text and "Område: <strong>" not in page.text


# ------------------------------------------------------------------ inställningar

def test_prefs_defaults_and_clamping(client):
    conn, uid = _student(client)
    p = logic.get_prefs(conn, uid)
    assert p["areas_on"] and p["points_on"] and p["badges_on"] and p["daily_goal"] == 15 and p["points_since"]
    logic.save_prefs(conn, uid, False, 9999, False, False)
    conn.commit()
    p = logic.get_prefs(conn, uid)
    assert not p["areas_on"] and not p["points_on"] and not p["badges_on"] and p["daily_goal"] == 200
    logic.save_prefs(conn, uid, True, -5, True, True)
    assert logic.get_prefs(conn, uid)["daily_goal"] == 0
    conn.close()


def test_points_start_is_not_moved_by_later_visits(client):
    conn, uid = _student(client)
    first = logic.get_prefs(conn, uid)["points_since"]
    conn.execute("UPDATE user_prefs SET points_since='2021-05-05 10:00:00' WHERE user_id=?", (uid,))
    conn.commit()
    assert logic.get_prefs(conn, uid)["points_since"] != first
    assert logic.get_prefs(conn, uid)["points_since"] == "2021-05-05 10:00:00"
    conn.close()


def test_admin_can_save_prefs_and_students_cannot(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    login(client, "mia", "hemligt1")
    r = client.post(f"/admin/student/{uid}/prefs", data={"daily_goal": "50"})
    assert r.status_code in (302, 303, 401, 403) and logic.get_prefs(conn, uid)["daily_goal"] == 15
    client.post("/logout")
    login(client, "admin", "adminpass1")
    page = client.get(f"/admin/student/{uid}").text
    assert "Dagsmål, poäng och belöningar" in page and 'name="daily_goal"' in page
    r = client.post(f"/admin/student/{uid}/prefs", data={"daily_goal": "25", "points_on": "1"})
    assert r.status_code == 303
    p = logic.get_prefs(conn, uid)
    assert p["daily_goal"] == 25 and p["points_on"] and not p["areas_on"] and not p["badges_on"]
    assert client.post("/admin/student/9999/prefs", data={"daily_goal": "5"}).status_code == 404
    conn.close()


# ------------------------------------------------------------------ dagsmål

def test_goal_is_reached_by_school_answers_only(client):
    conn, uid = _student(client)
    logic.save_prefs(conn, uid, True, 3, True, True)
    conn.commit()
    for _ in range(5):                                  # K-pop räknas inte
        _answer(conn, uid, "kpop")
    st = logic.goal_status(conn, uid)
    assert st["done"] == 0 and not st["reached"]
    assert conn.execute("SELECT COUNT(*) FROM goal_days").fetchone()[0] == 0
    _answer(conn, uid, "matte"); _answer(conn, uid, "svenska")
    assert not logic.goal_status(conn, uid)["reached"]
    _answer(conn, uid, "fysik", right=False)            # fel svar räknas också som ett svar
    st = logic.goal_status(conn, uid)
    assert st["done"] == 3 and st["reached"] and st["streak"] == 1 and st["pct"] == 100
    assert conn.execute("SELECT day FROM goal_days WHERE user_id=?", (uid,)).fetchone()["day"] == logic.today().isoformat()
    conn.close()


def test_goal_zero_means_no_goal(client):
    conn, uid = _student(client)
    logic.save_prefs(conn, uid, True, 0, True, True)
    conn.commit()
    for _ in range(4):
        _answer(conn, uid, "matte")
    assert conn.execute("SELECT COUNT(*) FROM goal_days").fetchone()[0] == 0
    assert logic.goal_status(conn, uid)["pct"] == 0
    conn.close()


def test_goal_streak_counts_consecutive_days(client):
    conn, uid = _student(client)
    t = logic.today()
    for back in (1, 2, 3, 5):
        conn.execute("INSERT INTO goal_days(user_id, day) VALUES (?,?)", (uid, (t - timedelta(days=back)).isoformat()))
    conn.commit()
    assert logic.goal_status(conn, uid)["streak"] == 3     # igår, i förrgår och dagen före
    conn.close()


def test_day_runs():
    d = date(2026, 1, 1)
    days = [d, d + timedelta(1), d + timedelta(2), d + timedelta(5), d + timedelta(6), d + timedelta(9)]
    assert logic.day_runs(days) == [3, 2, 1]
    assert logic.day_runs([]) == [] and logic.day_runs(["2026-02-01", "2026-02-02"]) == [2]


# ------------------------------------------------------------------ poäng

def test_points_for_correct_practice_answers_only(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 4, correct=1)
    _ins(conn, uid, "matte", 3, correct=0)
    _ins(conn, uid, "kpop", 5, correct=1)                          # K-pop ger inga poäng
    conn.execute("INSERT INTO tests(user_id, subject, kind, total) VALUES (?, 'matte', 'status', 10)", (uid,))
    _ins(conn, uid, "matte", 5, correct=1, test_id=conn.execute("SELECT MAX(id) FROM tests").fetchone()[0])  # prov ger inga
    assert motivation.points(conn, uid)["answers"] == 40
    conn.close()


def test_points_are_capped_per_subject_and_day(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 25)
    _ins(conn, uid, "svenska", 4)
    assert motivation.points(conn, uid)["answers"] == (15 + 4) * 10
    _ins(conn, uid, "matte", 25, created=(logic.today() - timedelta(days=1)).isoformat() + " 12:00:00")
    conn.execute("UPDATE user_prefs SET points_since='2020-01-01 00:00:00' WHERE user_id=?", (uid,))
    conn.commit()
    assert motivation.points(conn, uid)["answers"] == (15 + 4 + 15) * 10    # ny dag, nytt tak
    conn.close()


def test_points_only_count_from_the_start_date(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 8, created="2020-03-03 10:00:00")
    _ins(conn, uid, "matte", 2)
    assert motivation.points(conn, uid)["answers"] == 20
    conn.close()


def test_bonus_points_for_goal_days_weeks_and_level_ups(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    conn.execute("UPDATE user_prefs SET points_since='2020-01-01 00:00:00' WHERE user_id=?", (uid,))
    start = date(2026, 3, 1)
    for i in range(8):                                    # 8 dagar i rad: en hel vecka
        conn.execute("INSERT INTO goal_days(user_id, day) VALUES (?,?)", (uid, (start + timedelta(days=i)).isoformat()))
    conn.execute("INSERT INTO goal_days(user_id, day) VALUES (?,?)", (uid, "2026-03-20"))
    conn.execute("INSERT INTO level_ups(user_id, subject, level) VALUES (?, 'matte', 2)", (uid,))
    conn.commit()
    p = motivation.points(conn, uid)
    assert p["goal"] == 9 * 20 and p["week"] == 50 and p["levels"] == 50
    assert p["total"] == 9 * 20 + 50 + 50
    conn.close()


def test_level_up_by_practice_is_recorded_once(client):
    conn, uid = _student(client)
    logic.set_level(conn, uid, "matte", 1)
    conn.commit()
    changes = [_answer(conn, uid, "matte")[2] for _ in range(6)]
    assert changes[-1] == "up"
    rows = conn.execute("SELECT subject, level FROM level_ups WHERE user_id=?", (uid,)).fetchall()
    assert [(r["subject"], r["level"]) for r in rows] == [("matte", 2)]
    assert motivation.points(conn, uid)["levels"] == 50
    conn.execute("INSERT OR IGNORE INTO level_ups(user_id, subject, level) VALUES (?, 'matte', 2)", (uid,))
    assert conn.execute("SELECT COUNT(*) FROM level_ups").fetchone()[0] == 1
    conn.close()


# ------------------------------------------------------------------ belöningar

def test_reward_validation(client):
    conn, uid = _student(client)
    assert motivation.add_reward(conn, uid, "  Bio   kväll ", "300") == ""
    assert conn.execute("SELECT title FROM rewards").fetchone()["title"] == "Bio kväll"
    for title, cost in (("", "10"), ("X", "0"), ("X", "abc"), ("X", "-5"), ("X", "100001"), ("X", "")):
        assert motivation.add_reward(conn, uid, title, cost) != ""
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 1
    conn.close()


def test_giving_a_reward_costs_points_and_can_be_undone(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 10)                                   # 100 poäng
    motivation.add_reward(conn, uid, "Glass", 60)
    motivation.add_reward(conn, uid, "Bio", 80)
    rid = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM rewards")}
    p = motivation.points(conn, uid)
    rewards = motivation.reward_list(conn, uid, p["balance"])
    assert [r["title"] for r in rewards] == ["Glass", "Bio"] and all(r["ready"] for r in rewards)
    assert motivation.give_reward(conn, uid, rid["Glass"]) == ""
    assert motivation.give_reward(conn, uid, rid["Glass"]) != ""        # redan utdelad
    p = motivation.points(conn, uid)
    assert p["spent"] == 60 and p["balance"] == 40
    assert motivation.give_reward(conn, uid, rid["Bio"]) != ""          # 40 räcker inte till 80
    rewards = motivation.reward_list(conn, uid, p["balance"])
    bio = [r for r in rewards if r["title"] == "Bio"][0]
    assert not bio["ready"] and bio["missing"] == 40 and bio["pct"] == 50
    assert [r["title"] for r in rewards] == ["Bio", "Glass"]            # utdelade sist
    assert motivation.next_reward(rewards)["title"] == "Bio"
    motivation.undo_reward(conn, uid, rid["Glass"])
    assert motivation.points(conn, uid)["balance"] == 100
    motivation.delete_reward(conn, uid, rid["Bio"])
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 1
    conn.close()


def test_admin_reward_routes(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 10)
    login(client, "admin", "adminpass1")
    assert client.post(f"/admin/student/{uid}/rewards", data={"title": "Bio-kväll", "cost": "50"}).status_code == 303
    assert client.post(f"/admin/student/{uid}/rewards", data={"title": "", "cost": "50"}).status_code == 303
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 1
    page = client.get(f"/admin/student/{uid}").text
    assert "Bio-kväll" in page and "uppnådd, kan delas ut" in page
    rid = conn.execute("SELECT id FROM rewards").fetchone()["id"]
    assert client.post(f"/admin/student/{uid}/rewards/{rid}", data={"action": "give"}).status_code == 303
    assert "utdelad" in client.get(f"/admin/student/{uid}").text
    assert client.post(f"/admin/student/{uid}/rewards/{rid}", data={"action": "oops"}).status_code == 400
    assert client.post(f"/admin/student/{uid}/rewards/{rid}", data={"action": "delete"}).status_code == 303
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 0
    client.post("/logout")
    login(client, "mia", "hemligt1")
    r = client.post(f"/admin/student/{uid}/rewards", data={"title": "Egen", "cost": "1"})
    assert r.status_code in (302, 303, 401, 403)
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 0
    conn.close()


def test_rewards_of_one_student_are_not_given_via_another(client):
    _make_student(client)
    _make_student(client, "olle")
    conn = _conn()
    mia, olle = _uid(conn), _uid(conn, "olle")
    logic.get_prefs(conn, mia)
    _ins(conn, mia, "matte", 10)
    motivation.add_reward(conn, mia, "Glass", 10)
    rid = conn.execute("SELECT id FROM rewards").fetchone()["id"]
    assert motivation.give_reward(conn, olle, rid) == "Belöningen finns inte."
    motivation.delete_reward(conn, olle, rid)
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 1
    conn.close()


# ------------------------------------------------------------------ märken

def test_badges_follow_the_answers(client):
    conn, uid = _student(client)

    def earned():
        return {b["key"] for b in motivation.badges(conn, uid) if b["earned"]}

    assert earned() == set()
    _ins(conn, uid, "matte", 1)
    assert earned() == {"forsta"}
    _ins(conn, uid, "matte", 99)
    assert {"svar100", "ratt10"} <= earned() and "svar500" not in earned()
    _ins(conn, uid, "kpop", 900)                                   # K-pop räknas inte
    assert "svar500" not in earned()
    conn.close()


def test_streak_and_exploration_badges(client):
    conn, uid = _student(client)
    t = logic.today()
    for back in range(3):
        _ins(conn, uid, "matte", 1, created=(t - timedelta(days=back)).isoformat() + " 12:00:00")
    for s in ("svenska", "engelska", "fysik", "kemi"):
        _ins(conn, uid, s, 1)
    got = {b["key"] for b in motivation.badges(conn, uid) if b["earned"]}
    assert "rad3" in got and "rad7" not in got and "utforskare" in got
    conn.close()


def test_level_and_test_badges(client):
    conn, uid = _student(client)
    logic.set_level(conn, uid, "matte", 4)
    conn.execute("INSERT INTO tests(user_id, subject, kind, total, score, finished_at) VALUES (?, 'matte', 'status', 10, 10, datetime('now'))", (uid,))
    conn.execute("INSERT INTO level_ups(user_id, subject, level) VALUES (?, 'matte', 4)", (uid,))
    conn.commit()
    got = {b["key"] for b in motivation.badges(conn, uid) if b["earned"]}
    assert {"niva4", "prov1", "fullt", "uppat"} <= got and "niva5" not in got
    conn.close()


def test_badge_keys_are_unique():
    keys = [b[0] for b in motivation.BADGES]
    assert len(keys) == len(set(keys))


# ------------------------------------------------------------------ elevens sidor

def test_home_panel_and_progress_page(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 12)
    motivation.add_reward(conn, uid, "Bio-kväll", 500)
    conn.commit()
    login(client, "mia", "hemligt1")
    home = client.get("/home").text
    assert "Dagsmål" in home and "Poäng" in home and "Märken" in home and 'href="/framsteg"' in home
    assert "Bio-kväll" in home and "380 poäng kvar" in home          # 12 svar = 120 poäng, 500 - 120
    page = client.get("/framsteg")
    assert page.status_code == 200
    assert "Så får du poäng" in page.text and "Bio-kväll" in page.text and "Första steget" in page.text
    conn.close()


def test_everything_can_be_switched_off_per_student(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.save_prefs(conn, uid, False, 0, False, False)
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    home = client.get("/home").text
    assert "Dagsmål" not in home and "🏅" not in home and "/framsteg" not in home and 'name="omrade"' not in home
    assert client.get("/framsteg").status_code == 303                # inget att visa -> tillbaka till Övningar


def test_parts_can_be_switched_off_one_by_one(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.save_prefs(conn, uid, True, 20, False, True)               # utan poäng
    conn.commit()
    login(client, "mia", "hemligt1")
    home = client.get("/home").text
    assert "Dagsmål" in home and "⭐ Poäng" not in home and "Märken" in home
    page = client.get("/framsteg").text
    assert "Belöningar" not in page and "Så får du poäng" not in page and "Märken" in page
    logic.save_prefs(conn, uid, True, 0, True, False)                # utan dagsmål och märken
    conn.commit()
    conn.close()
    home = client.get("/home").text
    assert "Dagsmål" not in home and "⭐ Poäng" in home and "🏅" not in home


def test_new_tables_are_added_to_an_existing_database(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, password_hash TEXT, role TEXT);"
                      "INSERT INTO users(username, display_name, password_hash, role) VALUES ('a','A','x','student');")
    old.commit()
    old.close()
    from app import db
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    conn = db.connect()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"user_prefs", "goal_days", "level_ups", "rewards"} <= tables
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()
