"""Tester för fliken Uppgifter: skapa, ge till elever, markera utförd, godkänn/avslå och poäng."""
import http.server
import re
import threading
from pathlib import Path

import pytest

from app import logic, motivation, tasks
from app import db as database

from .conftest import login
from .test_features import PNG, _make_student


def _conn():
    """Testets egen anslutning. Autocommit, så att en öppen transaktion här aldrig håller låset mot appen."""
    c = database.connect()
    c.isolation_level = None
    return c


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


def _admin(client):
    client.post("/logout")
    login(client, "admin", "adminpass1")


def _student(client, name="mia"):
    client.post("/logout")
    login(client, name, "hemligt1")


def _new_task(client, title="Städa rummet", body="Plocka upp allt från golvet.", points="50"):
    """Skapar en uppgift som admin och returnerar dess id."""
    _admin(client)
    r = client.post("/admin/uppgifter/ny", data={"title": title, "body": body, "points": points})
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1])


def _give(client, task_id, *names):
    _admin(client)
    ids = [_uid(_conn(), n) for n in names]
    assert client.post(f"/admin/uppgifter/{task_id}/tilldela", data={"students": ids}).status_code == 303


def _aid(task_id, name="mia"):
    c = _conn()
    return c.execute("SELECT id FROM task_assignments WHERE task_id=? AND user_id=? ORDER BY id DESC",
                     (task_id, _uid(c, name))).fetchone()["id"]


def _done(client, task_id, name="mia", note=""):
    _student(client, name)
    aid = _aid(task_id, name)
    assert client.post(f"/uppgifter/{aid}/klar", data={"note": note}).status_code == 303
    return aid


def _review(client, aid, decision, comment="", back=""):
    _admin(client)
    return client.post(f"/admin/uppgifter/tilldelning/{aid}/granska",
                       data={"decision": decision, "comment": comment, "back": back})


def _points(name="mia"):
    c = _conn()
    return motivation.points(c, _uid(c, name))


# ---------------------------------------------------------------- skapa och ändra

def test_admin_creates_task_and_it_is_listed(client):
    _make_student(client)
    tid = _new_task(client)
    page = client.get("/admin/uppgifter").text
    assert "Städa rummet" in page and "ingen än" in page
    detail = client.get(f"/admin/uppgifter/{tid}").text
    assert "Plocka upp allt från golvet." in detail and 'value="50"' in detail
    row = _conn().execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    assert (row["points"], row["active"], row["image"]) == (50, 1, None)


def test_task_validation_keeps_what_was_typed(client):
    login(client, "admin", "adminpass1")
    for data, text in (({"title": "  ", "body": "x", "points": "5"}, "Skriv en rubrik"),
                       ({"title": "A", "body": "Min långa text", "points": "abc"}, "heltal"),
                       ({"title": "A", "body": "Min långa text", "points": "-3"}, "mellan 0 och"),
                       ({"title": "A", "body": "Min långa text", "points": "999999999"}, "mellan 0 och")):
        r = client.post("/admin/uppgifter/ny", data=data)
        assert r.status_code == 400 and text in r.text
        assert data["body"] in r.text                      # texten som skrevs finns kvar i formuläret
    assert _conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_task_can_be_edited_and_text_is_escaped(client):
    tid = _new_task(client, title="<b>Fet</b>", body="<script>alert(1)</script>")
    page = client.get(f"/admin/uppgifter/{tid}").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    r = client.post(f"/admin/uppgifter/{tid}", data={"title": "Ny rubrik", "body": "Ny text", "points": "70"})
    assert r.status_code == 303
    row = _conn().execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    assert (row["title"], row["body"], row["points"]) == ("Ny rubrik", "Ny text", 70)
    assert client.post(f"/admin/uppgifter/{tid}", data={"title": "", "points": "1"}).status_code == 400
    assert client.get("/admin/uppgifter/9999").status_code == 404


def test_only_admin_can_use_admin_task_routes_and_only_students_the_student_ones(client):
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _aid(tid)
    _student(client)
    for method, url, data in (("get", "/admin/uppgifter", None), ("get", f"/admin/uppgifter/{tid}", None),
                              ("post", "/admin/uppgifter/ny", {"title": "x"}),
                              ("post", f"/admin/uppgifter/{tid}/tilldela", {"students": [1]}),
                              ("post", f"/admin/uppgifter/tilldelning/{aid}/granska", {"decision": "approve"}),
                              ("post", f"/admin/uppgifter/{tid}/ta-bort", None)):
        assert getattr(client, method)(url, **({"data": data} if data is not None else {})).status_code == 403, url
    _admin(client)
    assert client.get("/uppgifter").status_code == 403
    client.post("/logout")
    assert client.get("/uppgifter").status_code == 303        # inloggning krävs


# ---------------------------------------------------------------- bild

def test_task_image_upload_replace_remove_and_cleanup(client):
    _make_student(client)
    _admin(client)
    r = client.post("/admin/uppgifter/ny", data={"title": "Rita", "body": "", "points": "10"},
                    files={"image": ("hund.png", PNG, "image/png")})
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    img = _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"]
    assert re.fullmatch(r"uppgift-[0-9a-f]{10}\.png", img)
    from app import main
    path = main.media_dir() / img
    assert path.is_file() and client.get(f"/media/{img}").status_code == 200
    assert f"/media/{img}" in client.get(f"/admin/uppgifter/{tid}").text

    # byte av bild raderar den gamla filen
    client.post(f"/admin/uppgifter/{tid}", data={"title": "Rita", "points": "10"},
                files={"image": ("katt.png", PNG, "image/png")})
    img2 = _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"]
    assert img2 != img and not path.exists() and (main.media_dir() / img2).is_file()

    # ta bort bilden
    client.post(f"/admin/uppgifter/{tid}", data={"title": "Rita", "points": "10", "remove_image": "1"})
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"] is None
    assert not (main.media_dir() / img2).exists()

    # radera uppgiften raderar bilden
    r = client.post("/admin/uppgifter/ny", data={"title": "Två", "points": "1"},
                    files={"image": ("a.png", PNG, "image/png")})
    t2 = int(r.headers["location"].rsplit("/", 1)[1])
    img3 = _conn().execute("SELECT image FROM tasks WHERE id=?", (t2,)).fetchone()["image"]
    assert (main.media_dir() / img3).is_file()
    client.post(f"/admin/uppgifter/{t2}/ta-bort")
    assert not (main.media_dir() / img3).exists()


