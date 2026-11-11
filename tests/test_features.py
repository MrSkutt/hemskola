"""Tester för genererade frågor i appen, bilder och uppgradering av en gammal databas."""
import json
import re
import sqlite3

from app import db as database
from app import logic

from .conftest import login

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")


def _make_student(client, name="mia"):
    login(client, "admin", "adminpass1")
    client.post("/admin/users/new", data={"username": name, "display_name": name.title(), "password": "hemligt1", "role": "student"})
    client.post("/logout")


def _conn():
    return database.connect()


def test_generators_exist_as_exercises_and_can_be_toggled(client):
    login(client, "admin", "adminpass1")
    page = client.get("/admin/exercises?subject=matte&level=2").text
    assert "∞ generator" in page
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM exercises WHERE generator IS NOT NULL").fetchone()[0]
    assert n >= 70
    conn.close()


def test_practice_with_generated_questions(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    logic.set_level(conn, uid, "matte", 2)
    conn.execute("UPDATE exercises SET active=0 WHERE generator IS NULL")   # bara generatorer kvar
    conn.commit()
    conn.close()

    login(client, "mia", "hemligt1")
    seen = set()
    for _ in range(6):
        page = client.get("/practice/matte")
        assert page.status_code == 200
        ex_id = re.search(r'name="exercise_id" value="(\d+)"', page.text).group(1)
        gen_id = re.search(r'name="generated_id" value="(\d+)"', page.text).group(1)
        assert gen_id
        conn = _conn()
        row = conn.execute("SELECT question, answers FROM generated WHERE id=?", (gen_id,)).fetchone()
        conn.close()
        seen.add(row["question"])
        right = json.loads(row["answers"])[0]
        r = client.post("/practice/matte", data={"exercise_id": ex_id, "generated_id": gen_id, "given": right})
        assert "/answer/" in r.headers["location"]
        assert "Rätt!" in client.get(r.headers["location"]).text
        # samma fråga kan inte besvaras två gånger
        again = client.post("/practice/matte", data={"exercise_id": ex_id, "generated_id": gen_id, "given": "999999"})
        assert "/answer/" not in again.headers["location"]
    assert len(seen) >= 4   # nya frågor varje gång

    conn = _conn()
    assert conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id=?", (uid,)).fetchone()[0] == 6
    assert conn.execute("SELECT SUM(correct) FROM attempts WHERE user_id=?", (uid,)).fetchone()[0] == 6
    conn.close()
    client.post("/logout")
    login(client, "admin", "adminpass1")
    detail = client.get(f"/admin/student/{uid}")
    assert detail.status_code == 200 and any(q.split("\n")[0][:15] in detail.text for q in seen)


def test_cannot_answer_someone_elses_generated_question(client):
    _make_student(client, "mia")
    _make_student(client, "ida")
    conn = _conn()
    mia = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    logic.set_level(conn, mia, "matte", 1)
    conn.execute("UPDATE exercises SET active=0 WHERE generator IS NULL")
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    page = client.get("/practice/matte")
    ex_id = re.search(r'name="exercise_id" value="(\d+)"', page.text).group(1)
    gen_id = re.search(r'name="generated_id" value="(\d+)"', page.text).group(1)
    client.post("/logout")
    login(client, "ida", "hemligt1")
    conn = _conn()
    ida = conn.execute("SELECT id FROM users WHERE username='ida'").fetchone()["id"]
    logic.set_level(conn, ida, "matte", 1)
    conn.close()
    r = client.post("/practice/matte", data={"exercise_id": ex_id, "generated_id": gen_id, "given": "1"})
    assert "/answer/" not in r.headers["location"]


def test_test_contains_generated_and_review_shows_them(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    url = client.post("/test/start/svenska").headers["location"]
    for _ in range(10):
        page = client.get(url)
        ex_id = re.search(r'name="exercise_id" value="(\d+)"', page.text).group(1)
        gen_id = re.search(r'name="generated_id" value="(\d*)"', page.text).group(1)
        client.post(url, data={"exercise_id": ex_id, "generated_id": gen_id, "given": "xx"})
    res = client.get(client.get(url).headers["location"])
    assert res.status_code == 200 and "0 av 10 rätt" in res.text
    conn = _conn()
    n_gen = conn.execute("SELECT COUNT(*) FROM test_items WHERE generated_id IS NOT NULL").fetchone()[0]
    conn.close()
    assert n_gen >= 1


def test_diagram_questions_are_drawn(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    logic.set_level(conn, uid, "matte", 1)
    conn.execute("UPDATE exercises SET active=0 WHERE COALESCE(generator,'') NOT IN ('m1_clock','m1_fraction','m1_bar_read')")
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    for _ in range(5):
        page = client.get("/practice/matte").text
        assert '<svg class="diagram"' in page


def test_import_with_diagram_image_and_words(client):
    login(client, "admin", "adminpass1")
    data = {"exercises": [
        {"subject": "matte", "topic": "Diagram", "level": 2, "type": "text", "question": "Hur högt är stapeln?",
         "answer": "4", "diagram": {"type": "bar_chart", "labels": ["a", "b"], "values": [4, 2]}, "image": "karta.png"},
        {"subject": "matte", "topic": "Diagram", "level": 2, "type": "text", "question": "Trasigt diagram?",
         "answer": "4", "diagram": {"type": "bar_chart", "labels": ["a"], "values": [-4]}},
        {"subject": "matte", "topic": "x", "level": 2, "type": "text", "question": "Dålig bild?", "answer": "1", "image": "../../etc/passwd"},
    ], "words": [
        {"word": "cykla", "pos": "verb", "level": 1, "forms": {"presens": "cyklar", "preteritum": "cyklade"}},
        {"word": "felord", "pos": "ingen", "level": 1},
    ]}
    r = client.post("/admin/import", data={"pasted": json.dumps(data)})
    assert "1 nya övningar" in r.text and "1 nya ord" in r.text and r.text.count("flash warn") == 1
    assert "okänd" in r.text or "pos måste" in r.text and "image måste" in r.text
    assert "cykla" in client.get("/admin/words?pos=verb").text
    export = client.get("/admin/exercises/export.json").json()
    mine = [e for e in export if e["question"] == "Hur högt är stapeln?"][0]
    assert mine["diagram"]["type"] == "bar_chart" and mine["image"] == "karta.png"


def test_media_upload_serve_and_security(client):
    _make_student(client)
    login(client, "admin", "adminpass1")
    r = client.post("/admin/media", files=[("files", ("Min Bild.PNG", PNG, "image/png"))])
    assert r.status_code == 303
    page = client.get("/admin/media").text
    assert "min-bild.png" in page
    # skadliga eller felaktiga filer avvisas
    bad = [("files", ("x.svg", b"<svg onload='alert(1)'></svg>", "image/svg+xml")),
           ("files", ("y.png", b"inte en bild", "image/png")),
           ("files", ("z.exe", b"MZ", "application/octet-stream")),
           ("files", ("big.png", PNG + b"0" * 3_100_000, "image/png"))]
    client.post("/admin/media", files=bad)
    page = client.get("/admin/media").text
    assert "x.svg" not in page.split("Ladda upp")[-1] or "avvis" not in page
    m = client.get("/media/min-bild.png")
    assert m.status_code == 200 and m.headers["content-type"] == "image/png"
    assert m.headers["x-content-type-options"] == "nosniff" and "sandbox" in m.headers["content-security-policy"]
    assert client.get("/media/finns-inte.png").status_code == 404
    assert client.get("/media/..%2Fsecret.key").status_code == 404
    client.post("/logout")
    assert client.get("/media/min-bild.png").status_code == 303        # kräver inloggning
    login(client, "mia", "hemligt1")
    assert client.get("/media/min-bild.png").status_code == 200        # elever får se bilder
    assert client.post("/admin/media", files=[("files", ("a.png", PNG, "image/png"))]).status_code == 403


def test_svg_upload_without_scripts_is_allowed(client):
    login(client, "admin", "adminpass1")
    svg = b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'><circle cx='5' cy='5' r='4'/></svg>"
    client.post("/admin/media", files=[("files", ("cirkel.svg", svg, "image/svg+xml"))])
    assert client.get("/media/cirkel.svg").status_code == 200


# ------------------------------------------------------------------ uppgradering av en gammal databas

OLD_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','student')),
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE exercises (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, topic TEXT NOT NULL,
  level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5), type TEXT NOT NULL CHECK (type IN ('mc','text')),
  question TEXT NOT NULL, options TEXT, answers TEXT NOT NULL, explanation TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT (datetime('now')), UNIQUE (subject, question));
CREATE TABLE user_levels (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, subject TEXT NOT NULL,
  level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5), since_attempt_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, subject));
