"""Övningslogik: rättning, adaptiv nivå, urval, prov och statistik."""
import json
import os
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Stockholm"))

LEVELS = range(1, 6)
WINDOW = 6          # antal senaste svar på nuvarande nivå som avgör nivåbyte
UP_AT = 5           # så många rätt av WINDOW -> upp en nivå
DOWN_AT = 2         # så få rätt (eller färre) av WINDOW -> ner en nivå
PER_LEVEL_IN_TEST = 2

SUBJECT_LABELS = {
    "matte": "Matematik",
    "svenska": "Svenska",
    "engelska": "Engelska",
    "no": "NO (natur)",
    "so": "SO (samhälle)",
}

LEVEL_HINTS = {  # visas bara för admin
    1: "ungefär åk 4–5",
    2: "ungefär åk 6",
    3: "ungefär åk 7",
    4: "ungefär åk 8",
    5: "ungefär åk 9",
}


def label(subject: str) -> str:
    return SUBJECT_LABELS.get(subject, subject.capitalize())


# ---------------------------------------------------------------- tid

def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(TZ)


def today() -> date:
    return datetime.now(TZ).date()


# ---------------------------------------------------------------- rättning

def _num(text: str):
    t = str(text).strip().replace("−", "-").replace(" ", "").replace(",", ".").replace("%", "")
    try:
        if "/" in t:
            a, b = t.split("/", 1)
            return float(a) / float(b)
        return float(t)
    except (ValueError, ZeroDivisionError):
        return None


def is_correct(given: str, answers: list) -> bool:
    g = " ".join(str(given).strip().lower().split())
    if not g:
        return False
    for a in answers:
        a_norm = " ".join(str(a).strip().lower().split())
        if g == a_norm:
            return True
        gn, an = _num(g), _num(a)
        # bråk jämförs bara som bråk, tal som tal (1/2 == 0,5 är ok)
        if gn is not None and an is not None and abs(gn - an) < 1e-9:
            return True
    return False


# ---------------------------------------------------------------- nivåer

def get_level(db, user_id: int, subject: str):
    row = db.execute(
        "SELECT level FROM user_levels WHERE user_id=? AND subject=?", (user_id, subject)
    ).fetchone()
    return row["level"] if row else None


def set_level(db, user_id: int, subject: str, level: int) -> None:
    level = max(1, min(5, int(level)))
    last = db.execute("SELECT COALESCE(MAX(id), 0) AS m FROM attempts WHERE user_id=?", (user_id,)).fetchone()["m"]
    db.execute(
        """INSERT INTO user_levels(user_id, subject, level, since_attempt_id) VALUES (?,?,?,?)
           ON CONFLICT(user_id, subject) DO UPDATE SET level=excluded.level,
           since_attempt_id=excluded.since_attempt_id""",
        (user_id, subject, level, last),
    )


def window_results(db, user_id: int, subject: str) -> list:
    """Senaste övningssvar (max WINDOW) på nuvarande nivå sedan senaste nivåbyte, äldst först."""
    row = db.execute(
        "SELECT level, since_attempt_id FROM user_levels WHERE user_id=? AND subject=?",
        (user_id, subject),
    ).fetchone()
    if not row:
        return []
    rows = db.execute(
        """SELECT a.correct FROM attempts a JOIN exercises e ON e.id = a.exercise_id
           WHERE a.user_id=? AND e.subject=? AND a.test_id IS NULL AND e.level=? AND a.id>?
           ORDER BY a.id DESC LIMIT ?""",
        (user_id, subject, row["level"], row["since_attempt_id"], WINDOW),
    ).fetchall()
    return [bool(r["correct"]) for r in reversed(rows)]


def adjust_level(db, user_id: int, subject: str, attempt_id: int):
    """Returnerar 'up', 'down' eller None."""
    row = db.execute(
        "SELECT level FROM user_levels WHERE user_id=? AND subject=?", (user_id, subject)
    ).fetchone()
    if not row:
        return None
    results = window_results(db, user_id, subject)
    if len(results) < WINDOW:
        return None
    correct = sum(results)
    level = row["level"]
    if correct >= UP_AT and level < 5:
        new, change = level + 1, "up"
    elif correct <= DOWN_AT and level > 1:
        new, change = level - 1, "down"
    else:
        return None
    db.execute(
        "UPDATE user_levels SET level=?, since_attempt_id=? WHERE user_id=? AND subject=?",
        (new, attempt_id, user_id, subject),
    )
    return change


# ---------------------------------------------------------------- övningar

def exercise_row(db, exercise_id: int):
    return db.execute("SELECT * FROM exercises WHERE id=?", (exercise_id,)).fetchone()


