"""Generatorer: övningar som skapas med slumptal varje gång (matematik).

Varje generator är en funktion fn(rng, bank) -> Q. `bank` är ordlistan (används bara av
de svenska generatorerna i generators_sv.py). Facit räknas fram i koden, och testerna kontrollerar
det oberoende via fältet `calc` (ett Python-uttryck som bara används i tester).
"""
import math
import random
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Callable, Optional

NUM = "\nSvara endast med talet."


class NoData(Exception):
    """Generatorn saknar underlag (t.ex. ordlistan är tom)."""


@dataclass
class Q:
    question: str
    answers: list
    explanation: str = ""
    options: Optional[list] = None
    diagram: Optional[dict] = None
    calc: Optional[str] = None


@dataclass
class Gen:
    name: str
    subject: str
    topic: str
    level: int
    fn: Callable
    words: bool = False


REGISTRY: dict = {}


def register(name, subject, topic, level, words=False):
    def deco(fn):
        REGISTRY[name] = Gen(name, subject, topic, level, fn, words)
        return fn
    return deco


# ------------------------------------------------------------------ hjälpare

def fmt(x) -> str:
    """Tal till svensk text: decimalkomma och riktigt minustecken."""
    if isinstance(x, Fraction):
        if x.denominator != 1:
            return f"{x.numerator}/{x.denominator}".replace("-", "−")
        x = x.numerator
    d = x if isinstance(x, Decimal) else Decimal(x)
    s = format(d.normalize(), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",").replace("-", "−")


def ans(x) -> list:
    s = fmt(x)
    return [s, "-" + s[1:]] if s.startswith("−") else [s]


def signed(n: int) -> str:
    """'+ 7' eller '− 8' (tom sträng för 0)."""
    if n == 0:
        return ""
    return f"+ {n}" if n > 0 else f"− {abs(n)}"


def par(n) -> str:
    """Tal med parentes om det är negativt: (−3)."""
    return f"({fmt(n)})" if n < 0 else fmt(n)


def coef(c: int) -> str:
    return "x" if c == 1 else f"{c}x"


_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def sup(n: int) -> str:
    return str(n).translate(_SUP)


