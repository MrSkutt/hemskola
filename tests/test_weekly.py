"""Tester för veckosammanfattningen på admins startsida."""
from datetime import datetime, timedelta, timezone

from app import logic, weekly

from .conftest import login
from .test_editor import _admin, _ex
from .test_features import _conn, _make_student


def _ts(days_ago=0, hours_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]


def _att(conn, uid, ex, correct, ts):
    conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct, created_at) VALUES (?,?,?,?,?)",
                 (uid, ex, "x", 1 if correct else 0, ts))
    conn.commit()


def _student(client):
    _make_student(client)
    conn = _conn()
    return conn, _uid(conn)


def test_counts_this_week_against_the_one_before(client):
    conn, uid = _student(client)
    ex = _ex(conn, subject="matte", question="A?")
    for i, ok in enumerate([True, True, False, True]):
        _att(conn, uid, ex, ok, _ts(hours_ago=2 + i))                    # idag
    _att(conn, uid, ex, True, _ts(days_ago=3))
    for _ in range(2):
        _att(conn, uid, ex, False, _ts(days_ago=9))                      # veckan före
    _att(conn, uid, ex, True, _ts(days_ago=30))                          # långt tillbaka: räknas inte
    w = weekly.week_summary(conn, uid)
    assert (w["n"], w["pct"]) == (5, 80)
    assert (w["prev_n"], w["prev_pct"]) == (2, 0) and w["trend"] == 1
    assert w["active_days"] == 2
    conn.close()


