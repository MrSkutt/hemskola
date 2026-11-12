"""Redigerare för övningar: formulär -> övning, spara, ta bort och sök i listan.

Formuläret kontrolleras med samma validate_exercise som importen, så en övning är giltig på samma sätt oavsett hur
den läggs in. Generatorer (övningar som är kod) kan inte redigeras här, bara döljas."""
import json
import re

from . import areas, diagrams, logic

OPTION_SLOTS = 6         # så många alternativrutor visas som standard (fler om en övning redan har fler)
MAX_OPTIONS = 8
MAX_ANSWERS = 20
PAGE_SIZE = 50
NEW_SUBJECT = "__ny__"
LIMITS = {"topic": 60, "question": 1500, "option": 200, "answer": 200, "explanation": 2000, "diagram": 4000}
SUBJECT_RE = re.compile(r"^[a-zåäöé0-9][a-zåäöé0-9_-]{1,29}$")
KINDS = {"mc": "Flerval", "text": "Fritext", "gen": "Generator (∞)"}
# Svarsstatistik att filtrera och sortera på, för att hitta övningar som kan vara felaktiga eller otydliga.
STATS = {"answered": "Besvarade", "hard": "Många fel", "unanswered": "Aldrig besvarade"}
SORTS = {"low": "Lägst andel rätt", "many": "Flest svar"}
HARD_MIN_ANSWERS = 3         # "många fel": minst så här många svar ...
HARD_MAX_SHARE = 1 / 3       # ... och högst så stor andel rätt


def is_hard(n: int, c: int) -> bool:
    return n >= HARD_MIN_ANSWERS and c <= n * HARD_MAX_SHARE


def clean_subject(raw) -> str:
    """Ett nytt ämnesnamn som tecken som går att ha i en webbadress (små bokstäver, bindestreck i stället för mellanslag).
    Tom sträng om det inte går."""
    s = "-".join(str(raw or "").strip().lower().split())
    return s if SUBJECT_RE.match(s) else ""


# ---------------------------------------------------------------- formulär

def blank_form(subject="", level=3, typ="mc", topic="") -> dict:
    return {"subject": subject, "new_subject": "", "topic": topic, "level": level, "type": typ, "question": "",
            "options": [""] * OPTION_SLOTS, "correct": [], "answers_text": "", "explanation": "", "image": "",
            "diagram_type": "", "diagram": "", "active": True}


def form_from_row(row) -> dict:
    """Fyller formuläret från en befintlig övning."""
    answers = json.loads(row["answers"])
    options = json.loads(row["options"]) if row["options"] else []
    diagram = json.loads(row["diagram"]) if row["diagram"] else None
    slots = options + [""] * max(0, OPTION_SLOTS - len(options))
    return {
        "subject": row["subject"], "new_subject": "", "topic": row["topic"], "level": row["level"], "type": row["type"],
        "question": row["question"], "options": slots,
        "correct": [i for i, o in enumerate(options) if o in answers],
        "answers_text": "\n".join(answers) if row["type"] == "text" else "",
        "explanation": row["explanation"] or "", "image": row["image"] or "",
        "diagram_type": diagram.get("type", "") if diagram else "",
        "diagram": json.dumps(diagram, ensure_ascii=False, indent=2) if diagram else "",
        "active": bool(row["active"]),
    }


def form_from_post(values) -> dict:
    """Läser ett inskickat formulär (starlette FormData eller en dict med listor) till samma form som blank_form."""
    def one(key, default=""):
        v = values.get(key, default)
        return str(v if v is not None else default)

    def many(key):
        return [str(x) for x in (values.getlist(key) if hasattr(values, "getlist") else values.get(key, []))]

    try:
        level = int(one("level", "0"))
    except ValueError:
        level = 0
    correct = []
    for c in many("correct"):
        if c.strip().isdigit():
            correct.append(int(c))
    options = many("option")[:MAX_OPTIONS + OPTION_SLOTS]
    options += [""] * max(0, OPTION_SLOTS - len(options))
    return {
        "subject": one("subject").strip(), "new_subject": one("new_subject"), "topic": one("topic"), "level": level,
        "type": one("type"), "question": one("question"), "options": options, "correct": correct,
        "answers_text": one("answers_text"), "explanation": one("explanation"),
        "image": (one("image_existing") or one("image_current")).strip(),
        "diagram_type": one("diagram_type"), "diagram": one("diagram"), "active": bool(one("active")),
    }


