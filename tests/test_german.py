"""Tyska som valfritt extraämne: ordlista, generatorer, övningspaket, uppläsning och att ämnet är dolt tills admin slår på det."""
import json
import random
import re
import zlib
from pathlib import Path

import pytest

from app import areas, generators, logic, speech
from app.words import WordBank, validate_word

from .conftest import login
from .test_features import _conn, _make_student

generators.load_all()
SEED = Path(__file__).resolve().parent.parent / "app" / "seed"
WORDS = json.loads((SEED / "words_de.json").read_text(encoding="utf-8"))["words"]
BANK = WordBank(WORDS)
PACK = json.loads((SEED / "tyska.json").read_text(encoding="utf-8"))
BY_WORD = {w["word"]: w for w in WORDS}
GENS = {n: g for n, g in generators.REGISTRY.items() if g.subject == "tyska"}


def _uid(conn, name="mia"):
    return conn.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]


# ------------------------------------------------------------------ ordlistan

def test_wordlist_is_valid_unique_and_covers_all_levels():
    seen = set()
    for w in WORDS:
        row, err = validate_word(w)
        assert err is None, (w, err)
        assert w["pos"] == "tyska" and w["word"] not in seen
        seen.add(w["word"])
    assert {w["level"] for w in WORDS} == {1, 2, 3, 4, 5}
    assert len(WORDS) >= 250


def test_nouns_have_an_article_and_everything_else_does_not():
    for w in WORDS:
        if w["word"][0].isupper():
            assert w.get("article") in ("der", "die", "das"), w["word"]
        else:
            assert "article" not in w, w["word"]
    assert validate_word({"word": "Hund", "pos": "tyska", "level": 1, "sv": ["hund"], "article": "den"})[1]


def test_verbs_have_all_forms_and_modals_have_no_perfect():
    verbs = [w for w in WORDS if "ich" in w.get("forms", {})]
    assert len(verbs) >= 35
    for w in verbs:
        assert w["word"].endswith("n") and w["word"].islower()
        assert all(w["forms"][k] for k in ("ich", "du", "er", "wir", "ihr", "sie")), w["word"]
    assert all("perfekt" not in BY_WORD[m]["forms"] for m in ("können", "müssen", "wollen", "dürfen", "sollen"))
    assert all(w["forms"]["perfekt"].split()[0] in ("hat", "ist") for w in verbs if "perfekt" in w["forms"])


def test_known_german_facts_are_right():
    """Stickprov på det som är lätt att få fel: artiklar, plural, vokalbyte och hjälpverb."""
    art = {w["word"]: w["article"] for w in WORDS if "article" in w}
    assert (art["Hund"], art["Katze"], art["Haus"], art["Mädchen"], art["Montag"], art["Juli"]) == \
        ("der", "die", "das", "das", "der", "der")
    plural = {w["word"]: w["forms"]["plural"] for w in WORDS if "plural" in w.get("forms", {})}
    assert (plural["Kind"], plural["Apfel"], plural["Buch"], plural["Frau"], plural["Auto"], plural["Bruder"]) == \
        ("Kinder", "Äpfel", "Bücher", "Frauen", "Autos", "Brüder")
    f = {w["word"]: w["forms"] for w in WORDS if "ich" in w.get("forms", {})}
    assert [f["sein"][k] for k in ("ich", "du", "er", "wir", "ihr", "sie")] == ["bin", "bist", "ist", "sind", "seid", "sind"]
    assert [f["haben"][k] for k in ("ich", "du", "er", "wir", "ihr")] == ["habe", "hast", "hat", "haben", "habt"]
    assert (f["sprechen"]["du"], f["sprechen"]["er"]) == ("sprichst", "spricht")
    assert (f["essen"]["du"], f["essen"]["er"]) == ("isst", "isst")
    assert (f["fahren"]["du"], f["fahren"]["er"]) == ("fährst", "fährt")
    assert (f["tanzen"]["du"], f["arbeiten"]["du"], f["heißen"]["du"]) == ("tanzt", "arbeitest", "heißt")
    assert (f["können"]["ich"], f["müssen"]["du"], f["wollen"]["er"]) == ("kann", "musst", "will")
    assert f["gehen"]["perfekt"] == "ist gegangen" and f["machen"]["perfekt"] == "hat gemacht"
    assert f["verstehen"]["perfekt"] == "hat verstanden" and f["fahren"]["perfekt"] == "ist gefahren"


# ------------------------------------------------------------------ generatorer

def test_generators_cover_all_levels_and_topics():
    assert {g.level for g in GENS.values()} == {1, 2, 3, 4, 5}
    assert {g.topic for g in GENS.values()} == {"Glosor", "Artiklar", "Plural", "Verb i presens", "Perfekt"}
    assert all(areas.area_of("tyska", g.topic) != areas.OVRIGT for g in GENS.values())


