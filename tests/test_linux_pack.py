"""Tester för Linux-paketet (exercises/linux.json) och för att Linux är ett ämne som ingen elev ser förrän admin
slår på det för just den eleven."""
import json
import re
from pathlib import Path

from app import areas
from app import exercise_editor as ed
from app import logic

from .conftest import login
from .test_features import _conn, _make_student

PACK = Path(__file__).resolve().parent.parent / "exercises" / "linux.json"


def _pack():
    return json.loads(PACK.read_text(encoding="utf-8"))


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


def _import_and_approve(conn):
    res = logic.import_exercises(conn, _pack(), review=True)
    assert res["errors"] == []
    ed.approve_matching(conn, subject="linux")
    conn.commit()
    return res


# ------------------------------------------------------------------ själva övningarna

def test_every_exercise_in_the_pack_is_valid_and_unique():
    data = _pack()
    assert len(data) >= 100
    questions = []
    for i, item in enumerate(data, start=1):
        row, err = logic.validate_exercise(item)
        assert err is None, (i, err, item.get("question"))
        assert row["subject"] == "linux"
        questions.append(row["question"])
    assert len(set(questions)) == len(questions)


def test_pack_covers_all_levels_and_both_kinds():
    data = _pack()
    levels = {}
    for item in data:
        levels[item["level"]] = levels.get(item["level"], 0) + 1
    assert set(levels) == {1, 2, 3, 4, 5}
    assert all(n >= 10 for n in levels.values()), levels
    assert {item["type"] for item in data} == {"mc", "text"}


def test_multiple_choice_has_exactly_one_correct_option():
    for item in _pack():
        if item["type"] != "mc":
            continue
        options = item["options"]
        answers = item["answer"] if isinstance(item["answer"], list) else [item["answer"]]
        assert len(answers) == 1, item["question"]
        assert len(options) == 4 and len(set(options)) == 4, item["question"]
        assert options.count(answers[0]) == 1, item["question"]
        assert item["explanation"].strip(), item["question"]


def test_correct_option_is_rarely_the_obviously_longest_one():
    """Rätt svar ska inte gå att gissa på längden: bara några få får vara tydligt längre än alla felaktiga."""
    mcs = [i for i in _pack() if i["type"] == "mc"]
    clearly_longest = [i["question"] for i in mcs
                       if len(i["answer"]) > max(len(o) for o in i["options"] if o != i["answer"]) + 3]
    assert len(clearly_longest) <= len(mcs) * 0.1, clearly_longest


def test_text_questions_accept_the_common_ways_of_writing_the_command():
    by_question = {i["question"]: i for i in _pack() if i["type"] == "text"}

    def accepts(start, given):
        item = next(i for q, i in by_question.items() if q.startswith(start))
        return logic.is_correct(given, item["answer"] if isinstance(item["answer"], list) else [item["answer"]])

    assert accepts("Skriv kommandot, med sudo, som installerar paketet htop", "sudo apt install htop")
    assert accepts("Skriv kommandot, med sudo, som installerar paketet htop", "  SUDO  apt  install  -y htop ")
    assert accepts("Skriv kommandot som visar de 20 sista raderna", "tail -n 20 app.log")
    assert accepts("Skriv kommandot som visar de 20 sista raderna", "tail -20 app.log")
    assert accepts("Skriv kommandot som startar alla tjänster", "docker compose up -d")
    assert accepts("Skriv kommandot som startar alla tjänster", "docker-compose up -d")
    assert accepts("Skriv kommandot som raderar mappen gammal", "rm -rf gammal")
    assert accepts("Skriv kommandot som visar journalen", "journalctl -u nginx")
    assert accepts("Skriv kommandot, med sudo, som startar om datorn", "sudo reboot")
    assert accepts("Vilket tresiffrigt chmod-nummer", "644")
    assert accepts("Skriv kommandot som skapar en ny katalog", "mkdir test")
    assert not accepts("Skriv kommandot som skapar en ny katalog", "mkdir")
    assert not accepts("Skriv kommandot som raderar mappen gammal", "rm gammal")
    assert not accepts("Vilket tresiffrigt chmod-nummer", "755")


def test_every_topic_belongs_to_an_area():
    topics = {i["topic"] for i in _pack()}
    assert [t for t in topics if areas.area_of("linux", t) == areas.OVRIGT] == []


# ------------------------------------------------------------------ ämnet och dess grupp

def test_linux_has_a_label_and_its_own_group():
    assert logic.label("linux") == "Linux"
    groups = logic.group_subjects(["matte", "kpop", "linux"])
    assert [g["key"] for g in groups] == ["grund", "fritid", "extra"]
    assert groups[-1]["subjects"] == ["linux"]
    assert "linux" in logic.OPT_IN_SUBJECTS and "linux" not in logic.LEISURE_SUBJECTS


# ------------------------------------------------------------------ dolt tills admin slår på det

def test_import_for_review_adds_the_pack_hidden(client):
    conn = _conn()
    res = logic.import_exercises(conn, _pack(), review=True)
    assert res["added"] == len(_pack()) and res["skipped"] == 0 and res["review"] is True
    rows = conn.execute("SELECT active, review FROM exercises WHERE subject='linux'").fetchall()
    assert all(r["active"] == 0 and r["review"] == 1 for r in rows)
    assert "linux" not in logic.active_subjects(conn)
    conn.close()


def test_pack_can_be_imported_twice_without_duplicates(client):
    conn = _conn()
    logic.import_exercises(conn, _pack(), review=True)
    again = logic.import_exercises(conn, _pack(), review=True)
    assert again["added"] == 0 and again["skipped"] == len(_pack())
    conn.close()