def test_form_with_empty_file_field_like_a_browser_sends_it(client):
    """En webbläsare skickar med ett tomt filfält när ingen bild valts. Det ska fungera som "ingen bild"."""
    _admin(client)
    r = client.post("/admin/uppgifter/ny", data={"title": "Utan bild", "body": "x", "points": "5", "image_url": ""},
                    files={"image": ("", b"", "application/octet-stream")})
    assert r.status_code == 303
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"] is None
    r = client.post(f"/admin/uppgifter/{tid}", data={"title": "Utan bild 2", "body": "x", "points": "6"},
                    files={"image": ("", b"", "application/octet-stream")})
    assert r.status_code == 303
    assert _conn().execute("SELECT title, points FROM tasks WHERE id=?", (tid,)).fetchone()[:] == ("Utan bild 2", 6)


def test_task_image_does_not_delete_other_media_files(client):
    """Bara filer som heter uppgift-* tas bort, aldrig övningsbilder eller startmaterial."""
    from app import main
    _admin(client)
    seed = next(f for f in main.media_dir().iterdir() if f.is_file())
    _conn().execute("INSERT INTO tasks(title, image) VALUES ('X', ?)", (seed.name,)).connection.commit()
    tid = _conn().execute("SELECT id FROM tasks").fetchone()["id"]
    client.post(f"/admin/uppgifter/{tid}", data={"title": "X", "points": "1", "remove_image": "1"})
    assert seed.is_file()


def test_task_image_rejects_bad_uploads_and_keeps_form(client):
    _admin(client)
    for name, data, text in (("x.exe", b"MZ....", "filtyp"), ("x.png", b"not a png", "ser inte ut som"),
                             ("x.png", PNG + b"0" * 3_100_000, "större än 3 MB")):
        r = client.post("/admin/uppgifter/ny", data={"title": "Min rubrik", "points": "5"},
                        files={"image": (name, data, "application/octet-stream")})
        assert r.status_code == 400 and text in r.text and "Min rubrik" in r.text, text
    assert _conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_task_image_from_url_uses_fetch_and_reports_errors(client, monkeypatch):
    _admin(client)
    seen = []
    monkeypatch.setattr(tasks, "fetch_image", lambda url: seen.append(url) or (".png", PNG))
    r = client.post("/admin/uppgifter/ny", data={"title": "Webbild", "points": "5", "image_url": " https://exempel.se/a.png "})
    assert r.status_code == 303 and seen == [" https://exempel.se/a.png "]
    img = _conn().execute("SELECT image FROM tasks").fetchone()["image"]
    from app import main
    assert re.fullmatch(r"uppgift-[0-9a-f]{10}\.png", img) and (main.media_dir() / img).read_bytes() == PNG

    def boom(url):
        raise ValueError("Webbadressen pekar på en intern adress och kan inte användas.")
    monkeypatch.setattr(tasks, "fetch_image", boom)
    r = client.post("/admin/uppgifter/ny", data={"title": "Dålig", "points": "5", "image_url": "http://10.0.0.1/x.png"})
    assert r.status_code == 400 and "intern adress" in r.text and "http://10.0.0.1/x.png" in r.text
    assert _conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


# ---------------------------------------------------------------- hämta bild från webbadress

class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        routes = {"/img.png": (200, "image/png", PNG), "/text": (200, "text/plain", b"hej"),
                  "/big": (200, "image/png", PNG + b"0" * 3_100_000), "/missing": (404, "text/plain", b"nej")}
        if self.path == "/redir":
            self.send_response(302); self.send_header("Location", "/img.png"); self.end_headers(); return
        if self.path == "/redir-private":
            self.send_response(302); self.send_header("Location", "http://10.0.0.5/secret.png"); self.end_headers(); return
        status, ctype, body = routes.get(self.path, (404, "text/plain", b""))
        self.send_response(status); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


