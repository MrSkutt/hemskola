"""Generatorer för NO- och SO-ämnena: kemi, fysik, teknik, biologi, geografi, historia och samhällskunskap.
Alla facit räknas fram i koden. Faktalistorna (grundämnen, länder, årtal) är handkontrollerade."""
import re
from decimal import Decimal

from .generators import NUM, Q, ans, fmt, group, register

# ------------------------------------------------------------------ hjälp


def _choose(rng, correct, pool, k=3):
    """Fyra alternativ: det rätta och k felaktiga ur pool (utan dubbletter)."""
    others = [x for x in dict.fromkeys(pool) if x != correct]
    rng.shuffle(others)
    return [correct] + others[:k]


def _num(x):
    return ans(x)


# ================================================================== KEMI

# (symbol, namn, atomnummer, nivå)
ELEMENTS = [
    ("H", "väte", 1, 1), ("He", "helium", 2, 1), ("C", "kol", 6, 1), ("N", "kväve", 7, 1), ("O", "syre", 8, 1),
    ("Na", "natrium", 11, 1), ("Cl", "klor", 17, 1), ("Ca", "kalcium", 20, 1), ("Fe", "järn", 26, 1),
    ("Cu", "koppar", 29, 1), ("Ag", "silver", 47, 1), ("Au", "guld", 79, 1),
    ("Li", "litium", 3, 2), ("F", "fluor", 9, 2), ("Ne", "neon", 10, 2), ("Mg", "magnesium", 12, 2),
    ("Al", "aluminium", 13, 2), ("Si", "kisel", 14, 2), ("P", "fosfor", 15, 2), ("S", "svavel", 16, 2),
    ("K", "kalium", 19, 2), ("Zn", "zink", 30, 2), ("Sn", "tenn", 50, 2), ("Hg", "kvicksilver", 80, 2),
    ("Pb", "bly", 82, 2),
    ("Be", "beryllium", 4, 3), ("B", "bor", 5, 3), ("Ar", "argon", 18, 3), ("Ti", "titan", 22, 3),
    ("Cr", "krom", 24, 3), ("Mn", "mangan", 25, 3), ("Ni", "nickel", 28, 3), ("Br", "brom", 35, 3),
    ("I", "jod", 53, 3), ("W", "volfram", 74, 3), ("Pt", "platina", 78, 3), ("U", "uran", 92, 3),
]


def _elems(level):
    return [e for e in ELEMENTS if e[3] <= level]


def _make_symbol(level):
    def fn(rng, bank):
        e = rng.choice(_elems(level))
        pool = [x[0] for x in _elems(level)]
        return Q(f"Vilken kemisk beteckning har grundämnet {e[1]}?", [e[0]], f"{e[1].capitalize()} har beteckningen {e[0]}.",
                 options=_choose(rng, e[0], pool))
    return fn


def _make_name(level):
    def fn(rng, bank):
        e = rng.choice(_elems(level))
        pool = [x[1] for x in _elems(level)]
        return Q(f"Vilket grundämne har den kemiska beteckningen {e[0]}?", [e[1]], f"{e[0]} betyder {e[1]}.",
                 options=_choose(rng, e[1], pool))
    return fn


for _l in (1, 2, 3):
    register(f"k{_l}_elem_symbol", "kemi", "Grundämnen", _l)(_make_symbol(_l))
for _l in (1, 2, 3):
    register(f"k{_l}_elem_name", "kemi", "Grundämnen", _l)(_make_name(_l))


@register("k3_atomic_number", "kemi", "Atomer", 3)
def k3_atomic_number(rng, bank):
    e = rng.choice(_elems(2))
    n = e[2]
    opts = _choose(rng, str(n), [str(n + d) for d in (-2, -1, 1, 2, 3, 4) if n + d > 0])
    return Q(f"Vilket atomnummer har {e[1]} ({e[0]})?", [str(n)],
             f"Atomnumret är antalet protoner i atomkärnan. {e[1].capitalize()} har {n} protoner.", options=opts)


@register("k4_electrons", "kemi", "Atomer", 4)
def k4_electrons(rng, bank):
    e = rng.choice([x for x in ELEMENTS if x[2] <= 30])
    return Q(f"Hur många elektroner har en neutral atom av {e[1]} ({e[0]})?{NUM}", [str(e[2])],
             f"I en neutral atom är antalet elektroner lika med antalet protoner, alltså atomnumret {e[2]}.",
             calc=str(e[2]))


@register("k4_neutrons", "kemi", "Atomer", 4)
def k4_neutrons(rng, bank):
    e = rng.choice([("kol-12", 12, 6), ("natrium-23", 23, 11), ("syre-16", 16, 8), ("kväve-14", 14, 7),
                    ("järn-56", 56, 26), ("aluminium-27", 27, 13), ("kalcium-40", 40, 20), ("magnesium-24", 24, 12),
                    ("litium-7", 7, 3), ("helium-4", 4, 2), ("klor-35", 35, 17), ("koppar-63", 63, 29)])
    n = e[1] - e[2]
    return Q(f"En atom av {e[0]} har masstalet {e[1]} och atomnumret {e[2]}. Hur många neutroner har den?{NUM}", [str(n)],
             f"Neutroner = masstal − atomnummer = {e[1]} − {e[2]} = {n}.", calc=f"{e[1]}-{e[2]}")


