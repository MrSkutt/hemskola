import json
import math
import random
import re
import zlib
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from app import diagrams, generators, logic
from app.words import WordBank, validate_word

generators.load_all()
SEED = Path(__file__).parent.parent / "app" / "seed"
BANK = WordBank(json.loads((SEED / "words.json").read_text(encoding="utf-8"))["words"])
MATH = {n: g for n, g in generators.REGISTRY.items() if g.subject == "matte"}
SV = {n: g for n, g in generators.REGISTRY.items() if g.subject == "svenska"}
# Dessa har inget talsvar att räkna om med ett uttryck (klocka, bråkfigur, avläsning ur diagram)
SUBJECTS_WITH_GENERATORS = ("matte", "svenska", "engelska", "kpop", "kemi", "fysik", "teknik", "biologi", "geografi", "historia", "samhallskunskap")
NO_CALC = {"m1_clock", "m1_fraction", "m1_bar_read", "m1_bar_max", "m2_number_line", "m3_coord_read"}
NS = {"math": math, "Fraction": Fraction, "Decimal": Decimal, "ROUND_HALF_UP": ROUND_HALF_UP}


@pytest.mark.parametrize("name", sorted(MATH))
def test_math_answers_are_correct(name):
    g = MATH[name]
    rng = random.Random(zlib.crc32(name.encode()))
    for _ in range(400):
        q = g.fn(rng, None)
        assert q.question.strip() and q.answers and all(isinstance(a, str) and a for a in q.answers)
        assert "{" not in q.question and "}" not in q.question
        assert logic.is_correct(q.answers[0], q.answers)
        assert not logic.is_correct("wrong-answer", q.answers)
        if q.options:
            assert q.answers[0] in q.options and len(set(q.options)) == len(q.options)
        if q.diagram:
            assert diagrams.validate(q.diagram) is None, q.diagram
        if name not in NO_CALC:
            assert q.calc, f"{name} saknar calc"
            expected = eval(q.calc, NS)   # oberoende uträkning
            got = logic._num(q.answers[0])
            assert got is not None and abs(got - float(expected)) < 1e-9, (q.question, q.answers, expected)


def test_math_levels_cover_1_to_5():
    assert {g.level for g in MATH.values()} == {1, 2, 3, 4, 5}
    assert len(MATH) >= 50


def test_clock_and_fraction_answers():
    rng = random.Random(5)
    for _ in range(100):
        q = MATH["m1_clock"].fn(rng, None)
        h, m = map(int, q.diagram["time"].split(":"))
        assert logic.is_correct(f"{h}:{m:02d}", q.answers) and logic.is_correct(f"{h}.{m:02d}", q.answers)
        q = MATH["m1_fraction"].fn(rng, None)
        k, n = q.diagram["shaded"], q.diagram["parts"]
        assert q.answers == [f"{k}/{n}"]


def test_bar_read_matches_the_chart():
    rng = random.Random(9)
    for _ in range(100):
        q = MATH["m1_bar_read"].fn(rng, None)
        labels, values = q.diagram["labels"], q.diagram["values"]
        asked = [l for l in labels if l in q.question]
        assert len(asked) == 1
        assert q.answers == [str(values[labels.index(asked[0])])]


def test_all_generators_have_unique_names_and_valid_levels():
    for n, g in generators.REGISTRY.items():
        assert g.name == n and 1 <= g.level <= 5 and g.subject in SUBJECTS_WITH_GENERATORS


# ------------------------------------------------------------------ svenska / ordlista

def test_wordlist_is_consistent():
    words = json.loads((SEED / "words.json").read_text(encoding="utf-8"))["words"]
    keys = set()
    for w in words:
        row, err = validate_word(w)
        assert err is None, (w, err)
        assert (w["word"], w["pos"]) not in keys
        keys.add((w["word"], w["pos"]))
        if w["pos"] == "substantiv":
            assert w["gender"] in ("en", "ett") and {"plural", "bestamd", "bestamd_plural"} <= set(w["forms"])
            # bestämd form hör ihop med ordet: ändelse -n/-t/-en/-et
            assert w["forms"]["bestamd"][-1] in "nt"
        if w["pos"] == "verb":
            assert {"presens", "preteritum", "supinum", "imperativ"} <= set(w["forms"])
        if w["pos"] == "adjektiv":
            assert {"komparativ", "superlativ", "neutrum"} <= set(w["forms"])
    assert {w["level"] for w in words} == {1, 2, 3, 4, 5}


@pytest.mark.parametrize("name", sorted(SV))
def test_swedish_generators(name):
    g = SV[name]
    rng = random.Random(zlib.crc32(name.encode()))
    for _ in range(300):
        q = g.fn(rng, BANK)
        assert q.answers and q.question.strip() and "{" not in q.question
        assert logic.is_correct(q.answers[0], q.answers)
        if q.options:
            assert q.answers[0] in q.options and len(set(q.options)) == len(q.options) and len(q.options) >= 2