@pytest.fixture()
def web(monkeypatch):
    """En lokal webbserver som får gälla som 'publik' i testet (och som får använda sin slumpmässiga port)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    real = tasks._public_ip
    monkeypatch.setattr(tasks, "_public_ip", lambda host, p: "127.0.0.1" if host == "bilder.test" else real(host, p))
    monkeypatch.setattr(tasks, "ALLOWED_PORTS", {80, 443, port})
    yield f"http://bilder.test:{port}"
    server.shutdown()


def test_fetch_image_downloads_follows_redirects_and_sniffs(web):
    assert tasks.fetch_image(web + "/img.png") == (".png", PNG)
    assert tasks.fetch_image(web + "/redir") == (".png", PNG)


def test_fetch_image_rejects_non_images_errors_and_big_files(web):
    for path, text in (("/text", "ingen bild"), ("/missing", r"fel \(404\)"), ("/big", "större än 3 MB")):
        with pytest.raises(ValueError, match=text):
            tasks.fetch_image(web + path)


def test_fetch_image_does_not_follow_redirects_to_private_addresses(web):
    with pytest.raises(ValueError, match="intern adress"):
        tasks.fetch_image(web + "/redir-private")


@pytest.mark.parametrize("url,text", [
    ("", "börjar med http"), ("ftp://exempel.se/a.png", "börjar med http"), ("javascript:alert(1)", "börjar med http"),
    ("file:///etc/passwd", "börjar med http"), ("http://", "börjar med http"),
    ("http://127.0.0.1/a.png", "intern adress"), ("http://localhost/a.png", "intern adress"),
    ("http://10.1.2.3/a.png", "intern adress"), ("http://192.168.1.1/a.png", "intern adress"),
    ("http://172.16.0.9/a.png", "intern adress"), ("http://169.254.169.254/latest/meta-data", "intern adress"),
    ("http://[::1]/a.png", "intern adress"), ("http://[::ffff:127.0.0.1]/a.png", "intern adress"),
    ("http://0.0.0.0/a.png", "intern adress"),
    ("http://exempel.se:22/a.png", "vanliga webbportar"), ("http://exempel.se:99999/a.png", "giltig"),
])
def test_fetch_image_blocks_unsafe_urls(url, text):
    with pytest.raises(ValueError, match=text):
        tasks.fetch_image(url)


# ---------------------------------------------------------------- ge till elever

def test_assign_to_several_students_skips_duplicates_and_inactive(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    _make_student(client, "cia")
    c = _conn()
    c.execute("UPDATE users SET active=0 WHERE username='cia'")
    c.commit()
    tid = _new_task(client)
    ids = [_uid(_conn(), n) for n in ("mia", "ben", "cia")]
    admin_id = _uid(_conn(), "admin")
    r = client.post(f"/admin/uppgifter/{tid}/tilldela", data={"students": ids + [admin_id, 9999]})
    assert r.status_code == 303
    assert [row["user_id"] for row in _conn().execute("SELECT user_id FROM task_assignments ORDER BY user_id")] == sorted(ids[:2])
    # ger man den igen hoppas de över
    r = client.post(f"/admin/uppgifter/{tid}/tilldela", data={"students": ids[:2]})
    assert "Hoppade över" in client.get(r.headers["location"]).text
    assert _conn().execute("SELECT COUNT(*) FROM task_assignments").fetchone()[0] == 2
    page = client.get(f"/admin/uppgifter/{tid}").text
    assert page.count("(har den redan)") == 2
    assert client.post(f"/admin/uppgifter/{tid}/tilldela", data={}).status_code == 303
    assert _conn().execute("SELECT COUNT(*) FROM task_assignments").fetchone()[0] == 2


def test_archived_task_cannot_be_given_and_delete_needs_no_assignments(client):
    _make_student(client)
    tid = _new_task(client)
    client.post(f"/admin/uppgifter/{tid}/arkiv")
    assert _conn().execute("SELECT active FROM tasks WHERE id=?", (tid,)).fetchone()[0] == 0
    client.post(f"/admin/uppgifter/{tid}/tilldela", data={"students": [_uid(_conn())]})
    assert _conn().execute("SELECT COUNT(*) FROM task_assignments").fetchone()[0] == 0
    client.post(f"/admin/uppgifter/{tid}/arkiv")
    _give(client, tid, "mia")
    client.post(f"/admin/uppgifter/{tid}/ta-bort")                       # har tilldelningar → ska inte gå
    assert _conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    client.post(f"/admin/uppgifter/tilldelning/{_aid(tid)}/ta-bort")
    client.post(f"/admin/uppgifter/{tid}/ta-bort")
    assert _conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


# ---------------------------------------------------------------- elevens sida

def test_student_sees_only_own_tasks_and_a_badge_in_the_tab(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    tid = _new_task(client, title="Läs en bok")
    _give(client, tid, "mia")
    _student(client, "ben")
    page = client.get("/uppgifter").text
    assert "Läs en bok" not in page and "inga uppgifter just nu" in page
    assert client.get(f"/uppgifter/{_aid(tid)}").status_code == 404      # någon annans uppgift
    assert client.post(f"/uppgifter/{_aid(tid)}/klar").status_code == 303
    assert _conn().execute("SELECT status FROM task_assignments").fetchone()[0] == "todo"   # bens försök gjorde inget
    _student(client, "mia")
    page = client.get("/uppgifter").text
    assert "Läs en bok" in page and "Att göra" in page and "50 poäng" in page
    assert re.search(r'href="/uppgifter"[^>]*>Uppgifter <span class="pill wait"[^>]*>1</span>', page)
    detail = client.get(f"/uppgifter/{_aid(tid)}").text
    assert "Plocka upp allt från golvet." in detail and "Jag har gjort uppgiften" in detail
    assert client.get("/uppgifter/9999").status_code == 404


def test_task_image_is_shown_to_the_student(client):
    _make_student(client)
    _admin(client)
    r = client.post("/admin/uppgifter/ny", data={"title": "Titta", "points": "5"}, files={"image": ("a.png", PNG, "image/png")})
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    img = _conn().execute("SELECT image FROM tasks").fetchone()["image"]
    _give(client, tid, "mia")
    _student(client)
    assert f'src="/media/{img}"' in client.get(f"/uppgifter/{_aid(tid)}").text
    assert client.get(f"/media/{img}").status_code == 200


def test_student_marks_done_once_with_optional_note(client):
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _done(client, tid, note="Det gick bra, tog 10 minuter.")
    row = _conn().execute("SELECT * FROM task_assignments WHERE id=?", (aid,)).fetchone()
    assert row["status"] == "done" and row["done_at"] and row["student_note"] == "Det gick bra, tog 10 minuter."
    page = client.get(f"/uppgifter/{aid}").text
    assert "nu tittar admin" in page and "Det gick bra" in page and "Jag har gjort uppgiften" not in page
    assert "Väntar på att admin" in client.get("/uppgifter").text
    # en andra gång ändrar ingenting
    client.post(f"/uppgifter/{aid}/klar", data={"note": "ändrad"})
    assert _conn().execute("SELECT student_note FROM task_assignments WHERE id=?", (aid,)).fetchone()[0] == "Det gick bra, tog 10 minuter."
    assert _points()["tasks"] == 0                                        # ingen poäng före godkännande


# ---------------------------------------------------------------- granska och poäng

def test_approve_gives_points_and_student_sees_the_result(client):
    _make_student(client)
    tid = _new_task(client, points="80")
    _give(client, tid, "mia")
    aid = _done(client, tid, note="Klart!")
    _admin(client)
    page = client.get("/admin/uppgifter").text
    assert "Att granska" in page and "Klart!" in page and re.search(r'href="/admin/uppgifter"[^>]*>Uppgifter <span class="pill wait"[^>]*>1</span>', page)
    r = _review(client, aid, "approve", "Fint jobbat!", back="/admin/uppgifter")
    assert r.status_code == 303 and r.headers["location"] == "/admin/uppgifter"
    row = _conn().execute("SELECT * FROM task_assignments WHERE id=?", (aid,)).fetchone()
    assert (row["status"], row["points_awarded"], row["admin_comment"]) == ("approved", 80, "Fint jobbat!")
    assert "Att granska" not in client.get("/admin/uppgifter").text
    p = _points()
    assert p["tasks"] == 80 and p["total"] == 80 and p["balance"] == 80
    _student(client)
    page = client.get(f"/uppgifter/{aid}").text
    assert "Godkänd" in page and "Du fick 80 poäng" in page and "Fint jobbat!" in page
    assert "Klara" in client.get("/uppgifter").text
    assert "80" in client.get("/framsteg").text and "från uppgifter" in client.get("/framsteg").text


def test_reject_needs_comment_then_student_redoes_and_gets_points(client):
    _make_student(client)
    tid = _new_task(client, points="30")
    _give(client, tid, "mia")
    aid = _done(client, tid)
    assert _review(client, aid, "reject", "   ").status_code == 303
    assert _conn().execute("SELECT status FROM task_assignments").fetchone()[0] == "done"   # kräver kommentar
    assert "Skriv en kommentar" in client.get(f"/admin/uppgifter/{tid}").text
    _review(client, aid, "reject", "Du glömde under sängen.")
    assert _conn().execute("SELECT status FROM task_assignments").fetchone()[0] == "rejected"
    assert _points()["tasks"] == 0
    _student(client)
    page = client.get(f"/uppgifter/{aid}").text
    assert "Gör om uppgiften" in page and "Du glömde under sängen." in page and "Jag har gjort uppgiften" in page
    assert "Du glömde under sängen." in client.get("/uppgifter").text
    assert re.search(r'Uppgifter <span class="pill wait"[^>]*>1</span>', client.get("/uppgifter").text)   # räknas som "att göra"
    _done(client, tid, note="Nu med under sängen")
    _review(client, aid, "approve")
    assert _points()["tasks"] == 30


def test_decision_can_be_changed_and_points_follow(client):
    _make_student(client)
    tid = _new_task(client, points="40")
    _give(client, tid, "mia")
    aid = _done(client, tid)
    _review(client, aid, "approve")
    assert _points()["total"] == 40
    _review(client, aid, "reject", "Det blev fel ändå.")
    assert _points()["total"] == 0
    assert _conn().execute("SELECT points_awarded FROM task_assignments").fetchone()[0] == 0
    _student(client)
    assert client.post(f"/uppgifter/{aid}/klar").status_code == 303
    _review(client, aid, "approve")
    assert _points()["total"] == 40
    _review(client, aid, "approve", "Ny kommentar")                      # godkänt igen ger inga extra poäng
    assert _points()["total"] == 40


def test_review_before_student_is_done_is_refused(client):
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _aid(tid)
    _review(client, aid, "approve")
    assert _conn().execute("SELECT status FROM task_assignments WHERE id=?", (aid,)).fetchone()[0] == "todo"
    assert _review(client, aid, "kanske").status_code == 400
    assert _review(client, 99999, "approve").status_code == 404


def test_points_are_a_snapshot_and_count_toward_rewards(client):
    _make_student(client)
    tid = _new_task(client, points="100")
    _give(client, tid, "mia")
    aid = _done(client, tid)
    _review(client, aid, "approve")
    client.post(f"/admin/uppgifter/{tid}", data={"title": "Städa rummet", "points": "5"})    # ändrar poängen i efterhand
    assert _points()["tasks"] == 100
    sid = _uid(_conn())
    assert client.post(f"/admin/student/{sid}/rewards", data={"title": "Glass", "cost": "90"}).status_code == 303
    assert motivation.reward_list(_conn(), sid, _points()["balance"])[0]["ready"] is True
    # en ny tilldelning efter godkännande går bra och använder de nya poängen
    _give(client, tid, "mia")
    aid2 = _done(client, tid)
    _review(client, aid2, "approve")
    assert _points()["tasks"] == 105


def test_points_before_points_since_do_not_count(client):
    _make_student(client)
    tid = _new_task(client, points="60")
    _give(client, tid, "mia")
    aid = _done(client, tid)
    _review(client, aid, "approve")
    c = _conn()
    logic.get_prefs(c, _uid(c))
    c.execute("UPDATE user_prefs SET points_since=datetime('now', '+1 hour') WHERE user_id=?", (_uid(c),))
    c.commit()
    assert _points()["tasks"] == 0


def test_task_points_hidden_for_student_with_points_off(client):
    _make_student(client)
    tid = _new_task(client, points="77")
    _give(client, tid, "mia")
    aid = _aid(tid)
    c = _conn()
    logic.get_prefs(c, _uid(c))
    c.execute("UPDATE user_prefs SET points_on=0 WHERE user_id=?", (_uid(c),))
    c.commit()
    _student(client)
    assert "77" not in client.get("/uppgifter").text and "77" not in client.get(f"/uppgifter/{aid}").text
    c.execute("UPDATE user_prefs SET points_on=1 WHERE user_id=?", (_uid(c),))
    c.commit()
    assert "77 poäng" in client.get("/uppgifter").text


def test_remove_assignment_rules(client):
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _done(client, tid)
    _review(client, aid, "approve")
    client.post(f"/admin/uppgifter/tilldelning/{aid}/ta-bort")           # godkänd går inte att ta bort
    assert _conn().execute("SELECT COUNT(*) FROM task_assignments").fetchone()[0] == 1
    _give(client, tid, "mia")                                            # ny tilldelning efter godkännande
    new = _aid(tid)
    assert new != aid
    client.post(f"/admin/uppgifter/tilldelning/{new}/ta-bort", data={"back": "/admin/uppgifter/" + str(tid)})
    assert _conn().execute("SELECT COUNT(*) FROM task_assignments").fetchone()[0] == 1
    assert client.post("/admin/uppgifter/tilldelning/9999/ta-bort").status_code == 404


def test_back_parameter_cannot_redirect_elsewhere(client):
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _done(client, tid)
    for evil in ("https://evil.example", "//evil.example", "/admin/uppgifter//evil.example", "/home", "/admin/uppgifter\\x"):
        r = _review(client, aid, "reject", "Nej", back=evil)
        assert r.headers["location"] == f"/admin/uppgifter/{tid}", evil
    r = _review(client, aid, "reject", "Nej", back="/admin/uppgifter")
    assert r.headers["location"] == "/admin/uppgifter"


def test_task_counts_in_the_admin_list(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    tid = _new_task(client)
    _give(client, tid, "mia", "ben")
    _done(client, tid, "mia")
    _admin(client)
    page = client.get("/admin/uppgifter").text
    assert "1 att göra · 1 väntar på granskning" in page
    _review(client, _aid(tid, "mia"), "approve")
    assert "1 att göra · 1 godkänd" in client.get("/admin/uppgifter").text


def test_tables_are_added_to_an_old_database(tmp_path, monkeypatch):
    """En databas från före uppgifterna får tabellerna när appen startar, utan att data försvinner."""
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, password_hash TEXT, "
                      "role TEXT, active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));"
                      "INSERT INTO users(username, display_name, password_hash, role) VALUES ('a','A','x','admin');")
    old.commit()
    old.close()
    monkeypatch.setattr(database, "DB_PATH", str(path))
    database.init_db()
    conn = database.connect()
    assert {"tasks", "task_assignments"} <= {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()


# ---------------------------------------------------------------- siffra i elevens flik vid godkänt/avslag

def _badge(page: str):
    """Siffran i fliken Uppgifter (None om ingen siffra visas)."""
    m = re.search(r'href="/uppgifter"[^>]*>Uppgifter(?: <span class="pill wait"[^>]*>(\d+)</span>)?', page)
    assert m, "fliken Uppgifter finns inte"
    return int(m.group(1)) if m.group(1) else None


def test_student_gets_a_number_when_a_task_is_approved(client):
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _done(client, tid)
    assert _badge(client.get("/home").text) is None                     # klar och inväntar granskning: inget att göra
    _review(client, aid, "approve", "Bra!")
    _student(client)
    assert _badge(client.get("/home").text) == 1                        # syns på alla sidor, inte bara på Uppgifter
    page = client.get("/uppgifter").text
    assert "Nytt svar från admin" in page and _badge(page) == 1         # markerad i listan
    assert _badge(client.get("/fakta").text) == 1
    detail = client.get(f"/uppgifter/{aid}").text
    assert "Godkänd" in detail and _badge(detail) is None               # siffran är borta redan på den här sidan
    assert _badge(client.get("/home").text) is None
    page = client.get("/uppgifter").text
    assert "Nytt svar från admin" not in page and "Klara" in page


def test_rejection_counts_as_a_number_and_stays_until_redone(client):
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _done(client, tid)
    _review(client, aid, "reject", "Gör om, tack.")
    _student(client)
    assert _badge(client.get("/home").text) == 1
    assert "Nytt svar från admin" in client.get("/uppgifter").text
    assert _badge(client.get(f"/uppgifter/{aid}").text) == 1             # avslaget är kvar att göra
    assert "Nytt svar från admin" not in client.get("/uppgifter").text   # men inte längre "nytt"
    assert client.post(f"/uppgifter/{aid}/klar").status_code == 303
    assert _badge(client.get("/home").text) is None
    _review(client, aid, "approve")
    _student(client)
    assert _badge(client.get("/home").text) == 1


def test_a_changed_decision_is_new_again_and_other_students_do_not_clear_it(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    tid = _new_task(client)
    _give(client, tid, "mia", "ben")
    aid = _done(client, tid, "mia")
    _review(client, aid, "approve")
    _student(client, "ben")
    assert client.get(f"/uppgifter/{aid}").status_code == 404           # bens försök varken visar eller kvitterar
    assert _conn().execute("SELECT result_seen FROM task_assignments WHERE id=?", (aid,)).fetchone()[0] == 0
    _student(client, "mia")
    client.get(f"/uppgifter/{aid}")
    assert _conn().execute("SELECT result_seen FROM task_assignments WHERE id=?", (aid,)).fetchone()[0] == 1
    _review(client, aid, "approve", "Bra, och jag la till en kommentar.")      # admin ändrar i efterhand
    _student(client, "mia")
    assert _badge(client.get("/home").text) == 1


def test_only_the_admin_sees_the_review_count_and_not_the_student_one(client):
    """Admins siffra är antalet att granska och påverkas inte av elevens notiser."""
    _make_student(client)
    tid = _new_task(client)
    _give(client, tid, "mia")
    aid = _done(client, tid)
    _admin(client)
    assert re.search(r'href="/admin/uppgifter"[^>]*>Uppgifter <span class="pill wait"[^>]*>1</span>', client.get("/admin").text)
    _review(client, aid, "approve")
    assert "pill wait" not in re.search(r'<nav>.*?</nav>', client.get("/admin").text, re.S).group(0)


def test_result_seen_column_is_added_to_a_database_made_before_it_existed(tmp_path, monkeypatch):
    """Redan givna uppgifter får inte plötsligt se ut som nya svar när kolumnen läggs till."""
    import sqlite3
    path = tmp_path / "mid.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, password_hash TEXT, role TEXT,
                            active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
        INSERT INTO users(username, display_name, password_hash, role) VALUES ('mia','Mia','x','student');
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', image TEXT,
                            points INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
        INSERT INTO tasks(title, points) VALUES ('Gammal', 10);
        CREATE TABLE task_assignments (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'todo', student_note TEXT NOT NULL DEFAULT '', admin_comment TEXT NOT NULL DEFAULT '',
            points_awarded INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT (datetime('now')), done_at TEXT, reviewed_at TEXT);
        INSERT INTO task_assignments(task_id, user_id, status, points_awarded, reviewed_at) VALUES (1, 1, 'approved', 10, datetime('now'));
    """)
    old.commit()
    old.close()
    monkeypatch.setattr(database, "DB_PATH", str(path))
    database.init_db()
    database.init_db()                                                 # går att köra igen
    conn = database.connect()
    row = conn.execute("SELECT status, points_awarded, result_seen FROM task_assignments").fetchone()
    assert tuple(row) == ("approved", 10, 1)
    assert tasks.badge_count(conn, {"role": "student", "id": 1}) == 0
    conn.close()


