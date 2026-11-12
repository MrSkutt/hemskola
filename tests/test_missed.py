"""Tester för "Öva på det jag missat": repetition av felsvar tills eleven klarar dem."""
import re

from app import logic, missed

from .conftest import login
from .test_editor import _admin, _ex
from .test_features import _conn, _make_student


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]


def _answer(conn, uid, ex_id, correct, test_id=None, generated_id=None):
    conn.execute("INSERT INTO attempts(user_id, exercise_id, test_id, given, correct, generated_id) VALUES (?,?,?,?,?,?)",
                 (uid, ex_id, test_id, "x", 1 if correct else 0, generated_id))
    conn.commit()


def _setup(client, n=5, subject="matte"):
    """En elev och n frågor som hon svarat fel på."""
    _make_student(client)
    conn = _conn()
    uid = _uid(conn)
    ids = [_ex(conn, subject=subject, question=f"Fråga {subject} {i}?", answers='["x"]') for i in range(n)]
    for i in ids:
        _answer(conn, uid, i, False)
    return conn, uid, ids


def _student(client):
    login(client, "mia", "hemligt1")


# ------------------------------------------------------------------ vad som räknas som missat

def test_latest_answer_decides(client):
    conn, uid, (a, b, c) = _setup(client, 3)
    assert {r["id"] for r in missed.missed_items(conn, uid)} == {a, b, c}
    _answer(conn, uid, a, True)                       # klarade den sedan
    assert {r["id"] for r in missed.missed_items(conn, uid)} == {b, c}
    _answer(conn, uid, a, False)                      # och missade den igen
    assert {r["id"] for r in missed.missed_items(conn, uid)} == {a, b, c}
    conn.close()


def test_answered_right_first_and_never_missed_is_not_listed(client):
    conn, uid, _ = _setup(client, 1)
    ok = _ex(conn, subject="matte", question="Lätt?")
    _answer(conn, uid, ok, True)
    assert ok not in {r["id"] for r in missed.missed_items(conn, uid)}
    conn.close()


def test_misses_from_tests_count_too(client):
    conn, uid, _ = _setup(client, 0)
    ex = _ex(conn, subject="matte", question="Provfråga?")
    conn.execute("INSERT INTO tests(user_id, subject, kind, total) VALUES (?,?,?,?)", (uid, "matte", "status", 1))
    test_id = conn.execute("SELECT MAX(id) FROM tests").fetchone()[0]
    _answer(conn, uid, ex, False, test_id=test_id)
    assert [r["id"] for r in missed.missed_items(conn, uid)] == [ex]
    conn.close()


def test_only_the_students_own_answers(client):
    conn, uid, ids = _setup(client, 2)
    conn.execute("INSERT INTO users(username, display_name, password_hash, role) VALUES ('ali','Ali','x','student')")
    conn.commit()
    other = _uid(conn, "ali")
    assert missed.missed_items(conn, other) == []
    _answer(conn, other, ids[0], True)               # någon annans rätta svar rör inte Mias lista
    assert len(missed.missed_items(conn, uid)) == 2
    conn.close()


def test_hidden_disabled_and_other_subjects(client):
    conn, uid, ids = _setup(client, 3)
    conn.execute("UPDATE exercises SET active=0 WHERE id=?", (ids[0],))
    conn.commit()
    assert {r["id"] for r in missed.missed_items(conn, uid)} == set(ids[1:])
    other = _ex(conn, subject="svenska", question="Svensk fråga?")
    _answer(conn, uid, other, False)
    assert missed.counts(conn, uid) == {"matte": 2, "svenska": 1}
    assert [r["id"] for r in missed.missed_items(conn, uid, "svenska")] == [other]
    conn.execute("INSERT INTO user_subjects(user_id, subject, enabled) VALUES (?,?,0)", (uid, "svenska"))
    conn.commit()
    assert missed.counts(conn, uid) == {"matte": 2}
    assert missed.missed_items(conn, uid, "svenska") == []
    assert missed.missed_items(conn, uid, "finns-inte") == []
    conn.close()


def test_a_missed_generator_comes_back_as_a_new_question(client):
    conn, uid, _ = _setup(client, 0)
    gen = conn.execute("SELECT id FROM exercises WHERE generator IS NOT NULL AND subject='matte' LIMIT 1").fetchone()[0]
    _answer(conn, uid, gen, False)
    state = missed.next_missed(conn, uid)
    assert state["remaining"] == 1 and state["paused"] is True           # nyss besvarad: vänta
    _answer(conn, uid, _ex(conn, subject="matte", question="Annat?"), True)
    state = missed.next_missed(conn, uid)
    assert state["item"] and state["item"]["id"] == gen and state["item"]["generated_id"]
    conn.close()


# ------------------------------------------------------------------ vilken fråga som kommer härnäst