def test_swedish_forms_come_from_the_wordlist():
    rng = random.Random(1)
    all_forms = {v for w in BANK.words for v in w.get("forms", {}).values()}
    for name, g in SV.items():
        for _ in range(100):
            q = g.fn(rng, BANK)
            if not q.options and g.topic in ("Verb", "Ordböjning", "Adjektiv"):
                assert q.answers[0] in all_forms


def test_ordklass_pick_has_exactly_one_correct_option():
    rng = random.Random(2)
    by_word = {}
    for w in BANK.words:
        by_word.setdefault(w["word"], set()).add(w["pos"])
    for _ in range(300):
        q = SV["s1_ordklass_pick"].fn(rng, BANK)
        pos = re.search(r"är ett (\w+)\?", q.question).group(1)
        right = [o for o in q.options if pos in by_word[o]]
        assert right == q.answers


def test_ordklass_name_answer_matches_word():
    rng = random.Random(4)
    for lvl in (2, 3, 4, 5):
        for _ in range(200):
            q = SV[f"s{lvl}_ordklass_name"].fn(rng, BANK)
            word = re.search(r"ordet '([^']+)'", q.question).group(1)
            assert q.answers[0] in {w["pos"] for w in BANK.words if w["word"] == word}


def test_empty_wordlist_raises_nodata():
    with pytest.raises(generators.NoData):
        SV["s2_verb_pret"].fn(random.Random(1), WordBank([]))


# ------------------------------------------------------------------ diagram

def test_diagrams_validate_and_escape():
    assert diagrams.validate({"type": "nope"})
    assert diagrams.validate("x")
    assert diagrams.validate({"type": "bar_chart", "labels": ["a"], "values": [-1]})
    assert diagrams.validate({"type": "clock", "time": "3:99"})
    assert diagrams.validate({"type": "angle", "degrees": 400})
    svg = diagrams.render({"type": "bar_chart", "labels": ["<script>alert(1)</script>"], "values": [3]})
    assert "<script>" not in svg and "&lt;script&gt;" in svg
    for t, spec in {"clock": {"time": "12:00"}, "fraction": {"parts": 3, "shaded": 1},
                    "number_line": {"min": 0, "max": 10, "marks": [{"value": 5, "label": "x"}]}}.items():
        assert diagrams.render({"type": t, **spec}).startswith("<svg")


# ------------------------------------------------------------------ engelska

EN_WORDS = json.loads((SEED / "words_en.json").read_text(encoding="utf-8"))["words"]
EN_BANK = WordBank(EN_WORDS)
EN = {n: g for n, g in generators.REGISTRY.items() if g.subject == "engelska"}


def test_english_wordlist_is_valid_and_unique():
    seen_en, seen_sv = set(), set()
    for w in EN_WORDS:
        row, err = validate_word(w)
        assert err is None, (w, err)
        assert w["word"] not in seen_en and w["sv"][0] not in seen_sv
        seen_en.add(w["word"])
        seen_sv.add(w["sv"][0])
    assert {w["level"] for w in EN_WORDS} == {1, 2, 3, 4, 5}
    assert len([w for w in EN_WORDS if "forms" in w]) >= 25


def test_english_generators_cover_levels():
    assert {g.level for g in EN.values()} == {1, 2, 3, 4, 5} and len(EN) >= 12


@pytest.mark.parametrize("name", sorted(EN))
def test_english_generators(name):
    rng = random.Random(zlib.crc32(name.encode()))
    by_en = {w["word"]: w for w in EN_WORDS}
    for _ in range(300):
        q = EN[name].fn(rng, EN_BANK)
        assert q.answers and q.question.strip() and "{" not in q.question
        assert logic.is_correct(q.answers[0], q.answers)
        if q.options:
            assert q.answers[0] in q.options and len(set(q.options)) == len(q.options) == 4
        if "gloss_en_sv" in name:
            word = re.search(r"'([^']+)'", q.question).group(1)
            assert q.answers[0] == by_en[word]["sv"][0]
        elif "gloss_sv_en" in name:
            sv = re.search(r"'([^']+)'", q.question).group(1)
            assert q.answers == [w["word"] for w in EN_WORDS if w["sv"][0] == sv]
        else:
            verb = re.search(r"'([^']+)'", q.question).group(1)
            key = "past" if name == "e3_past" else "pastpart"
            assert q.answers == [by_en[verb]["forms"][key]]


def test_english_needs_wordlist():
    with pytest.raises(generators.NoData):
        EN["e1_gloss_en_sv"].fn(random.Random(1), WordBank([]))


# ------------------------------------------------------------------ k-pop / koreanska