# ---------------------------------------------------------------- Bilder: hämta från webbadress

def _media_flash(client) -> str:
    return client.get("/admin/media").text


def test_media_page_fetches_image_from_url_and_never_overwrites(client, web):
    from app import main
    _admin(client)
    assert 'action="/admin/media/url"' in client.get("/admin/media").text
    r = client.post("/admin/media/url", data={"image_url": web + "/img.png"})
    assert r.status_code == 303 and r.headers["location"] == "/admin/media"
    assert "sparade den som img.png" in _media_flash(client)
    path = main.media_dir() / "img.png"
    assert path.read_bytes() == PNG and client.get("/media/img.png").status_code == 200
    assert "img.png" in client.get("/admin/media").text                  # syns i listan

    path.write_bytes(b"originalet")                                      # samma namn igen skriver inte över
    client.post("/admin/media/url", data={"image_url": web + "/img.png"})
    flash = _media_flash(client)
    assert path.read_bytes() == b"originalet"
    new = re.search(r"sparade den som (img-[0-9a-f]{4}\.png)", flash).group(1)
    assert (main.media_dir() / new).read_bytes() == PNG


def test_media_from_url_name_handling(client, web):
    from app import main
    _admin(client)
    for given, expected in (("Karta Sverige", "karta-sverige.png"), ("karta.jpg", "karta.png"),      # ändelsen följer innehållet
                            ("../../evil", "evil.png"), ("   ", "img.png"), ("åäö", "bild.png")):
        client.post("/admin/media/url", data={"image_url": web + "/img.png", "name": given})
        saved = re.search(r"sparade den som ([^\s.]+(?:\.[a-z]+)?)\. ", _media_flash(client))
        assert saved and saved.group(1).startswith(expected.rsplit(".", 1)[0]), (given, saved)
    names = {f.name for f in main.media_dir().iterdir()}
    assert "karta-sverige.png" in names and "karta.png" in names and "evil.png" in names
    assert not any(n.endswith(".jpg") and n.startswith("karta") for n in names)
    assert all(f.resolve().parent == main.media_dir().resolve() for f in main.media_dir().iterdir())


