"""Svenska generatorer som bygger på ordlistan."""
from .generators import Q, register

ART = {"substantiv": "ett", "verb": "ett", "adjektiv": "ett", "adverb": "ett", "preposition": "en", "pronomen": "ett",
       "räkneord": "ett", "konjunktion": "en", "subjunktion": "en", "interjektion": "en"}
POS_INFO = {
    "substantiv": "är namn på personer, djur, saker och idéer",
    "verb": "säger vad någon gör eller vad som händer",
    "adjektiv": "beskriver hur något är",
    "adverb": "säger hur, när eller var något sker",
    "preposition": "visar läge eller riktning, t.ex. på, under och till",
    "pronomen": "ersätter eller pekar ut ett substantiv, t.ex. jag, du och hon",
    "räkneord": "säger hur många eller i vilken ordning",
    "konjunktion": "binder ihop ord eller satser (och, men, eller)",
    "subjunktion": "inleder en bisats (eftersom, att, när)",
    "interjektion": "är ett utrop som visar en känsla (aj, hej)",
}
BASIC = ["substantiv", "verb", "adjektiv", "adverb", "preposition", "pronomen", "räkneord"]
MID = BASIC + ["konjunktion", "interjektion"]
ALL = MID + ["subjunktion"]


def _forms_text(w) -> str:
    f = w.get("forms", {})
    if w["pos"] == "verb":
        return f"{w['word']} – {f.get('presens')} – {f.get('preteritum')} – {f.get('supinum')} (imperativ: {f.get('imperativ')})"
    if w["pos"] == "substantiv":
        return f"{w.get('gender', '')} {w['word']} – {f.get('plural')} – {f.get('bestamd')} – {f.get('bestamd_plural')}".strip()
    if w["pos"] == "adjektiv":
        return f"{w['word']} – {f.get('komparativ')} – {f.get('superlativ')} (ett-ord: {f.get('neutrum')})"
    return w["word"]


# ------------------------------------------------------------------ ordklasser

@register("s1_ordklass_pick", "svenska", "Ordklasser", 1, words=True)
def s1_pick(rng, bank):
    pos = rng.choice(["substantiv", "verb", "adjektiv"])
    target = bank.pick(rng, pos, 1, quiz=True)
    others = bank.distractors(rng, 3, [p for p in ("substantiv", "verb", "adjektiv") if p != pos], 2, forbid_pos=pos)
    return Q(f"Vilket av orden är {ART[pos]} {pos}?", [target["word"]],
             f"'{target['word']}' är {ART[pos]} {pos}. Ett {pos} {POS_INFO[pos]}.",
             options=[target["word"]] + [w["word"] for w in others])


def _ordklass(level, pool):
    def fn(rng, bank):
        avail = [p for p in pool if bank.has(p, level)]
        if len(avail) < 4:
            from .generators import NoData
            raise NoData("för få ordklasser")
        pos = rng.choice(avail)
        w = bank.pick(rng, pos, level, quiz=True)
        ex = f" i meningen \"{w['example']}\"" if w.get("example") else ""
        others = [p for p in pool if p != pos]
        rng.shuffle(others)
        return Q(f"Vilken ordklass tillhör ordet '{w['word']}'{ex}?", [pos],
                 f"'{w['word']}' är {ART[pos]} {pos}. Ett {pos} {POS_INFO[pos]}.", options=[pos] + others[:3])
    return fn


for _lvl, _pool in ((2, BASIC), (3, MID), (4, ALL), (5, ALL)):
    register(f"s{_lvl}_ordklass_name", "svenska", "Ordklasser", _lvl, words=True)(_ordklass(_lvl, _pool))


# ------------------------------------------------------------------ en/ett, ordförråd

@register("s1_en_ett", "svenska", "En och ett", 1, words=True)
def s1_en_ett(rng, bank):
    w = bank.pick(rng, "substantiv", 2, need=("gender",), quiz=True)
    return Q(f"Vilket ord passar framför '{w['word']}'?", [w["gender"]],
             f"Det heter {w['gender']} {w['word']}. Bestämd form: {w['forms'].get('bestamd', '')}.".replace(" Bestämd form: .", ""),
             options=["en", "ett"])