FORMULAS = [("vatten", "H2O"), ("koldioxid", "CO2"), ("bordssalt (natriumklorid)", "NaCl"), ("metan", "CH4"),
            ("ammoniak", "NH3"), ("glukos (druvsocker)", "C6H12O6"), ("svavelsyra", "H2SO4"), ("saltsyra", "HCl"),
            ("natriumhydroxid", "NaOH"), ("kalciumkarbonat (kalksten)", "CaCO3"), ("väteperoxid", "H2O2"),
            ("syrgas", "O2"), ("ozon", "O3"), ("koloxid", "CO")]
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _sub(f):
    return f.translate(_SUB)


@register("k3_formula", "kemi", "Kemiska föreningar", 3)
def k3_formula(rng, bank):
    name, f = rng.choice(FORMULAS)
    return Q(f"Vilken är den kemiska formeln för {name}?", [_sub(f)], f"Formeln för {name} är {_sub(f)}.",
             options=_choose(rng, _sub(f), [_sub(x[1]) for x in FORMULAS]))


def _atoms(f):
    return sum(int(n or 1) for _, n in re.findall(r"([A-Z][a-z]?)(\d*)", f))


@register("k4_atom_count", "kemi", "Kemiska föreningar", 4)
def k4_atom_count(rng, bank):
    name, f = rng.choice(FORMULAS)
    total = _atoms(f)
    return Q(f"Hur många atomer finns det sammanlagt i en molekyl av {name}, {_sub(f)}?{NUM}", [str(total)],
             "Räkna alla atomer: siffran efter ett ämne anger hur många atomer av det som finns.", calc=str(total))


MASS = {"H": 1, "C": 12, "N": 14, "O": 16, "Na": 23, "S": 32, "Cl": Decimal("35.5"), "Ca": 40}


@register("k5_molar_mass", "kemi", "Kemiska föreningar", 5)
def k5_molar_mass(rng, bank):
    name, f = rng.choice([x for x in FORMULAS if all(a in MASS for a, _ in re.findall(r"([A-Z][a-z]?)(\d*)", x[1]))])
    parts = re.findall(r"([A-Z][a-z]?)(\d*)", f)
    total = sum(Decimal(str(MASS[a])) * int(n or 1) for a, n in parts)
    used = ", ".join(f"{a} = {fmt(Decimal(str(MASS[a])))}" for a in dict.fromkeys(a for a, _ in parts))
    expr = "+".join(f"{MASS[a]}*{int(n or 1)}" for a, n in parts)
    return Q(f"Beräkna molmassan för {name}, {_sub(f)}, i g/mol. Atommassor: {used}.{NUM}", ans(total),
             "Multiplicera varje atommassa med antalet atomer och addera.", calc=expr)


# ================================================================== FYSIK

@register("f1_units_length", "fysik", "Enheter", 1)
def f1_units(rng, bank):
    kind = rng.choice(["m-cm", "km-m", "kg-g", "l-dl", "min-s", "h-min"])
    n = rng.randint(2, 40)
    if kind == "m-cm":
        return Q(f"Hur många centimeter är {n} meter?{NUM}", [str(n * 100)], "1 m = 100 cm.", calc=f"{n}*100")
    if kind == "km-m":
        return Q(f"Hur många meter är {n} kilometer?{NUM}", [str(n * 1000)], "1 km = 1000 m.", calc=f"{n}*1000")
    if kind == "kg-g":
        return Q(f"Hur många gram är {n} kilogram?{NUM}", [str(n * 1000)], "1 kg = 1000 g.", calc=f"{n}*1000")
    if kind == "l-dl":
        return Q(f"Hur många deciliter är {n} liter?{NUM}", [str(n * 10)], "1 l = 10 dl.", calc=f"{n}*10")
    if kind == "min-s":
        return Q(f"Hur många sekunder är {n} minuter?{NUM}", [str(n * 60)], "1 min = 60 s.", calc=f"{n}*60")
    return Q(f"Hur många minuter är {n} timmar?{NUM}", [str(n * 60)], "1 h = 60 min.", calc=f"{n}*60")


@register("f2_temp_change", "fysik", "Temperatur", 2)
def f2_temp_change(rng, bank):
    a = rng.randint(-12, 5)
    b = a + rng.randint(4, 14)
    return Q(f"Temperaturen stiger från {fmt(a)} °C till {fmt(b)} °C. Hur många grader steg den?{NUM}", [str(b - a)],
             "Skillnaden är det högre minus det lägre värdet. Titta på tallinjen.",
             diagram={"type": "number_line", "min": min(a, -5) - 2, "max": max(b, 5) + 2, "step": 1, "label_step": 5,
                      "marks": [{"value": a, "label": "start"}, {"value": b, "label": "slut"}]},
             calc=f"{b}-({a})")


@register("f3_kelvin", "fysik", "Temperatur", 3)
def f3_kelvin(rng, bank):
    c = rng.randint(-40, 100)
    if rng.random() < 0.5:
        return Q(f"Hur många kelvin motsvarar {fmt(c)} °C? Räkna med att 0 °C = 273 K.{NUM}", [str(c + 273)],
                 "Kelvin = grader Celsius + 273.", calc=f"{c}+273")
    k = c + 273
    return Q(f"Hur många grader Celsius motsvarar {k} K? Räkna med att 0 °C = 273 K.{NUM}", ans(c),
             "Celsius = kelvin − 273.", calc=f"{k}-273")