@pytest.mark.parametrize("name", sorted(GENS))
def test_german_generators(name):
    rng = random.Random(zlib.crc32(name.encode()))
    for _ in range(200):
        q = GENS[name].fn(rng, BANK)
        assert q.answers and q.question.strip() and "{" not in q.question and "}" not in q.question
        assert logic.is_correct(q.answers[0], q.answers) and not logic.is_correct("fel-svar", q.answers)
        if q.options:
            assert q.answers[0] in q.options and len(set(q.options)) == len(q.options) and len(q.options) in (3, 4)
        word = re.search(r"'([^']+)'", q.question).group(1)
        if "gloss_de_sv" in name:
            bare = word.split()[-1]
            assert q.answers[0] == BY_WORD[bare]["sv"][0]
        elif "gloss_sv_de" in name:
            candidates = [w for w in WORDS if w["sv"][0] == word]
            assert len(candidates) == 1 and not candidates[0].get("ambig")
            w = candidates[0]
            shown = f"{w['article']} {w['word']}" if w.get("article") else w["word"]
            assert q.answers[0] == shown
            if q.options:                                       # alla felsvar är samma slags ord, så formen avslöjar inget
                assert all(o.split()[0] in ("der", "die", "das") for o in q.options) == bool(w.get("article"))
        elif "artikel" in name:
            assert q.answers == [BY_WORD[word]["article"]] and q.options == ["der", "die", "das"]
        elif "plural" in name:
            noun = word.split()[-1]
            assert f"die {BY_WORD[noun]['forms']['plural']}" in q.answers
        elif "verb" in name:
            verb = word
            person = q.question.splitlines()[1].split()[0]
            key = person
            assert q.answers[0] == BY_WORD[verb]["forms"][key]
            if q.options:                                       # exakt ett av alternativen är rätt för personen
                assert q.options.count(q.answers[0]) == 1
        elif "perfekt" in name:
            assert q.answers[0] == BY_WORD[word]["forms"]["perfekt"]


def test_typed_answers_accept_the_spelling_without_umlauts():
    rng = random.Random(3)
    seen = 0
    for _ in range(400):
        q = GENS["de5_plural"].fn(rng, BANK)
        if "die Bücher" in q.answers:
            seen += 1
            assert logic.is_correct("die buecher", q.answers) and logic.is_correct("Bücher", q.answers)
            assert not logic.is_correct("die Bucher", q.answers)
    assert seen


def test_german_needs_wordlist():
    with pytest.raises(generators.NoData):
        GENS["de1_gloss_de_sv"].fn(random.Random(1), WordBank([]))
    with pytest.raises(generators.NoData):
        GENS["de4_perfekt"].fn(random.Random(1), WordBank([w for w in WORDS if "perfekt" not in w.get("forms", {})]))


# ------------------------------------------------------------------ övningspaketet

def test_pack_is_valid_unique_and_covers_all_levels():
    questions = []
    for i, item in enumerate(PACK, start=1):
        row, err = logic.validate_exercise(item)
        assert err is None, (i, err, item["question"])
        assert row["subject"] == "tyska" and item["explanation"].strip()
        questions.append(row["question"])
    assert len(set(questions)) == len(questions) and len(PACK) >= 150
    levels = {}
    for item in PACK:
        levels[item["level"]] = levels.get(item["level"], 0) + 1
    assert set(levels) == {1, 2, 3, 4, 5} and all(n >= 15 for n in levels.values()), levels
    assert {item["type"] for item in PACK} == {"mc", "text"}


def test_multiple_choice_has_exactly_one_correct_option():
    for item in PACK:
        if item["type"] != "mc":
            continue
        options = item["options"]
        assert len(options) in (3, 4) and len(set(options)) == len(options), item["question"]
        assert options.count(item["answer"]) == 1, item["question"]


def test_correct_option_is_rarely_the_obviously_longest_one():
    mcs = [i for i in PACK if i["type"] == "mc"]
    clearly_longest = [i["question"] for i in mcs
                       if len(i["answer"]) > max(len(o) for o in i["options"] if o != i["answer"]) + 3]
    assert len(clearly_longest) <= len(mcs) * 0.1, clearly_longest


def test_every_topic_belongs_to_an_area_and_every_area_has_enough_questions():
    per = {}
    for item in PACK:
        area = areas.area_of("tyska", item["topic"])
        assert area != areas.OVRIGT, item["topic"]
        per[area] = per.get(area, 0) + 1
    assert set(per) == set(areas.AREAS["tyska"]) and min(per.values()) >= logic.MIN_AREA_QUESTIONS, per