def test_media_from_url_errors_are_shown_and_nothing_is_saved(client, web):
    from app import main
    _admin(client)
    before = {f.name for f in main.media_dir().iterdir()}
    for url, text in (("", "Klistra in en webbadress"), ("   ", "Klistra in en webbadress"),
                      ("http://127.0.0.1/a.png", "intern adress"), ("http://192.168.0.1/a.png", "intern adress"),
                      ("ftp://x/a.png", "börjar med http"), (web + "/text", "ingen bild"), (web + "/missing", "fel \\(404\\)"),
                      (web + "/big", "större än 3 MB")):
        r = client.post("/admin/media/url", data={"image_url": url})
        assert r.status_code == 303
        assert re.search(text, _media_flash(client)), url
    assert {f.name for f in main.media_dir().iterdir()} == before


def test_media_from_url_is_admin_only(client, web):
    _make_student(client)
    _student(client)
    assert client.post("/admin/media/url", data={"image_url": web + "/img.png"}).status_code == 403
    client.post("/logout")
    assert client.post("/admin/media/url", data={"image_url": web + "/img.png"}).status_code == 303   # till inloggningen


def test_reused_media_is_safe_for_tasks_and_exercises(client):
    """Bilder i mediamappen kan återanvändas: en uppgiftsbild som en övning också använder raderas inte, och att ta bort
    en bild på Bilder-sidan tar bort hänvisningen i uppgiften i stället för att lämna en trasig bild."""
    from app import main
    _admin(client)
    r = client.post("/admin/uppgifter/ny", data={"title": "A", "points": "1"}, files={"image": ("a.png", PNG, "image/png")})
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    img = _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"]
    assert f"{img}" in client.get("/admin/media").text and "1 uppgift" in client.get("/admin/media").text
    # en övning återanvänder samma bild
    ex = _conn().execute("INSERT INTO exercises(subject, topic, level, type, question, answers, image) "
                         "VALUES ('matte','t',1,'text','Vilken bild?','[\"x\"]', ?)", (img,)).lastrowid
    client.post(f"/admin/uppgifter/{tid}", data={"title": "A", "points": "1", "remove_image": "1"})
    assert (main.media_dir() / img).is_file()                             # övningen använder den, så den ligger kvar
    # tillbaka i en uppgift, och sedan raderas bilden på Bilder-sidan
    _conn().execute("UPDATE tasks SET image=? WHERE id=?", (img, tid))
    client.post(f"/admin/media/{img}/delete")
    assert not (main.media_dir() / img).exists()
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"] is None
    assert "bilden användes av 1 övning och 1 uppgift." in _media_flash(client)
    assert ex


