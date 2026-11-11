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
    # en utdelad belöning döljs i stället för att raderas, så att de använda poängen fortsätter dras av
    assert conn.execute("SELECT COUNT(*) FROM rewards WHERE retired=0").fetchone()[0] == 0
    assert motivation.points(conn, uid)["spent"] == 50
    conn.commit()                                                       # släpp lånet så att appen kan skriva igen
    assert f"/rewards/{rid}" not in client.get(f"/admin/student/{uid}").text   # syns inte längre i listan
    client.post("/logout")
    login(client, "mia", "hemligt1")
    r = client.post(f"/admin/student/{uid}/rewards", data={"title": "Egen", "cost": "1"})
    assert r.status_code in (302, 303, 401, 403)
    assert conn.execute("SELECT COUNT(*) FROM rewards WHERE title='Egen'").fetchone()[0] == 0   # elever kan inte lägga till
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


# ------------------------------------------------------------------ elevlistan i admin

def test_admin_student_list_is_collapsed_by_default(client):
    _make_student(client)
    _make_student(client, "olle")
    login(client, "admin", "adminpass1")
    page = client.get("/admin").text
    assert page.count('<details class="card student">') == 2            # en rad per elev, stängd som standard
    assert "<details class=\"card student\" open" not in page
    assert 'href="/admin/student/' in page and "Mia" in page and "Olle" in page
    assert "Visa alla" in page and "Dölj alla" in page
    assert "Idag: 0 svar" in page and "Senaste 7 dagarna" in page          # ämnesöversikten finns inuti raden


# ---------------------------------------------------------------- belöningar som kan tas ut flera gånger

def test_repeatable_reward_can_be_given_again_until_points_run_out(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 13)                                        # 130 poäng
    assert motivation.add_reward(conn, uid, "Godis", 50, repeatable=True) == ""
    rid = conn.execute("SELECT id FROM rewards").fetchone()["id"]
    r = motivation.reward_list(conn, uid, motivation.points(conn, uid)["balance"])[0]
    assert r["repeatable"] and r["ready"] and not r["given"] and r["times_given"] == 0
    assert motivation.give_reward(conn, uid, rid) == ""
    assert motivation.give_reward(conn, uid, rid) == ""                 # går att dela ut igen
    p = motivation.points(conn, uid)
    assert (p["spent"], p["balance"]) == (100, 30)                      # poängen dras för varje utdelning
    assert motivation.give_reward(conn, uid, rid) != ""                 # 30 räcker inte till 50
    r = motivation.reward_list(conn, uid, p["balance"])[0]
    assert (r["times_given"], r["given"], r["ready"], r["missing"], r["pct"]) == (2, False, False, 20, 60)
    assert motivation.next_reward([r])["title"] == "Godis"              # den är fortfarande något att sikta mot
    row = conn.execute("SELECT * FROM rewards").fetchone()
    assert row["times_given"] == 2 and row["given_at"]

    motivation.undo_reward(conn, uid, rid)                              # ångrar bara den senaste utdelningen
    assert conn.execute("SELECT times_given FROM rewards").fetchone()[0] == 1
    assert motivation.points(conn, uid)["balance"] == 80
    assert conn.execute("SELECT given_at FROM rewards").fetchone()[0] is not None
    motivation.undo_reward(conn, uid, rid)
    assert conn.execute("SELECT times_given, given_at FROM rewards").fetchone()[:] == (0, None)
    motivation.undo_reward(conn, uid, rid)                              # ingenting att ångra: aldrig negativt
    assert conn.execute("SELECT times_given FROM rewards").fetchone()[0] == 0
    assert motivation.points(conn, uid)["balance"] == 130
    conn.close()


