"""Uppläsning i språkämnen: vilka delar av en fråga som är på målspråket, att rätt svar inte avslöjas före svaret,
inställningen per elev och att knapparna hamnar rätt i sidorna."""
import html
import json
import random
import re
from pathlib import Path

from app import db as database
from app import generators, logic, speech
from app.words import WordBank

from .conftest import login
from .test_editor import _ex
from .test_features import _conn, _make_student

SEED = Path(__file__).resolve().parent.parent / "app" / "seed"


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


def _texts(segments):
    return [s["t"] for s in segments]


# ------------------------------------------------------------------ vilka delar som läses

def test_a_question_fully_in_the_language_is_read_whole_with_its_options():
    p = speech.plan("engelska", "Which word is a verb?", ["quickly", "decide", "beautiful"], ["decide"])
    assert _texts(p["question"]) == ["Which word is a verb?"]
    assert set(p["options"]) == {"quickly", "decide", "beautiful"}
    assert p["question"][0]["l"] == "en-GB"


def test_swedish_question_with_an_english_word_reads_only_the_word():
    p = speech.plan("engelska", "Vad betyder 'dog' på svenska?", ["hund", "katt", "häst"], ["hund"])
    assert _texts(p["question"]) == ["dog"]
    assert p["options"] == {}, "svenska alternativ ska inte läsas med en engelsk röst"


def test_swedish_word_in_the_question_is_not_read_but_the_english_options_are():
    p = speech.plan("engelska", "Hur säger man 'hund' på engelska?", ["dog", "cat", "horse"], ["dog"])
    assert p["question"] == []
    assert set(p["options"]) == {"dog", "cat", "horse"}


def test_the_hint_about_language_decides_which_quoted_word_is_which():
    p = speech.plan("franska", "Vad betyder 'chat' på svenska?", ["katt", "hund"], ["katt"])
    assert _texts(p["question"]) == ["chat"] and p["question"][0]["l"] == "fr-FR"
    p = speech.plan("franska", "Hur säger man 'hund' på franska?", ["chien", "chat"], ["chien"])
    assert p["question"] == [] and set(p["options"]) == {"chien", "chat"}
    p = speech.plan("tyska", "Översätt 'hund' till tyska.", None, ["Hund"], reveal=True)
    assert p["question"] == [] and _texts(p["answer"]) == ["Hund"]


def test_a_sentence_in_the_language_after_a_swedish_instruction_is_read():
    p = speech.plan("engelska", "Fyll i: I ___ twelve years old.", ["am", "is", "are"], ["am"])
    assert _texts(p["question"]) == ["I, twelve years old."], "luckan blir en paus, inte ett ord"
    assert set(p["options"]) == {"am", "is", "are"}


def test_quotes_are_not_read_but_apostrophes_inside_words_stay():
    p = speech.plan("engelska", "Which sentence is correct?", ["He doesn't like fish.", "He not like fish."], ["He doesn't like fish."])
    assert "He doesn't like fish." in p["options"]
    p = speech.plan("engelska", 'What does "look after" mean?', None, ["take care of"])
    assert _texts(p["question"]) == ["What does look after mean?"]


def test_unsure_text_is_not_read_at_all():
    assert speech.plan("engelska", "Vad är 2 + 2?", ["3", "4"], ["4"]) is None
    assert speech.plan("engelska", "Vilken bild visar en hund?", ["a", "b"], ["a"]) is None
    # ett svenskt ord utan ledtråd får inte läsas som engelska
    p = speech.plan("engelska", "Vad är motsatsen till 'stor'?", ["liten"], ["liten"], reveal=True)
    assert p is None or (p["options"] == {} and p["answer"] == [])


def test_only_language_subjects_get_speech():
    for subject in ("matte", "svenska", "biologi", "kpop", "linux"):
        assert speech.plan(subject, "Which word is a verb?", ["a", "b"], ["a"]) is None


def test_german_umlauts_do_not_make_german_look_swedish():
    p = speech.plan("tyska", "Wie ist das Wort für 'Straße'? Ich möchte ein Brötchen.", None, ["x"])
    assert p is not None and any("Brötchen" in t for t in _texts(p["question"]))
    p = speech.plan("tyska", "Vad betyder 'schön' på svenska?", ["vacker"], ["vacker"])
    assert _texts(p["question"]) == ["schön"]


def test_a_text_question_reads_the_answer_only_when_revealed():
    q = "Skriv imperfekt (past simple) av verbet 'buy'. Exempel: go → went.\nSkriv ordet på engelska."
    hidden = speech.plan("engelska", q, None, ["bought"])
    assert _texts(hidden["question"]) == ["buy"] and hidden["answer"] == []
    shown = speech.plan("engelska", q, None, ["bought"], reveal=True)
    assert _texts(shown["answer"]) == ["bought"]