def test_week_boundaries_are_local_days(client):
    conn, uid = _student(client)
    ex = _ex(conn, subject="matte", question="A?")
    first_day = logic.today() - timedelta(days=weekly.DAYS - 1)
    start = weekly._utc(first_day)
    before = (datetime.strptime(start, "%Y-%m-%d %H:%M:%S") - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    _att(conn, uid, ex, True, start)           # första sekunden på första dagen: ingår
    _att(conn, uid, ex, False, before)         # sekunden före: veckan före
    w = weekly.week_summary(conn, uid)
    assert (w["n"], w["prev_n"]) == (1, 1)
    conn.close()


def test_trend_down_and_flat(client):
    conn, uid = _student(client)
    ex = _ex(conn, subject="matte", question="A?")
    _att(conn, uid, ex, True, _ts(days_ago=1))
    for _ in range(3):
        _att(conn, uid, ex, True, _ts(days_ago=10))
    assert weekly.week_summary(conn, uid)["trend"] == -1
    for _ in range(2):
        _att(conn, uid, ex, True, _ts(days_ago=2))
    assert weekly.week_summary(conn, uid)["trend"] == 0
    conn.close()


def test_no_activity(client):
    conn, uid = _student(client)
    w = weekly.week_summary(conn, uid)
    assert w["n"] == 0 and w["pct"] is None and w["active_days"] == 0 and w["subjects"] == [] and w["trend"] == 0
    conn.close()


def test_subjects_are_sorted_by_most_answers(client):
    conn, uid = _student(client)
    a = _ex(conn, subject="matte", question="M?")
    b = _ex(conn, subject="svenska", question="S?")
    for ok in (True, False, True):
        _att(conn, uid, b, ok, _ts(days_ago=1))
    _att(conn, uid, a, True, _ts(days_ago=1))
    w = weekly.week_summary(conn, uid)
    assert [(s["subject"], s["n"], s["pct"]) for s in w["subjects"]] == [("svenska", 3, 67), ("matte", 1, 100)]
    conn.close()


def test_weak_topics_need_enough_answers_and_a_low_share(client):
    conn, uid = _student(client)
    weak = _ex(conn, subject="matte", question="Svag?", topic="Procent")
    few = _ex(conn, subject="matte", question="Få?", topic="Bråk")
    fine = _ex(conn, subject="matte", question="Bra?", topic="Algebra")
    fun = _ex(conn, subject="kpop", question="Skoj?", topic="Låtar")
    for i in range(5):
        _att(conn, uid, weak, i == 0, _ts(days_ago=1))        # 20 % av 5
        _att(conn, uid, fine, i != 0, _ts(days_ago=1))        # 80 %
        _att(conn, uid, fun, False, _ts(days_ago=1))          # fritid räknas inte som svagt
    for _ in range(3):
        _att(conn, uid, few, False, _ts(days_ago=1))          # för få svar
    w = weekly.week_summary(conn, uid)
    assert [(x["topic"], x["pct"], x["n"]) for x in w["weak"]] == [("Procent", 20, 5)]
    conn.close()


def test_at_most_three_weak_topics_worst_first(client):
    conn, uid = _student(client)
    for topic, rights in (("A", 2), ("B", 0), ("C", 1), ("D", 3)):
        ex = _ex(conn, subject="matte", question=f"{topic}?", topic=topic)
        for i in range(5):
            _att(conn, uid, ex, i < rights, _ts(days_ago=1))
    assert [x["topic"] for x in weekly.week_summary(conn, uid)["weak"]] == ["B", "C", "A"]
    conn.close()


def test_level_ups_and_tests_this_week(client):
    conn, uid = _student(client)
    conn.execute("INSERT INTO level_ups(user_id, subject, level, created_at) VALUES (?,?,?,?)", (uid, "matte", 3, _ts(days_ago=2)))
    conn.execute("INSERT INTO level_ups(user_id, subject, level, created_at) VALUES (?,?,?,?)", (uid, "matte", 2, _ts(days_ago=20)))
    conn.execute("INSERT INTO tests(user_id, subject, kind, total, score, finished_at) VALUES (?,?,?,?,?,?)",
                 (uid, "svenska", "status", 10, 7, _ts(days_ago=1)))
    conn.execute("INSERT INTO tests(user_id, subject, kind, total, score, finished_at) VALUES (?,?,?,?,?,?)",
                 (uid, "svenska", "status", 10, 4, _ts(days_ago=15)))
    conn.execute("INSERT INTO tests(user_id, subject, kind, total) VALUES (?,?,?,?)", (uid, "matte", "status", 10))   # ej klart
    conn.commit()
    w = weekly.week_summary(conn, uid)
    assert w["level_ups"] == [{"subject": "matte", "level": 3}]
    assert w["tests"] == [{"subject": "svenska", "kind": "status", "score": 7, "total": 10}]
    conn.close()


def test_daily_goal_days(client):
    conn, uid = _student(client)
    conn.execute("INSERT INTO user_prefs(user_id, daily_goal) VALUES (?, 10)", (uid,))
    for d in (0, 1, 3, 9):
        conn.execute("INSERT INTO goal_days(user_id, day) VALUES (?,?)", (uid, (logic.today() - timedelta(days=d)).isoformat()))
    conn.commit()
    w = weekly.week_summary(conn, uid)
    assert w["goal"] == 10 and w["goal_days"] == 3
    conn.execute("UPDATE user_prefs SET daily_goal=0 WHERE user_id=?", (uid,))
    conn.commit()
    assert weekly.week_summary(conn, uid)["goal_days"] is None
    conn.close()


def test_a_summary_creates_nothing_for_a_student_without_prefs(client):
    conn, uid = _student(client)
    before = conn.execute("SELECT COUNT(*) FROM user_prefs").fetchone()[0]
    w = weekly.week_summary(conn, uid)
    assert w["goal"] == 0 and w["goal_days"] is None
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM user_prefs").fetchone()[0] == before
    conn.close()


def test_missed_count_is_included(client):
    conn, uid = _student(client)
    ex = _ex(conn, subject="matte", question="A?")
    _att(conn, uid, ex, False, _ts(days_ago=30))                     # missad för länge sedan, men den väntar fortfarande
    assert weekly.week_summary(conn, uid)["missed"] == 1
    conn.close()


# ------------------------------------------------------------------ startsidan

def test_admin_home_shows_the_week(client):
    conn, uid = _student(client)
    ex = _ex(conn, subject="matte", question="A?", topic="Procent")
    for _ in range(3):
        _att(conn, uid, ex, True, _ts(days_ago=9))
    for i in range(5):
        _att(conn, uid, ex, i == 0, _ts(days_ago=1))
    conn.execute("INSERT INTO level_ups(user_id, subject, level) VALUES (?,?,?)", (uid, "matte", 4))
    conn.commit()
    conn.close()
    _admin(client)
    page = client.get("/admin").text
    assert "Veckan som gått" in page and "Mia" in page
    assert "<strong>5</strong> svar" in page and "<strong>20 %</strong> rätt" in page and "<strong>1</strong> av 7 dagar" in page
    assert "↑ upp från 3" in page
    assert "Mest övat: Matematik 5 (20 %)" in page
    assert "Högre nivå: Matematik nivå 4" in page
    assert "Behöver mer träning: Procent (Matematik, 20 % rätt av 5)" in page
    assert "att repetera under" in page


def test_admin_home_for_a_quiet_week(client):
    _student(client)
    _admin(client)
    page = client.get("/admin").text
    assert "Veckan som gått" in page and "Inga svar de senaste 7 dagarna" in page
    assert "Behöver mer träning" not in page and "Mest övat" not in page


def test_admin_home_skips_inactive_students_and_shows_none_without_students(client):
    _admin(client)
    assert "Veckan som gått" not in client.get("/admin").text
    _make_student(client)
    conn = _conn()
    conn.execute("UPDATE users SET active=0 WHERE username='mia'")
    conn.commit()
    conn.close()
    _admin(client)
    assert "Veckan som gått" not in client.get("/admin").text