def build(form: dict, known_subjects=()) -> tuple:
    """(rad, fel). Raden är klar för INSERT/UPDATE (se logic.validate_exercise), felen är en lista med meddelanden."""
    errors = []
    if form["subject"] == NEW_SUBJECT:
        subject = clean_subject(form["new_subject"])
        if not subject:
            errors.append("Skriv ett nytt ämnesnamn med 2–30 bokstäver eller siffror, till exempel franska.")
    else:
        subject = form["subject"].strip().lower()
        if not subject:
            errors.append("Välj ett ämne.")
        elif subject not in known_subjects and not SUBJECT_RE.match(subject):
            errors.append("Ämnet finns inte.")
    topic = " ".join(form["topic"].split())
    if not topic:
        errors.append("Skriv vilket område övningen hör till, till exempel Bråk.")
    elif len(topic) > LIMITS["topic"]:
        errors.append(f"Området får vara högst {LIMITS['topic']} tecken.")
    if form["level"] not in logic.LEVELS:
        errors.append("Välj en nivå mellan 1 och 5.")
    question = form["question"].replace("\r\n", "\n").strip()
    if not question:
        errors.append("Skriv frågan.")
    elif len(question) > LIMITS["question"]:
        errors.append(f"Frågan får vara högst {LIMITS['question']} tecken.")
    explanation = form["explanation"].replace("\r\n", "\n").strip()
    if len(explanation) > LIMITS["explanation"]:
        errors.append(f"Förklaringen får vara högst {LIMITS['explanation']} tecken.")
    typ = form["type"]
    options, answers = None, []
    if typ == "mc":
        slots = [" ".join(o.split()) for o in form["options"]]
        options = [o for o in slots if o]
        if len(options) < 2:
            errors.append("Ett flervalsval behöver minst två alternativ.")
        elif len(options) > MAX_OPTIONS:
            errors.append(f"Högst {MAX_OPTIONS} alternativ.")
        elif len({o.casefold() for o in options}) != len(options):
            errors.append("Två alternativ är likadana. Alla alternativ måste vara olika.")
        if any(len(o) > LIMITS["option"] for o in options):
            errors.append(f"Ett alternativ får vara högst {LIMITS['option']} tecken.")
        answers = [slots[i] for i in dict.fromkeys(form["correct"]) if 0 <= i < len(slots) and slots[i]]
        if not answers:
            errors.append("Markera vilket alternativ som är rätt.")
    elif typ == "text":
        answers = list(dict.fromkeys(" ".join(a.split()) for a in form["answers_text"].splitlines() if a.strip()))
        if not answers:
            errors.append("Skriv minst ett godkänt svar.")
        elif len(answers) > MAX_ANSWERS:
            errors.append(f"Högst {MAX_ANSWERS} godkända svar.")
        if any(len(a) > LIMITS["answer"] for a in answers):
            errors.append(f"Ett svar får vara högst {LIMITS['answer']} tecken.")
    else:
        errors.append("Välj om övningen är flerval eller fritext.")
    diagram = None
    text = form["diagram"].strip()
    if text:
        if len(text) > LIMITS["diagram"]:
            errors.append("Diagrammets inställningar är för långa.")
        else:
            try:
                diagram = json.loads(text)
            except ValueError as e:
                errors.append(f"Diagrammets inställningar är inte giltig JSON ({e}).")
    elif form["diagram_type"]:
        errors.append("Du valde en diagramtyp men inga inställningar finns. Ta bort valet eller fyll i inställningarna.")
    if errors:
        return None, errors
    row, err = logic.validate_exercise({
        "subject": subject, "topic": topic, "level": form["level"], "type": typ, "question": question,
        "options": options, "answer": answers, "explanation": explanation, "image": form["image"] or None,
        "diagram": diagram})
    if err:
        return None, [_friendly(err)]
    return row, []


def _friendly(err: str) -> str:
    """Importens felmeddelanden pratar om JSON-nycklar. Här översätts de som kan uppstå i formuläret."""
    if err.startswith("image måste"):
        return "Bildens filnamn får bara ha bokstäver, siffror, punkt, bindestreck och understreck."
    if err.startswith("diagram måste"):
        return "Diagrammet måste vara ett objekt med en \"type\", till exempel {\"type\": \"clock\", \"time\": \"2:10\"}."
    return err[0].upper() + err[1:]


# ---------------------------------------------------------------- spara

def find_duplicate(db, subject: str, question: str, exclude_id=None):
    row = db.execute("SELECT id FROM exercises WHERE subject=? AND question=? AND id<>?",
                     (subject, question, exclude_id or 0)).fetchone()
    return row["id"] if row else None