def test_the_answer_to_a_gap_question_is_the_whole_sentence():
    p = speech.plan("engelska", "I ___ twelve years old.", ["am", "is"], ["am"], reveal=True)
    assert _texts(p["answer"]) == ["I am twelve years old."]


def test_a_swedish_answer_is_never_read_with_the_foreign_voice():
    p = speech.plan("engelska", "Vad betyder 'dog' på svenska?", ["hund"], ["hund"], reveal=True)
    assert p["answer"] == []


def test_the_english_exercises_in_the_seed_data_get_a_sensible_plan():
    """De flesta engelska frågorna ska ha uppläsning, och ingen ska läsa svenska med engelsk röst."""
    seed = []
    for name in ("engelska", "engelska_2"):
        seed += [e for e in json.loads((SEED / f"{name}.json").read_text(encoding="utf-8")) if e["subject"] == "engelska"]
    got = 0
    for e in seed:
        p = speech.plan("engelska", e["question"], e.get("options"), e.get("answer", e.get("answers")), reveal=True)
        if p and p["question"]:
            got += 1
            for seg in p["question"] + p["answer"] + [s for v in p["options"].values() for s in v]:
                assert not speech._is_swedish(seg["t"], "engelska"), seg["t"]
    assert got >= 0.9 * len(seed), (got, len(seed))


def test_the_english_generators_read_the_right_parts():
    generators.load_all()
    bank = WordBank(json.loads((SEED / "words_en.json").read_text(encoding="utf-8"))["words"])
    checked = set()
    for name, g in sorted(generators.REGISTRY.items()):
        if g.subject != "engelska":
            continue
        rng = random.Random(name)
        for _ in range(25):
            try:
                q = g.fn(rng, bank)
            except generators.NoData:
                continue
            p = speech.plan("engelska", q.question, q.options, q.answers, reveal=True)
            if "gloss_en_sv" in name:                     # engelskt ord i frågan, svenskt svar
                word = re.search(r"'(.+?)'", q.question).group(1)
                assert _texts(p["question"]) == [word] and p["options"] == {} and p["answer"] == [], q.question
            elif "gloss_sv_en" in name or "past" in name:  # svenskt ord (eller verb) i frågan, engelskt svar
                assert p["answer"] and _texts(p["answer"]) == [q.answers[0]], q.question
                assert all(o in p["options"] for o in (q.options or [])), q.question
            if p:
                for seg in p["question"] + p["answer"]:
                    assert not speech._is_swedish(seg["t"], "engelska"), (name, seg["t"])
            checked.add(name)
    assert len([n for n in checked if "gloss" in n]) >= 10


# ------------------------------------------------------------------ inställning och databas

def _student_with_french(client, **kw):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()[0]
    ids = [_ex(conn, subject="franska", level=2, **kw)]
    logic.set_level(conn, uid, "franska", 2)
    conn.commit()
    conn.close()
    return uid, ids[0]


def _payloads(page):
    return [json.loads(html.unescape(x)) for x in re.findall(r"data-speak='([^']*)'", page)]


def test_speech_is_on_by_default_and_old_databases_get_the_column(client):
    _make_student(client)
    conn = _conn()
    uid = conn.execute("SELECT id FROM users WHERE username='mia'").fetchone()[0]
    assert logic.get_prefs(conn, uid)["speech_on"] is True
    conn.execute("ALTER TABLE user_prefs DROP COLUMN speech_on")      # en databas från före uppläsningen
    database.migrate(conn)
    conn.commit()
    assert logic.get_prefs(conn, uid)["speech_on"] is True
    logic.save_prefs(conn, uid, True, 15, True, True, speech_on=False)
    assert logic.get_prefs(conn, uid)["speech_on"] is False
    logic.save_prefs(conn, uid, True, 15, True, True)                 # utan angivet värde slås den på
    assert logic.get_prefs(conn, uid)["speech_on"] is True


def test_admin_switches_speech_per_student(client):
    uid, _ = _student_with_french(client, typ="mc", question="Hur säger man 'hund' på franska?",
                                  options='["chien","chat"]', answers='["chien"]')
    login(client, "admin", "adminpass1")
    assert 'name="speech_on" value="1" checked' in client.get(f"/admin/student/{uid}").text
    r = client.post(f"/admin/student/{uid}/prefs", data={"daily_goal": "15", "areas_on": "1"})
    assert r.status_code == 303
    assert 'name="speech_on" value="1" checked' not in client.get(f"/admin/student/{uid}").text
    client.post("/logout")
    login(client, "mia", "hemligt1")
    page = client.get("/practice/franska").text
    assert 'class="speak"' not in page and "speak.js" not in page and "Hur säger man" in page
    login(client, "admin", "adminpass1")
    client.post(f"/admin/student/{uid}/prefs", data={"daily_goal": "15", "speech_on": "1"})
    client.post("/logout")
    login(client, "mia", "hemligt1")
    assert 'class="speak"' in client.get("/practice/franska").text


