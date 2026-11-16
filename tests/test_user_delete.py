"""Ta bort användare: allt som hör till användaren försvinner, andras data rörs inte, och man kan inte ta bort sig själv."""
import json
import re

from app import logic

from .conftest import login
from .test_features import _conn, _make_student


def _uid(conn, name):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


def _count(conn, table, uid):
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (uid,)).fetchone()[0]


def _give_data(client, name, answers=3):
    """Ger eleven svar på genererade frågor, ett prov, nivå, belöning och en uppgift."""
    conn = _conn()
    uid = _uid(conn, name)
    logic.set_level(conn, uid, "matte", 2)
    conn.execute("UPDATE exercises SET active=0 WHERE generator IS NULL")
    conn.commit()
    conn.close()
    login(client, name, "hemligt1")
    for _ in range(answers):
        page = client.get("/practice/matte")
        ex_id = re.search(r'name="exercise_id" value="(\d+)"', page.text).group(1)
        gen_id = re.search(r'name="generated_id" value="(\d+)"', page.text).group(1)
        conn = _conn()
        right = json.loads(conn.execute("SELECT answers FROM generated WHERE id=?", (gen_id,)).fetchone()["answers"])[0]
        conn.close()
        client.post("/practice/matte", data={"exercise_id": ex_id, "generated_id": gen_id, "given": right})
    client.post("/logout")
    conn = _conn()
    tid = conn.execute("INSERT INTO tests(user_id, subject, kind) VALUES (?, 'matte', 'status')", (uid,)).lastrowid
    ex = conn.execute("SELECT id FROM exercises WHERE generator IS NOT NULL AND subject='matte' LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO test_items(test_id, position, exercise_id) VALUES (?, 1, ?)", (tid, ex))
    conn.execute("INSERT INTO rewards(user_id, title, cost) VALUES (?, 'Glass', 30)", (uid,))
    task = conn.execute("INSERT INTO tasks(title) VALUES ('Läs ett kapitel')").lastrowid
    conn.execute("INSERT INTO task_assignments(task_id, user_id) VALUES (?, ?)", (task, uid))
    conn.commit()
    conn.close()
    return uid


def test_admin_can_delete_a_user_created_by_mistake(client):
    _make_student(client, "fel")
    login(client, "admin", "adminpass1")
    page = client.get("/admin/users").text
    assert "Fel" in page and "/delete" in page
    uid = _uid(_conn(), "fel")
    r = client.post(f"/admin/users/{uid}/delete")
    assert r.status_code == 303 and r.headers["location"] == "/admin/users"
    assert "Användaren Fel är borttagen" in client.get("/admin/users").text
    assert _conn().execute("SELECT COUNT(*) FROM users WHERE username='fel'").fetchone()[0] == 0
    client.post("/logout")
    assert client.post("/login", data={"username": "fel", "password": "hemligt1"}).status_code == 401
    # användarnamnet går att använda igen, nu som admin
    login(client, "admin", "adminpass1")
    client.post("/admin/users/new", data={"username": "fel", "display_name": "Fel", "password": "hemligt1", "role": "admin"})
    assert _conn().execute("SELECT role FROM users WHERE username='fel'").fetchone()["role"] == "admin"


def test_an_admin_can_be_deleted_by_another_admin(client):
    login(client, "admin", "adminpass1")
    client.post("/admin/users/new", data={"username": "extra", "display_name": "Extra", "password": "hemligt1", "role": "admin"})
    uid = _uid(_conn(), "extra")
    client.post(f"/admin/users/{uid}/delete")
    assert _conn().execute("SELECT COUNT(*) FROM users WHERE username='extra'").fetchone()[0] == 0
    assert _conn().execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0] == 1