def _dup_message(subject: str) -> str:
    return f"Det finns redan en övning med exakt samma fråga i {logic.label(subject)}."


def create_exercise(db, row: dict, active=True) -> tuple:
    """(id, fel, id på dubblett)."""
    dup = find_duplicate(db, row["subject"], row["question"])
    if dup:
        return None, _dup_message(row["subject"]), dup
    cur = db.execute(
        """INSERT INTO exercises(subject, topic, level, type, question, options, answers, explanation, image, diagram,
                                 active)
           VALUES (:subject, :topic, :level, :type, :question, :options, :answers, :explanation, :image, :diagram, :a)""",
        {**row, "a": 1 if active else 0})
    return cur.lastrowid, "", None


def update_exercise(db, ex_id: int, row: dict, active=True) -> tuple:
    """(fel, id på dubblett)."""
    old = db.execute("SELECT subject, generator FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not old:
        return "Övningen finns inte.", None
    if old["generator"]:
        return "Generatorer är kod och kan inte redigeras. Du kan dölja dem.", None
    dup = find_duplicate(db, row["subject"], row["question"], ex_id)
    if dup:
        return _dup_message(row["subject"]), dup
    db.execute(
        """UPDATE exercises SET subject=:subject, topic=:topic, level=:level, type=:type, question=:question,
                  options=:options, answers=:answers, explanation=:explanation, image=:image, diagram=:diagram,
                  active=:a, review=CASE WHEN :a=1 THEN 0 ELSE review END
           WHERE id=:id""", {**row, "a": 1 if active else 0, "id": ex_id})
    if old["subject"] != row["subject"] and old["subject"] in logic.LEGACY_SUBJECTS:
        logic.migrate_legacy_levels(db)
    return "", None


def replace_exercise(db, ex_id: int, row: dict) -> tuple:
    """Sparar ändringarna som en ny övning och döljer den gamla, så att elevernas historik och statistik hör till
    den gamla frågan. Eftersom en fråga bara får finnas en gång per ämne måste frågetexten eller ämnet skilja sig.
    (id på den nya, fel, id på dubblett)."""
    old = db.execute("SELECT generator FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not old:
        return None, "Övningen finns inte.", None
    if old["generator"]:
        return None, "Generatorer är kod och kan inte redigeras. Du kan dölja dem.", None
    new_id, err, dup = create_exercise(db, row, active=True)
    if err:
        if dup == ex_id:
            err = ("Den nya övningen måste ha en annan frågetext än den gamla (den gamla finns kvar, dold). "
                   "Ändra frågan lite, eller spara utan att skapa en ny.")
        return None, err, dup
    db.execute("UPDATE exercises SET active=0 WHERE id=?", (ex_id,))
    return new_id, "", None


def answer_count(db, ex_id: int) -> int:
    return db.execute("SELECT COUNT(*) AS n FROM attempts WHERE exercise_id=?", (ex_id,)).fetchone()["n"]


def delete_exercise(db, ex_id: int) -> str:
    """Tar bort en övning som ingen har svarat på. Annars (eller om den ingår i ett prov) får man dölja den."""
    row = db.execute("SELECT generator FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not row:
        return "Övningen finns inte."
    if row["generator"]:
        return "Generatorer kan inte tas bort. Du kan dölja dem."
    n = answer_count(db, ex_id)
    if n:
        return f"Elever har svarat på den ({n} svar), så den kan inte tas bort. Dölj den i stället."
    if db.execute("SELECT 1 FROM test_items WHERE exercise_id=?", (ex_id,)).fetchone():
        return "Övningen ingår i ett prov och kan inte tas bort. Dölj den i stället."
    db.execute("DELETE FROM exercises WHERE id=?", (ex_id,))
    return ""


# ---------------------------------------------------------------- lista och sök

def topics_by_subject(db) -> dict:
    out = {}
    for r in db.execute("SELECT DISTINCT subject, topic FROM exercises ORDER BY subject, topic"):
        out.setdefault(r["subject"], []).append(r["topic"])
    return out


def search(db, q="", subject="", level=0, topic="", kind="", state="", page=1, stat="", sort="",
           page_size=PAGE_SIZE) -> dict:
    """Övningar som matchar filtren, en sida i taget. `q` söker i fråga, område, svar och förklaring (utan hänsyn till
    stor eller liten bokstav, även åäö). kind: mc, text eller gen. state: on (synliga), off (dolda av admin) eller
    review (importerade, väntar på godkännande). stat: answered, hard eller unanswered (se STATS). sort: low (lägst
    andel rätt) eller many (flest svar)."""
    sql = """SELECT e.*, COUNT(a.id) AS n, COALESCE(SUM(a.correct), 0) AS c
             FROM exercises e LEFT JOIN attempts a ON a.exercise_id=e.id WHERE 1=1"""
    params = []
    if subject:
        sql += " AND e.subject=?"
        params.append(subject)
    if level:
        sql += " AND e.level=?"
        params.append(level)
    if topic:
        sql += " AND e.topic=?"
        params.append(topic)
    if kind == "gen":
        sql += " AND e.generator IS NOT NULL"
    elif kind in ("mc", "text"):
        sql += " AND e.generator IS NULL AND e.type=?"
        params.append(kind)
    if state == "on":
        sql += " AND e.active=1"
    elif state == "off":
        sql += " AND e.active=0 AND e.review=0"
    elif state == "review":
        sql += " AND e.review=1"
    sql += " GROUP BY e.id"
    if stat == "answered":
        sql += " HAVING n > 0"
    elif stat == "unanswered":
        sql += " HAVING n = 0"
    elif stat == "hard":
        sql += f" HAVING n >= {HARD_MIN_ANSWERS} AND c * 3 <= n"
    default = "e.subject, e.level, e.generator IS NOT NULL, e.topic, e.id"
    if sort == "low":      # obesvarade sist, sedan lägst andel rätt och därefter flest svar
        sql += f" ORDER BY n = 0, c * 1.0 / NULLIF(n, 0), n DESC, {default}"
    elif sort == "many":
        sql += f" ORDER BY n DESC, {default}"
    else:
        sql += f" ORDER BY {default}"
    rows = db.execute(sql, params).fetchall()
    needle = " ".join(q.split()).casefold()
    if needle:
        rows = [r for r in rows if needle in " ".join(
            [r["question"], r["topic"], r["answers"], r["explanation"] or ""]).casefold()]
    total = len(rows)
    pages = max(1, -(-total // page_size))
    page = min(max(1, page), pages)
    start = (page - 1) * page_size
    return {"rows": rows[start:start + page_size], "total": total, "page": page, "pages": pages,
            "first": start + 1 if total else 0, "last": min(total, start + page_size)}


# ---------------------------------------------------------------- granskning av importerade övningar
#
# Importerade övningar kan läggas in som dolda och märkta med review=1. Eleverna ser dem först när admin har
# godkänt dem (active=1, review=0). Märkningen försvinner också om övningen på annat sätt görs synlig.

def review_count(db) -> int:
    return db.execute("SELECT COUNT(*) AS n FROM exercises WHERE review=1").fetchone()["n"]


def approve(db, ex_id: int) -> bool:
    """Godkänner en övning som väntar på granskning. False om den inte väntar på något."""
    cur = db.execute("UPDATE exercises SET active=1, review=0 WHERE id=? AND review=1", (ex_id,))
    return cur.rowcount > 0


def approve_matching(db, **filters) -> int:
    """Godkänner alla övningar som väntar på granskning och matchar filtren (över alla sidor). Antal godkända."""
    rows = search(db, **{**filters, "state": "review", "page": 1, "page_size": 10 ** 9})["rows"]
    n = 0
    for r in rows:
        n += approve(db, r["id"])
    return n


# ---------------------------------------------------------------- förhandsvisning

def recent_attempts(db, ex_id: int, limit: int = 15) -> list:
    """Elevernas senaste svar på en övning, för att se om facit eller de godkända svaren behöver ändras."""
    return db.execute(
        """SELECT a.given, a.correct, a.created_at, u.display_name FROM attempts a JOIN users u ON u.id=a.user_id
           WHERE a.exercise_id=? ORDER BY a.id DESC LIMIT ?""", (ex_id, limit)).fetchall()


def preview_item(row: dict) -> dict:
    """En övning som den ser ut för eleven (svg ritad), för förhandsvisningen."""
    diagram = json.loads(row["diagram"]) if row["diagram"] else None
    return {
        "subject": row["subject"], "topic": row["topic"], "level": row["level"], "type": row["type"],
        "question": row["question"], "options": json.loads(row["options"]) if row["options"] else None,
        "answers": json.loads(row["answers"]), "explanation": row["explanation"], "image": row["image"],
        "svg": diagrams.render(diagram) if diagram else None,
        "area": areas.area_of(row["subject"], row["topic"]),
        "area_unknown": areas.area_of(row["subject"], row["topic"]) == areas.OVRIGT,
    }
