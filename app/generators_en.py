"""Engelska generatorer (glosor och oregelbundna verb) som bygger på ordlistan."""
from .generators import NoData, Q, register


def _gloss_en_sv(level):
    def fn(rng, bank):
        w = bank.pick(rng, "glosa", level, need=("sv",))
        sv = w["sv"][0]
        others = bank.distractors(rng, 3, ["glosa"], level, exclude=[w["word"]])
        opts = [sv] + [o["sv"][0] for o in others if o["sv"][0] != sv]
        if len(set(opts)) < 4:
            raise NoData("för få avledare")
        extra = f" (också: {', '.join(w['sv'][1:])})" if len(w["sv"]) > 1 else ""
        return Q(f"Vad betyder '{w['word']}' på svenska?", [sv], f"'{w['word']}' betyder '{sv}'{extra}.", options=opts)
    return fn


def _gloss_sv_en(level, choice):
    def fn(rng, bank):
        w = bank.pick(rng, "glosa", level, need=("sv",))
        sv = w["sv"][0]
        if choice:
            others = bank.distractors(rng, 3, ["glosa"], level, exclude=[w["word"]])
            return Q(f"Hur säger man '{sv}' på engelska?", [w["word"]], f"'{sv}' heter '{w['word']}' på engelska.",
                     options=[w["word"]] + [o["word"] for o in others])
        return Q(f"Hur säger man '{sv}' på engelska?\nSkriv ordet på engelska.", [w["word"]],
                 f"'{sv}' heter '{w['word']}' på engelska.")
    return fn


for _lvl in range(1, 6):
    register(f"e{_lvl}_gloss_en_sv", "engelska", "Glosor", _lvl, words=True)(_gloss_en_sv(_lvl))
    register(f"e{_lvl}_gloss_sv_en", "engelska", "Glosor", _lvl, words=True)(_gloss_sv_en(_lvl, _lvl == 1))


def _irregular(level, key, label, sentence):
    def fn(rng, bank):
        w = bank.pick(rng, "glosa", level, need=(key,))
        f = w["forms"]
        return Q(f"{sentence.format(v=w['word'])}\nSkriv ordet på engelska.", [f[key]],
                 f"{w['word']} – {f['past']} – {f['pastpart']}. {label}")
    return fn


register("e3_past", "engelska", "Oregelbundna verb", 3, words=True)(
    _irregular(3, "past", "Imperfekt (past simple) är den form som beskriver något som hänt.",
               "Skriv imperfekt (past simple) av verbet '{v}'. Exempel: go → went."))
register("e4_pastpart", "engelska", "Oregelbundna verb", 4, words=True)(
    _irregular(4, "pastpart", "Particip (past participle) används efter 'have'.",
               "Skriv particip (past participle) av verbet '{v}'. Exempel: go → gone."))
