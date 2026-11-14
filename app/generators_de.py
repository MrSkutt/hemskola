"""Tyska: glosor, artiklar, plural, verbformer och perfekt ur ordlistan (pos 'tyska').

Substantiv visas alltid med artikel ("der Hund"), för det är så man ska lära sig dem. Skrivsvar godkänns även utan
ä, ö, ü och ß om man skriver ae, oe, ue och ss i stället (som man gör på ett tangentbord utan dem)."""
from .generators import NoData, Q, register

POS = ["tyska"]
PERSONS = [("ich", "ich"), ("du", "du"), ("er", "er"), ("wir", "wir"), ("ihr", "ihr")]
# ordändelser som avslöjar artikeln (och som stämmer för alla ord i ordlistan)
ARTICLE_TIPS = [
    (("ung", "heit", "keit", "schaft"), "die", "Ord som slutar på -ung, -heit, -keit och -schaft är nästan alltid die-ord."),
    (("chen", "lein"), "das", "Ord som slutar på -chen och -lein är alltid das-ord (och gör något litet)."),
]


def _show(w) -> str:
    return f"{w['article']} {w['word']}" if w.get("article") else w["word"]


def _spellings(text: str) -> list:
    """Skrivsätt som godkänns: originalet och varianten utan ä, ö, ü och ß."""
    plain = text
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue")):
        plain = plain.replace(a, b)
    return [text] if plain == text else [text, plain]


NUMBERS_SV = frozenset("""ett två tre fyra fem sex sju åtta nio tio elva tolv tretton fjorton femton sexton sjutton arton
nitton tjugo trettio fyrtio femtio hundra""".split())


def _kind(w) -> str:
    """Substantiv, verb, tal och övriga ord blandas inte som felsvar, annars går det att gissa på formen."""
    if w.get("article"):
        return "noun"
    if w.get("forms", {}).get("ich"):
        return "verb"
    return "number" if w["sv"][0] in NUMBERS_SV else "other"


def _others(bank, rng, w, level, k=3, need_sv=True):
    """k andra ord av samma slag med olika svensk översättning."""
    pool = [x for x in bank.words if x["pos"] == "tyska" and x["level"] <= level and not x.get("ambig")
            and x["word"] != w["word"] and _kind(x) == _kind(w) and x["sv"][0] != w["sv"][0]]
    rng.shuffle(pool)
    out, seen = [], set()
    for x in pool:
        if x["sv"][0] not in seen:
            seen.add(x["sv"][0])
            out.append(x)
        if len(out) == k:
            return out
    raise NoData("för få avledare")


def _de_sv(level):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level)
        sv = w["sv"][0]
        others = _others(bank, rng, w, level)
        extra = f" (också: {', '.join(w['sv'][1:])})" if len(w["sv"]) > 1 else ""
        return Q(f"Vad betyder '{_show(w)}' på svenska?", [sv], f"{_show(w)} betyder '{sv}'{extra}.",
                 options=[sv] + [o["sv"][0] for o in others])
    return fn


def _sv_de(level, choice):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level, quiz=True)
        sv = w["sv"][0]
        if choice:
            others = _others(bank, rng, w, level)
            return Q(f"Hur säger man '{sv}' på tyska?", [_show(w)], f"'{sv}' heter '{_show(w)}' på tyska.",
                     options=[_show(w)] + [_show(o) for o in others])
        how = "Skriv ordet på tyska, med artikel." if w.get("article") else "Skriv ordet på tyska."
        return Q(f"Hur säger man '{sv}' på tyska?\n{how}", _spellings(_show(w)), f"'{sv}' heter '{_show(w)}' på tyska.")
    return fn


def _article(level):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level, need=("article",))
        art, word = w["article"], w["word"]
        tip = next((t for ends, a, t in ARTICLE_TIPS if word.lower().endswith(ends) and a == art), "")
        gender = {"der": "maskulinum", "die": "femininum", "das": "neutrum"}[art]
        return Q(f"Vilken artikel har ordet '{word}'?", [art],
                 f"{_show(w)} ('{w['sv'][0]}') är {gender}. Lär dig alltid ordet tillsammans med artikeln. {tip}".strip(),
                 options=["der", "die", "das"])
    return fn


def _plural(level):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level, need=("article", "plural"))
        pl = w["forms"]["plural"]
        answers = _spellings(f"die {pl}") + _spellings(pl)
        return Q(f"Skriv på tyska pluralformen av '{_show(w)}' (börja med die).", answers,
                 f"Plural av {_show(w)} är 'die {pl}'. I plural är artikeln alltid die.")
    return fn


def _verb(level, choice):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level, need=("ich", "du", "er", "wir", "ihr"))
        key, pron = rng.choice(PERSONS)
        forms = w["forms"]
        right = forms[key]
        head = f"Fyll i rätt form av verbet '{w['word']}' ({w['sv'][0]}):\n{pron} ___"
        expl = (f"{w['word']}: ich {forms['ich']}, du {forms['du']}, er {forms['er']}, wir {forms['wir']}, "
                f"ihr {forms['ihr']}, sie {forms['sie']}.")
        if not choice:
            return Q(head, _spellings(right), expl)
        options = list(dict.fromkeys(forms[k] for k in ("ich", "du", "er", "wir", "ihr", "sie")))
        stem = w["word"][:-2] if w["word"].endswith("en") else w["word"][:-1]
        for extra in (stem + "st", stem + "t", stem + "e", stem + "en", stem + "est"):   # fel som någon kan göra
            if len(options) >= 4:
                break
            if extra not in options:
                options.append(extra)
        options.remove(right)
        rng.shuffle(options)
        return Q(head, [right], expl, options=[right] + options[:3])
    return fn


def _perfekt(level):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level, need=("perfekt",))
        perfekt = w["forms"]["perfekt"]
        aux = ("Verb som beskriver rörelse eller förändring (gehen, fahren, kommen, bleiben) bildar perfekt med sein."
               if perfekt.startswith("ist") else "De flesta verb bildar perfekt med haben.")
        return Q(f"Fyll i perfekt av verbet '{w['word']}' ({w['sv'][0]}):\ner ___", _spellings(perfekt),
                 f"Perfekt = hjälpverb + particip: er {perfekt}. {aux}")
    return fn


for _lvl in range(1, 6):
    register(f"de{_lvl}_gloss_de_sv", "tyska", "Glosor", _lvl, words=True)(_de_sv(_lvl))
    register(f"de{_lvl}_gloss_sv_de", "tyska", "Glosor", _lvl, words=True)(_sv_de(_lvl, _lvl <= 2))
    register(f"de{_lvl}_artikel", "tyska", "Artiklar", _lvl, words=True)(_article(_lvl))
for _lvl in range(2, 6):
    register(f"de{_lvl}_plural", "tyska", "Plural", _lvl, words=True)(_plural(_lvl))
    register(f"de{_lvl}_verb", "tyska", "Verb i presens", _lvl, words=True)(_verb(_lvl, _lvl == 2))
for _lvl in (4, 5):
    register(f"de{_lvl}_perfekt", "tyska", "Perfekt", _lvl, words=True)(_perfekt(_lvl))