def group(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# ================================================================== NIVÅ 1

@register("m1_add", "matte", "Huvudräkning", 1)
def m1_add(rng, bank):
    a = rng.randint(11, 79)
    b = rng.randint(11, 100 - a)
    t = b // 10 * 10
    return Q(f"Vad är {a} + {b}?{NUM}", [str(a + b)],
             f"Dela upp det: {a} + {t} = {a + t}, och sedan + {b - t} = {a + b}.", calc=f"{a}+{b}")


@register("m1_sub", "matte", "Huvudräkning", 1)
def m1_sub(rng, bank):
    a = rng.randint(31, 99)
    b = rng.randint(11, a - 10)
    t = b // 10 * 10
    return Q(f"Vad är {a} − {b}?{NUM}", [str(a - b)],
             f"Dra av tiotalen först: {a} − {t} = {a - t}, och sedan − {b - t} = {a - b}.", calc=f"{a}-{b}")


@register("m1_mul_table", "matte", "Multiplikation", 1)
def m1_mul(rng, bank):
    a, b = rng.randint(2, 10), rng.randint(2, 10)
    return Q(f"Vad är {a} · {b}?{NUM}", [str(a * b)], f"{a} · {b} = {a * b}.", calc=f"{a}*{b}")


@register("m1_div_table", "matte", "Division", 1)
def m1_div(rng, bank):
    b, q = rng.randint(2, 10), rng.randint(2, 10)
    return Q(f"Vad är {b * q} : {b}?{NUM}", [str(q)],
             f"{b} · {q} = {b * q}, alltså är {b * q} : {b} = {q}.", calc=f"{b * q}/{b}")


@register("m1_missing", "matte", "Huvudräkning", 1)
def m1_missing(rng, bank):
    a, b = rng.randint(5, 60), rng.randint(5, 40)
    c = a + b
    form = rng.choice(["{a} + □ = {c}", "□ + {a} = {c}", "{c} − □ = {a}"])
    return Q(f"Vilket tal ska stå i rutan?\n{form.format(a=a, c=c)}{NUM}", [str(b)],
             f"Räkna baklänges: {c} − {a} = {b}.", calc=f"{c}-{a}")


@register("m1_round", "matte", "Avrundning", 1)
def m1_round(rng, bank):
    n = rng.choice([x for x in range(11, 200) if x % 10])
    r = (n + 5) // 10 * 10
    return Q(f"Avrunda {n} till närmaste tiotal.{NUM}", [str(r)],
             f"Entalssiffran är {n % 10}. 5 eller mer rundar uppåt, annars nedåt: {r}.", calc=f"int(Decimal({n}).quantize(Decimal('1E1'), rounding=ROUND_HALF_UP))")


@register("m1_clock", "matte", "Tid", 1)
def m1_clock(rng, bank):
    h, m = rng.randint(1, 12), rng.choice(range(0, 60, 5))
    return Q("Vad är klockan?\nSkriv med timme och minut, t.ex. 3:25.",
             [f"{h}:{m:02d}", f"{h:02d}:{m:02d}", f"{h}.{m:02d}"],
             "Korta visaren visar timmen och långa visaren minuterna: varje sträck är 1 minut, och varje siffra är 5 minuter.",
             diagram={"type": "clock", "time": f"{h}:{m:02d}"})


@register("m1_fraction", "matte", "Bråk", 1)
def m1_fraction(rng, bank):
    n = rng.randint(2, 8)
    k = rng.randint(1, n - 1)
    return Q("Hur stor del av figuren är färgad?\nSkriv som bråk, t.ex. 1/2.", [f"{k}/{n}"],
             f"Figuren är delad i {n} lika stora delar och {k} av dem är färgade: {k}/{n}.",
             diagram={"type": "fraction", "shape": rng.choice(["circle", "bar"]), "parts": n, "shaded": k})


@register("m1_perimeter", "matte", "Geometri", 1)
def m1_perimeter(rng, bank):
    w, h = rng.randint(2, 12), rng.randint(2, 12)
    return Q("Hur lång är rektangelns omkrets?\nSvara med talet (i cm).", [str(2 * (w + h))],
             f"Omkretsen är summan av alla fyra sidor: {w} + {h} + {w} + {h} = {2 * (w + h)}.",
             diagram={"type": "rectangle", "w": w, "h": h, "unit": "cm"}, calc=f"2*({w}+{h})")


BAR_THEMES = [
    ("Husdjur i klassen", ["Hund", "Katt", "Fisk", "Kanin", "Fågel", "Hamster"], "Hur många elever har {l}?"),
    ("Favoritfrukt", ["Äpple", "Banan", "Päron", "Apelsin", "Druvor", "Melon"], "Hur många elever gillar {l} bäst?"),
    ("Utlånade böcker", ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag"], "Hur många böcker lånades ut på {l}?"),
    ("Sport efter skolan", ["Fotboll", "Simning", "Dans", "Innebandy", "Gymnastik", "Ridning"], "Hur många elever tränar {l}?"),
]


def _bars(rng, lo=1, hi=12, n=4, unique=False):
    title, pool, tmpl = rng.choice(BAR_THEMES)
    labels = rng.sample(pool, n)
    if unique:
        values = rng.sample(range(lo, hi + 1), n)
    else:
        values = [rng.randint(lo, hi) for _ in range(n)]
    return title, labels, values, tmpl


@register("m1_bar_read", "matte", "Diagram", 1)
def m1_bar_read(rng, bank):
    title, labels, values, tmpl = _bars(rng)
    i = rng.randrange(len(labels))
    return Q(f"{tmpl.format(l=labels[i])}{NUM}", [str(values[i])],
             "Läs av hur högt stapeln når mot siffrorna till vänster.",
             diagram={"type": "bar_chart", "title": title, "labels": labels, "values": values})


@register("m1_bar_max", "matte", "Diagram", 1)
def m1_bar_max(rng, bank):
    title, labels, values, _ = _bars(rng, unique=True)
    top = labels[values.index(max(values))]
    return Q("Vilken stapel är högst?", [top], "Den högsta stapeln har störst värde.",
             options=list(labels), diagram={"type": "bar_chart", "title": title, "labels": labels, "values": values})


# ================================================================== NIVÅ 2

@register("m2_dec_add", "matte", "Decimaltal", 2)
def m2_dec_add(rng, bank):
    a, b = Decimal(rng.randint(11, 99)) / 10, Decimal(rng.randint(11, 99)) / 10
    return Q(f"Vad är {fmt(a)} + {fmt(b)}?{NUM}", ans(a + b),
             "Ställ upp med decimalkommana under varandra och räkna som vanligt.", calc=f"{a}+{b}")


@register("m2_pow10", "matte", "Decimaltal", 2)
def m2_pow10(rng, bank):
    base = Decimal(rng.randint(11, 999)) / rng.choice([1, 10, 100])
    p = rng.choice([10, 100, 1000])
    k = len(str(p)) - 1
    if rng.random() < 0.5:
        return Q(f"Vad är {fmt(base)} · {p}?{NUM}", ans(base * p),
                 f"Att multiplicera med {p} flyttar decimalkommat {k} steg åt höger.", calc=f"{base}*{p}")
    return Q(f"Vad är {fmt(base)} : {p}?{NUM}", ans(base / p),
             f"Att dela med {p} flyttar decimalkommat {k} steg åt vänster.", calc=f"{base}/{p}")


@register("m2_percent_easy", "matte", "Procent", 2)
def m2_percent_easy(rng, bank):
    base = rng.randrange(20, 501, 10)
    p = rng.choice([10, 20, 50])
    hint = {10: "10 % är en tiondel: dela med 10.", 20: "20 % är två gånger 10 %: dela med 10 och multiplicera med 2.",
            50: "50 % är hälften: dela med 2."}[p]
    return Q(f"Hur mycket är {p} % av {base}?{NUM}", [str(base * p // 100)], hint, calc=f"{base}*{p}/100")


@register("m2_mul_2x1", "matte", "Multiplikation", 2)
def m2_mul2(rng, bank):
    a, b = rng.randint(12, 99), rng.randint(2, 9)
    t = a // 10 * 10
    return Q(f"Vad är {a} · {b}?{NUM}", [str(a * b)],
             f"Dela upp: {t} · {b} = {t * b} och {a - t} · {b} = {(a - t) * b}. Summan är {a * b}.", calc=f"{a}*{b}")


@register("m2_div_exact", "matte", "Division", 2)
def m2_div(rng, bank):
    b, q = rng.randint(2, 12), rng.randint(6, 20)
    return Q(f"Vad är {b * q} : {b}?{NUM}", [str(q)], f"Kontrollera med multiplikation: {b} · {q} = {b * q}.",
             calc=f"{b * q}/{b}")


@register("m2_negative", "matte", "Negativa tal", 2)
def m2_negative(rng, bank):
    form = rng.choice(["a", "b", "c"])
    if form == "a":
        x, y = rng.randint(1, 9), rng.randint(10, 20)
        text, val, calc = f"{x} − {y}", x - y, f"{x}-{y}"
    elif form == "b":
        x, y = rng.randint(1, 9), rng.randint(2, 15)
        text, val, calc = f"−{x} + {y}", -x + y, f"-{x}+{y}"
    else:
        x, y = rng.randint(1, 9), rng.randint(1, 9)
        text, val, calc = f"−{x} − {y}", -x - y, f"-{x}-{y}"
    return Q(f"Vad är {text}?{NUM}", ans(val), "Tänk på en tallinje: plus går åt höger och minus åt vänster.", calc=calc)


@register("m2_area_rect", "matte", "Geometri", 2)
def m2_area(rng, bank):
    w, h = rng.randint(3, 15), rng.randint(3, 15)
    return Q("Hur stor är rektangelns area?\nSvara med talet (i cm²).", [str(w * h)],
             f"Area = längd · bredd = {w} · {h} = {w * h}.",
             diagram={"type": "rectangle", "w": w, "h": h, "unit": "cm", "center_label": "Area = ?"}, calc=f"{w}*{h}")


@register("m2_fraction_of", "matte", "Bråk", 2)
def m2_fraction_of(rng, bank):
    d = rng.choice([2, 3, 4, 5, 10])
    n = rng.randint(1, d - 1)
    m = rng.randint(2, 12)
    return Q(f"Hur mycket är {n}/{d} av {d * m}?{NUM}", [str(n * m)],
             f"Dela med {d} först: {d * m} : {d} = {m}. Multiplicera sedan med {n}: {n * m}.", calc=f"{n}/{d}*{d * m}")


UNITS = [("meter", "centimeter", 100), ("kilometer", "meter", 1000), ("kilogram", "gram", 1000),
         ("liter", "deciliter", 10), ("liter", "milliliter", 1000), ("centimeter", "millimeter", 10),
         ("meter", "millimeter", 1000)]


@register("m2_units", "matte", "Enheter", 2)
def m2_units(rng, bank):
    if rng.random() < 0.15:
        v = rng.randint(2, 9)
        return Q(f"Hur många minuter är {v} timmar?{NUM}", [str(v * 60)], f"1 timme = 60 minuter. {v} · 60 = {v * 60}.",
                 calc=f"{v}*60")
    large, small, f = rng.choice(UNITS)
    v = Decimal(rng.randint(21, 99)) / 10
    if rng.random() < 0.5:
        return Q(f"Hur många {small} är {fmt(v)} {large}?{NUM}", ans(v * f),
                 f"1 {large} = {f} {small}. Multiplicera med {f}.", calc=f"{v}*{f}")
    amount = Decimal(int(v * 10) * f // 10)
    return Q(f"Hur många {large} är {fmt(amount)} {small}?{NUM}", ans(amount / f),
             f"1 {large} = {f} {small}. Dela med {f}.", calc=f"{amount}/{f}")


@register("m2_number_line", "matte", "Tal", 2)
def m2_number_line(rng, bank):
    lo = rng.choice([0, 10, 20, 30, 50, 100])
    v = rng.randint(lo + 1, lo + 9)
    return Q(f"Vilket tal pekar pricken på?{NUM}", [str(v)], "Räkna sträcken från ett tal du kan läsa av.",
             diagram={"type": "number_line", "min": lo, "max": lo + 10, "step": 1, "label_step": 5,
                      "marks": [{"value": v, "label": "?"}]})


@register("m2_bar_diff", "matte", "Diagram", 2)
def m2_bar_diff(rng, bank):
    title, labels, values, _ = _bars(rng, 2, 16, unique=True)
    i, j = rng.sample(range(4), 2)
    if values[i] < values[j]:
        i, j = j, i
    return Q(f"Hur många fler är det för '{labels[i]}' än för '{labels[j]}'?{NUM}", [str(values[i] - values[j])],
             "Läs av båda staplarna och räkna ut skillnaden.",
             diagram={"type": "bar_chart", "title": title, "labels": labels, "values": values},
             calc=f"{values[i]}-{values[j]}")


# ================================================================== NIVÅ 3

@register("m3_eq_add", "matte", "Ekvationer", 3)
def m3_eq_add(rng, bank):
    x, a = rng.randint(2, 40), rng.randint(2, 30)
    form = rng.choice(["add", "sub", "add2"])
    if form == "add":
        text, how = f"x + {a} = {x + a}", f"Subtrahera {a} från båda sidor: x = {x + a} − {a} = {x}."
    elif form == "add2":
        text, how = f"{a} + x = {x + a}", f"Subtrahera {a} från båda sidor: x = {x + a} − {a} = {x}."
    else:
        text, how = f"x − {a} = {x - a}", f"Addera {a} till båda sidor: x = {x - a} + {a} = {x}."
    return Q(f"Lös ekvationen {text}.{NUM}", [str(x)], how, calc=str(x))


@register("m3_eq_mul", "matte", "Ekvationer", 3)
def m3_eq_mul(rng, bank):
    if rng.random() < 0.7:
        a, x = rng.randint(2, 12), rng.randint(2, 12)
        return Q(f"Lös ekvationen {a}x = {a * x}.{NUM}", [str(x)], f"Dela båda sidor med {a}: x = {a * x} : {a} = {x}.",
                 calc=str(x))
    a, b = rng.randint(2, 9), rng.randint(2, 12)
    return Q(f"Lös ekvationen x : {a} = {b}.{NUM}", [str(a * b)], f"Multiplicera båda sidor med {a}: x = {b} · {a} = {a * b}.",
             calc=f"{a}*{b}")


@register("m3_percent", "matte", "Procent", 3)
def m3_percent(rng, bank):
    base = rng.randrange(20, 401, 20)
    p = rng.choice([5, 10, 15, 20, 25, 30, 40, 60, 75])
    return Q(f"Hur mycket är {p} % av {base}?{NUM}", [str(base * p // 100)],
             f"Hitta 10 % ({base // 10}) eller 1 % ({fmt(Decimal(base) / 100)}) och bygg upp {p} %.", calc=f"{base}*{p}/100")


THINGS = [("en", "tröja"), ("en", "jacka"), ("en", "bok"), ("en", "cykel"), ("ett", "spel"), ("ett", "par skor"),
          ("en", "väska"), ("ett", "klockradio")]


@register("m3_discount", "matte", "Procent", 3)
def m3_discount(rng, bank):
    art, thing = rng.choice(THINGS)
    price = rng.randrange(40, 801, 20)
    pron = "den" if art == "en" else "det"
    if rng.random() < 0.6:
        p = rng.choice([10, 20, 25, 30, 40, 50])
        new = price * (100 - p) // 100
        return Q(f"{art.capitalize()} {thing} kostar {price} kr. Priset sänks med {p} %. Vad kostar {pron} nu (kr)?{NUM}",
                 [str(new)], f"{p} % av {price} är {price * p // 100}. Dra av: {price} − {price * p // 100} = {new}.",
                 calc=f"{price}*(100-{p})/100")
    p = rng.choice([10, 20, 25, 50])
    new = price * (100 + p) // 100
    return Q(f"{art.capitalize()} {thing} kostar {price} kr. Priset höjs med {p} %. Vad kostar {pron} nu (kr)?{NUM}",
             [str(new)], f"{p} % av {price} är {price * p // 100}. Lägg till: {price} + {price * p // 100} = {new}.",
             calc=f"{price}*(100+{p})/100")


@register("m3_mean", "matte", "Statistik", 3)
def m3_mean(rng, bank):
    nums = [rng.randint(2, 20) for _ in range(4)]
    last = rng.choice([x for x in range(2, 21) if (sum(nums) + x) % 5 == 0])
    nums.append(last)
    rng.shuffle(nums)
    total = sum(nums)
    return Q(f"Vad är medelvärdet av {', '.join(map(str, nums[:-1]))} och {nums[-1]}?{NUM}", [str(total // 5)],
             f"Summan är {total}. Dela med antalet tal, 5: {total} : 5 = {total // 5}.", calc=f"({'+'.join(map(str, nums))})/5")


@register("m3_median", "matte", "Statistik", 3)
def m3_median(rng, bank):
    n = rng.choice([5, 7])
    nums = [rng.randint(1, 30) for _ in range(n)]
    s = sorted(nums)
    return Q(f"Vad är medianen av {', '.join(map(str, nums[:-1]))} och {nums[-1]}?{NUM}", [str(s[n // 2])],
             f"Sortera talen: {', '.join(map(str, s))}. Medianen är det mittersta talet.", calc=f"sorted({nums})[{n // 2}]")


@register("m3_order_ops", "matte", "Räkneregler", 3)
def m3_order(rng, bank):
    form = rng.choice(["a + b * c", "a * b - c", "(a + b) * c", "a - b * c", "a + b * c - d"])
    for _ in range(100):
        a, b, c, d = (rng.randint(2, 12) for _ in range(4))
        py = form.replace("a", str(a)).replace("b", str(b)).replace("c", str(c)).replace("d", str(d))
        val = eval(py)
        if val > 0:
            break
    shown = py.replace("*", "·").replace("-", "−")
    return Q(f"Vad är {shown}?{NUM}", [str(val)],
             "Parenteser först, sedan multiplikation och division, sist addition och subtraktion.", calc=py)


@register("m3_fraction_add", "matte", "Bråk", 3)
def m3_fraction_add(rng, bank):
    if rng.random() < 0.5:
        d = rng.randint(3, 12)
        a = rng.randint(1, d - 2)
        b = rng.randint(1, d - a - 1)
        r = Fraction(a + b, d)
        return Q(f"Vad är {a}/{d} + {b}/{d}?\nSvara som bråk, t.ex. 1/2.", [f"{a + b}/{d}", fmt(r)],
                 f"Samma nämnare: addera täljarna, {a} + {b} = {a + b}. Nämnaren är kvar: {d}.", calc=f"Fraction({a},{d})+Fraction({b},{d})")
    d = rng.choice([2, 3, 4, 5])
    a, b = rng.randint(1, d - 1), rng.randint(1, 2 * d - 1)
    r = Fraction(a, d) + Fraction(b, 2 * d)
    return Q(f"Vad är {a}/{d} + {b}/{2 * d}?\nSvara som bråk, t.ex. 1/2.", [fmt(r), f"{2 * a + b}/{2 * d}"],
             f"Gör lika nämnare: {a}/{d} = {2 * a}/{2 * d}. Addera: {2 * a}/{2 * d} + {b}/{2 * d} = {2 * a + b}/{2 * d}.",
             calc=f"Fraction({a},{d})+Fraction({b},{2 * d})")


@register("m3_triangle", "matte", "Geometri", 3)
def m3_triangle(rng, bank):
    a, b = rng.randint(30, 80), rng.randint(30, 90)
    return Q(f"I en triangel är två av vinklarna {a}° och {b}°. Hur stor är den tredje vinkeln?\nSvara med talet (i grader).",
             [str(180 - a - b)], f"Vinkelsumman i en triangel är 180°. 180 − {a} − {b} = {180 - a - b}.", calc=f"180-{a}-{b}")


RATIOS = [("pojkar", "flickor"), ("röda kulor", "blå kulor"), ("äpplen", "päron"), ("ettor", "nollor"),
          ("liter saft", "liter vatten")]


@register("m3_ratio", "matte", "Förhållande", 3)
def m3_ratio(rng, bank):
    x, y = rng.choice(RATIOS)
    a, b = rng.sample(range(1, 6), 2)
    m = rng.randint(2, 9)
    return Q(f"Förhållandet mellan {x} och {y} är {a}:{b}. Det finns {a * m} {x}. Hur många {y} finns det?{NUM}",
             [str(b * m)], f"{a * m} är {m} gånger {a}, så antalet {y} är {m} gånger {b} = {b * m}.", calc=f"{b}*{m}")


@register("m3_coord_read", "matte", "Koordinatsystem", 3)
def m3_coord(rng, bank):
    x, y = rng.randint(1, 8), rng.randint(1, 8)
    which = rng.choice(["x", "y"])
    return Q(f"Vilket är punktens {which}-värde?{NUM}", [str(x if which == "x" else y)],
             "Läs x-värdet längs den vågräta axeln och y-värdet längs den lodräta axeln.",
             diagram={"type": "coordinate", "xmin": 0, "xmax": 9, "ymin": 0, "ymax": 9,
                      "points": [{"x": x, "y": y, "label": "P"}]})


@register("m3_rect_missing", "matte", "Geometri", 3)
def m3_rect_missing(rng, bank):
    w, h = rng.randint(3, 12), rng.randint(3, 12)
    return Q(f"En rektangel har arean {w * h} cm² och bredden {w} cm. Hur lång är längden?\nSvara med talet (i cm).", [str(h)],
             f"Area = bredd · längd, så längd = {w * h} : {w} = {h}.",
             diagram={"type": "rectangle", "w": w, "h": h, "w_label": f"{w} cm", "h_label": "?",
                      "center_label": f"Area = {w * h} cm²"}, calc=f"{w * h}/{w}")


# ================================================================== NIVÅ 4

@register("m4_eq_two_step", "matte", "Ekvationer", 4)
def m4_eq_two(rng, bank):
    a, x, b = rng.randint(2, 9), rng.randint(1, 12), rng.randint(1, 20)
    if rng.random() < 0.5 or a * x <= b:
        c = a * x + b
        return Q(f"Lös ekvationen {a}x + {b} = {c}.{NUM}", [str(x)],
                 f"Subtrahera {b}: {a}x = {c - b}. Dela med {a}: x = {x}.", calc=str(x))
    c = a * x - b
    return Q(f"Lös ekvationen {a}x − {b} = {c}.{NUM}", [str(x)],
             f"Addera {b}: {a}x = {c + b}. Dela med {a}: x = {x}.", calc=str(x))


@register("m4_eq_both", "matte", "Ekvationer", 4)
def m4_eq_both(rng, bank):
    a = rng.randint(3, 9)
    c = rng.randint(1, a - 1)
    x = rng.randint(1, 12)
    b = rng.choice([n for n in range(-12, 13) if n])
    d = (a - c) * x + b
    lhs = (coef(a) + " " + signed(b)).strip()
    rhs = (coef(c) + " " + signed(d)).strip()
    return Q(f"Lös ekvationen {lhs} = {rhs}.{NUM}", [str(x)],
             f"Subtrahera {coef(c)} från båda sidor: {(coef(a - c) + ' ' + signed(b)).strip()} = {d}. "
             f"Lös sedan ut x: x = {x}.", calc=str(x))


@register("m4_percent_change", "matte", "Procent", 4)
def m4_percent_change(rng, bank):
    old = rng.randrange(40, 401, 20)
    p = rng.choice([10, 20, 25, 50])
    if rng.random() < 0.5:
        new = old * (100 + p) // 100
        txt, verb = f"höjs från {old} kr till {new} kr", "ökat"
    else:
        new = old * (100 - p) // 100
        txt, verb = f"sänks från {old} kr till {new} kr", "minskat"
    return Q(f"Ett pris {txt}. Hur många procent har priset {verb}?{NUM}", [str(p), f"{p}%", f"{p} %"],
             f"Förändringen är {abs(new - old)} kr av ursprungliga {old} kr: {abs(new - old)}/{old} = {p} %.",
             calc=f"abs({new}-{old})/{old}*100")


@register("m4_power", "matte", "Potenser", 4)
def m4_power(rng, bank):
    a, b = rng.choice([(2, e) for e in range(2, 9)] + [(3, e) for e in range(2, 6)] + [(4, e) for e in range(2, 5)] +
                      [(5, e) for e in (2, 3)] + [(6, 2), (6, 3), (7, 2), (10, 2), (10, 3), (10, 4), (10, 5)])
    parts = " · ".join([str(a)] * b)
    return Q(f"Vad är {a}{sup(b)}?{NUM}", [str(a ** b)], f"{a}{sup(b)} betyder {parts} = {a ** b}.", calc=f"{a}**{b}")


TRIPLES = [(3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25), (6, 8, 10), (9, 12, 15), (12, 16, 20), (15, 20, 25), (20, 21, 29)]


@register("m4_pythagoras", "matte", "Pythagoras", 4)
def m4_pythagoras(rng, bank):
    a, b, c = rng.choice(TRIPLES)
    if rng.random() < 0.5:
        a, b = b, a
    if rng.random() < 0.5:
        return Q(f"I en rätvinklig triangel är kateterna {a} cm och {b} cm. Hur lång är hypotenusan?\nSvara med talet (i cm).",
                 [str(c)], f"{a}² + {b}² = {a * a} + {b * b} = {c * c}, och √{c * c} = {c}.",
                 diagram={"type": "right_triangle", "a": a, "b": b, "bottom_label": f"{a} cm", "left_label": f"{b} cm", "hyp_label": "?"},
                 calc=f"math.sqrt({a}**2+{b}**2)")
    return Q(f"I en rätvinklig triangel är hypotenusan {c} cm och den ena kateten {a} cm. Hur lång är den andra kateten?\nSvara med talet (i cm).",
             [str(b)], f"{c}² − {a}² = {c * c} − {a * a} = {b * b}, och √{b * b} = {b}.",
             diagram={"type": "right_triangle", "a": a, "b": b, "bottom_label": f"{a} cm", "left_label": "?", "hyp_label": f"{c} cm"},
             calc=f"math.sqrt({c}**2-{a}**2)")


@register("m4_linear_value", "matte", "Funktioner", 4)
def m4_linear(rng, bank):
    k = rng.choice([-4, -3, -2, 2, 3, 4, 5, 6])
    m = rng.choice([n for n in range(-5, 10) if n])
    x = rng.randint(1, 8)
    return Q(f"Vad är y när x = {x} i funktionen y = {coef(k)} {signed(m)}?{NUM}", ans(k * x + m),
             f"Sätt in x = {x}: y = {fmt(k)} · {x} {signed(m)} = {fmt(k * x + m)}.", calc=f"{k}*{x}+({m})")


PRODUCTS = ["äpplen", "potatis", "apelsiner", "tomater", "mandlar"]


@register("m4_proportion", "matte", "Proportionalitet", 4)
def m4_proportion(rng, bank):
    p, q1 = rng.randint(5, 30), rng.randint(2, 8)
    q2 = q1 + rng.randint(1, 6)
    thing = rng.choice(PRODUCTS)
    return Q(f"{q1} kg {thing} kostar {p * q1} kr. Vad kostar {q2} kg?{NUM}", [str(p * q2)],
             f"Pris per kg: {p * q1} : {q1} = {p} kr. Då kostar {q2} kg {q2} · {p} = {p * q2} kr.", calc=f"{p}*{q2}")


@register("m4_circle", "matte", "Geometri", 4)
def m4_circle(rng, bank):
    r = rng.randint(2, 10)
    pi = Decimal("3.14")
    if rng.random() < 0.5:
        return Q(f"En cirkel har radien {r} cm. Beräkna arean. Använd π ≈ 3,14.\nSvara med talet (i cm²).", ans(pi * r * r),
                 f"Area = π · r² = 3,14 · {r} · {r} = {fmt(pi * r * r)}.", calc=f"3.14*{r}*{r}")
    return Q(f"En cirkel har radien {r} cm. Beräkna omkretsen. Använd π ≈ 3,14.\nSvara med talet (i cm).", ans(2 * pi * r),
             f"Omkrets = 2 · π · r = 2 · 3,14 · {r} = {fmt(2 * pi * r)}.", calc=f"2*3.14*{r}")


@register("m4_volume", "matte", "Geometri", 4)
def m4_volume(rng, bank):
    a, b, c = rng.randint(2, 9), rng.randint(2, 9), rng.randint(2, 9)
    return Q(f"Ett rätblock är {a} cm långt, {b} cm brett och {c} cm högt. Hur stor är volymen?\nSvara med talet (i cm³).",
             [str(a * b * c)], f"Volym = längd · bredd · höjd = {a} · {b} · {c} = {a * b * c}.", calc=f"{a}*{b}*{c}")


@register("m4_probability", "matte", "Sannolikhet", 4)
def m4_probability(rng, bank):
    t = rng.choice([4, 5, 10, 20, 25])
    r = rng.randint(1, t - 1)
    p = r * 100 // t
    return Q(f"I en påse finns {r} röda och {t - r} blå kulor. Hur stor är sannolikheten att dra en röd kula?\nSvara i procent.",
             [str(p), f"{p}%", f"{p} %"], f"{r} av {t} kulor är röda: {r}/{t} = {p} %.", calc=f"{r}/{t}*100")


# ================================================================== NIVÅ 5

@register("m5_system", "matte", "Ekvationssystem", 5)
def m5_system(rng, bank):
    y = rng.randint(1, 9)
    x = y + rng.randint(1, 8)
    ask = rng.choice(["x", "y"])
    return Q(f"Lös ekvationssystemet\nx + y = {x + y}\nx − y = {x - y}\nVad är {ask}?{NUM}", [str(x if ask == "x" else y)],
             f"Addera ekvationerna: 2x = {2 * x}, så x = {x}. Sätt in i första ekvationen: y = {x + y} − {x} = {y}.",
             calc=str(x if ask == "x" else y))


@register("m5_vat", "matte", "Procent", 5)
def m5_vat(rng, bank):
    ex = rng.randrange(40, 801, 4)
    incl = ex * 5 // 4
    if rng.random() < 0.6:
        return Q(f"En vara kostar {incl} kr inklusive 25 % moms. Vad kostar den utan moms (kr)?{NUM}", [str(ex)],
                 f"Priset med moms är 125 % av priset utan moms: {incl} : 1,25 = {ex}.", calc=f"{incl}/1.25")
    return Q(f"En vara kostar {incl} kr inklusive 25 % moms. Hur mycket av priset är moms (kr)?{NUM}", [str(incl - ex)],
             f"Priset utan moms är {incl} : 1,25 = {ex}. Momsen är {incl} − {ex} = {incl - ex}.", calc=f"{incl}-{incl}/1.25")


@register("m5_percent_chain", "matte", "Procent", 5)
def m5_chain(rng, bank):
    start = 100 * rng.randint(2, 9)
    p1, p2 = rng.choice([10, 20, 30, 40, 50]), rng.choice([10, 20, 50])
    final = start * (100 - p1) * (100 + p2) // 10000
    return Q(f"En vara kostar {start} kr. Priset sänks med {p1} %. Därefter höjs det nya priset med {p2} %. "
             f"Vad kostar varan till sist (kr)?{NUM}", [str(final)],
             f"Först: {start} · {fmt(Decimal(100 - p1) / 100)} = {start * (100 - p1) // 100}. "
             f"Sedan: det · {fmt(Decimal(100 + p2) / 100)} = {final}.", calc=f"{start}*(1-{p1}/100)*(1+{p2}/100)")


@register("m5_std_form", "matte", "Potenser", 5)
def m5_std_form(rng, bank):
    mant = Decimal(rng.randint(10, 99)) / 10
    n = rng.choice([-6, -5, -4, -3, -2, 3, 4, 5, 6, 7, 8])
    val = mant.scaleb(n)
    if n < 0:
        shown = fmt(val)
    else:
        shown = group(int(val))
    return Q(f"Skriv {shown} i grundpotensform, a · 10ⁿ, där a är ett tal mellan 1 och 10.\nVad är n?{NUM}", ans(n),
             f"{shown} = {fmt(mant)} · 10{sup(n)}. Flytta decimalkommat tills du får ett tal mellan 1 och 10 och räkna stegen.",
             calc=str(n))


@register("m5_eq_paren", "matte", "Ekvationer", 5)
def m5_eq_paren(rng, bank):
    a = rng.randint(2, 5)
    c = rng.randint(1, a - 1)
    b = rng.randint(1, 6)
    x = rng.randint(2, 12)
    d = a * (x - b) - c * x
    rhs = (coef(c) + " " + signed(d)).strip()
    return Q(f"Lös ekvationen {a}(x − {b}) = {rhs}.{NUM}", [str(x)],
             f"Multiplicera in: {a}x − {a * b} = {rhs}. Samla x på ena sidan och tal på den andra, så får du x = {x}.", calc=str(x))


@register("m5_slope", "matte", "Funktioner", 5)
def m5_slope(rng, bank):
    while True:  # håll rutnätet litet nog att ritas
        k = rng.choice([-4, -3, -2, -1, 1, 2, 3, 4, 5])
        m = rng.randint(-3, 6)
        x1 = rng.randint(0, 3)
        x2 = x1 + rng.randint(1, 3)
        y1, y2 = k * x1 + m, k * x2 + m
        if max(y1, y2, 0) - min(y1, y2, 0) <= 18:
            break
    return Q(f"En rät linje går genom punkterna ({x1}, {fmt(y1)}) och ({x2}, {fmt(y2)}). Vad är linjens lutning k?{NUM}", ans(k),
             f"k = (y₂ − y₁) / (x₂ − x₁) = ({fmt(y2)} − {par(y1)}) / ({x2} − {x1}) = {fmt(k)}.",
             diagram={"type": "coordinate", "xmin": min(0, x1) - 1, "xmax": x2 + 1, "ymin": min(y1, y2, 0) - 1,
                      "ymax": max(y1, y2, 0) + 1, "points": [{"x": x1, "y": y1, "label": "A"}, {"x": x2, "y": y2, "label": "B"}],
                      "line": {"k": k, "m": m}}, calc=f"({y2}-({y1}))/({x2}-{x1})")


@register("m5_cylinder", "matte", "Geometri", 5)
def m5_cylinder(rng, bank):
    r, h = rng.randint(1, 6), rng.randint(2, 10)
    v = Decimal("3.14") * r * r * h
    return Q(f"En cylinder har radien {r} cm och höjden {h} cm. Beräkna volymen. Använd π ≈ 3,14.\nSvara med talet (i cm³).", ans(v),
             f"V = π · r² · h = 3,14 · {r}² · {h} = 3,14 · {r * r} · {h} = {fmt(v)}.", calc=f"3.14*{r}**2*{h}")


@register("m5_combinatorics", "matte", "Kombinatorik", 5)
def m5_comb(rng, bank):
    if rng.random() < 0.4:
        n = rng.randint(3, 5)
        return Q(f"På hur många olika sätt kan {n} personer ställa sig i en kö?{NUM}", [str(math.factorial(n))],
                 f"Första platsen kan väljas på {n} sätt, nästa på {n - 1} och så vidare: {' · '.join(str(i) for i in range(n, 0, -1))} = {math.factorial(n)}.",
                 calc=f"math.factorial({n})")
    a, b, c = rng.randint(2, 5), rng.randint(2, 5), rng.randint(2, 4)
    return Q(f"Du har {a} tröjor, {b} byxor och {c} mössor. Hur många olika klädkombinationer kan du göra?{NUM}", [str(a * b * c)],
             f"Multiplicera antalen: {a} · {b} · {c} = {a * b * c}.", calc=f"{a}*{b}*{c}")


@register("m5_exp_rules", "matte", "Potenser", 5)
def m5_exp_rules(rng, bank):
    a = rng.randint(2, 9)
    form = rng.choice(["mul", "div", "pow"])
    if form == "mul":
        m, n = rng.randint(2, 6), rng.randint(2, 6)
        return Q(f"Skriv {a}{sup(m)} · {a}{sup(n)} som en enda potens med basen {a}.\nVilken exponent får potensen?{NUM}", [str(m + n)],
                 f"Vid multiplikation adderas exponenterna: {m} + {n} = {m + n}.", calc=f"{m}+{n}")
    if form == "div":
        n = rng.randint(2, 5)
        m = n + rng.randint(1, 4)
        return Q(f"Skriv {a}{sup(m)} : {a}{sup(n)} som en enda potens med basen {a}.\nVilken exponent får potensen?{NUM}", [str(m - n)],
                 f"Vid division subtraheras exponenterna: {m} − {n} = {m - n}.", calc=f"{m}-{n}")
    m, n = rng.randint(2, 4), rng.randint(2, 4)
    return Q(f"Skriv ({a}{sup(m)}){sup(n)} som en enda potens med basen {a}.\nVilken exponent får potensen?{NUM}", [str(m * n)],
             f"En potens upphöjd till något multiplicerar exponenterna: {m} · {n} = {m * n}.", calc=f"{m}*{n}")


@register("m5_sqrt", "matte", "Potenser", 5)
def m5_sqrt(rng, bank):
    n = rng.randint(6, 20)
    if rng.random() < 0.5:
        return Q(f"Vad är √{n * n}?{NUM}", [str(n)], f"{n} · {n} = {n * n}, alltså är √{n * n} = {n}.", calc=f"math.sqrt({n * n})")
    return Q(f"Lös ekvationen x² = {n * n}. Vad är det positiva värdet på x?{NUM}", [str(n)],
             f"x = √{n * n} = {n}, eftersom {n} · {n} = {n * n}.", calc=f"math.sqrt({n * n})")


# ------------------------------------------------------------------ användning

def load_all():
    """Registrerar även de svenska generatorerna."""
    from . import generators_en, generators_kpop, generators_no, generators_sv  # noqa: F401


def generate(ex_row, bank=None, rng=None):
    """Skapar en fråga för en generatorövning, eller None om underlag saknas."""
    load_all()
    g = REGISTRY.get(ex_row["generator"])
    if not g:
        return None
    try:
        return g.fn(rng or random, bank)
    except NoData:
        return None