def _antonym(level):
    def fn(rng, bank):
        w = bank.pick(rng, "adjektiv", level, need=("antonym",), quiz=True)
        others = bank.distractors(rng, 3, ["adjektiv"], level + 1, exclude={w["word"], w["antonym"]})
        return Q(f"Vad är motsatsen till '{w['word']}'?", [w["antonym"]],
                 f"Motsatsen till {w['word']} är {w['antonym']}.", options=[w["antonym"]] + [o["word"] for o in others])
    return fn


def _synonym(level):
    def fn(rng, bank):
        w = bank.pick(rng, "adjektiv", level, need=("synonym",), quiz=True)
        ex = {w["word"], w["synonym"]} | ({w["antonym"]} if w.get("antonym") else set())
        others = bank.distractors(rng, 3, ["adjektiv"], level + 1, exclude=ex)
        return Q(f"Vilket ord betyder ungefär samma sak som '{w['word']}'?", [w["synonym"]],
                 f"{w['word']} och {w['synonym']} är synonymer, ord med ungefär samma betydelse.",
                 options=[w["synonym"]] + [o["word"] for o in others])
    return fn


for _lvl in (1, 4, 5):
    register(f"s{_lvl}_antonym", "svenska", "Ordförråd", _lvl, words=True)(_antonym(_lvl))
for _lvl in (2, 4):
    register(f"s{_lvl}_synonym", "svenska", "Ordförråd", _lvl, words=True)(_synonym(_lvl))


# ------------------------------------------------------------------ böjning

NOUN = "substantiv"
PROMPTS = {
    ("substantiv", "plural"): lambda w: f"Skriv ordet '{w['word']}' i plural (flera stycken).",
    ("substantiv", "bestamd"): lambda w: f"Skriv '{w['word']}' i bestämd form singular.\nExempel: en bok → boken",
    ("substantiv", "bestamd_plural"): lambda w: f"Skriv '{w['word']}' i bestämd form plural.\nExempel: en bok → böckerna",
    ("verb", "presens"): lambda w: f"Skriv verbet '{w['word']}' i nutid (presens).",
    ("verb", "preteritum"): lambda w: f"Skriv verbet '{w['word']}' i dåtid (preteritum).",
    ("verb", "supinum"): lambda w: f"Fyll i rätt form av verbet:\n'Hon har ___ ({w['word']}).'",
    ("verb", "imperativ"): lambda w: f"Skriv verbet '{w['word']}' som en uppmaning (imperativ):\n'___!'",
    ("adjektiv", "komparativ"): lambda w: f"Skriv komparativ av '{w['word']}':\n'Den här är ___ än den där.'",
    ("adjektiv", "superlativ"): lambda w: f"Skriv superlativ av '{w['word']}':\n'Hon är ___ av alla.'",
    ("adjektiv", "neutrum"): lambda w: f"Skriv '{w['word']}' så att det passar framför ett ett-ord:\n'ett ___ hus'",
}


def _inflect(level, pos, keys):
    def fn(rng, bank):
        key = rng.choice(keys)
        w = bank.pick(rng, pos, level, need=(key,), quiz=False)
        return Q(PROMPTS[(pos, key)](w), [w["forms"][key]], _forms_text(w))
    return fn


INFLECT = [
    # (nivå, ordklass, former, tema)
    (1, "substantiv", ["plural"], "Ordböjning"),
    (2, "substantiv", ["bestamd"], "Ordböjning"),
    (2, "verb", ["preteritum"], "Verb"),
    (3, "substantiv", ["plural"], "Ordböjning"),
    (3, "verb", ["presens"], "Verb"),
    (3, "verb", ["supinum"], "Verb"),
    (3, "adjektiv", ["komparativ"], "Adjektiv"),
    (3, "adjektiv", ["neutrum"], "Adjektiv"),
    (4, "substantiv", ["bestamd_plural"], "Ordböjning"),
    (4, "verb", ["preteritum", "supinum"], "Verb"),
    (4, "verb", ["imperativ"], "Verb"),
    (4, "adjektiv", ["superlativ"], "Adjektiv"),
    (5, "substantiv", ["plural", "bestamd_plural"], "Ordböjning"),
    (5, "verb", ["preteritum", "supinum", "imperativ"], "Verb"),
    (5, "adjektiv", ["komparativ", "superlativ", "neutrum"], "Adjektiv"),
]
for _lvl, _pos, _keys, _topic in INFLECT:
    _name = f"s{_lvl}_{_pos[:4]}_{'_'.join(k[:4] for k in _keys)}"
    register(_name, "svenska", _topic, _lvl, words=True)(_inflect(_lvl, _pos, _keys))