def pick_exercise(db, user_id: int, subject: str):
    """Väljer nästa övning: mest på nuvarande nivå, lite repetition av missade och av nivån under."""
    level = get_level(db, user_id, subject) or 1
    rows = db.execute("SELECT id, level FROM exercises WHERE subject=? AND active=1", (subject,)).fetchall()
    if not rows:
        return None
    by_level = {}
    for r in rows:
        by_level.setdefault(r["level"], []).append(r["id"])
    level_of = {r["id"]: r["level"] for r in rows}

    recent = [r["exercise_id"] for r in db.execute(
        "SELECT exercise_id FROM attempts WHERE user_id=? ORDER BY id DESC LIMIT 12", (user_id,))]
    last = {}
    for r in db.execute(
        """SELECT a.exercise_id, a.correct FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? AND e.subject=? ORDER BY a.id""", (user_id, subject)):
        last[r["exercise_id"]] = r["correct"]
    missed = [e for e, c in last.items() if not c and e not in recent and e in level_of and level_of[e] <= level]

    pool = by_level.get(level)
    if not pool:
        nearest = min(by_level, key=lambda l: abs(l - level))
        pool = by_level[nearest]

    roll = random.random()
    if roll < 0.2 and missed:
        return random.choice(missed)
    if roll < 0.3 and (level - 1) in by_level:
        pool = by_level[level - 1]
    fresh = [e for e in pool if e not in recent]
    unseen = [e for e in fresh if e not in last]
    return random.choice(unseen or fresh or pool)


def record_attempt(db, user_id: int, exercise, given: str, test_id=None):
    answers = json.loads(exercise["answers"])
    correct = 1 if is_correct(given, answers) else 0
    cur = db.execute(
        "INSERT INTO attempts(user_id, exercise_id, test_id, given, correct) VALUES (?,?,?,?,?)",
        (user_id, exercise["id"], test_id, given.strip(), correct),
    )
    attempt_id = cur.lastrowid
    change = None
    if test_id is None:
        change = adjust_level(db, user_id, exercise["subject"], attempt_id)
    db.commit()
    return attempt_id, bool(correct), change


# ---------------------------------------------------------------- prov

def create_test(db, user_id: int, subject: str):
    kind = "placement" if get_level(db, user_id, subject) is None else "status"
    recent = {r["exercise_id"] for r in db.execute(
        "SELECT exercise_id FROM attempts WHERE user_id=? ORDER BY id DESC LIMIT 40", (user_id,))}
    chosen = []
    for lvl in LEVELS:
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM exercises WHERE subject=? AND level=? AND active=1", (subject, lvl))]
        ids.sort(key=lambda e: (e in recent, random.random()))
        chosen.extend(ids[:PER_LEVEL_IN_TEST])
    if not chosen:
        return None
    cur = db.execute(
        "INSERT INTO tests(user_id, subject, kind, total) VALUES (?,?,?,?)",
        (user_id, subject, kind, len(chosen)),
    )
    test_id = cur.lastrowid
    for pos, ex_id in enumerate(chosen, start=1):
        db.execute("INSERT INTO test_items(test_id, position, exercise_id) VALUES (?,?,?)", (test_id, pos, ex_id))
    db.commit()
    return test_id


def next_test_item(db, test_id: int):
    """Första obesvarade frågan i provet: (position, exercise_row) eller None."""
    row = db.execute(
        """SELECT ti.position, ti.exercise_id FROM test_items ti
           WHERE ti.test_id=? AND NOT EXISTS (
               SELECT 1 FROM attempts a WHERE a.test_id=ti.test_id AND a.exercise_id=ti.exercise_id)
           ORDER BY ti.position LIMIT 1""",
        (test_id,),
    ).fetchone()
    if not row:
        return None
    return row["position"], exercise_row(db, row["exercise_id"])


def test_breakdown(db, test_id: int) -> dict:
    per = {}
    for r in db.execute(
        """SELECT e.level, a.correct FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.test_id=?""", (test_id,)):
        d = per.setdefault(r["level"], {"total": 0, "correct": 0})
        d["total"] += 1
        d["correct"] += r["correct"]
    return per


def estimate_level(per: dict) -> int:
    est = 0
    for lvl in LEVELS:
        d = per.get(lvl)
        if not d:
            continue
        if d["correct"] / d["total"] >= 0.5:
            est = lvl
        else:
            break
    return max(est, 1)


def finish_test(db, test_id: int) -> int:
    test = db.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
    per = test_breakdown(db, test_id)
    est = estimate_level(per)
    score = sum(d["correct"] for d in per.values())
    db.execute(
        "UPDATE tests SET score=?, estimated_level=?, finished_at=datetime('now') WHERE id=?",
        (score, est, test_id),
    )
    current = get_level(db, test["user_id"], test["subject"])
    if test["kind"] == "placement" or current is None:
        set_level(db, test["user_id"], test["subject"], est)
    elif est > current:  # ett statusprov kan höja nivån men sänker den aldrig
        set_level(db, test["user_id"], test["subject"], est)
    db.commit()
    return est


def test_review(db, test_id: int) -> list:
    out = []
    for r in db.execute(
        """SELECT e.*, a.given, a.correct FROM test_items ti
           JOIN exercises e ON e.id=ti.exercise_id
           LEFT JOIN attempts a ON a.test_id=ti.test_id AND a.exercise_id=ti.exercise_id
           WHERE ti.test_id=? ORDER BY ti.position""", (test_id,)):
        d = dict(r)
        d["answers_list"] = json.loads(r["answers"])
        out.append(d)
    return out