# ---------------------------------------------------------------- välja en befintlig bild

def _media_file():
    """En av de medföljande bilderna i mediamappen."""
    from app import main
    return sorted(f.name for f in main.media_dir().iterdir() if f.suffix == ".svg")[0]


def test_task_form_lists_existing_images_to_pick_from(client):
    _admin(client)
    img = _media_file()
    page = client.get("/admin/uppgifter").text
    assert 'name="image_existing"' in page and f'value="{img}"' in page and f'src="/media/{img}"' in page
    assert "välj en bild som redan finns" in page


def test_task_can_use_an_existing_image_without_copying_it(client):
    from app import main
    _admin(client)
    img = _media_file()
    before = sorted(f.name for f in main.media_dir().iterdir())
    r = client.post("/admin/uppgifter/ny", data={"title": "Med bild", "points": "5", "image_existing": img})
    assert r.status_code == 303
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"] == img
    assert sorted(f.name for f in main.media_dir().iterdir()) == before            # ingen kopia
    detail = client.get(f"/admin/uppgifter/{tid}").text
    assert f"{img} (nuvarande)" in detail and "Behåll nuvarande" in detail
    # eleven ser bilden
    _make_student(client)
    _give(client, tid, "mia")
    _student(client)
    assert f'src="/media/{img}"' in client.get(f"/uppgifter/{_aid(tid)}").text


