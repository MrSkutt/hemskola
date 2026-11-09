import json

from app import db as database
from app import logic


def test_is_correct_numbers_and_text():
    assert logic.is_correct("4,25", ["4,25"])
    assert logic.is_correct("4.25", ["4,25"])
    assert logic.is_correct(" 1/2 ", ["0,5"])
    assert logic.is_correct("−5", ["-5"])
    assert logic.is_correct("30 %", ["30"])
    assert logic.is_correct("Hatt", ["hatt"])
    assert not logic.is_correct("", ["0"])
    assert not logic.is_correct("12", ["13"])


def test_validate_exercise():
    ok, err = logic.validate_exercise({"subject": "Matte", "topic": "x", "level": 2, "type": "text",
                                       "question": "1+1?", "answer": 2})
    assert err is None and ok["subject"] == "matte" and json.loads(ok["answers"]) == ["2"]
    assert logic.validate_exercise({"subject": "m", "topic": "x", "level": 9, "type": "text", "question": "q", "answer": "a"})[1]
    assert logic.validate_exercise({"subject": "m", "topic": "x", "level": 1, "type": "mc", "question": "q",
                                    "options": ["a", "b"], "answer": "c"})[1]


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "l.db"))
    database.init_db()
    conn = database.connect()
    conn.execute("INSERT INTO users(username, display_name, password_hash, role) VALUES ('e','E','x','student')")
    items = [{"subject": "matte", "topic": "t", "level": lvl, "type": "text", "question": f"q{lvl}-{i}", "answer": "1"}
             for lvl in range(1, 6) for i in range(4)]
    logic.import_exercises(conn, items)
    return conn


def test_level_up_and_down(tmp_path, monkeypatch):
    conn = _setup(tmp_path, monkeypatch)
    logic.set_level(conn, 1, "matte", 2)
    ex = conn.execute("SELECT * FROM exercises WHERE level=2").fetchone()
    changes = [logic.record_attempt(conn, 1, ex, "1")[2] for _ in range(6)]
    assert changes[-1] == "up" and logic.get_level(conn, 1, "matte") == 3
    ex3 = conn.execute("SELECT * FROM exercises WHERE level=3").fetchone()
    changes = [logic.record_attempt(conn, 1, ex3, "9")[2] for _ in range(6)]
    assert changes[-1] == "down" and logic.get_level(conn, 1, "matte") == 2


def test_no_change_in_the_middle(tmp_path, monkeypatch):
    conn = _setup(tmp_path, monkeypatch)
    logic.set_level(conn, 1, "matte", 2)
    ex = conn.execute("SELECT * FROM exercises WHERE level=2").fetchone()
    for given in ["1", "1", "1", "1", "9", "9"]:   # 4 av 6 rätt
        logic.record_attempt(conn, 1, ex, given)
    assert logic.get_level(conn, 1, "matte") == 2


def test_placement_test_sets_level(tmp_path, monkeypatch):
    conn = _setup(tmp_path, monkeypatch)
    tid = logic.create_test(conn, 1, "matte")
    assert conn.execute("SELECT kind, total FROM tests WHERE id=?", (tid,)).fetchone()["total"] == 10
    while True:
        nxt = logic.next_test_item(conn, tid)
        if not nxt:
            break
        _, ex = nxt
        logic.record_attempt(conn, 1, ex, "1" if ex["level"] <= 3 else "9", test_id=tid)
    assert logic.finish_test(conn, tid) == 3
    assert logic.get_level(conn, 1, "matte") == 3
    assert conn.execute("SELECT score FROM tests WHERE id=?", (tid,)).fetchone()["score"] == 6


def test_status_test_never_lowers_level(tmp_path, monkeypatch):
    conn = _setup(tmp_path, monkeypatch)
    logic.set_level(conn, 1, "matte", 4)
    tid = logic.create_test(conn, 1, "matte")
    assert conn.execute("SELECT kind FROM tests WHERE id=?", (tid,)).fetchone()["kind"] == "status"
    while (nxt := logic.next_test_item(conn, tid)):
        logic.record_attempt(conn, 1, nxt[1], "9", test_id=tid)
    logic.finish_test(conn, tid)
    assert logic.get_level(conn, 1, "matte") == 4
