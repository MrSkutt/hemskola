"""Uppläsning i språkämnen med webbläsarens egen röst (Web Speech API, kostar inget).

Frågorna i ett språkämne blandar ofta svenska och målspråk: "Vad betyder 'dog' på svenska?" har svensk instruktion men
engelskt ord. En enda röst skulle uttala hälften fel, så servern avgör vilka delar som är på målspråket och skickar bara
dem till webbläsaren, tillsammans med rätt språkkod. Reglerna är försiktiga: är det oklart vilket språk en text har
läses den inte upp alls. Rätt svar skickas aldrig med innan eleven svarat."""
import re

# ämne -> (språkkod, hur språket böjs i meddelanden: "ingen ___ röst")
LANGUAGES = {
    "engelska": ("en-GB", "engelsk"),
    "franska": ("fr-FR", "fransk"),
    "tyska": ("de-DE", "tysk"),
    "spanska": ("es-ES", "spansk"),
    "italienska": ("it-IT", "italiensk"),
}

# Ord som bara finns på svenska (inte i något av målspråken). Räcker ett enda träffar delen som svensk.
SWEDISH_WORDS = frozenset("""
och att det som är på vad vilket vilken vilka hur skriv ordet orden betyder svenska engelska franska tyska spanska
italienska inte ett jag här där eller också finns bilden meningen rätt fel verbet substantiv adjektiv
imperfekt particip exempel vem när varför ska kan har med av om mig dig sig han hon vilket följande något ingen
fråga svar välj fyll luckan mening översätt betydelse glosa uttala uttalas säger heter bokstav bokstäver
""".split())

# Små, vanliga ord för varje målspråk. Behövs för att vara säker på att en text verkligen är på språket.
FUNCTION_WORDS = {
    "engelska": frozenset("""
        the a an is are was were be been being am do does did have has had will would can could should must may
        i you he she it we they me him her us them my your his its our their this that these those what which who
        whom whose when where why how not no yes and or but if of to in on at for from with by about as than then
        there here very much many some any all one two write choose word sentence correct picture look mean means meaning
        """.split()),
    "franska": frozenset("""
        le la les un une des du de au aux et ou est sont suis es sommes êtes ai as avons avez ont je tu il elle
        nous vous ils elles on ne pas que qui quoi quel quelle quels quelles comment où pourquoi quand avec dans
        pour sur sous ce cet cette ces mon ma mes ton ta tes son sa ses notre votre leur oui non très aussi mais
        """.split()),
    "tyska": frozenset("""
        der die das den dem des ein eine einen einem einer und oder ist sind bin bist seid war waren hat haben
        habe wird werden kann können ich du er sie es wir ihr nicht kein keine was wer wie wo wann warum welche
        welcher welches mit von zu auf aus bei nach für über unter sehr auch aber ja nein
        """.split()),
    "spanska": frozenset("""
        el la los las un una unos unas y o es son soy eres somos están está estoy tengo tiene tienen yo tú él ella
        nosotros ellos ellas no sí que qué quién cuál cuándo dónde cómo por para con sin sobre en de del al muy
        también pero este esta estos estas mi mis tu tus su sus
        """.split()),
    "italienska": frozenset("""
        il lo la gli le un uno una e o è sono sei siamo siete ho hai ha abbiamo hanno io tu lui lei noi voi loro
        non sì che chi cosa quale quando dove come perché con senza su per di del della in da molto anche ma questo
        questa questi queste mio mia miei mie tuo tua suo sua
        """.split()),
}

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
_BLANK = re.compile(r"_{2,}")
_QUOTES = re.compile(r"\"|[“”«»]|(?<!\w)['‘’]|['‘’](?!\w)")
_SPAN = re.compile(r"""(?<!\w)'([^'\n]{1,80}?)'(?!\w)|"([^"\n]{1,80}?)"|“([^”\n]{1,80}?)”|‘([^’\n]{1,80}?)’""")
_CUE = re.compile(r"\b(?:på|till)\s+(svenska|engelska|franska|tyska|spanska|italienska)\b", re.I)
_CHUNK = re.compile(r"(?<=[.!?:])\s+|\n+")
_AFTER_SPAN = re.compile(r"\s*(?:på|till)\s+(svenska|engelska|franska|tyska|spanska|italienska)\b", re.I)


def _words(text: str) -> list:
    return [w.lower() for w in _WORD.findall(text)]