def test_one_time_reward_is_still_one_time_and_sorted_last_when_given(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 15)                                        # 150 poäng (taket är 15 rätta per ämne och dag)
    motivation.add_reward(conn, uid, "Bio", 60)
    motivation.add_reward(conn, uid, "Godis", 30, repeatable=True)
    motivation.add_reward(conn, uid, "Glass", 60)
    rid = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM rewards")}
    assert motivation.give_reward(conn, uid, rid["Bio"]) == ""
    assert motivation.give_reward(conn, uid, rid["Bio"]) == "Den är redan utdelad."
    assert motivation.give_reward(conn, uid, rid["Godis"]) == "" and motivation.give_reward(conn, uid, rid["Godis"]) == ""
    titles = [r["title"] for r in motivation.reward_list(conn, uid, motivation.points(conn, uid)["balance"])]
    assert titles == ["Godis", "Glass", "Bio"]                          # engångsbelöningen som delats ut hamnar sist
    assert motivation.points(conn, uid)["spent"] == 60 + 30 * 2
    conn.close()


def test_deleting_a_given_reward_hides_it_but_never_refunds_points(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 13)                                        # 130 poäng
    motivation.add_reward(conn, uid, "Godis", 50, repeatable=True)
    motivation.add_reward(conn, uid, "Aldrig", 10)
    rid = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM rewards")}
    motivation.give_reward(conn, uid, rid["Godis"])
    motivation.give_reward(conn, uid, rid["Godis"])
    before = motivation.points(conn, uid)
    assert motivation.delete_reward(conn, uid, rid["Godis"]) == 100     # så många poäng räknas fortfarande som använda
    assert motivation.delete_reward(conn, uid, rid["Aldrig"]) == 0      # aldrig utdelad: raderas helt
    assert conn.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 1
    after = motivation.points(conn, uid)
    assert (after["spent"], after["balance"]) == (before["spent"], before["balance"]) == (100, 30)
    assert motivation.reward_list(conn, uid, after["balance"]) == []
    assert motivation.give_reward(conn, uid, rid["Godis"]) == "Belöningen finns inte."
    motivation.undo_reward(conn, uid, rid["Godis"])                     # en borttagen belöning går inte att ångra
    assert motivation.points(conn, uid)["spent"] == 100
    assert motivation.delete_reward(conn, uid, rid["Godis"]) == 0       # och tas inte bort två gånger
    conn.close()


def test_admin_adds_repeatable_reward_and_gives_it_twice(client):
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 12)                                        # 120 poäng
    login(client, "admin", "adminpass1")
    client.post(f"/admin/student/{uid}/rewards", data={"title": "Godis", "cost": "50", "repeatable": "1"})
    client.post(f"/admin/student/{uid}/rewards", data={"title": "Bio", "cost": "60"})
    rows = {r["title"]: r for r in conn.execute("SELECT * FROM rewards")}
    assert rows["Godis"]["repeatable"] == 1 and rows["Bio"]["repeatable"] == 0
    page = client.get(f"/admin/student/{uid}").text
    assert "flera gånger" in page and 'name="repeatable"' in page
    rid = rows["Godis"]["id"]
    for _ in range(2):
        assert client.post(f"/admin/student/{uid}/rewards/{rid}", data={"action": "give"}).status_code == 303
    page = client.get(f"/admin/student/{uid}").text
    assert "Utdelad 2 gånger" in page
    assert client.post(f"/admin/student/{uid}/rewards/{rid}", data={"action": "give"}).status_code == 303
    assert "inte tillräckligt" in client.get(f"/admin/student/{uid}").text
    assert conn.execute("SELECT times_given FROM rewards WHERE id=?", (rid,)).fetchone()[0] == 2
    client.post(f"/admin/student/{uid}/rewards/{rid}", data={"action": "undo"})
    assert "Utdelad 1 gång," in client.get(f"/admin/student/{uid}").text
    client.post(f"/admin/student/{uid}/rewards/{rid}", data={"action": "delete"})
    assert "De 50 poäng som redan använts" in client.get(f"/admin/student/{uid}").text
    assert motivation.points(conn, uid)["spent"] == 50
    conn.close()


def test_student_sees_repeatable_reward_with_count(client):
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", 12)
    motivation.add_reward(conn, uid, "Godis", 50, repeatable=True)
    rid = conn.execute("SELECT id FROM rewards").fetchone()["id"]
    motivation.give_reward(conn, uid, rid)
    motivation.give_reward(conn, uid, rid)
    conn.commit()
    client.post("/logout")
    login(client, "mia", "hemligt1")
    page = client.get("/framsteg").text
    assert "Godis" in page and "går att få flera gånger" in page and "du har fått den 2 gånger" in page
    conn.close()