def test_nothing_missed_gives_nothing(client):
    conn, uid, _ = _setup(client, 0)
    assert missed.next_missed(conn, uid) == {"item": None, "remaining": 0, "paused": False}
    conn.close()


def test_the_last_answered_ones_are_not_asked_again_straight_away(client):
    conn, uid, ids = _setup(client, 6)               # sex missade, de svarades fel i ordning
    for _ in range(40):
        state = missed.next_missed(conn, uid)
        assert state["remaining"] == 6
        assert state["item"]["id"] not in ids[-missed.GAP:]
    conn.close()


def test_with_two_left_the_one_just_answered_waits(client):
    conn, uid, (a, b) = _setup(client, 2)
    for _ in range(20):
        assert missed.next_missed(conn, uid)["item"]["id"] == a
    conn.close()


def test_the_last_one_waits_until_something_else_has_been_answered(client):
    conn, uid, (a,) = _setup(client, 1)
    state = missed.next_missed(conn, uid)
    assert state == {"item": None, "remaining": 1, "paused": True}
    _answer(conn, uid, _ex(conn, subject="svenska", question="Något annat?"), True)
    assert missed.next_missed(conn, uid)["item"]["id"] == a
    conn.close()


# ------------------------------------------------------------------ startsidan

def test_home_card_shows_the_count_and_per_subject_links(client):
    conn, uid, _ = _setup(client, 3)
    _answer(conn, uid, _ex(conn, subject="svenska", question="Svensk?"), False)
    conn.close()
    _student(client)
    home = client.get("/home").text
    assert "Öva på det jag missat" in home and "<strong>4</strong> frågor" in home
    assert 'href="/missat"' in home
    assert 'href="/missat?amne=matte"' in home and "Matematik (3)" in home and "Svenska (1)" in home


def test_home_card_for_one_subject_has_no_extra_links(client):
    _setup(client, 1)
    _student(client)
    home = client.get("/home").text
    assert "<strong>1</strong> fråga som" in home and "?amne=" not in home


def test_home_has_no_card_when_nothing_is_missed(client):
    _setup(client, 0)
    _student(client)
    assert "Öva på det jag missat" not in client.get("/home").text


# ------------------------------------------------------------------ sidorna

def test_question_page_shows_what_is_left(client):
    conn, uid, ids = _setup(client, 5)
    conn.close()
    _student(client)
    page = client.get("/missat").text
    assert "Öva på det jag missat" in page and "Kvar att klara: <strong>5</strong>" in page
    assert 'action="/missat"' in page and 'name="exercise_id"' in page


def test_right_answer_clears_it_and_the_page_says_so(client):
    conn, uid, ids = _setup(client, 5)
    conn.close()
    _student(client)
    page = client.get("/missat").text
    ex_id = int(re.search(r'name="exercise_id" value="(\d+)"', page).group(1))
    r = client.post("/missat", data={"exercise_id": ex_id, "generated_id": "", "given": "x"}, follow_redirects=False)
    assert r.status_code == 303 and re.fullmatch(r"/answer/\d+\?fran=missat", r.headers["location"])
    done = client.get(r.headers["location"]).text
    assert "Den är avklarad." in done and "Kvar att klara: <strong>4</strong>" in done
    assert 'href="/missat"' in done and "Nästa fråga" in done
    c = _conn()
    assert ex_id not in {m["id"] for m in missed.missed_items(c, _uid(c))}
    assert c.execute("SELECT test_id FROM attempts ORDER BY id DESC LIMIT 1").fetchone()[0] is None
    c.close()


def test_wrong_answer_keeps_it_on_the_list(client):
    conn, uid, ids = _setup(client, 5)
    conn.close()
    _student(client)
    page = client.get("/missat").text
    ex_id = int(re.search(r'name="exercise_id" value="(\d+)"', page).group(1))
    r = client.post("/missat", data={"exercise_id": ex_id, "given": "fel svar"}, follow_redirects=False)
    done = client.get(r.headers["location"]).text
    assert "Den kommer tillbaka lite senare." in done and "Kvar att klara: <strong>5</strong>" in done
    assert "Rätt svar:" in done
    c = _conn()
    assert ex_id in {m["id"] for m in missed.missed_items(c, _uid(c))}
    c.close()


def test_working_through_the_whole_list(client):
    conn, uid, ids = _setup(client, 4)
    conn.close()
    _student(client)
    for left in (4, 3, 2, 1):
        page = client.get("/missat").text
        if "Kvar att klara" not in page:              # den sista väntar tills något annat besvarats
            c = _conn()
            _answer(c, _uid(c), _ex(c, subject="svenska", question=f"Mellanfråga {left}?"), True)
            c.close()
            page = client.get("/missat").text
        assert f"Kvar att klara: <strong>{left}</strong>" in page
        ex_id = int(re.search(r'name="exercise_id" value="(\d+)"', page).group(1))
        r = client.post("/missat", data={"exercise_id": ex_id, "given": "x"}, follow_redirects=False)
    last = client.get(r.headers["location"]).text
    assert "Du har klarat allt du missat" in last and 'href="/home"' in last and "Nästa fråga" not in last
    assert "inget att repetera" in client.get("/missat").text.lower()