CREATE TABLE tests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  subject TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('placement','status')), total INTEGER NOT NULL DEFAULT 0,
  score INTEGER, estimated_level INTEGER, started_at TEXT NOT NULL DEFAULT (datetime('now')), finished_at TEXT);
CREATE TABLE test_items (test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE, position INTEGER NOT NULL,
  exercise_id INTEGER NOT NULL REFERENCES exercises(id), PRIMARY KEY (test_id, position));
CREATE TABLE attempts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  exercise_id INTEGER NOT NULL REFERENCES exercises(id), test_id INTEGER REFERENCES tests(id) ON DELETE CASCADE,
  given TEXT NOT NULL, correct INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE INDEX idx_attempts_user ON attempts(user_id, id);
CREATE INDEX idx_exercises_pick ON exercises(subject, level, active);
"""


def test_old_database_is_upgraded_without_losing_data(tmp_path, monkeypatch):
    from app.security import hash_password
    path = tmp_path / "old.db"
    monkeypatch.setattr(database, "DB_PATH", str(path))
    old = sqlite3.connect(path)
    old.executescript(OLD_SCHEMA)
    old.execute("INSERT INTO users(username, display_name, password_hash, role) VALUES ('mia','Mia',?, 'student')", (hash_password("x"),))
    old.execute("INSERT INTO exercises(subject, topic, level, type, question, answers) VALUES ('matte','t',1,'text','1+1?','[\"2\"]')")
    old.execute("INSERT INTO user_levels(user_id, subject, level, since_attempt_id) VALUES (1,'matte',3,0)")
    old.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (1,1,'2',1)")
    old.execute("INSERT INTO tests(user_id, subject, kind, total, score, estimated_level, finished_at) "
                "VALUES (1,'matte','placement',10,6,3,datetime('now'))")
    old.commit()
    old.close()

    database.init_db()
    database.init_db()          # ska vara upprepbart
    conn = database.connect()
    assert {"image", "diagram", "generator"} <= {r["name"] for r in conn.execute("PRAGMA table_info(exercises)")}
    assert "generated_id" in {r["name"] for r in conn.execute("PRAGMA table_info(attempts)")}
    assert conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    assert logic.get_level(conn, 1, "matte") == 3
    logic.ensure_generator_exercises(conn)
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE generator IS NOT NULL").fetchone()[0] >= 70
    # gamla frågor fungerar fortfarande
    item = logic.item_from_exercise(logic.exercise_row(conn, 1))
    assert item["generated_id"] is None and item["answers"] == ["2"]
    _, correct, _ = logic.record_attempt(conn, 1, item, "2")
    assert correct and conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 2
    conn.close()


def test_example_images_and_subjects_are_installed(client):
    login(client, "admin", "adminpass1")
    for name in ("scene.svg", "vattnets_kretslopp.svg", "solsystemet.svg", "vaxtens_delar.svg", "lightstick.svg", "scen.svg", "hangul_block.svg", "taegukgi.svg"):
        r = client.get(f"/media/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/svg+xml"
    conn = _conn()
    subjects = {r[0] for r in conn.execute("SELECT DISTINCT subject FROM exercises WHERE active=1")}
    assert {"matte", "svenska", "engelska", "no", "so", "kpop"} <= subjects
    refs = {r[0] for r in conn.execute("SELECT image FROM exercises WHERE image IS NOT NULL")}
    conn.close()
    assert refs and all(client.get(f"/media/{n}").status_code == 200 for n in refs)


def test_student_can_take_english_test_and_practice(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    assert "Engelska" in client.get("/home").text
    url = client.post("/test/start/engelska").headers["location"]
    for _ in range(10):
        page = client.get(url)
        ex_id = re.search(r'name="exercise_id" value="(\d+)"', page.text).group(1)
        gen_id = re.search(r'name="generated_id" value="(\d*)"', page.text).group(1)
        client.post(url, data={"exercise_id": ex_id, "generated_id": gen_id, "given": "x"})
    assert client.get(client.get(url).headers["location"]).status_code == 200
    assert client.get("/practice/engelska").status_code == 200


def test_pdf_report(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    url = client.post("/test/start/matte").headers["location"]
    for _ in range(10):
        page = client.get(url)
        ex_id = re.search(r'name="exercise_id" value="(\d+)"', page.text).group(1)
        gen_id = re.search(r'name="generated_id" value="(\d*)"', page.text).group(1)
        client.post(url, data={"exercise_id": ex_id, "generated_id": gen_id, "given": "fel"})
    client.get(url)
    assert client.get("/admin/student/2/report.pdf").status_code in (303, 403)     # elever får inte se rapporter
    client.post("/logout")
    login(client, "admin", "adminpass1")
    sid = _conn().execute("SELECT id FROM users WHERE username='mia'").fetchone()["id"]
    assert "report.pdf" in client.get(f"/admin/student/{sid}").text
    for days in (7, 30, 90, 0, 999):
        r = client.get(f"/admin/student/{sid}/report.pdf?days={days}")
        assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert "rapport_mia" in r.headers["content-disposition"]
    assert client.get("/admin/student/9999/report.pdf").status_code == 404
    admin_id = _conn().execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
    assert client.get(f"/admin/student/{admin_id}/report.pdf").status_code == 404   # bara elever
