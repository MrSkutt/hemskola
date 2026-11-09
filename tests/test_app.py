import json

from .conftest import login


def test_requires_login(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert client.get("/admin").status_code == 303


def test_bad_login(client):
    r = client.post("/login", data={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_seed_loaded_and_admin_pages(client):
    login(client, "admin", "adminpass1")
    for url in ["/admin", "/admin/users", "/admin/exercises", "/admin/import", "/admin/exercises/export.json"]:
        r = client.get(url)
        assert r.status_code == 200, url
    assert len(client.get("/admin/exercises/export.json").json()) == 100


def test_full_student_flow(client):
    login(client, "admin", "adminpass1")
    r = client.post("/admin/users/new", data={"username": "mia", "display_name": "Mia", "password": "hemligt1", "role": "student"})
    assert r.status_code == 303
    client.post("/logout")

    login(client, "mia", "hemligt1")
    assert client.get("/admin").status_code == 403
    home = client.get("/home")
    assert "Starta inledande test" in home.text

    r = client.post("/test/start/matte")
    test_url = r.headers["location"]
    for _ in range(10):
        page = client.get(test_url)
        assert page.status_code == 200
        import re
        ex_id = re.search(r'name="exercise_id" value="(\d+)"', page.text).group(1)
        client.post(test_url, data={"exercise_id": ex_id, "given": "0"})
    r = client.get(test_url)
    assert r.headers["location"].endswith("/result")
    res = client.get(r.headers["location"])
    assert "0 av 10 rätt" in res.text

    # efter provet finns en nivå och man kan öva
    r = client.get("/practice/matte")
    assert r.status_code == 200
    ex_id = re.search(r'name="exercise_id" value="(\d+)"', r.text).group(1)
    r = client.post("/practice/matte", data={"exercise_id": ex_id, "given": "-12345"})
    assert r.status_code == 303 and "/answer/" in r.headers["location"]
    assert client.get(r.headers["location"]).status_code == 200

    # eleven kommer inte åt någon annans svar/prov
    assert client.get("/answer/99999").status_code == 404
    client.post("/logout")

    login(client, "admin", "adminpass1")
    page = client.get("/admin")
    assert "Mia" in page.text
    sid = re.search(r"/admin/student/(\d+)", page.text).group(1)
    detail = client.get(f"/admin/student/{sid}")
    assert detail.status_code == 200 and "Senaste svaren" in detail.text
    r = client.post(f"/admin/student/{sid}/level", data={"subject": "matte", "level": 4})
    assert r.status_code == 303
    assert "Nivå <span class=\"level\">4</span>" in client.get(f"/admin/student/{sid}").text


def test_import(client):
    login(client, "admin", "adminpass1")
    data = [{"subject": "engelska", "topic": "Glosor", "level": 1, "type": "mc", "question": "Vad betyder 'dog'?",
             "options": ["hund", "katt"], "answer": "hund"}, {"subject": "x"}]
    r = client.post("/admin/import", data={"pasted": json.dumps(data)})
    assert r.status_code == 200 and "1 nya övningar" in r.text and "1 fel" in r.text
    r = client.post("/admin/import", data={"pasted": json.dumps(data)})
    assert "1 fanns redan" in r.text