def test_the_page_pauses_instead_of_repeating_the_same_question(client):
    conn, uid, (a,) = _setup(client, 1)
    conn.close()
    _student(client)
    page = client.get("/missat").text
    assert "nyss svarat" in page and "Kvar att klara" not in page and 'name="exercise_id"' not in page
    assert "<strong>1</strong> fråga kvar" in page


def test_empty_state(client):
    _setup(client, 0)
    _student(client)
    page = client.get("/missat").text
    assert "inget att repetera" in page.lower() and 'name="exercise_id"' not in page


def test_subject_filter_follows_through_the_whole_flow(client):
    conn, uid, ids = _setup(client, 3)
    sv = [_ex(conn, subject="svenska", question=f"Svensk fråga {i}?") for i in range(3)]
    for i in sv:
        _answer(conn, uid, i, False)
    conn.close()
    _student(client)
    page = client.get("/missat?amne=svenska").text
    assert 'action="/missat?amne=svenska"' in page and "Kvar att klara: <strong>3</strong>" in page
    ex_id = int(re.search(r'name="exercise_id" value="(\d+)"', page).group(1))
    assert ex_id in sv
    r = client.post("/missat?amne=svenska", data={"exercise_id": ex_id, "given": "x"}, follow_redirects=False)
    assert r.headers["location"].endswith("fran=missat&amne=svenska")
    done = client.get(r.headers["location"]).text
    assert "Kvar att klara: <strong>2</strong>" in done and 'href="/missat?amne=svenska"' in done


def test_a_missed_generator_can_be_practised_and_cleared(client):
    conn, uid, _ = _setup(client, 0)
    gen = conn.execute("SELECT id FROM exercises WHERE generator IS NOT NULL AND subject='matte' LIMIT 1").fetchone()[0]
    _answer(conn, uid, gen, False)
    _answer(conn, uid, _ex(conn, subject="matte", question="Mellanfråga?"), True)
    conn.close()
    _student(client)
    page = client.get("/missat").text
    gid = re.search(r'name="generated_id" value="(\d+)"', page).group(1)
    assert int(re.search(r'name="exercise_id" value="(\d+)"', page).group(1)) == gen
    c = _conn()
    answer = logic.item_from_generated(c, int(gid))["answers"][0]
    c.close()
    r = client.post("/missat", data={"exercise_id": gen, "generated_id": gid, "given": answer}, follow_redirects=False)
    assert r.status_code == 303
    c = _conn()
    assert gen not in {m["id"] for m in missed.missed_items(c, _uid(c))}
    assert c.execute("SELECT generated_id, correct FROM attempts ORDER BY id DESC LIMIT 1").fetchone()[:] == (int(gid), 1)
    c.close()


# ------------------------------------------------------------------ säkerhet och felsvar

def test_admin_cannot_use_the_student_page(client):
    _admin(client)
    assert client.get("/missat").status_code == 403
    assert client.post("/missat", data={"exercise_id": 1, "given": "x"}).status_code == 403


def test_bad_posts_record_nothing(client):
    conn, uid, ids = _setup(client, 2)
    before = conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    conn.execute("INSERT INTO user_subjects(user_id, subject, enabled) VALUES (?,?,0)", (uid, "svenska"))
    off = _ex(conn, subject="svenska", question="Avstängt ämne?")
    conn.close()
    _student(client)
    for data in ({"exercise_id": ids[0], "given": "   "}, {"exercise_id": 999999, "given": "x"},
                 {"exercise_id": off, "given": "x"}, {"exercise_id": ids[0], "generated_id": "424242", "given": "x"}):
        r = client.post("/missat", data=data, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/missat"
    assert _conn().execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == before


def test_a_strange_subject_param_is_ignored_everywhere(client):
    conn, uid, ids = _setup(client, 4)
    conn.close()
    _student(client)
    bad = "<script>alert(1)</script>"
    page = client.get("/missat", params={"amne": bad}).text            # som om inget ämne valts
    assert "<script>alert(1)" not in page and "Kvar att klara: <strong>4</strong>" in page
    assert 'action="/missat"' in page
    r = client.post("/missat", params={"amne": bad}, data={"exercise_id": ids[0], "given": "x"}, follow_redirects=False)
    assert r.headers["location"].endswith("?fran=missat")
    done = client.get(r.headers["location"] + "&amne=" + bad).text
    assert "<script>alert(1)" not in done and "Kvar att klara: <strong>3</strong>" in done
    assert 'href="/missat"' in done