def test_reward_columns_are_added_to_an_old_database_and_old_gifts_count_once(tmp_path, monkeypatch):
    import sqlite3
    from app import db as database
    path = tmp_path / "rw.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, password_hash TEXT, role TEXT,
                            active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
        INSERT INTO users(username, display_name, password_hash, role) VALUES ('mia','Mia','x','student');
        CREATE TABLE rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
            cost INTEGER NOT NULL, created_at TEXT DEFAULT (datetime('now')), given_at TEXT);
        INSERT INTO rewards(user_id, title, cost, given_at) VALUES (1, 'Gammal utdelad', 80, datetime('now'));
        INSERT INTO rewards(user_id, title, cost) VALUES (1, 'Gammal öppen', 30);
    """)
    old.commit()
    old.close()
    monkeypatch.setattr(database, "DB_PATH", str(path))
    database.init_db()
    database.init_db()                                                  # köras om utan att räkna dubbelt
    conn = database.connect()
    rows = {r["title"]: r for r in conn.execute("SELECT * FROM rewards")}
    assert (rows["Gammal utdelad"]["times_given"], rows["Gammal utdelad"]["repeatable"], rows["Gammal utdelad"]["retired"]) == (1, 0, 0)
    assert rows["Gammal öppen"]["times_given"] == 0
    assert conn.execute("SELECT COALESCE(SUM(cost * times_given), 0) FROM rewards").fetchone()[0] == 80
    conn.close()


# ---------------------------------------------------------------- eleven ber om belöningar

def _rich(client, points_rows=13):
    """Elev med poäng (130 vid 13 rader) och en belöning som kan tas ut flera gånger (50) samt en engångsbelöning (60)."""
    conn, uid = _student(client)
    logic.get_prefs(conn, uid)
    _ins(conn, uid, "matte", points_rows)
    motivation.add_reward(conn, uid, "Godis", 50, repeatable=True)
    motivation.add_reward(conn, uid, "Bio", 60)
    conn.commit()
    rid = {r["title"]: r["id"] for r in conn.execute("SELECT id, title FROM rewards")}
    return conn, uid, rid


def test_requesting_a_reward_reserves_points_but_does_not_spend_them(client):
    conn, uid, rid = _rich(client)
    assert motivation.request_reward(conn, uid, rid["Godis"], 2) == ""
    conn.commit()
    p = motivation.points(conn, uid)
    assert (p["balance"], p["reserved"], p["available"], p["spent"]) == (130, 100, 30, 0)
    assert conn.execute("SELECT times_given FROM rewards WHERE title='Godis'").fetchone()[0] == 0   # inget utdelat än
    rows = {r["title"]: r for r in motivation.reward_list(conn, uid, p["available"])}
    assert rows["Godis"]["pending"] == 2 and rows["Godis"]["request_id"] and not rows["Godis"]["can_request"]
    assert rows["Bio"]["pending"] == 0 and not rows["Bio"]["can_request"]     # 30 kvar räcker inte till 60
    assert motivation.pending_count(conn) == 1
    conn.close()


def test_request_validation(client):
    conn, uid, rid = _rich(client)
    assert motivation.request_reward(conn, uid, 9999, 1) == "Belöningen finns inte."
    assert "mellan 1 och 20" in motivation.request_reward(conn, uid, rid["Godis"], 0)
    assert "mellan 1 och 20" in motivation.request_reward(conn, uid, rid["Godis"], -3)
    assert "mellan 1 och 20" in motivation.request_reward(conn, uid, rid["Godis"], 21)
    assert "heltal" in motivation.request_reward(conn, uid, rid["Godis"], "två")
    assert "heltal" in motivation.request_reward(conn, uid, rid["Godis"], "")
    msg = motivation.request_reward(conn, uid, rid["Godis"], 3)              # 150 > 130
    assert "inte tillräckligt" in msg and "2 st" in msg                       # säger hur många som räcker
    motivation.add_reward(conn, uid, "Resa", 500)
    resa = conn.execute("SELECT id FROM rewards WHERE title='Resa'").fetchone()["id"]
    msg = motivation.request_reward(conn, uid, resa, 1)
    assert "inte tillräckligt" in msg and "st" not in msg                     # engångsbelöning: ingen "räcker till N st"
    assert conn.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 0
    conn.close()


def test_one_time_reward_can_only_be_requested_once_and_quantity_is_forced_to_one(client):
    conn, uid, rid = _rich(client)
    assert motivation.request_reward(conn, uid, rid["Bio"], 5) == ""         # antalet ignoreras för en engångsbelöning
    assert conn.execute("SELECT quantity FROM reward_requests").fetchone()[0] == 1
    assert "redan bett" in motivation.request_reward(conn, uid, rid["Bio"], 1)
    assert conn.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 1
    conn.commit()
    rows = {r["title"]: r for r in motivation.reward_list(conn, uid, motivation.points(conn, uid)["available"])}
    assert rows["Bio"]["pending"] == 1 and not rows["Bio"]["can_request"]
    conn.close()


def test_requests_for_the_same_repeatable_reward_are_merged_and_limited_by_available_points(client):
    conn, uid, rid = _rich(client)
    assert motivation.request_reward(conn, uid, rid["Godis"], 1) == ""
    conn.commit()
    assert motivation.request_reward(conn, uid, rid["Godis"], 1) == ""       # läggs på samma förfrågan
    conn.commit()
    assert conn.execute("SELECT COUNT(*), SUM(quantity) FROM reward_requests").fetchone()[:] == (1, 2)
    assert "inte tillräckligt" in motivation.request_reward(conn, uid, rid["Godis"], 1)   # 30 kvar
    assert motivation.points(conn, uid)["available"] == 30
    conn.close()


def test_cannot_request_a_reward_that_was_already_given(client):
    conn, uid, rid = _rich(client)
    assert motivation.give_reward(conn, uid, rid["Bio"]) == ""
    assert motivation.request_reward(conn, uid, rid["Bio"], 1) == "Du har redan fått den."
    conn.close()


def test_cancelling_a_request_frees_the_points_and_only_your_own(client):
    conn, uid, rid = _rich(client)
    motivation.request_reward(conn, uid, rid["Godis"], 2)
    conn.commit()
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    assert motivation.cancel_request(conn, uid + 99, qid) != ""              # någon annans förfrågan
    assert motivation.cancel_request(conn, uid, qid) == ""
    conn.commit()
    assert motivation.points(conn, uid)["available"] == 130
    assert motivation.cancel_request(conn, uid, qid) != ""                   # redan borta
    conn.close()


def test_approving_a_request_spends_the_points_for_real(client):
    conn, uid, rid = _rich(client)
    motivation.request_reward(conn, uid, rid["Godis"], 2)
    conn.commit()
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    (q,) = motivation.pending_requests(conn)
    assert (q["student"], q["title"], q["quantity"], q["total"], q["balance"], q["enough"]) == ("Mia", "Godis", 2, 100, 130, True)
    assert motivation.approve_request(conn, qid) == ""
    conn.commit()
    row = conn.execute("SELECT times_given, given_at FROM rewards WHERE title='Godis'").fetchone()
    assert row["times_given"] == 2 and row["given_at"]
    p = motivation.points(conn, uid)
    assert (p["spent"], p["balance"], p["reserved"], p["available"]) == (100, 30, 0, 30)   # inte dubbelt avdrag
    st = conn.execute("SELECT status, handled_at FROM reward_requests").fetchone()
    assert st["status"] == "approved" and st["handled_at"]
    assert motivation.pending_count(conn) == 0 and motivation.pending_requests(conn) == []
    assert motivation.approve_request(conn, qid) != ""                       # kan inte godkännas två gånger
    assert conn.execute("SELECT times_given FROM rewards WHERE title='Godis'").fetchone()[0] == 2
    conn.close()


def test_approve_fails_when_the_student_no_longer_has_the_points(client):
    conn, uid, rid = _rich(client)
    motivation.request_reward(conn, uid, rid["Godis"], 2)                    # 100 av 130 reserverade
    conn.commit()
    assert motivation.give_reward(conn, uid, rid["Bio"]) == ""               # admin delar ut Bio direkt: 60 poäng dras, 70 kvar
    conn.commit()
    (q,) = motivation.pending_requests(conn)
    assert q["balance"] == 70 and not q["enough"]
    assert "inte tillräckligt" in motivation.approve_request(conn, q["id"])
    assert conn.execute("SELECT status FROM reward_requests").fetchone()[0] == "pending"
    assert conn.execute("SELECT times_given FROM rewards WHERE title='Godis'").fetchone()[0] == 0
    assert motivation.points(conn, uid)["available"] == 0                    # aldrig negativt
    conn.close()


def test_declining_a_request_frees_the_points(client):
    conn, uid, rid = _rich(client)
    motivation.request_reward(conn, uid, rid["Godis"], 2)
    conn.commit()
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    assert motivation.decline_request(conn, qid) == ""
    conn.commit()
    assert conn.execute("SELECT status FROM reward_requests").fetchone()[0] == "declined"
    p = motivation.points(conn, uid)
    assert (p["balance"], p["reserved"], p["available"], p["spent"]) == (130, 0, 130, 0)
    assert conn.execute("SELECT times_given FROM rewards WHERE title='Godis'").fetchone()[0] == 0
    assert motivation.decline_request(conn, qid) != ""
    assert motivation.approve_request(conn, qid) != ""                       # en avslagen förfrågan kan inte godkännas
    assert motivation.request_reward(conn, uid, rid["Godis"], 2) == ""       # och eleven kan be igen
    conn.close()


def test_giving_a_one_time_reward_directly_closes_its_pending_request(client):
    conn, uid, rid = _rich(client)
    motivation.request_reward(conn, uid, rid["Bio"], 1)
    conn.commit()
    assert motivation.give_reward(conn, uid, rid["Bio"]) == ""
    conn.commit()
    assert conn.execute("SELECT status FROM reward_requests").fetchone()[0] == "approved"
    assert motivation.points(conn, uid)["reserved"] == 0
    assert motivation.points(conn, uid)["spent"] == 60                       # dras bara en gång
    conn.close()


def test_deleting_a_given_reward_declines_its_pending_requests(client):
    conn, uid, rid = _rich(client)
    motivation.give_reward(conn, uid, rid["Godis"])                          # utdelad en gång, så den döljs när den tas bort
    motivation.request_reward(conn, uid, rid["Godis"], 1)
    conn.commit()
    motivation.delete_reward(conn, uid, rid["Godis"])
    conn.commit()
    assert conn.execute("SELECT status FROM reward_requests").fetchone()[0] == "declined"
    assert motivation.pending_count(conn) == 0 and motivation.points(conn, uid)["reserved"] == 0
    conn.close()


def test_deleting_a_never_given_reward_removes_its_requests(client):
    conn, uid, rid = _rich(client)
    motivation.request_reward(conn, uid, rid["Godis"], 1)
    conn.commit()
    motivation.delete_reward(conn, uid, rid["Godis"])
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 0   # ON DELETE CASCADE
    assert motivation.pending_count(conn) == 0
    conn.close()


def test_pending_requests_are_oldest_first_and_per_student(client):
    conn, uid, rid = _rich(client)
    _make_student(client, "olle")
    conn.commit()
    olle = _uid(conn, "olle")
    logic.get_prefs(conn, olle)
    _ins(conn, olle, "matte", 6)
    motivation.add_reward(conn, olle, "Glass", 20)
    conn.commit()
    gl = conn.execute("SELECT id FROM rewards WHERE user_id=?", (olle,)).fetchone()["id"]
    assert motivation.request_reward(conn, olle, rid["Godis"], 1) == "Belöningen finns inte."   # Mias belöning
    motivation.request_reward(conn, uid, rid["Godis"], 1)
    motivation.request_reward(conn, olle, gl, 1)
    conn.commit()
    conn.execute("UPDATE reward_requests SET created_at='2020-01-01 10:00:00' WHERE user_id=?", (olle,))
    conn.commit()
    assert [q["student"] for q in motivation.pending_requests(conn)] == ["Olle", "Mia"]
    assert motivation.points(conn, olle)["reserved"] == 20 and motivation.points(conn, uid)["reserved"] == 50
    conn.close()


# --- rutter

def _req_routes(client):
    conn, uid, rid = _rich(client)
    login(client, "mia", "hemligt1")
    return conn, uid, rid


def test_student_requests_via_route_and_sees_it_pending(client):
    conn, uid, rid = _req_routes(client)
    r = client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "2"})
    assert r.status_code == 303 and r.headers["location"] == "/framsteg#belonningar"
    assert conn.execute("SELECT quantity, status FROM reward_requests").fetchone()[:] == (2, "pending")
    page = client.get("/framsteg").text
    assert "Du har bett om 2 st" in page and "ta-tillbaka" in page
    assert "100 poäng är reserverade" in page
    assert "30" in page                                                       # tillgängliga poäng
    assert 'id="belonningar"' in page
    assert f"/framsteg/belonning/{rid['Godis']}/be-om" not in page            # 30 kvar: ingen ny förfrågan av Godis
    conn.close()


def test_student_request_form_shows_quantity_only_for_repeatable(client):
    conn, uid, rid = _req_routes(client)
    page = client.get("/framsteg").text
    assert f'action="/framsteg/belonning/{rid["Godis"]}/be-om"' in page and f'action="/framsteg/belonning/{rid["Bio"]}/be-om"' in page
    godis = page.split(f'/framsteg/belonning/{rid["Godis"]}/be-om')[1].split("</form>")[0]
    bio = page.split(f'/framsteg/belonning/{rid["Bio"]}/be-om')[1].split("</form>")[0]
    assert 'name="quantity"' in godis and 'max="2"' in godis                  # 130 // 50
    assert 'name="quantity"' not in bio
    conn.close()


def test_student_route_errors_are_flashed_not_crashes(client):
    conn, uid, rid = _req_routes(client)
    for q in ("0", "99", "abc", "3"):
        r = client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": q})
        assert r.status_code == 303
    assert conn.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 0
    assert client.post("/framsteg/belonning/9999/be-om", data={"quantity": "1"}).status_code == 303
    page = client.get("/framsteg").text                                        # felet visas som meddelande (flash)
    assert "finns inte" in page
    conn.close()


def test_student_cannot_cancel_or_request_for_others_and_admin_routes_are_closed(client):
    conn, uid, rid = _req_routes(client)
    client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "1"})
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    assert client.post(f"/admin/belonningar/{qid}/godkann").status_code in (303, 401, 403)
    assert conn.execute("SELECT status FROM reward_requests").fetchone()[0] == "pending"   # eleven kan inte godkänna själv
    assert motivation.points(conn, uid)["spent"] == 0
    client.post("/logout")
    assert client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "1"}).status_code in (303, 401, 403)
    assert conn.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 1
    conn.close()


def test_student_cancel_route(client):
    conn, uid, rid = _req_routes(client)
    client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "2"})
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    r = client.post(f"/framsteg/forfragan/{qid}/ta-tillbaka")
    assert r.status_code == 303
    assert conn.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 0
    assert motivation.points(conn, uid)["available"] == 130
    conn.commit()                                                              # släpp testets öppna transaktion
    assert client.post(f"/framsteg/forfragan/{qid}/ta-tillbaka").status_code == 303   # ingen krasch
    conn.close()


def test_requests_are_blocked_when_points_are_off(client):
    conn, uid, rid = _req_routes(client)
    conn.execute("UPDATE user_prefs SET points_on=0 WHERE user_id=?", (uid,))
    conn.commit()
    assert client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "1"}).status_code == 403
    assert conn.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 0
    conn.close()


def test_admin_sees_requests_on_start_page_and_approves(client):
    conn, uid, rid = _req_routes(client)
    client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "2"})
    client.post("/logout")
    login(client, "admin", "adminpass1")
    page = client.get("/admin").text
    assert "Belöningar att godkänna" in page and "2 × Godis" in page and "100 poäng" in page
    assert "har 130" in page
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    assert f"/admin/belonningar/{qid}/godkann" in page and f"/admin/belonningar/{qid}/avsla" in page
    nav = client.get("/admin/uppgifter").text
    assert 'class="pill wait"' in nav.split("Elever")[1].split("</a>")[0]      # siffran vid Elever-fliken
    r = client.post(f"/admin/belonningar/{qid}/godkann", data={"back": "/admin"})
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    p = motivation.points(conn, uid)
    assert (p["spent"], p["balance"], p["reserved"]) == (100, 30, 0)
    page = client.get("/admin").text
    assert "Belöningar att godkänna" not in page
    assert "Godkänt. Mia fick 2 × Godis och 100 poäng drogs." in page          # meddelandet
    conn.close()


def test_admin_declines_via_route_and_back_param_is_safe(client):
    conn, uid, rid = _req_routes(client)
    client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "1"})
    client.post("/logout")
    login(client, "admin", "adminpass1")
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    r = client.post(f"/admin/belonningar/{qid}/avsla", data={"back": "https://evil.example/x"})
    assert r.status_code == 303 and r.headers["location"] == "/admin"          # extern adress ignoreras
    assert conn.execute("SELECT status FROM reward_requests").fetchone()[0] == "declined"
    assert motivation.points(conn, uid)["available"] == 130
    assert client.post(f"/admin/belonningar/{qid}/oops").status_code == 404
    assert client.post("/admin/belonningar/9999/godkann").status_code == 404
    assert client.post(f"/admin/belonningar/{qid}/godkann").status_code == 303   # redan hanterad: flash, ingen krasch
    assert conn.execute("SELECT times_given FROM rewards WHERE title='Godis'").fetchone()[0] == 0
    conn.close()


def test_admin_approve_with_too_few_points_is_refused_in_the_ui(client):
    conn, uid, rid = _req_routes(client)
    client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "2"})
    conn.execute("INSERT INTO rewards(user_id, title, cost, times_given) VALUES (?, 'Extra', 90, 1)", (uid,))
    conn.commit()                                                              # admin har redan delat ut 90 (kvar: 40)
    client.post("/logout")
    login(client, "admin", "adminpass1")
    page = client.get("/admin").text
    assert "inte tillräckligt med poäng längre" in page and "disabled" in page
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    client.post(f"/admin/belonningar/{qid}/godkann", data={"back": "/admin"})
    assert conn.execute("SELECT status FROM reward_requests").fetchone()[0] == "pending"
    conn.close()


def test_admin_student_page_shows_pending_request_and_reserved_points(client):
    conn, uid, rid = _req_routes(client)
    client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "2"})
    client.post("/logout")
    login(client, "admin", "adminpass1")
    page = client.get(f"/admin/student/{uid}").text
    assert "har bett om 2 st" in page and "(100 poäng)" in page
    assert "100</strong> reserverade" in page
    qid = conn.execute("SELECT id FROM reward_requests").fetchone()["id"]
    assert f'/admin/belonningar/{qid}/godkann' in page and f"/admin/student/{uid}#motivation" in page
    r = client.post(f"/admin/belonningar/{qid}/godkann", data={"back": f"/admin/student/{uid}#motivation"})
    assert r.headers["location"] == f"/admin/student/{uid}#motivation"
    conn.close()


def test_home_page_shows_available_points_and_request_link(client):
    conn, uid, rid = _req_routes(client)
    page = client.get("/home").text
    assert "/framsteg#belonningar" in page                                     # "Be om den"
    client.post(f"/framsteg/belonning/{rid['Godis']}/be-om", data={"quantity": "2"})
    page = client.get("/home").text
    assert "Du har bett om" in page and "Väntar på admin" in page
    conn.close()


def test_reward_requests_table_is_created_on_an_old_database(client):
    conn = _conn()
    conn.execute("DROP TABLE reward_requests")
    conn.commit()
    conn.close()
    from app import db as database
    database.init_db()                                                         # körs vid varje uppstart
    c = database.connect()
    assert c.execute("SELECT COUNT(*) FROM reward_requests").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM rewards").fetchone()[0] == 0        # befintlig data orörd
    c.close()