def test_typed_answers_in_the_pack_accept_sensible_spellings():
    by_q = {i["question"]: i for i in PACK if i["type"] == "text"}

    def accepts(start, given):
        item = next(i for q, i in by_q.items() if q.startswith(start))
        return logic.is_correct(given, item["answer"])

    assert accepts("Hur säger man 'tack'", "danke") and accepts("Hur säger man 'tack'", " Danke ")
    assert accepts("Hur säger man 'Jag heter Anna'", "Ich heisse Anna.") and not accepts("Hur säger man 'Jag heter Anna'", "Ich heiße")
    assert accepts("Skriv 'sieben' som en siffra", "7") and not accepts("Skriv 'sieben' som en siffra", "sieben")
    assert accepts("Skriv på tyska pluralformen av 'das Haus'", "die Häuser") and accepts("Skriv på tyska pluralformen av 'das Haus'", "Haeuser")
    assert accepts("Skriv participet av verbet 'kaufen'", "gekauft") and not accepts("Skriv participet av verbet 'kaufen'", "gekaufen")


# ------------------------------------------------------------------ uppläsning

def test_german_questions_are_read_with_a_german_voice_and_never_swedish():
    reads = 0
    for item in PACK:
        p = speech.plan("tyska", item["question"], item.get("options"), item["answer"], reveal=True)
        if not p:
            continue
        for seg in p["question"] + p["answer"] + [s for v in p["options"].values() for s in v]:
            assert seg["l"] == "de-DE" and seg["n"] == "tysk"
            assert not speech._is_swedish(seg["t"], "tyska"), (item["question"], seg["t"])
            reads += 1
    assert reads > 300


def test_typical_german_questions_read_the_right_parts():
    p = speech.plan("tyska", "Hur säger man 'hund' på tyska?", ["der Hund", "die Katze"], ["der Hund"], reveal=True)
    assert p["question"] == [] and set(p["options"]) == {"der Hund", "die Katze"}
    p = speech.plan("tyska", "Vad betyder 'die Schule' på svenska?", ["skola", "bok"], ["skola"], reveal=True)
    assert [s["t"] for s in p["question"]] == ["die Schule"] and p["options"] == {} and p["answer"] == []
    p = speech.plan("tyska", "Fyll i: Ich ___ Anna.", ["heiße", "heißt"], ["heiße"], reveal=True)
    assert [s["t"] for s in p["question"]] == ["Ich, Anna."] and [s["t"] for s in p["answer"]] == ["Ich heiße Anna."]
    p = speech.plan("tyska", "Vad betyder 'Wie geht's?' på svenska?", ["Hur mår du?"], ["Hur mår du?"], reveal=True)
    assert [s["t"] for s in p["question"]] == ["Wie geht's?"] and p["answer"] == []
    p = speech.plan("tyska", "Hur ska substantiv skrivas på tyska?", ["Alltid med stor bokstav", "Alltid med liten bokstav"],
                    ["Alltid med stor bokstav"], reveal=True)
    assert p is None, "svenska alternativ läses aldrig med tysk röst, ens när frågan nämner tyska"


def test_every_generated_german_question_has_a_safe_reading():
    for name, g in sorted(GENS.items()):
        rng = random.Random(name)
        for _ in range(60):
            q = g.fn(rng, BANK)
            p = speech.plan("tyska", q.question, q.options, q.answers, reveal=True)
            assert p is not None, q.question
            for seg in p["question"] + p["answer"] + [s for v in p["options"].values() for s in v]:
                assert not speech._is_swedish(seg["t"], "tyska"), (name, q.question, seg["t"])
            if "gloss_de_sv" in name:                                  # tyskt ord i frågan, svenskt svar
                assert p["question"] and p["options"] == {} and p["answer"] == [], q.question
            if "gloss_sv_de" in name and q.options:                    # svenskt ord i frågan, tyska alternativ
                assert p["question"] == [] and set(p["options"]) == set(q.options), q.question
            if "gloss_sv_de" in name or "plural" in name:
                assert [s["t"] for s in p["answer"]] == [q.answers[0]], q.question
            if "perfekt" in name or "verb" in name:                    # svaret läses som hela meningen: "er hat gebracht"
                assert len(p["answer"]) == 1 and p["answer"][0]["t"].endswith(q.answers[0]), q.question


# ------------------------------------------------------------------ ämnet och dess grupp

def test_german_has_a_label_a_group_and_is_opt_in():
    assert logic.label("tyska") == "Tyska" and logic.label_inline("tyska") == "tyska"
    groups = logic.group_subjects(["matte", "tyska", "linux"])
    assert [g["key"] for g in groups] == ["grund", "extra"] and groups[-1]["subjects"] == ["tyska", "linux"]
    assert "tyska" in logic.OPT_IN_SUBJECTS and "tyska" not in logic.LEISURE_SUBJECTS
    assert "tyska" in speech.LANGUAGES