def _is_swedish(text: str, subject: str) -> bool:
    """Innehåller texten något som bara finns på svenska? å finns inte i något målspråk, ä och ö finns i tyskan."""
    if "å" in text.lower():
        return True
    if subject != "tyska" and re.search(r"[äö]", text.lower()):
        return True
    return any(w in SWEDISH_WORDS for w in _words(text))


def _is_target(text: str, subject: str) -> bool:
    """Säkert på målspråket: inget svenskt och minst ett vanligt ord från språket."""
    return not _is_swedish(text, subject) and any(w in FUNCTION_WORDS[subject] for w in _words(text))


def clean(text: str) -> str:
    """Text som ska läsas: utan citattecken runt orden, luckan ___ blir en kort paus."""
    text = _BLANK.sub(", ", text)
    text = _QUOTES.sub("", text)
    return re.sub(r"\s+", " ", text).replace(" ,", ",").strip(" ,")


def _cue_language(question: str, subject: str):
    """Vilket språk frågan ber om svaret på ('på engelska', 'till svenska'): 'target', 'sv' eller None."""
    cues = _CUE.findall(question)
    if not cues:
        return None
    last = cues[-1].lower()
    if last == "svenska":
        return "sv"
    return "target" if last == subject else None


def _spans(chunk: str, subject: str) -> list:
    """Citerade ord i en svensk mening som är på målspråket. 'dog' på svenska → dog är engelska; 'hund' på engelska → hund
    är svenska och läses inte. Utan ledtråd antas ordet vara på målspråket, om det inte ser svenskt ut."""
    found = []
    for m in _SPAN.finditer(chunk):
        text = next(g for g in m.groups() if g is not None).strip()
        after = _AFTER_SPAN.match(chunk, m.end())
        if after:
            is_target = after.group(1).lower() == "svenska"
        else:
            is_target = not _is_swedish(text, subject)
        if is_target and _words(text):
            found.append(text)
    return found


def _pieces(question: str, subject: str) -> list:
    """(text, har_lucka)-par för de delar av frågan som är på målspråket, i läsordning."""
    out = []
    for chunk in _CHUNK.split(question):
        chunk = chunk.strip()
        if not chunk:
            continue
        if _is_target(chunk, subject):
            out.append((clean(chunk), bool(_BLANK.search(chunk))))
        elif _is_swedish(chunk, subject):
            out.extend((clean(t), False) for t in _spans(chunk, subject))
    return [(t, b) for t, b in out if t]


def _segment(text: str, subject: str) -> dict:
    code, name = LANGUAGES[subject]
    return {"t": text, "l": code, "n": name}


def plan(subject: str, question: str, options=None, answers=None, reveal: bool = False):
    """Vad som får läsas upp för en fråga, eller None om ämnet inte är ett språkämne eller inget går att läsa säkert.

    question: segment som läses för frågan. options: {alternativ: [segment]} för de alternativ som är på målspråket.
    answer: bara med reveal=True (svarssidan), aldrig på frågesidan."""
    if subject not in LANGUAGES:
        return None
    pieces = _pieces(question, subject)
    has_blank = any(blank for _, blank in pieces)
    cue = _cue_language(question, subject)
    # Alternativ och svar är på målspråket om frågan ber om det, om de ska in i en lucka i en målspråksmening, eller om
    # hela frågan är på målspråket (inget svenskt någonstans och minst en del som säkert är målspråk)
    chunks = [c.strip() for c in _CHUNK.split(question) if c.strip()]
    pure = bool(pieces) and not any(_is_swedish(c, subject) for c in chunks)
    answer_is_target = has_blank or cue == "target" or (cue is None and pure)
    result = {"question": [_segment(t, subject) for t, _ in pieces], "options": {}, "answer": []}
    if answer_is_target:
        for o in options or []:
            text = clean(str(o))
            if _words(text):
                result["options"][str(o)] = [_segment(text, subject)]
    if reveal and answer_is_target and answers:
        right = str(answers[0])
        filled = None
        if has_blank:
            for chunk in _CHUNK.split(question):
                if len(_BLANK.findall(chunk)) == 1 and _is_target(chunk, subject):
                    filled = _BLANK.sub(lambda _m: right, chunk.strip())
                    break
        text = clean(filled or right)
        if _words(text):
            result["answer"] = [_segment(text, subject)]
    if not (result["question"] or result["options"] or result["answer"]):
        return None
    return result