@register("f3_speed", "fysik", "Rörelse", 3)
def f3_speed(rng, bank):
    v = rng.choice([30, 40, 50, 60, 80, 90, 100, 120])
    t = rng.choice([Decimal("0.5"), 1, Decimal("1.5"), 2, Decimal("2.5"), 3, 4])
    s = v * Decimal(t)
    form = rng.choice(["v", "s", "t"])
    if form == "v":
        return Q(f"En bil kör {fmt(s)} km på {fmt(Decimal(t))} timmar. Vilken medelhastighet har den i km/h?{NUM}", [fmt(v)],
                 "Hastighet = sträcka / tid.", calc=f"{s}/{Decimal(t)}")
    if form == "s":
        return Q(f"En bil håller medelhastigheten {v} km/h i {fmt(Decimal(t))} timmar. Hur långt kommer den (km)?{NUM}", ans(s),
                 "Sträcka = hastighet · tid.", calc=f"{v}*{Decimal(t)}")
    return Q(f"Hur många timmar tar det att köra {fmt(s)} km med medelhastigheten {v} km/h?{NUM}", ans(Decimal(t)),
             "Tid = sträcka / hastighet.", calc=f"{s}/{v}")


@register("f4_density", "fysik", "Densitet", 4)
def f4_density(rng, bank):
    d = rng.choice([Decimal("0.9"), 1, Decimal("2.7"), Decimal("7.8"), Decimal("8.9"), Decimal("11.3")])
    v = rng.choice([10, 20, 50, 100, 200])
    m = d * v
    name = {Decimal("0.9"): "olja", 1: "vatten", Decimal("2.7"): "aluminium", Decimal("7.8"): "järn",
            Decimal("8.9"): "koppar", Decimal("11.3"): "bly"}[d]
    if rng.random() < 0.5:
        return Q(f"Ett stycke {name} har massan {fmt(m)} g och volymen {v} cm³. Vilken densitet har det i g/cm³?{NUM}", ans(d),
                 "Densitet = massa / volym.", calc=f"{m}/{v}")
    return Q(f"Densiteten för {name} är {fmt(d)} g/cm³. Vilken massa i gram har {v} cm³ {name}?{NUM}", ans(m),
             "Massa = densitet · volym.", calc=f"{d}*{v}")


@register("f4_ohm", "fysik", "El", 4)
def f4_ohm(rng, bank):
    r, i = rng.choice([2, 5, 10, 20, 50]), rng.randint(2, 12)
    u = r * i
    form = rng.choice(["u", "i", "r"])
    if form == "u":
        return Q(f"En resistor på {r} Ω har strömmen {i} A genom sig. Vilken spänning ligger över den (V)?{NUM}", [str(u)],
                 "Ohms lag: U = R · I.", calc=f"{r}*{i}")
    if form == "i":
        return Q(f"Spänningen {u} V ligger över en resistor på {r} Ω. Hur stor är strömmen (A)?{NUM}", [str(i)],
                 "I = U / R.", calc=f"{u}/{r}")
    return Q(f"Spänningen {u} V ger strömmen {i} A genom en resistor. Hur stor är resistansen (Ω)?{NUM}", [str(r)],
             "R = U / I.", calc=f"{u}/{i}")


@register("f4_power", "fysik", "El", 4)
def f4_power(rng, bank):
    u, i = rng.choice([12, 24, 230]), rng.randint(1, 10)
    p = u * i
    if rng.random() < 0.5:
        return Q(f"En apparat är kopplad till {u} V och drar {i} A. Vilken effekt har den (W)?{NUM}", [str(p)],
                 "Effekt = spänning · ström.", calc=f"{u}*{i}")
    return Q(f"En apparat har effekten {p} W och är kopplad till {u} V. Hur stor ström drar den (A)?{NUM}", [str(i)],
             "I = P / U.", calc=f"{p}/{u}")


@register("f4_energy_cost", "fysik", "El", 4)
def f4_energy_cost(rng, bank):
    p = rng.choice([500, 1000, 1500, 2000, 3000])
    h = rng.choice([1, 2, 3, 4, 5])
    price = rng.choice([1, 2, 3])
    kwh = Decimal(p) * h / 1000
    return Q(f"En kokplatta på {p} W är på i {h} timmar. Elen kostar {price} kr per kWh. Vad kostar det (kr)?{NUM}", ans(kwh * price),
             f"Energi = effekt · tid = {fmt(Decimal(p) / 1000)} kW · {h} h = {fmt(kwh)} kWh. Kostnaden är kWh · pris.",
             calc=f"{p}/1000*{h}*{price}")


