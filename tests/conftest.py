import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass1")
    monkeypatch.setenv("SECRET_FILE", str(tmp_path / "secret.key"))
    monkeypatch.setenv("BACKUPS", "0")      # ingen bakgrundstråd eller automatiska kopior i testerna
    from app import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    from app.main import app
    with TestClient(app, follow_redirects=False) as c:
        yield c


def login(client, user, pw):
    r = client.post("/login", data={"username": user, "password": pw})
    assert r.status_code == 303, r.text
    return r
