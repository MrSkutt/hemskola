"""K-pop-ämnet: koreanska glosor ur ordlistan (pos 'koreanska')."""
from .generators import NoData, Q, register

POS = ["koreanska"]


def _show(w):
    return f"'{w['word']}' ({w['hangul']})" if w.get("hangul") else f"'{w['word']}'"


def _ko_sv(level):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level)
        sv = w["sv"][0]
        others = bank.distractors(rng, 3, POS, level, exclude=[w["word"]])
        opts = [sv] + [o["sv"][0] for o in others]
        if len(set(opts)) < 4:
            raise NoData("för få avledare")
        return Q(f"Vad betyder {_show(w)} på svenska?", [sv], f"{_show(w)} betyder '{sv}'.", options=opts)
    return fn


def _sv_ko(level):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level)
        sv = w["sv"][0]
        others = bank.distractors(rng, 3, POS, level, exclude=[w["word"]])
        h = f" ({w['hangul']})" if w.get("hangul") else ""
        return Q(f"Hur säger man '{sv}' på koreanska? (skrivet med våra bokstäver)", [w["word"]],
                 f"'{sv}' heter '{w['word']}'{h} på koreanska.", options=[w["word"]] + [o["word"] for o in others])
    return fn


def _read(level):
    def fn(rng, bank):
        w = bank.pick(rng, POS, level, need=("hangul",))
        others = bank.distractors(rng, 3, POS, level, exclude=[w["word"]])
        return Q(f"Hur uttalas det koreanska ordet {w['hangul']}?", [w["word"]],
                 f"{w['hangul']} läses '{w['word']}' och betyder '{w['sv'][0]}'.",
                 options=[w["word"]] + [o["word"] for o in others])
    return fn


for _lvl in range(1, 6):
    register(f"k{_lvl}_ko_sv", "kpop", "Koreanska", _lvl, words=True)(_ko_sv(_lvl))
    register(f"k{_lvl}_sv_ko", "kpop", "Koreanska", _lvl, words=True)(_sv_ko(_lvl))
for _lvl in (3, 4, 5):
    register(f"k{_lvl}_read", "kpop", "Läs hangul", _lvl, words=True)(_read(_lvl))