# ---------------------------------------------------------------- statistik

def attempt_days(db, user_id: int, days: int = 60) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days + 1)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.execute(
        "SELECT created_at, correct FROM attempts WHERE user_id=? AND created_at>=?", (user_id, since)
    ).fetchall()
    return [(parse_ts(r["created_at"]).date(), r["correct"]) for r in rows]


def streak_and_today(db, user_id: int):
    items = attempt_days(db, user_id)
    days = {d for d, _ in items}
    t = today()
    count_today = sum(1 for d, _ in items if d == t)
    cursor = t if t in days else t - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak, count_today


def daily_chart(db, user_id: int, days: int = 14) -> list:
    items = attempt_days(db, user_id, days)
    t = today()
    out = []
    for i in range(days - 1, -1, -1):
        d = t - timedelta(days=i)
        total = sum(1 for x, _ in items if x == d)
        right = sum(c for x, c in items if x == d)
        out.append({"date": d, "total": total, "correct": right})
    return out


def subject_summary(db, user_id: int, subject: str) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    r = db.execute(
        """SELECT COUNT(*) AS n, COALESCE(SUM(a.correct), 0) AS c, MAX(a.created_at) AS last
           FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? AND e.subject=? AND a.created_at>=?""",
        (user_id, subject, since),
    ).fetchone()
    last_any = db.execute(
        """SELECT MAX(a.created_at) AS last FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? AND e.subject=?""", (user_id, subject)).fetchone()["last"]
    return {
        "subject": subject,
        "level": get_level(db, user_id, subject),
        "n7": r["n"],
        "acc7": round(100 * r["c"] / r["n"]) if r["n"] else None,
        "last": parse_ts(last_any) if last_any else None,
    }


def topic_stats(db, user_id: int, subject: str) -> list:
    rows = db.execute(
        """SELECT e.topic, COUNT(*) AS n, SUM(a.correct) AS c FROM attempts a
           JOIN exercises e ON e.id=a.exercise_id WHERE a.user_id=? AND e.subject=?
           GROUP BY e.topic ORDER BY (1.0*SUM(a.correct)/COUNT(*)) ASC""",
        (user_id, subject),
    ).fetchall()
    return [{"topic": r["topic"], "n": r["n"], "pct": round(100 * r["c"] / r["n"])} for r in rows]


def active_subjects(db) -> list:
    return [r["subject"] for r in db.execute(
        "SELECT DISTINCT subject FROM exercises WHERE active=1 ORDER BY subject")]


# ---------------------------------------------------------------- import

def validate_exercise(d) -> tuple:
    """Returnerar (rad, fel). Rad är en dict redo för INSERT."""
    if not isinstance(d, dict):
        return None, "inte ett objekt"
    subject = str(d.get("subject", "")).strip().lower()
    topic = str(d.get("topic", "")).strip()
    question = str(d.get("question", "")).strip()
    if not subject or not topic or not question:
        return None, "subject, topic och question måste fyllas i"
    try:
        level = int(d.get("level"))
    except (TypeError, ValueError):
        return None, "level måste vara 1–5"
    if level not in LEVELS:
        return None, "level måste vara 1–5"
    typ = str(d.get("type", "")).strip().lower()
    if typ not in ("mc", "text"):
        return None, "type måste vara 'mc' eller 'text'"
    answer = d.get("answer", d.get("answers"))
    answers = [answer] if isinstance(answer, (str, int, float)) else answer
    if not isinstance(answers, list) or not answers or not all(str(a).strip() for a in answers):
        return None, "answer saknas"
    answers = [str(a).strip() for a in answers]
    options = None
    if typ == "mc":
        options = d.get("options")
        if not isinstance(options, list) or len(options) < 2:
            return None, "mc kräver minst två options"
        options = [str(o).strip() for o in options]
        if not any(a in options for a in answers):
            return None, "answer måste finnas bland options"
    return {
        "subject": subject, "topic": topic, "level": level, "type": typ, "question": question,
        "options": json.dumps(options, ensure_ascii=False) if options else None,
        "answers": json.dumps(answers, ensure_ascii=False),
        "explanation": str(d.get("explanation", "")).strip(),
    }, None


def import_exercises(db, data) -> dict:
    if isinstance(data, dict):
        data = data.get("exercises", [])
    if not isinstance(data, list):
        raise ValueError("JSON måste vara en lista av övningar (eller {\"exercises\": [...]})")
    added = skipped = 0
    errors = []
    for i, item in enumerate(data, start=1):
        row, err = validate_exercise(item)
        if err:
            errors.append(f"Övning {i}: {err}")
            continue
        cur = db.execute(
            """INSERT OR IGNORE INTO exercises(subject, topic, level, type, question, options, answers, explanation)
               VALUES (:subject, :topic, :level, :type, :question, :options, :answers, :explanation)""",
            row,
        )
        if cur.rowcount:
            added += 1
        else:
            skipped += 1
    db.commit()
    return {"added": added, "skipped": skipped, "errors": errors}