def test_you_cannot_delete_yourself(client):
    login(client, "admin", "adminpass1")
    me = _uid(_conn(), "admin")
    client.post(f"/admin/users/{me}/delete")
    assert "Du kan inte ta bort dig själv" in client.get("/admin/users").text
    assert _conn().execute("SELECT COUNT(*) FROM users WHERE id=?", (me,)).fetchone()[0] == 1
    assert f"/admin/users/{me}/delete" not in client.get("/admin/users").text        # ingen knapp för dig själv


def test_deleting_removes_everything_that_belongs_to_the_user_and_nothing_else(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    mia = _give_data(client, "mia", answers=3)
    ben = _give_data(client, "ben", answers=2)
    conn = _conn()
    assert _count(conn, "attempts", mia) == 3 and _count(conn, "generated", mia) >= 3
    ben_before = {t: _count(conn, t, ben) for t in ("attempts", "generated", "tests", "rewards", "task_assignments", "user_levels")}
    assert ben_before["attempts"] == 2
    conn.close()

    login(client, "admin", "adminpass1")
    assert "3 svar" in client.get("/admin/users").text                                 # bekräftelsen säger vad som försvinner
    client.post(f"/admin/users/{mia}/delete")

    conn = _conn()
    for table in ("attempts", "generated", "tests", "rewards", "task_assignments", "user_levels", "user_subjects", "user_prefs"):
        assert _count(conn, table, mia) == 0, table
    assert conn.execute("SELECT COUNT(*) FROM test_items WHERE test_id NOT IN (SELECT id FROM tests)").fetchone()[0] == 0
    assert {t: _count(conn, t, ben) for t in ben_before} == ben_before                 # Bens data är orörd
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_confirmation_text_mentions_the_name_and_suggests_turning_off_when_there_is_data(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    _give_data(client, "mia", answers=2)
    login(client, "admin", "adminpass1")
    page = client.get("/admin/users").text
    forms = re.findall(r"<form[^>]*/delete\"[^>]*onsubmit='return confirm\((.*?)\)'", page)
    assert len(forms) == 2
    texts = [json.loads(f) for f in forms]
    mia = next(t for t in texts if "Mia" in t)
    ben = next(t for t in texts if "Ben" in t)
    assert "2 svar" in mia and "Stäng av" in mia and "ångra" in mia
    assert "svar" not in ben and "Stäng av" not in ben


def test_confirmation_text_is_safe_with_quotes_in_the_name(client):
    login(client, "admin", "adminpass1")
    client.post("/admin/users/new", data={"username": "oj", "display_name": "O'Brien \"Bo\" <b>", "password": "hemligt1", "role": "student"})
    page = client.get("/admin/users").text
    m = re.search(r"/delete\"[^>]*onsubmit='return confirm\((.*?)\)'", page)
    assert m and json.loads(m.group(1)).startswith("Ta bort O'Brien \"Bo\" <b>")      # tojson hanterar citattecknen
    assert "<b>" not in m.group(1)


def test_unknown_user_gives_a_message_not_an_error(client):
    login(client, "admin", "adminpass1")
    r = client.post("/admin/users/9999/delete")
    assert r.status_code == 303
    assert "Användaren finns inte" in client.get("/admin/users").text


def test_students_cannot_delete_users(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    ben = _uid(_conn(), "ben")
    login(client, "mia", "hemligt1")
    r = client.post(f"/admin/users/{ben}/delete")
    assert r.status_code in (303, 403)
    assert _conn().execute("SELECT COUNT(*) FROM users WHERE username='ben'").fetchone()[0] == 1


def test_a_deleted_user_who_is_logged_in_is_sent_to_the_login_page(client):
    _make_student(client, "mia")
    login(client, "mia", "hemligt1")
    assert client.get("/home").status_code == 200
    conn = _conn()
    mia = _uid(conn, "mia")
    assert logic.delete_user(conn, mia, acting_id=0) == ("Mia", None)
    conn.commit()
    conn.close()
    r = client.get("/home")
    assert r.status_code in (303, 401) and "/login" in r.headers.get("location", "/login")