def test_german_is_seeded_and_importing_it_again_adds_nothing(client):
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM exercises WHERE subject='tyska' AND generator IS NULL").fetchone()[0]
    assert n == len(PACK)
    assert conn.execute("SELECT COUNT(*) FROM words WHERE pos='tyska'").fetchone()[0] == len(WORDS)
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE subject='tyska' AND generator IS NOT NULL").fetchone()[0] == len(GENS)
    again = logic.import_bundle(conn, {"exercises": PACK, "words": WORDS})
    assert again["added"] == 0 and again["words_added"] == 0
    conn.close()


# ------------------------------------------------------------------ dolt tills admin slår på det

def test_nobody_sees_german_until_the_admin_turns_it_on(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    conn = _conn()
    mia, ben = _uid(conn, "mia"), _uid(conn, "ben")
    assert "tyska" in logic.active_subjects(conn)
    for uid in (mia, ben):
        assert logic.subject_settings(conn, uid)["tyska"] == {"enabled": False, "in_report": False}
        assert "tyska" not in logic.enabled_subjects(conn, uid) and "tyska" not in logic.report_subjects(conn, uid)
    logic.set_level(conn, mia, "tyska", 1)
    conn.commit()
    conn.close()

    login(client, "mia", "hemligt1")
    assert "Tyska" not in client.get("/home").text
    r = client.get("/practice/tyska")
    assert r.status_code == 303 and r.headers["location"] == "/home"
    assert client.post("/test/start/tyska").headers["location"] == "/home"
    assert client.get("/fakta/tyska").status_code == 404
    ex_id = _conn().execute("SELECT id FROM exercises WHERE subject='tyska' AND generator IS NULL LIMIT 1").fetchone()["id"]
    assert client.post("/practice/tyska", data={"exercise_id": ex_id, "given": "x"}).headers["location"] == "/home"
    assert _conn().execute("SELECT COUNT(*) FROM attempts WHERE user_id=?", (mia,)).fetchone()[0] == 0


def test_students_who_already_saved_their_subject_choices_do_not_get_german(client):
    _make_student(client, "mia")
    conn = _conn()
    uid = _uid(conn)
    subjects = [s for s in logic.active_subjects(conn) if s != "tyska"]
    logic.save_subject_settings(conn, uid, enabled=subjects, in_report=subjects, subjects=subjects)
    conn.commit()
    assert "tyska" not in logic.enabled_subjects(conn, uid)
    conn.close()


def test_admin_turns_german_on_for_one_student_who_then_gets_practice_facts_and_speakers(client):
    _make_student(client, "mia")
    _make_student(client, "ben")
    conn = _conn()
    mia = _uid(conn, "mia")
    others = [s for s in logic.active_subjects(conn) if s != "tyska"]
    logic.set_level(conn, mia, "tyska", 1)
    conn.commit()
    conn.close()

    login(client, "admin", "adminpass1")
    page = client.get(f"/admin/student/{mia}").text
    assert "checked" not in re.search(r'<input type="checkbox" name="enabled" value="tyska"[^>]*>', page).group(0)
    assert client.post(f"/admin/student/{mia}/subjects", data={"enabled": others + ["tyska"], "report": []}).status_code == 303
    client.post("/logout")

    login(client, "mia", "hemligt1")
    assert "Tyska" in client.get("/home").text
    facts = client.get("/fakta/tyska")
    assert facts.status_code == 200 and "Uttal" in facts.text and "der Hund" in facts.text
    speakers = 0
    for _ in range(25):                          # frågorna dras slumpmässigt: några av dem ska ha uppläsning
        r = client.get("/practice/tyska")
        assert r.status_code == 200
        speakers += r.text.count('class="speak"')
        if 'class="speak"' in r.text:
            assert "/static/speak.js" in r.text
            payloads = [json.loads(__import__("html").unescape(x)) for x in re.findall(r"data-speak='([^']*)'", r.text)]
            assert all(seg["l"] == "de-DE" for p in payloads for seg in p)
    assert speakers > 0
    client.post("/logout")

    login(client, "ben", "hemligt1")
    assert "Tyska" not in client.get("/home").text and client.get("/practice/tyska").headers["location"] == "/home"
    assert client.get("/fakta/tyska").status_code == 404


def test_german_is_not_in_the_report_unless_the_admin_chooses_it(client):
    _make_student(client, "mia")
    conn = _conn()
    uid = _uid(conn)
    subjects = logic.active_subjects(conn)
    logic.save_subject_settings(conn, uid, enabled=subjects, in_report=[s for s in subjects if s != "tyska"], subjects=subjects)
    conn.commit()
    assert "tyska" in logic.enabled_subjects(conn, uid) and "tyska" not in logic.report_subjects(conn, uid)
    logic.save_subject_settings(conn, uid, enabled=subjects, in_report=subjects, subjects=subjects)
    conn.commit()
    assert "tyska" in logic.report_subjects(conn, uid)
    conn.close()