def test_picking_a_new_image_replaces_the_old_and_never_deletes_library_images(client):
    from app import main
    _admin(client)
    lib = _media_file()
    # uppgiften börjar med en egen uppladdad bild
    r = client.post("/admin/uppgifter/ny", data={"title": "A", "points": "1"}, files={"image": ("a.png", PNG, "image/png")})
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    own = _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"]
    assert (main.media_dir() / own).is_file()
    # byte till en bild ur biblioteket: den egna bilden städas bort, biblioteksbilden finns kvar
    client.post(f"/admin/uppgifter/{tid}", data={"title": "A", "points": "1", "image_existing": lib})
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"] == lib
    assert not (main.media_dir() / own).exists() and (main.media_dir() / lib).is_file()
    # ta bort bilden: biblioteksbilden ligger kvar
    client.post(f"/admin/uppgifter/{tid}", data={"title": "A", "points": "1", "remove_image": "1"})
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"] is None
    assert (main.media_dir() / lib).is_file()
    # väljer man samma bild igen raderas ingenting
    client.post(f"/admin/uppgifter/{tid}", data={"title": "A", "points": "1", "image_existing": lib})
    client.post(f"/admin/uppgifter/{tid}", data={"title": "A", "points": "1", "image_existing": lib})
    assert (main.media_dir() / lib).is_file()
    # tom radioknapp ("Behåll nuvarande") ändrar ingenting
    client.post(f"/admin/uppgifter/{tid}", data={"title": "A2", "points": "1", "image_existing": ""})
    assert _conn().execute("SELECT image, title FROM tasks WHERE id=?", (tid,)).fetchone()[:] == (lib, "A2")


def test_two_tasks_can_share_an_uploaded_image_and_it_goes_with_the_last(client):
    from app import main
    _admin(client)
    r = client.post("/admin/uppgifter/ny", data={"title": "Först", "points": "1"}, files={"image": ("a.png", PNG, "image/png")})
    t1 = int(r.headers["location"].rsplit("/", 1)[1])
    shared = _conn().execute("SELECT image FROM tasks WHERE id=?", (t1,)).fetchone()["image"]
    r = client.post("/admin/uppgifter/ny", data={"title": "Sedan", "points": "1", "image_existing": shared})
    t2 = int(r.headers["location"].rsplit("/", 1)[1])
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (t2,)).fetchone()["image"] == shared
    assert "2 uppgifter" in client.get("/admin/media").text
    client.post(f"/admin/uppgifter/{t1}/ta-bort")
    assert (main.media_dir() / shared).is_file()                                  # den andra uppgiften använder den
    client.post(f"/admin/uppgifter/{t2}/ta-bort")
    assert not (main.media_dir() / shared).exists()


def test_image_priority_and_bad_picks(client):
    from app import main
    _admin(client)
    lib = _media_file()
    # uppladdning går före vald bild
    r = client.post("/admin/uppgifter/ny", data={"title": "Upp", "points": "1", "image_existing": lib},
                    files={"image": ("a.png", PNG, "image/png")})
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    assert _conn().execute("SELECT image FROM tasks WHERE id=?", (tid,)).fetchone()["image"].startswith("uppgift-")
    n = _conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    for bad in ("finns-inte.png", "../x.png", "..%2Fx.png", "/etc/passwd", "a/b.png", "notes.txt", "app", "x" * 200 + ".png"):
        r = client.post("/admin/uppgifter/ny", data={"title": "Min rubrik", "points": "1", "image_existing": bad})
        assert r.status_code == 400 and "Den valda bilden finns inte längre" in r.text and "Min rubrik" in r.text, bad
    (main.media_dir() / "anteckningar.txt").write_text("hej")
    r = client.post("/admin/uppgifter/ny", data={"title": "T", "points": "1", "image_existing": "anteckningar.txt"})
    assert r.status_code == 400                                                    # bara bilder går att välja
    assert _conn().execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == n


# ---------------------------------------------------------------- uppgifter på rapporten

def test_task_can_be_marked_for_the_report_when_created_and_edited(client):
    _admin(client)
    r = client.post("/admin/uppgifter/ny", data={"title": "Med", "points": "1", "in_report": "1"})
    t1 = int(r.headers["location"].rsplit("/", 1)[1])
    r = client.post("/admin/uppgifter/ny", data={"title": "Utan", "points": "1"})
    t2 = int(r.headers["location"].rsplit("/", 1)[1])
    flags = {r["id"]: r["in_report"] for r in _conn().execute("SELECT id, in_report FROM tasks")}
    assert flags == {t1: 1, t2: 0}
    assert re.search(r'name="in_report" value="1" checked', client.get(f"/admin/uppgifter/{t1}").text)
    assert not re.search(r'name="in_report" value="1" checked', client.get(f"/admin/uppgifter/{t2}").text)
    page = client.get("/admin/uppgifter").text
    assert page.count(">på rapporten</span>") == 1                                # pillret i listan, en gång
    client.post(f"/admin/uppgifter/{t1}", data={"title": "Med", "points": "1"})        # kryssrutan avmarkerad
    client.post(f"/admin/uppgifter/{t2}", data={"title": "Utan", "points": "1", "in_report": "1"})
    flags = {r["id"]: r["in_report"] for r in _conn().execute("SELECT id, in_report FROM tasks")}
    assert flags == {t1: 0, t2: 1}
    # ett fel i formuläret behåller kryssen
    r = client.post(f"/admin/uppgifter/{t1}", data={"title": "", "points": "1", "in_report": "1"})
    assert r.status_code == 400 and re.search(r'name="in_report" value="1" checked', r.text)