def test_students_do_not_get_linux_even_after_the_pack_is_approved(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    conn = _conn()
    _import_and_approve(conn)
    mia, ben = _uid(conn, "mia"), _uid(conn, "ben")
    assert "linux" in logic.active_subjects(conn)                       # övningarna är godkända och aktiva
    for uid in (mia, ben):
        assert logic.subject_settings(conn, uid)["linux"] == {"enabled": False, "in_report": False}
        assert "linux" not in logic.enabled_subjects(conn, uid)
        assert "linux" not in logic.report_subjects(conn, uid)
        assert logic.subject_enabled(conn, uid, "linux") is False
    logic.set_level(conn, mia, "linux", 1)
    conn.commit()
    conn.close()

    login(client, "mia", "hemligt1")
    assert "Linux" not in client.get("/home").text
    r = client.get("/practice/linux")
    assert r.status_code == 303 and r.headers["location"] == "/home"
    assert client.post("/test/start/linux").headers["location"] == "/home"
    ex_id = _conn().execute("SELECT id FROM exercises WHERE subject='linux' LIMIT 1").fetchone()["id"]
    assert client.post("/practice/linux", data={"exercise_id": ex_id, "given": "x"}).headers["location"] == "/home"
    conn = _conn()
    assert conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id=?", (mia,)).fetchone()[0] == 0
    conn.close()


def test_students_who_already_saved_their_subject_choices_do_not_get_linux_either(client):
    _make_student(client, "mia")
    conn = _conn()
    uid = _uid(conn)
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, enabled=subjects, in_report=subjects, subjects=subjects)   # sparat före Linux
    conn.commit()
    _import_and_approve(conn)
    assert "linux" not in logic.enabled_subjects(conn, uid)
    conn.close()


def test_admin_can_turn_linux_on_for_one_student_only(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    conn = _conn()
    _import_and_approve(conn)
    mia, ben = _uid(conn, "mia"), _uid(conn, "ben")
    others = [s for s in logic.active_subjects(conn) if s != "linux"]
    logic.set_level(conn, mia, "linux", 1)
    conn.commit()
    conn.close()

    login(client, "admin", "adminpass1")
    page = client.get(f"/admin/student/{mia}").text
    enabled_box = re.search(r'<input type="checkbox" name="enabled" value="linux"[^>]*>', page).group(0)
    report_box = re.search(r'<input type="checkbox" name="report" value="linux"[^>]*>', page).group(0)
    assert "checked" not in enabled_box and "checked" not in report_box
    assert "Extra" in page
    r = client.post(f"/admin/student/{mia}/subjects", data={"enabled": others + ["linux"], "report": []})
    assert r.status_code == 303
    page = client.get(f"/admin/student/{mia}").text
    assert "checked" in re.search(r'<input type="checkbox" name="enabled" value="linux"[^>]*>', page).group(0)
    assert "checked" not in re.search(r'<input type="checkbox" name="report" value="linux"[^>]*>', page).group(0)
    client.post("/logout")

    login(client, "mia", "hemligt1")
    assert "Linux" in client.get("/home").text
    r = client.get("/practice/linux")
    assert r.status_code == 200 and "Linux" in r.text
    client.post("/logout")

    login(client, "ben", "hemligt1")
    assert "Linux" not in client.get("/home").text
    assert client.get("/practice/linux").headers["location"] == "/home"
    conn = _conn()
    assert "linux" in logic.enabled_subjects(conn, mia) and "linux" not in logic.enabled_subjects(conn, ben)
    conn.close()


def test_admin_overview_says_linux_is_off_until_it_is_turned_on(client):
    _make_student(client, "mia")
    conn = _conn()
    _import_and_approve(conn)
    conn.close()
    login(client, "admin", "adminpass1")
    assert re.search(r"Avstängda för eleven: [^<]*Linux", client.get("/admin").text)


def test_linux_is_not_in_the_report_by_default_even_when_turned_on(client):
    _make_student(client, "mia")
    conn = _conn()
    _import_and_approve(conn)
    uid = _uid(conn)
    subjects = logic.active_subjects(conn)
    # admin slår på Linux men rör inte rapportvalet: raden för rapporten sparas som av, precis som formuläret gör
    logic.save_subject_settings(conn, uid, enabled=subjects, in_report=[s for s in subjects if s != "linux"], subjects=subjects)
    conn.commit()
    assert "linux" in logic.enabled_subjects(conn, uid) and "linux" not in logic.report_subjects(conn, uid)
    conn.close()


def test_linux_facts_page_follows_the_subject_choice(client):
    _make_student(client, "mia")
    conn = _conn()
    _import_and_approve(conn)
    uid = _uid(conn)
    conn.close()
    login(client, "mia", "hemligt1")
    assert client.get("/fakta/linux").status_code == 404
    assert "/fakta/linux" not in client.get("/fakta").text
    client.post("/logout")

    conn = _conn()
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, enabled=subjects, in_report=[], subjects=subjects)
    conn.commit()
    conn.close()
    login(client, "mia", "hemligt1")
    page = client.get("/fakta/linux")
    assert page.status_code == 200 and "Rättigheter och användare" in page.text and "chmod" in page.text
    assert "/fakta/linux" in client.get("/fakta").text
    client.post("/logout")

    login(client, "admin", "adminpass1")
    assert client.get("/fakta/linux").status_code == 200


def test_subject_names_in_running_text_keep_capital_only_for_proper_names():
    assert logic.label_inline("matte") == "matematik"
    assert logic.label_inline("linux") == "Linux"