@register("f5_wave", "fysik", "Vågor", 5)
def f5_wave(rng, bank):
    medium, v, lams = rng.choice([("ljud i luft (340 m/s)", 340, [2, 4, 5, 10, 20]),
                                  ("ljud i vatten (1 500 m/s)", 1500, [2, 4, 5, 10, 20]),
                                  ("ljus (300 000 000 m/s)", 300000000, [3, 30, 300])])
    lam = rng.choice(lams)
    return Q(f"En våg av typen {medium} har våglängden {lam} m. Hur många hertz är frekvensen?{NUM}", [str(v // lam)],
             "Vågekvationen: v = f · λ, alltså f = v / λ.", calc=f"{v}/{lam}")


@register("f5_resistors", "fysik", "El", 5)
def f5_resistors(rng, bank):
    a, b = rng.choice([(6, 3), (12, 4), (10, 10), (20, 5), (6, 12), (30, 30), (15, 10), (8, 8)])
    if rng.random() < 0.5:
        return Q(f"Två resistorer på {a} Ω och {b} Ω kopplas i serie. Hur stor är den totala resistansen (Ω)?{NUM}", [str(a + b)],
                 "I serie adderas resistanserna.", calc=f"{a}+{b}")
    r = Decimal(a * b) / Decimal(a + b)
    return Q(f"Två resistorer på {a} Ω och {b} Ω kopplas parallellt. Hur stor är den totala resistansen (Ω)?{NUM}", ans(r),
             "Vid parallellkoppling gäller R = (R₁ · R₂) / (R₁ + R₂).", calc=f"{a}*{b}/({a}+{b})")


# ================================================================== TEKNIK

@register("t2_data_units", "teknik", "Datalagring", 2)
def t2_data_units(rng, bank):
    n = rng.randint(2, 90)
    kind = rng.choice(["mb-kb", "gb-mb", "kb-b", "byte-bit"])
    if kind == "mb-kb":
        return Q(f"En fil är {n} MB. Hur många kB är det? Räkna med 1 MB = 1000 kB.{NUM}", [str(n * 1000)], "Multiplicera med 1000.", calc=f"{n}*1000")
    if kind == "gb-mb":
        return Q(f"Ett minneskort rymmer {n} GB. Hur många MB är det? Räkna med 1 GB = 1000 MB.{NUM}", [str(n * 1000)], "Multiplicera med 1000.", calc=f"{n}*1000")
    if kind == "kb-b":
        return Q(f"Hur många byte är {n} kB? Räkna med 1 kB = 1000 byte.{NUM}", [str(n * 1000)], "Multiplicera med 1000.", calc=f"{n}*1000")
    return Q(f"Hur många bitar är {n} byte?{NUM}", [str(n * 8)], "1 byte = 8 bitar.", calc=f"{n}*8")


@register("t3_bin_to_dec", "teknik", "Binära tal", 3)
def t3_bin_to_dec(rng, bank):
    n = rng.randint(3, 31)
    b = format(n, "b")
    return Q(f"Vilket tal i vårt vanliga talsystem är det binära talet {b}?{NUM}", [str(n)],
             "Positionerna är 1, 2, 4, 8, 16 … från höger. Lägg ihop de positioner som har en etta.", calc=str(n))


@register("t3_dec_to_bin", "teknik", "Binära tal", 3)
def t3_dec_to_bin(rng, bank):
    n = rng.randint(3, 31)
    b = format(n, "b")
    wrong = {format(x, "b") for x in (n + 1, n - 1, n + 2, n ^ 1, n ^ 2, n ^ 4) if x > 0 and x != n}
    return Q(f"Hur skriver man talet {n} binärt?", [b], "Dela upp talet i 16, 8, 4, 2 och 1.",
             options=_choose(rng, b, sorted(wrong)))


@register("t3_storage", "teknik", "Datalagring", 3)
def t3_storage(rng, bank):
    gb = rng.choice([16, 32, 64, 128, 256])
    mb = rng.choice([2, 4, 5, 8, 10])
    n = gb * 1000 // mb
    return Q(f"Ett minneskort på {gb} GB ska fyllas med låtar på {mb} MB var. Hur många låtar får plats? Räkna med 1 GB = 1000 MB.{NUM}",
             [str(n)], "Räkna om GB till MB och dela med storleken på en låt.", calc=f"{gb}*1000/{mb}")


@register("t4_download", "teknik", "Nätverk", 4)
def t4_download(rng, bank):
    size = rng.choice([50, 100, 200, 400, 500])
    speed = rng.choice([10, 20, 25, 40, 50, 100])
    t = Decimal(size * 8) / speed
    return Q(f"En fil på {size} MB laddas ned med hastigheten {speed} Mbit/s. Hur många sekunder tar det? (1 byte = 8 bitar){NUM}",
             ans(t), "Räkna om MB till Mbit (gånger 8) och dela med hastigheten.", calc=f"{size}*8/{speed}")


@register("t4_logic", "teknik", "Logik", 4)
def t4_logic(rng, bank):
    a, b = rng.randint(0, 1), rng.randint(0, 1)
    op = rng.choice(["AND", "OR", "XOR"])
    r = {"AND": a & b, "OR": a | b, "XOR": a ^ b}[op]
    hint = {"AND": "AND ger 1 bara om båda är 1.", "OR": "OR ger 1 om minst en är 1.",
            "XOR": "XOR ger 1 om bara en av dem är 1."}[op]
    return Q(f"Vad blir {a} {op} {b}?{NUM}", [str(r)], hint, calc=str(r))


@register("t5_hex", "teknik", "Binära tal", 5)
def t5_hex(rng, bank):
    n = rng.randint(16, 255)
    h = format(n, "X")
    return Q(f"Vilket tal i vårt vanliga talsystem är det hexadecimala talet {h}? (A = 10, B = 11, C = 12, D = 13, E = 14, F = 15){NUM}",
             [str(n)], "Första siffran gånger 16 plus andra siffran.", calc=str(n))


# ================================================================== BIOLOGI

@register("b2_pulse", "biologi", "Kroppen", 2)
def b2_pulse(rng, bank):
    p = rng.choice([60, 70, 72, 80, 90, 100])
    m = rng.choice([2, 5, 10])
    return Q(f"Hjärtat slår {p} slag per minut. Hur många slag blir det på {m} minuter?{NUM}", [str(p * m)],
             "Multiplicera slag per minut med antalet minuter.", calc=f"{p}*{m}")


@register("b4_energy_chain", "biologi", "Ekologi", 4)
def b4_energy_chain(rng, bank):
    e = rng.choice([1000, 5000, 10000, 20000, 50000])
    names = ["växter (producenter)", "gräshoppor (växtätare)", "grodor (köttätare)", "ormar (toppkonsumenter)"]
    step = rng.randint(1, 3)
    val = Decimal(e) / 10 ** step
    return Q(f"I en näringskedja når ungefär 10 % av energin nästa nivå. Växterna har {group(e)} kJ energi. Hur mycket "
             f"energi når {names[step]}?{NUM}", ans(val), f"Gå {step} steg: dela med 10 {step} gång{'er' if step > 1 else ''}.",
             calc=f"{e}/10**{step}")


@register("b5_punnett", "biologi", "Genetik", 5)
def b5_punnett(rng, bank):
    pairs = [("Aa", "Aa", 25), ("Aa", "aa", 50), ("AA", "Aa", 0), ("aa", "aa", 100), ("Aa", "AA", 0), ("AA", "aa", 0)]
    p1, p2, pct = rng.choice(pairs)
    return Q(f"I en ärftlighetskorsning är A dominant och a recessiv. Föräldrarna är {p1} och {p2}. Hur många procent av "
             f"avkomman får genotypen aa?{NUM}", [str(pct)], "Rita en korsningsruta (Punnettruta) och räkna rutorna med aa.",
             calc=str(pct))


@register("b5_dna", "biologi", "Genetik", 5)
def b5_dna(rng, bank):
    n = rng.randint(4, 7)
    s = "".join(rng.choice("ACGT") for _ in range(n))
    comp = "".join({"A": "T", "T": "A", "C": "G", "G": "C"}[c] for c in s)
    return Q(f"En DNA-sträng har basordningen {s}. Vilken är den komplementära strängen? (A pardar med T och C med G)\nSkriv bokstäverna utan mellanslag.",
             [comp], "A–T och C–G är baspar.")


# ================================================================== GEOGRAFI

# (land, huvudstad, kontinent, nivå)
COUNTRIES = [
    ("Sverige", "Stockholm", "Europa", 1), ("Norge", "Oslo", "Europa", 1), ("Danmark", "Köpenhamn", "Europa", 1),
    ("Finland", "Helsingfors", "Europa", 1), ("Tyskland", "Berlin", "Europa", 1), ("Frankrike", "Paris", "Europa", 1),
    ("Storbritannien", "London", "Europa", 1), ("Spanien", "Madrid", "Europa", 1), ("Italien", "Rom", "Europa", 1),
    ("Japan", "Tokyo", "Asien", 1), ("Kina", "Peking", "Asien", 1), ("Ryssland", "Moskva", "Europa", 1),
    ("USA", "Washington D.C.", "Nordamerika", 1), ("Sydkorea", "Seoul", "Asien", 1), ("Egypten", "Kairo", "Afrika", 1),
    ("Polen", "Warszawa", "Europa", 2), ("Grekland", "Aten", "Europa", 2), ("Portugal", "Lissabon", "Europa", 2),
    ("Österrike", "Wien", "Europa", 2), ("Schweiz", "Bern", "Europa", 2), ("Nederländerna", "Amsterdam", "Europa", 2),
    ("Belgien", "Bryssel", "Europa", 2), ("Irland", "Dublin", "Europa", 2), ("Island", "Reykjavik", "Europa", 2),
    ("Kanada", "Ottawa", "Nordamerika", 2), ("Mexiko", "Mexico City", "Nordamerika", 2), ("Brasilien", "Brasília", "Sydamerika", 2),
    ("Argentina", "Buenos Aires", "Sydamerika", 2), ("Indien", "New Delhi", "Asien", 2), ("Australien", "Canberra", "Oceanien", 2),
    ("Turkiet", "Ankara", "Asien", 2), ("Thailand", "Bangkok", "Asien", 2),
    ("Estland", "Tallinn", "Europa", 3), ("Lettland", "Riga", "Europa", 3), ("Litauen", "Vilnius", "Europa", 3),
    ("Tjeckien", "Prag", "Europa", 3), ("Ungern", "Budapest", "Europa", 3), ("Rumänien", "Bukarest", "Europa", 3),
    ("Ukraina", "Kiev", "Europa", 3), ("Vietnam", "Hanoi", "Asien", 3), ("Indonesien", "Jakarta", "Asien", 3),
    ("Filippinerna", "Manila", "Asien", 3), ("Saudiarabien", "Riyadh", "Asien", 3), ("Iran", "Teheran", "Asien", 3),
    ("Pakistan", "Islamabad", "Asien", 3), ("Chile", "Santiago", "Sydamerika", 3), ("Peru", "Lima", "Sydamerika", 3),
    ("Colombia", "Bogotá", "Sydamerika", 3), ("Kuba", "Havanna", "Nordamerika", 3), ("Marocko", "Rabat", "Afrika", 3),
    ("Kenya", "Nairobi", "Afrika", 3), ("Nigeria", "Abuja", "Afrika", 3), ("Etiopien", "Addis Abeba", "Afrika", 3),
    ("Nya Zeeland", "Wellington", "Oceanien", 3),
    ("Bulgarien", "Sofia", "Europa", 4), ("Serbien", "Belgrad", "Europa", 4), ("Kroatien", "Zagreb", "Europa", 4),
    ("Slovakien", "Bratislava", "Europa", 4), ("Slovenien", "Ljubljana", "Europa", 4), ("Vitryssland", "Minsk", "Europa", 4),
    ("Mongoliet", "Ulan Bator", "Asien", 4), ("Kazakstan", "Astana", "Asien", 4), ("Nepal", "Katmandu", "Asien", 4),
    ("Bangladesh", "Dhaka", "Asien", 4), ("Malaysia", "Kuala Lumpur", "Asien", 4), ("Venezuela", "Caracas", "Sydamerika", 4),
    ("Ecuador", "Quito", "Sydamerika", 4), ("Ghana", "Accra", "Afrika", 4),
    ("Tanzania", "Dodoma", "Afrika", 5), ("Algeriet", "Alger", "Afrika", 4), ("Senegal", "Dakar", "Afrika", 4),
    ("Azerbajdzjan", "Baku", "Asien", 5), ("Georgien", "Tbilisi", "Asien", 5), ("Armenien", "Jerevan", "Asien", 5),
    ("Uzbekistan", "Tasjkent", "Asien", 5), ("Myanmar", "Naypyidaw", "Asien", 5),
    ("Moldavien", "Chișinău", "Europa", 5), ("Nordmakedonien", "Skopje", "Europa", 5), ("Albanien", "Tirana", "Europa", 5),
]
_CAPITAL_LEVELS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


def _make_capital(level):
    def fn(rng, bank):
        pool = [c for c in COUNTRIES if c[3] == level]
        land = rng.choice(pool)
        near = [c[1] for c in COUNTRIES if c[3] <= level + 1 and c[2] == land[2]] or [c[1] for c in COUNTRIES]
        return Q(f"Vad heter huvudstaden i {land[0]}?", [land[1]], f"Huvudstaden i {land[0]} är {land[1]}.",
                 options=_choose(rng, land[1], near + [c[1] for c in COUNTRIES if c[3] <= level]))
    return fn


TWO_CONTINENTS = {"Ryssland", "Turkiet", "Kazakstan", "Georgien", "Azerbajdzjan", "Armenien"}


def _make_continent(level):
    def fn(rng, bank):
        land = rng.choice([c for c in COUNTRIES if max(1, level - 1) <= c[3] <= level and c[0] not in TWO_CONTINENTS])
        return Q(f"På vilken kontinent ligger {land[0]}?", [land[2]], f"{land[0]} ligger i {land[2]}.",
                 options=_choose(rng, land[2], ["Europa", "Asien", "Afrika", "Nordamerika", "Sydamerika", "Oceanien"]))
    return fn


def _make_country(level):
    def fn(rng, bank):
        land = rng.choice([c for c in COUNTRIES if c[3] == level])
        pool = [c[0] for c in COUNTRIES if c[2] == land[2] and c[3] <= level + 1] + [c[0] for c in COUNTRIES if c[3] <= level]
        return Q(f"Vilket land har huvudstaden {land[1]}?", [land[0]], f"{land[1]} är huvudstad i {land[0]}.",
                 options=_choose(rng, land[0], pool))
    return fn


for _l in range(1, 6):
    register(f"g{_l}_capital", "geografi", "Länder och huvudstäder", _l)(_make_capital(_l))
for _l in (2, 3, 4):
    register(f"g{_l}_continent", "geografi", "Länder och kontinenter", _l)(_make_continent(_l))
for _l in (2, 3, 4, 5):
    register(f"g{_l}_country", "geografi", "Länder och huvudstäder", _l)(_make_country(_l))


@register("g3_scale", "geografi", "Kartor", 3)
def g3_scale(rng, bank):
    scale = rng.choice([10000, 25000, 50000, 100000, 200000])
    cm = rng.choice([2, 3, 4, 5, 6, 8, 10])
    km = Decimal(scale * cm) / 100000
    return Q(f"På en karta med skalan 1:{group(scale)} är avståndet mellan två platser {cm} cm. Hur många kilometer är det i verkligheten?{NUM}",
             ans(km), "Multiplicera med skalan. 100 000 cm är 1 km.", calc=f"{scale}*{cm}/100000")


@register("g4_density", "geografi", "Befolkning", 4)
def g4_density(rng, bank):
    area = rng.choice([10, 20, 50, 100, 200, 500])
    d = rng.choice([5, 10, 20, 40, 100, 250])
    pop = area * d
    return Q(f"Ett land (på låtsas) har {group(pop)} invånare och ytan {group(area)} km². Hur många invånare bor det i genomsnitt per km²?{NUM}",
             [str(d)], "Befolkningstäthet = antal invånare / yta.", calc=f"{pop}/{area}")


CITIES = [("Seoul", 9), ("Tokyo", 9), ("Peking", 8), ("Bangkok", 7), ("Dubai", 4), ("Moskva", 3), ("Kairo", 2),
          ("London", 0), ("New York", -5), ("Chicago", -6), ("Los Angeles", -8), ("Mexico City", -6)]


@register("g4_timezone", "geografi", "Tidszoner", 4)
def g4_timezone(rng, bank):
    city, off = rng.choice(CITIES)
    h = rng.randint(6, 18)
    local = (h + off - 1) % 24
    diff = off - 1
    word = "före" if diff > 0 else "efter"
    unit = "timme" if abs(diff) == 1 else "timmar"
    return Q(f"Det är klockan {h:02d}:00 i Sverige (vintertid, UTC+1). Klockan i {city} går {abs(diff)} {unit} {word} Sverige. "
             f"Vad är klockan där? Svara på formen 12:00.", [f"{local:02d}:00", f"{local}:00", f"{local:02d}.00"],
             f"{h} {'+' if diff >= 0 else '−'} {abs(diff)} = {local} (om resultatet blir över 24 eller under 0 går man ett dygn framåt eller bakåt).")


# ================================================================== HISTORIA

# (år, händelse, nivå)
EVENTS = [
    (1523, "Gustav Vasa blir kung av Sverige", 1), (1628, "regalskeppet Vasa sjunker i Stockholm", 1),
    (1914, "första världskriget bryter ut", 1), (1939, "andra världskriget bryter ut", 1),
    (1945, "andra världskriget tar slut", 1), (1969, "människan går på månen för första gången", 1),
    (1995, "Sverige går med i EU", 1), (1989, "Berlinmuren faller", 1),
    (1492, "Columbus kommer till Amerika", 2), (1789, "franska revolutionen börjar", 2), (1809, "Sverige förlorar Finland till Ryssland", 2),
    (1814, "unionen mellan Sverige och Norge bildas", 3),
    (1866, "tvåkammarriksdagen ersätter ståndsriksdagen i Sverige", 3), (1905, "unionen mellan Sverige och Norge upplöses", 2),
    (1921, "kvinnor får rösta i riksdagsval i Sverige för första gången", 2), (1945, "FN grundas", 2),
    (1950, "Koreakriget börjar", 3), (1953, "Koreakriget slutar med vapenvila", 3), (1961, "Berlinmuren byggs", 3),
    (1991, "Sovjetunionen upplöses", 3), (2001, "terrorattackerna mot USA den 11 september sker", 2),
    (1066, "slaget vid Hastings", 4), (1215, "Magna Carta undertecknas i England", 4), (1453, "Konstantinopel erövras av osmanerna", 4),
    (1517, "Martin Luther sätter upp sina 95 teser", 4), (1618, "trettioåriga kriget börjar", 4), (1648, "trettioåriga kriget slutar", 4),
    (1776, "USA förklarar sig självständigt", 3), (1815, "Napoleon förlorar slaget vid Waterloo", 4),
    (1848, "revolutionsvåg sveper över Europa", 5), (1861, "amerikanska inbördeskriget börjar", 4),
    (1865, "slaveriet avskaffas i USA", 5), (1914, "ärkehertig Franz Ferdinand mördas i Sarajevo", 4),
    (1917, "ryska revolutionen", 4), (1918, "första världskriget tar slut", 3), (1929, "börskraschen på Wall Street", 4),
    (1948, "Israel grundas", 5), (1949, "Nato grundas", 5), (1957, "Sovjetunionen skickar upp Sputnik, den första satelliten", 4),
    (1962, "Kubakrisen", 5), (1986, "kärnkraftsolyckan i Tjernobyl", 4), (1994, "Nelson Mandela blir president i Sydafrika", 5),
    (1397, "Kalmarunionen bildas", 5),
    (1611, "Gustav II Adolf blir kung av Sverige", 4), (1632, "Gustav II Adolf stupar i slaget vid Lützen", 5),
    (1718, "Karl XII dör vid Fredriksten", 5), (1810, "Jean Baptiste Bernadotte väljs till svensk tronföljare", 5),
    (1842, "folkskolan införs i Sverige", 4), (1846, "skråtvånget avskaffas i Sverige", 5), (1971, "tvåkammarriksdagen avskaffas i Sverige", 5),
    (1974, "Sverige antar en ny regeringsform", 5), (1994, "Sverige har folkomröstning om EU", 4), (2000, "Öresundsbron öppnas", 3),
]


def _make_year(level):
    def fn(rng, bank):
        e = rng.choice([x for x in EVENTS if x[2] == level])
        y = e[0]
        wrongs = {y + d for d in (-100, -50, -25, -10, -5, 5, 10, 25, 50, 100) if abs(d) <= (60 if level <= 3 else 120)}
        wrongs = [w for w in wrongs if 1000 < w <= 2025 and all(x[0] != w for x in EVENTS if x[1] == e[1])]
        rng.shuffle(wrongs)
        opts = [str(y)] + [str(w) for w in wrongs[:3]]
        return Q(f"Vilket år hände detta: {e[1]}?", [str(y)], f"Det hände år {y}.", options=opts)
    return fn


def _make_first(level):
    def fn(rng, bank):
        pool = [e for e in EVENTS if e[2] <= level and e[2] >= max(1, level - 1)]
        for _ in range(40):
            a, b = rng.sample(pool, 2)
            if abs(a[0] - b[0]) >= 3:
                break
        first = a if a[0] < b[0] else b
        return Q(f"Vilken av dessa händelser inträffade först?", [first[1]], f"{first[1].capitalize()} hände {first[0]}, tidigast av de två.",
                 options=[first[1], (b if first is a else a)[1]])
    return fn


for _l in range(1, 6):
    register(f"h{_l}_year", "historia", "Årtal", _l)(_make_year(_l))
for _l in (2, 3, 4):
    register(f"h{_l}_first", "historia", "Tidslinje", _l)(_make_first(_l))


@register("h2_century", "historia", "Tidsräkning", 2)
def h2_century(rng, bank):
    y = rng.choice([1523, 1648, 1789, 1809, 1814, 1905, 1914, 1945, 1066, 1492, 1215, 1611, 1776, 1991, 2001, 1350, 1699, 1700, 1800, 1900, 2000])
    right = f"{(y // 100) * 100}-talet"
    return Q(f"Vilket århundrade tillhör år {y}?", [right], f"År {y} ligger i {right} (det vill säga från {(y // 100) * 100} till {(y // 100) * 100 + 99}).",
             options=_choose(rng, right, [f"{((y // 100) + d) * 100}-talet" for d in (-2, -1, 1, 2, 3)]))


@register("h3_years_between", "historia", "Tidsräkning", 3)
def h3_years_between(rng, bank):
    pool = [e for e in EVENTS if e[2] <= 3]
    a, b = rng.sample(pool, 2)
    a, b = (a, b) if a[0] < b[0] else (b, a)
    d = b[0] - a[0]
    return Q(f"Hur många år gick det mellan när {a[1]} ({a[0]}) och när {b[1]} ({b[0]})?{NUM}", [str(d)],
             "Subtrahera det tidigare årtalet från det senare.", calc=f"{b[0]}-{a[0]}")


@register("h3_timeline", "historia", "Tidslinje", 3)
def h3_timeline(rng, bank):
    pool = [e for e in EVENTS if 1700 <= e[0] <= 2000 and e[2] <= 3]
    es = rng.sample(pool, 3)
    while len({e[0] for e in es}) < 3:
        es = rng.sample(pool, 3)
    last = chr(65 + es.index(max(es)))
    return Q(f"Tidslinjen visar tre händelser: {', '.join(f'{e[1]} ({chr(65 + i)})' for i, e in enumerate(es))}. "
             f"Vilken bokstav står för den händelse som skedde sist?", [last],
             "Händelsen längst till höger på tidslinjen hände senast.",
             options=["A", "B", "C", "D"],
             diagram={"type": "number_line", "min": 1700, "max": 2000, "step": 50, "label_step": 100,
                      "marks": [{"value": e[0], "label": chr(65 + i)} for i, e in enumerate(es)]})


# ================================================================== SAMHÄLLSKUNSKAP

@register("s3_vat", "samhallskunskap", "Ekonomi", 3)
def s3_vat(rng, bank):
    price = rng.choice([40, 80, 100, 120, 200, 400, 800, 1000])
    return Q(f"En vara kostar {price} kr utan moms. Moms är 25 %. Vad kostar varan med moms (kr)?{NUM}", ans(Decimal(price) * Decimal("1.25")),
             "Pris + 25 % av priset, eller pris · 1,25.", calc=f"{price}*1.25")


@register("s4_vat_back", "samhallskunskap", "Ekonomi", 4)
def s4_vat_back(rng, bank):
    base = rng.choice([80, 120, 200, 400, 600, 800])
    incl = base * 5 // 4
    return Q(f"En vara kostar {incl} kr med 25 % moms. Vad kostar den utan moms (kr)?{NUM}", [str(base)],
             "Priset med moms är 125 % av priset utan moms, alltså pris utan moms = pris med moms / 1,25.", calc=f"{incl}/1.25")


@register("s3_salary", "samhallskunskap", "Ekonomi", 3)
def s3_salary(rng, bank):
    gross = rng.choice([20000, 25000, 30000, 35000, 40000])
    tax = rng.choice([20, 25, 30])
    net = gross * (100 - tax) // 100
    return Q(f"Anna har {group(gross)} kr i lön före skatt. Hon betalar {tax} % i skatt. Hur mycket får hon kvar efter skatt (kr)?{NUM}",
             [str(net)], "Räkna ut skatten och dra bort den, eller räkna direkt på resten.", calc=f"{gross}*(100-{tax})/100")


@register("s3_interest", "samhallskunskap", "Ekonomi", 3)
def s3_interest(rng, bank):
    amount = rng.choice([1000, 2000, 5000, 10000, 20000])
    rate = rng.choice([2, 3, 4, 5])
    return Q(f"Du sätter in {group(amount)} kr på ett konto med {rate} % ränta per år. Hur mycket ränta får du efter ett år (kr)?{NUM}",
             [str(amount * rate // 100)], "Beräkna procenten av beloppet.", calc=f"{amount}*{rate}/100")


@register("s5_compound", "samhallskunskap", "Ekonomi", 5)
def s5_compound(rng, bank):
    amount = rng.choice([1000, 2000, 5000, 10000])
    rate = rng.choice([2, 5, 10])
    total = Decimal(amount) * (1 + Decimal(rate) / 100) ** 2
    return Q(f"Du sparar {group(amount)} kr i två år med {rate} % ränta per år, och räntan läggs till kapitalet varje år (ränta på ränta). "
             f"Hur mycket har du efter två år (kr)?{NUM}", ans(total), "Multiplicera med förändringsfaktorn två gånger.",
             calc=f"{amount}*(1+{rate}/100)**2")


@register("s2_majority", "samhallskunskap", "Demokrati", 2)
def s2_majority(rng, bank):
    n = rng.choice([21, 25, 31, 49, 51, 99, 101, 349])
    name = "riksdagen" if n == 349 else "en nämnd på låtsas"
    return Q(f"{'Riksdagen har 349 ledamöter' if n == 349 else f'Ett elevråd har {n} ledamöter'}. Hur många röster behövs för en majoritet (mer än hälften)?{NUM}",
             [str(n // 2 + 1)], "Mer än hälften: hälften avrundat nedåt plus ett.", calc=f"{n}//2+1")


@register("s3_budget_pie", "samhallskunskap", "Ekonomi", 3)
def s3_budget_pie(rng, bank):
    cats = rng.sample(["Boende", "Mat", "Transport", "Kläder", "Fritid", "Sparande"], 4)
    parts = rng.choice([[40, 25, 20, 15], [50, 20, 20, 10], [35, 30, 20, 15], [30, 30, 25, 15]])
    income = rng.choice([20000, 30000, 40000])
    i = rng.randrange(4)
    return Q(f"Cirkeldiagrammet visar hur en familj fördelar sina utgifter. Familjen har {group(income)} kr i månaden att fördela. "
             f"Hur många kronor går till {cats[i].lower()}?{NUM}", [str(income * parts[i] // 100)],
             "Beräkna hur stor del av helheten som delen är.", calc=f"{income}*{parts[i]}/100",
             diagram={"type": "pie_chart", "title": "Familjens utgifter (%)", "labels": cats, "values": parts, "show_percent": True})


@register("s5_inflation", "samhallskunskap", "Ekonomi", 5)
def s5_inflation(rng, bank):
    p = rng.choice([100, 200, 500, 1000])
    r = rng.choice([2, 5, 10])
    return Q(f"Under ett år är inflationen {r} %. En vara kostade {group(p)} kr förra året. Vad kostar den nu om priset följer inflationen (kr)?{NUM}",
             ans(Decimal(p) * (100 + r) / 100), "Öka priset med procentsatsen.", calc=f"{p}*(100+{r})/100")