def _student_row(name="mia"):
    c = _conn()
    return c.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()


def _report_texts(monkeypatch, days=30, name="mia"):
    """Bygger rapporten och returnerar all text som hamnade i den."""
    from app import report
    texts = []
    real = report._p
    monkeypatch.setattr(report, "_p", lambda text, style: texts.append(str(text)) or real(text, style))
    pdf = report.build_pdf(_conn(), _student_row(name), days)
    assert pdf.startswith(b"%PDF")
    return "\n".join(texts)


def test_report_lists_only_approved_tasks_marked_for_the_report(client, monkeypatch):
    _make_student(client, "mia")
    _make_student(client, "ben")
    show = _new_task(client, title="Rita kretsloppet", body="Rita och skriv orden.\nMed   flera   mellanslag.", points="50")
    hide = _new_task(client, title="Städa rummet", points="20")
    client.post(f"/admin/uppgifter/{show}", data={"title": "Rita kretsloppet", "body": "Rita och skriv orden.\nMed   flera   mellanslag.", "points": "50", "in_report": "1"})
    open_t = _new_task(client, title="Ej klar uppgift", points="5")
    client.post(f"/admin/uppgifter/{open_t}", data={"title": "Ej klar uppgift", "points": "5", "in_report": "1"})
    for tid in (show, hide, open_t):
        _give(client, tid, "mia")
    _give(client, show, "ben")
    for tid in (show, hide):
        _review(client, _done(client, tid), "approve", "Hemlig kommentar")
    _done(client, show, "ben")                                                    # Ben är klar men inte godkänd
    # open_t lämnas som "att göra"
    from app import report
    c = _conn()
    data = report.collect(c, _student_row("mia"), 30)
    assert [t["title"] for t in data["tasks"]] == ["Rita kretsloppet"]
    text = _report_texts(monkeypatch)
    assert "Uppgifter" in text and "Rita kretsloppet – Rita och skriv orden. Med flera mellanslag." in text
    assert "Städa rummet" not in text and "Ej klar uppgift" not in text          # inte kryssad / inte godkänd
    assert "Hemlig kommentar" not in text and "50" not in text.split("Rita kretsloppet")[1].split("\n")[0]   # varken kommentar eller poäng
    assert "Rita kretsloppet" not in _report_texts(monkeypatch, name="ben")      # bara elevens egna, och bara godkända


def test_report_task_section_respects_period_and_later_changes(client, monkeypatch):
    _make_student(client)
    tid = _new_task(client, title="Gammal uppgift")
    client.post(f"/admin/uppgifter/{tid}", data={"title": "Gammal uppgift", "points": "50", "in_report": "1"})
    _give(client, tid, "mia")
    aid = _done(client, tid)
    _review(client, aid, "approve")
    c = _conn()
    c.execute("UPDATE task_assignments SET reviewed_at=datetime('now', '-100 days') WHERE id=?", (aid,))
    assert "Gammal uppgift" not in _report_texts(monkeypatch, 30)                # utanför 30 dagar
    assert "Gammal uppgift" not in _report_texts(monkeypatch, 90)
    assert "Gammal uppgift" in _report_texts(monkeypatch, 0)                     # hela tiden
    c.execute("UPDATE task_assignments SET reviewed_at=datetime('now') WHERE id=?", (aid,))
    assert "Gammal uppgift" in _report_texts(monkeypatch, 7)
    _review(client, aid, "reject", "Nej, gör om.")                               # avslås i efterhand → försvinner
    assert "Gammal uppgift" not in _report_texts(monkeypatch, 7)
    _student(client)
    client.post(f"/uppgifter/{aid}/klar")
    _review(client, aid, "approve")
    assert "Gammal uppgift" in _report_texts(monkeypatch, 7)
    client.post(f"/admin/uppgifter/{tid}", data={"title": "Gammal uppgift", "points": "50"})   # kryssen tas bort
    assert "Gammal uppgift" not in _report_texts(monkeypatch, 7)


def test_report_with_many_and_long_tasks_still_builds_and_text_is_escaped(client, monkeypatch):
    _make_student(client)
    for i in range(30):
        tid = _new_task(client, title=f"Uppgift {i} <b>&</b>", body="Lång text. " * 100)
        client.post(f"/admin/uppgifter/{tid}", data={"title": f"Uppgift {i} <b>&</b>", "body": "Lång text. " * 100, "points": "50", "in_report": "1"})
        _give(client, tid, "mia")
        _review(client, _done(client, tid), "approve")
    text = _report_texts(monkeypatch)
    assert text.count("Uppgift ") >= 30 and "…" in text
    assert all(len(line) < 260 for line in text.split("\n") if line.startswith("•"))
    _admin(client)
    sid = _uid(_conn())
    r = client.get(f"/admin/student/{sid}/report.pdf?days=0")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_report_column_is_added_to_a_database_with_tasks_but_no_flag(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "nf.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, password_hash TEXT, role TEXT,
                            active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', image TEXT,
                            points INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT (datetime('now')));
        INSERT INTO tasks(title, points) VALUES ('Från förra versionen', 10);
    """)
    old.commit()
    old.close()
    monkeypatch.setattr(database, "DB_PATH", str(path))
    database.init_db()
    conn = database.connect()
    assert conn.execute("SELECT in_report FROM tasks").fetchone()[0] == 0        # befintliga uppgifter visas inte på rapporten
    conn.close()