# ------------------------------------------------------------------ sidorna

def test_options_get_a_speaker_each_and_the_buttons_never_submit_the_form(client):
    _student_with_french(client, typ="mc", question="Hur säger man 'hund' på franska?",
                         options='["chien","chat","l\'école","<b>x</b>"]', answers='["chien"]')
    login(client, "mia", "hemligt1")
    page = client.get("/practice/franska").text
    assert page.count('class="speak"') == 4 and 'class="qrow"' not in page, "svenskt ord i frågan läses inte"
    assert '<script src="/static/speak.js' in page
    texts = sorted(p[0]["t"] for p in _payloads(page))
    assert texts == sorted(["chien", "chat", "l'école", "<b>x</b>"]), "citattecken och tecken som <> klarar sig genom attributet"
    assert all(p[0]["l"] == "fr-FR" for p in _payloads(page))
    assert len(re.findall(r'<button type="button" class="speak"', page)) == 4
    assert "hidden" in re.search(r'<button type="button" class="speak"[^>]*>', page).group(0), "göms tills JS visat sig stödja tal"


def test_the_question_gets_a_speaker_when_it_holds_a_word_in_the_language(client):
    _student_with_french(client, typ="mc", question="Vad betyder 'bonjour' på svenska?",
                         options='["hej","adjö"]', answers='["hej"]')
    login(client, "mia", "hemligt1")
    page = client.get("/practice/franska").text
    assert page.count('class="speak"') == 1 and 'class="qrow"' in page
    assert _payloads(page) == [[{"t": "bonjour", "l": "fr-FR", "n": "fransk"}]]


def test_the_right_answer_is_never_in_the_question_page_but_is_after_answering(client):
    _, ex_id = _student_with_french(client, typ="text", question="Hur säger man 'hund' på franska?\nSkriv ordet på franska.",
                                    answers='["chien"]')
    login(client, "mia", "hemligt1")
    page = client.get("/practice/franska").text
    assert "chien" not in page and 'class="speak"' not in page
    r = client.post("/practice/franska", data={"exercise_id": ex_id, "given": "chat"})
    answer = client.get(r.headers["location"]).text
    assert "Hör hur det låter" in answer
    assert _payloads(answer) == [[{"t": "chien", "l": "fr-FR", "n": "fransk"}]]
    assert "speak.js" in answer


def test_a_gap_sentence_is_read_complete_after_answering(client):
    _, ex_id = _student_with_french(client, typ="mc", question="Fyll i: Je ___ français.",
                                    options='["parle","parles"]', answers='["parle"]')
    login(client, "mia", "hemligt1")
    page = client.get("/practice/franska").text
    assert _payloads(page)[0] == [{"t": "Je, français.", "l": "fr-FR", "n": "fransk"}]
    r = client.post("/practice/franska", data={"exercise_id": ex_id, "given": "parles"})
    answer = client.get(r.headers["location"]).text
    assert [{"t": "Je parle français.", "l": "fr-FR", "n": "fransk"}] in _payloads(answer)


def test_subjects_that_are_not_languages_have_no_speakers(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    for subject in ("matte", "svenska"):
        page = client.get(f"/practice/{subject}").text
        assert 'class="speak"' not in page and "speak.js" not in page


def test_speakers_also_appear_in_tests_and_in_practice_on_what_was_missed(client):
    uid, ex_id = _student_with_french(client, typ="mc", question="Hur säger man 'hund' på franska?",
                                      options='["chien","chat"]', answers='["chien"]')
    login(client, "mia", "hemligt1")
    r = client.post("/test/start/franska")
    assert r.status_code == 303
    page = client.get(r.headers["location"]).text
    assert page.count('class="speak"') == 2 and "Du får se rätt svar när provet är klart" in page
    conn = _conn()
    other = _ex(conn, subject="franska", level=2, typ="mc", question="Hur säger man 'katt' på franska?",
                options='["chat","chien"]', answers='["chat"]')
    for ex in (ex_id, other):                  # den senast besvarade hoppas över, så en andra missad behövs
        conn.execute("INSERT INTO attempts(user_id, exercise_id, given, correct) VALUES (?,?,?,0)", (uid, ex, "x"))
    conn.commit()
    page = client.get("/missat").text
    assert page.count('class="speak"') == 2


def test_the_import_page_tells_how_to_write_language_questions(client):
    login(client, "admin", "adminpass1")
    page = client.get("/admin/import").text
    assert "Språkämnen och uppläsning" in page and "enkla citattecken" in page