KO_WORDS = json.loads((SEED / "words_kpop.json").read_text(encoding="utf-8"))["words"]
KO_BANK = WordBank(KO_WORDS)
KO = {n: g for n, g in generators.REGISTRY.items() if g.subject == "kpop"}


def test_korean_wordlist_is_valid():
    ro, sv = set(), set()
    for w in KO_WORDS:
        row, err = validate_word(w)
        assert err is None, (w, err)
        assert w["word"] not in ro and w["sv"][0] not in sv and w["hangul"]
        ro.add(w["word"])
        sv.add(w["sv"][0])
    assert {w["level"] for w in KO_WORDS} == {1, 2, 3, 4, 5}


@pytest.mark.parametrize("name", sorted(KO))
def test_korean_generators(name):
    rng = random.Random(zlib.crc32(name.encode()))
    by_ro = {w["word"]: w for w in KO_WORDS}
    for _ in range(300):
        q = KO[name].fn(rng, KO_BANK)
        assert q.options and len(set(q.options)) == 4 and q.answers[0] in q.options and "{" not in q.question
        if name.endswith("_ko_sv"):
            word = re.search(r"'([^']+)'", q.question).group(1)
            assert q.answers == [by_ro[word]["sv"][0]]
        elif name.endswith("_sv_ko"):
            sv = re.search(r"'([^']+)'", q.question).group(1)
            assert by_ro[q.answers[0]]["sv"][0] == sv
        else:
            hangul = q.question.split("ordet ", 1)[1].rstrip("?")
            assert by_ro[q.answers[0]]["hangul"] == hangul


# ------------------------------------------------------------------ NO/SO-generatorer

NOSO = {n: g for n, g in generators.REGISTRY.items()
        if g.subject in ("kemi", "fysik", "teknik", "biologi", "geografi", "historia", "samhallskunskap")}
NOSO_NO_CALC = {n for n, g in NOSO.items() if n.split("_", 1)[1] in (
    "elem_symbol", "elem_name", "atomic_number", "formula", "capital", "continent", "country", "year", "first",
    "century", "timeline", "bin_to_dec_x", "dec_to_bin", "logic_x", "punnett_x", "dna")}


@pytest.mark.parametrize("name", sorted(NOSO))
def test_noso_generators(name):
    rng = random.Random(zlib.crc32(name.encode()))
    for _ in range(300):
        q = NOSO[name].fn(rng, None)
        assert q.question.strip() and q.answers and all(isinstance(a, str) and a for a in q.answers)
        assert "{" not in q.question and "}" not in q.question
        assert logic.is_correct(q.answers[0], q.answers) and not logic.is_correct("wrong-answer", q.answers)
        if q.options:
            assert q.answers[0] in q.options and len(set(q.options)) == len(q.options) >= 2
        if q.diagram:
            assert diagrams.validate(q.diagram) is None, q.diagram
        if q.calc and name not in NOSO_NO_CALC:
            expected = eval(q.calc, NS)
            got = logic._num(q.answers[0])
            assert got is not None and abs(got - float(expected)) < 1e-9, (q.question, q.answers, expected)


def test_noso_levels_and_subjects():
    for subject in ("kemi", "fysik", "teknik", "geografi", "historia", "samhallskunskap", "biologi"):
        got = {g.level for g in NOSO.values() if g.subject == subject}
        assert len(got) >= 3, (subject, got)


def test_capital_and_year_facts_are_consistent():
    from app import generators_no as gn
    assert len({c[0] for c in gn.COUNTRIES}) == len(gn.COUNTRIES)
    assert len({c[1] for c in gn.COUNTRIES}) == len(gn.COUNTRIES)
    assert len({e[0] for e in gn.ELEMENTS}) == len(gn.ELEMENTS) == len({e[1] for e in gn.ELEMENTS}) == len({e[2] for e in gn.ELEMENTS})
    assert len({(e[1]) for e in gn.EVENTS}) == len(gn.EVENTS)
    for sym, name, z, lvl in gn.ELEMENTS:
        assert 1 <= lvl <= 3 and 1 <= z <= 118


def test_dna_complement_is_correct():
    rng = random.Random(3)
    for _ in range(100):
        q = NOSO["b5_dna"].fn(rng, None)
        s = re.search(r"basordningen ([ACGT]+)", q.question).group(1)
        assert q.answers == ["".join({"A": "T", "T": "A", "C": "G", "G": "C"}[c] for c in s)]


def test_timeline_answer_is_the_latest_event():
    rng = random.Random(4)
    from app import generators_no as gn
    years = {e[1]: e[0] for e in gn.EVENTS}
    for _ in range(100):
        q = NOSO["h3_timeline"].fn(rng, None)
        marks = {m["label"]: m["value"] for m in q.diagram["marks"]}
        assert marks[q.answers[0]] == max(marks.values())
