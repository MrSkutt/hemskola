"""Övningslogik: rättning, adaptiv nivå, urval, prov och statistik."""
import json
import os
import random
import re
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from zoneinfo import ZoneInfo

from . import areas, diagrams, generators
from .words import WordBank

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
    "biologi": "Biologi",
    "fysik": "Fysik",
    "kemi": "Kemi",
    "teknik": "Teknik",
    "geografi": "Geografi",
    "historia": "Historia",
    "religionskunskap": "Religionskunskap",
    "samhallskunskap": "Samhällskunskap",
    "no": "NO (natur)",      # gamla samlingsämnen, delades upp i enskilda ämnen
    "so": "SO (samhälle)",
    "kpop": "K-pop",
}

# Ämnesgrupper på startsidan och i adminvyerna. Okända ämnen (som admin själv skapat) hamnar i "Övrigt".
SUBJECT_GROUPS = [
    ("grund", "Grundämnen", ("matte", "svenska", "engelska")),
    ("no", "Naturorienterande ämnen (NO)", ("biologi", "fysik", "kemi", "teknik")),
    ("so", "Samhällsorienterande ämnen (SO)", ("geografi", "historia", "religionskunskap", "samhallskunskap")),
    ("fritid", "Fritid och skoj", ("kpop",)),
]
OTHER_GROUP = ("ovrigt", "Övrigt")
# Fritidsämnen tas som standard inte med i rapporten till skolan (admin kan slå på dem per elev).
LEISURE_SUBJECTS = frozenset(s for key, _, members in SUBJECT_GROUPS if key == "fritid" for s in members)

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
    if change == "up":
        db.execute("INSERT OR IGNORE INTO level_ups(user_id, subject, level) VALUES (?,?,?)", (user_id, subject, new))
    return change


# ---------------------------------------------------------------- frågor (item)
#
# Ett "item" är en fråga som visas för eleven: antingen en vanlig övning eller en genererad instans.
# Alla delar av appen arbetar med items, så genererade och vanliga frågor behandlas lika.

def _loads(v, default=None):
    return json.loads(v) if v else default


def _item(row, generated_id=None) -> dict:
    diagram = _loads(row["diagram"])
    return {
        "id": row["exercise_id"] if generated_id else row["id"], "generated_id": generated_id,
        "subject": row["subject"], "topic": row["topic"], "level": row["level"],
        "type": row["type"], "question": row["question"], "options": _loads(row["options"]),
        "answers": json.loads(row["answers"]), "explanation": row["explanation"] or "",
        "image": row["image"] if "image" in row.keys() else None,
        "diagram": diagram, "svg": diagrams.render(diagram) if diagram else None,
    }


def exercise_row(db, exercise_id: int):
    return db.execute("SELECT * FROM exercises WHERE id=?", (exercise_id,)).fetchone()


def item_from_exercise(row) -> dict:
    return _item(row)


def item_from_generated(db, generated_id: int):
    row = db.execute(
        """SELECT g.*, e.subject, e.topic, e.level, NULL AS image FROM generated g
           JOIN exercises e ON e.id = g.exercise_id WHERE g.id=?""", (generated_id,)).fetchone()
    return _item(row, generated_id) if row else None


def present(db, ex_row, user_id=None):
    """Gör en övning till en fråga. Generatorövningar skapar en ny instans. None om det inte går."""
    if not ex_row["generator"]:
        return item_from_exercise(ex_row)
    generators.load_all()
    gen = generators.REGISTRY.get(ex_row["generator"])
    if not gen:
        return None
    bank = WordBank.from_db(db) if gen.words else None
    q = generators.generate(ex_row, bank)
    if q is None:
        return None
    cur = db.execute(
        """INSERT INTO generated(exercise_id, user_id, type, question, options, answers, explanation, diagram)
           VALUES (?,?,?,?,?,?,?,?)""",
        (ex_row["id"], user_id, "mc" if q.options else "text", q.question,
         json.dumps(q.options, ensure_ascii=False) if q.options else None,
         json.dumps(q.answers, ensure_ascii=False), q.explanation,
         json.dumps(q.diagram) if q.diagram else None))
    db.commit()
    return item_from_generated(db, cur.lastrowid)


def cleanup_generated(db, days: int = 14) -> int:
    """Tar bort gamla genererade frågor som aldrig besvarats och inte ingår i något prov."""
    cur = db.execute(
        """DELETE FROM generated WHERE created_at < datetime('now', ?)
           AND id NOT IN (SELECT generated_id FROM attempts WHERE generated_id IS NOT NULL)
           AND id NOT IN (SELECT generated_id FROM test_items WHERE generated_id IS NOT NULL)""",
        (f"-{int(days)} days",))
    db.commit()
    return cur.rowcount


def ensure_generator_exercises(db) -> int:
    """Lägger in en övningsrad per kodad generator (så att de kan slås av/på och väljas som vanliga övningar)."""
    generators.load_all()
    added = 0
    for g in generators.REGISTRY.values():
        cur = db.execute(
            """INSERT OR IGNORE INTO exercises(subject, topic, level, type, question, answers, generator)
               VALUES (?,?,?,'text',?,'[]',?)""", (g.subject, g.topic, g.level, f"gen:{g.name}", g.name))
        added += cur.rowcount
    db.commit()
    return added


# ---------------------------------------------------------------- övningar

def pick_exercise(db, user_id: int, subject: str, exclude=(), area=None):
    """Väljer nästa övning: mest på nuvarande nivå, lite repetition av missade och av nivån under.
    Med `area` väljs bara frågor inom det området (nivåbyte och statistik fungerar som vanligt)."""
    level = get_level(db, user_id, subject) or 1
    rows = [r for r in db.execute(
        "SELECT id, level, generator, topic FROM exercises WHERE subject=? AND active=1", (subject,))
        if r["id"] not in exclude and (not area or areas.area_of(subject, r["topic"]) == area)]
    if not rows:
        return None
    by_level, level_of = {}, {}
    gen_ids = set()
    for r in rows:
        by_level.setdefault(r["level"], []).append(r["id"])
        level_of[r["id"]] = r["level"]
        if r["generator"]:
            gen_ids.add(r["id"])

    recent = [r["exercise_id"] for r in db.execute(
        "SELECT exercise_id FROM attempts WHERE user_id=? ORDER BY id DESC LIMIT 12", (user_id,))]
    last = {}   # senaste resultat per vanlig övning (genererade frågor är alltid nya)
    for r in db.execute(
        """SELECT a.exercise_id, a.correct FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? AND e.subject=? AND e.generator IS NULL ORDER BY a.id""", (user_id, subject)):
        last[r["exercise_id"]] = r["correct"]
    missed = [e for e, c in last.items() if not c and e not in recent and e in level_of and level_of[e] <= level]

    pool = by_level.get(level)
    if not pool:
        pool = by_level[min(by_level, key=lambda l: abs(l - level))]

    roll = random.random()
    if roll < 0.2 and missed:
        return random.choice(missed)
    if roll < 0.3 and (level - 1) in by_level:
        pool = by_level[level - 1]
    fresh = [e for e in pool if (e not in recent[:3] if e in gen_ids else e not in recent)]
    unseen = [e for e in fresh if e in gen_ids or e not in last]
    return random.choice(unseen or fresh or pool)


def next_item(db, user_id: int, subject: str, area=None):
    bad = set()
    for _ in range(8):
        ex_id = pick_exercise(db, user_id, subject, exclude=bad, area=area)
        if ex_id is None:
            return None
        item = present(db, exercise_row(db, ex_id), user_id)
        if item:
            return item
        bad.add(ex_id)
    return None


def resolve_item(db, user_id: int, exercise_id: int, generated_id=None):
    """Hittar frågan som ett inskickat svar hör till. None om den är ogiltig eller redan besvarad."""
    if generated_id:
        item = item_from_generated(db, int(generated_id))
        owner = db.execute("SELECT user_id FROM generated WHERE id=?", (int(generated_id),)).fetchone()
        if not item or item["id"] != exercise_id or (owner and owner["user_id"] not in (None, user_id)):
            return None
        if db.execute("SELECT 1 FROM attempts WHERE generated_id=?", (int(generated_id),)).fetchone():
            return None
        return item
    row = exercise_row(db, exercise_id)
    return item_from_exercise(row) if row and not row["generator"] else None


def record_attempt(db, user_id: int, item: dict, given: str, test_id=None):
    get_prefs(db, user_id, commit=False)    # finns raden före första svaret räknas även det svaret in i poängen
    correct = 1 if is_correct(given, item["answers"]) else 0
    cur = db.execute(
        "INSERT INTO attempts(user_id, exercise_id, generated_id, test_id, given, correct) VALUES (?,?,?,?,?,?)",
        (user_id, item["id"], item["generated_id"], test_id, given.strip(), correct),
    )
    attempt_id = cur.lastrowid
    change = None
    if test_id is None:
        change = adjust_level(db, user_id, item["subject"], attempt_id)
    record_goal(db, user_id, item["subject"])
    db.commit()
    return attempt_id, bool(correct), change


# ---------------------------------------------------------------- prov

def create_test(db, user_id: int, subject: str):
    kind = "placement" if get_level(db, user_id, subject) is None else "status"
    recent = {r["exercise_id"] for r in db.execute(
        "SELECT exercise_id FROM attempts WHERE user_id=? ORDER BY id DESC LIMIT 40", (user_id,))}
    chosen = []   # (exercise_id, generated_id)
    for lvl in LEVELS:
        rows = db.execute(
            "SELECT * FROM exercises WHERE subject=? AND level=? AND active=1", (subject, lvl)).fetchall()
        rows = sorted(rows, key=lambda r: (r["id"] in recent and not r["generator"], random.random()))
        taken = []
        for r in rows:
            if len(taken) >= PER_LEVEL_IN_TEST:
                break
            item = present(db, r, user_id) if r["generator"] else None
            if r["generator"] and not item:
                continue
            taken.append((r["id"], item["generated_id"] if item else None, r))
        # generatorer kan upprepas med nya slumptal om nivån har för få olika övningar
        gens = [t for t in taken if t[1]]
        while gens and len(taken) < PER_LEVEL_IN_TEST:
            r = gens[0][2]
            item = present(db, r, user_id)
            if not item:
                break
            taken.append((r["id"], item["generated_id"], r))
        chosen.extend((t[0], t[1]) for t in taken)
    if not chosen:
        return None
    cur = db.execute("INSERT INTO tests(user_id, subject, kind, total) VALUES (?,?,?,?)",
                     (user_id, subject, kind, len(chosen)))
    test_id = cur.lastrowid
    for pos, (ex_id, gen_id) in enumerate(chosen, start=1):
        db.execute("INSERT INTO test_items(test_id, position, exercise_id, generated_id) VALUES (?,?,?,?)",
                   (test_id, pos, ex_id, gen_id))
    db.commit()
    return test_id


def _test_item(db, ti):
    if ti["generated_id"]:
        return item_from_generated(db, ti["generated_id"])
    return item_from_exercise(exercise_row(db, ti["exercise_id"]))


def next_test_item(db, test_id: int):
    """Första obesvarade frågan i provet: (position, item) eller None."""
    ti = db.execute(
        """SELECT ti.position, ti.exercise_id, ti.generated_id FROM test_items ti
           WHERE ti.test_id=? AND NOT EXISTS (
               SELECT 1 FROM attempts a WHERE a.test_id=ti.test_id AND a.exercise_id=ti.exercise_id
               AND COALESCE(a.generated_id, 0) = COALESCE(ti.generated_id, 0))
           ORDER BY ti.position LIMIT 1""", (test_id,)).fetchone()
    if not ti:
        return None
    return ti["position"], _test_item(db, ti)


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
        for lvl in range(current + 1, est + 1):
            db.execute("INSERT OR IGNORE INTO level_ups(user_id, subject, level) VALUES (?,?,?)",
                       (test["user_id"], test["subject"], lvl))
    db.commit()
    return est


def test_review(db, test_id: int) -> list:
    out = []
    for ti in db.execute(
            "SELECT exercise_id, generated_id FROM test_items WHERE test_id=? ORDER BY position", (test_id,)).fetchall():
        item = _test_item(db, ti)
        a = db.execute(
            """SELECT given, correct FROM attempts WHERE test_id=? AND exercise_id=?
               AND COALESCE(generated_id, 0) = COALESCE(?, 0)""", (test_id, ti["exercise_id"], ti["generated_id"])).fetchone()
        item["given"] = a["given"] if a else None
        item["correct"] = a["correct"] if a else 0
        item["answers_list"] = item["answers"]
        out.append(item)
    return out


# ---------------------------------------------------------------- statistik

def attempt_days(db, user_id: int, days: int = 60, subjects=None) -> list:
    """Svar per dag. Med `subjects` räknas bara svar i de ämnena (t.ex. för skolrapporten)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days + 1)).strftime("%Y-%m-%d %H:%M:%S")
    if subjects is None:
        rows = db.execute(
            "SELECT created_at, correct FROM attempts WHERE user_id=? AND created_at>=?", (user_id, since)
        ).fetchall()
    else:
        subs = list(subjects)
        if not subs:
            return []
        marks = ",".join("?" * len(subs))
        rows = db.execute(
            f"""SELECT a.created_at, a.correct FROM attempts a JOIN exercises e ON e.id=a.exercise_id
                WHERE a.user_id=? AND a.created_at>=? AND e.subject IN ({marks})""", (user_id, since, *subs)
        ).fetchall()
    return [(parse_ts(r["created_at"]).date(), r["correct"]) for r in rows]


def streak_and_today(db, user_id: int, subjects=None):
    items = attempt_days(db, user_id, subjects=subjects)
    days = {d for d, _ in items}
    t = today()
    count_today = sum(1 for d, _ in items if d == t)
    cursor = t if t in days else t - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak, count_today


# ---------------------------------------------------------------- områden att öva på

MIN_AREA_QUESTIONS = 5   # ett område erbjuds om det har minst så många vanliga frågor (eller en generator)


def subject_areas(db, subject: str) -> list:
    """Områden eleven kan välja i ett ämne: [{"name", "n"}], i fast ordning."""
    count, has_gen = {}, set()
    for r in db.execute("SELECT topic, generator FROM exercises WHERE subject=? AND active=1", (subject,)):
        a = areas.area_of(subject, r["topic"])
        count[a] = count.get(a, 0) + 1
        if r["generator"]:
            has_gen.add(a)
    return [{"name": a, "n": count[a]} for a in areas.order(subject)
            if a in count and (count[a] >= MIN_AREA_QUESTIONS or a in has_gen)]


def weakest_area(db, user_id: int, subject: str):
    """Området där eleven har lägst andel rätt (minst 5 svar), eller None."""
    offered = {a["name"] for a in subject_areas(db, subject)}
    tot = {}
    for r in db.execute(
        """SELECT e.topic, COUNT(*) AS n, SUM(a.correct) AS c FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? AND e.subject=? GROUP BY e.topic""", (user_id, subject)):
        a = areas.area_of(subject, r["topic"])
        n, c = tot.get(a, (0, 0))
        tot[a] = (n + r["n"], c + r["c"])
    ranked = sorted((c / n, n, a) for a, (n, c) in tot.items() if n >= 5 and a in offered)
    return ranked[0][2] if ranked else None


# ---------------------------------------------------------------- motivation: inställningar och dagsmål

def school_subjects(db) -> list:
    """Ämnen som räknas för dagsmål, poäng och märken: alla utom fritidsämnen som K-pop."""
    return [s for s in active_subjects(db) if s not in LEISURE_SUBJECTS]


def get_prefs(db, user_id: int, commit: bool = True) -> dict:
    """Elevens val av område/dagsmål/poäng/märken. Raden skapas första gången (och poängräkningen börjar då)."""
    if db.execute("INSERT OR IGNORE INTO user_prefs(user_id) VALUES (?)", (user_id,)).rowcount and commit:
        db.commit()
    r = db.execute("SELECT * FROM user_prefs WHERE user_id=?", (user_id,)).fetchone()
    return {"areas_on": bool(r["areas_on"]), "daily_goal": r["daily_goal"], "points_on": bool(r["points_on"]),
            "badges_on": bool(r["badges_on"]), "points_since": r["points_since"]}


def save_prefs(db, user_id: int, areas_on: bool, daily_goal: int, points_on: bool, badges_on: bool) -> None:
    get_prefs(db, user_id, commit=False)
    db.execute("UPDATE user_prefs SET areas_on=?, daily_goal=?, points_on=?, badges_on=? WHERE user_id=?",
               (1 if areas_on else 0, max(0, min(200, int(daily_goal))), 1 if points_on else 0,
                1 if badges_on else 0, user_id))


def answers_today(db, user_id: int, subjects) -> int:
    subs = list(subjects)
    if not subs:
        return 0
    start = datetime.combine(today(), dtime.min, TZ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    marks = ",".join("?" * len(subs))
    return db.execute(
        f"""SELECT COUNT(*) AS c FROM attempts a JOIN exercises e ON e.id=a.exercise_id
            WHERE a.user_id=? AND a.created_at>=? AND e.subject IN ({marks})""", (user_id, start, *subs)).fetchone()["c"]


def record_goal(db, user_id: int, subject: str) -> None:
    """Sparar att dagens mål är nått (anropas efter varje svar, i skolämnen)."""
    if subject in LEISURE_SUBJECTS:
        return
    goal = get_prefs(db, user_id, commit=False)["daily_goal"]
    if goal > 0 and answers_today(db, user_id, school_subjects(db)) >= goal:
        db.execute("INSERT OR IGNORE INTO goal_days(user_id, day) VALUES (?,?)", (user_id, today().isoformat()))


def day_runs(days) -> list:
    """Längder på sammanhängande dagar i en lista av 'ÅÅÅÅ-MM-DD' eller date."""
    ds = sorted({date.fromisoformat(d) if isinstance(d, str) else d for d in days})
    runs, run = [], 0
    for i, d in enumerate(ds):
        run = run + 1 if i and (d - ds[i - 1]).days == 1 else 1
        if i + 1 == len(ds) or (ds[i + 1] - d).days != 1:
            runs.append(run)
    return runs


def goal_status(db, user_id: int, prefs=None) -> dict:
    prefs = prefs or get_prefs(db, user_id)
    goal = prefs["daily_goal"]
    done = answers_today(db, user_id, school_subjects(db))
    days = {r["day"] for r in db.execute("SELECT day FROM goal_days WHERE user_id=?", (user_id,))}
    t = today()
    cursor = t if t.isoformat() in days else t - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= timedelta(days=1)
    return {"goal": goal, "done": done, "reached": goal > 0 and done >= goal, "streak": streak,
            "pct": min(100, round(100 * done / goal)) if goal else 0}


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


# ---------------------------------------------------------------- ämnesgrupper och ämnesval per elev

def group_subjects(subjects) -> list:
    """Delar in ämnen i grupper (i fast ordning). Varje grupp: {"key", "title", "subjects"}."""
    present = list(subjects)
    groups, used = [], set()
    for key, title, members in SUBJECT_GROUPS:
        got = [s for s in members if s in present]
        if got:
            groups.append({"key": key, "title": title, "subjects": got})
            used.update(got)
    rest = sorted(s for s in present if s not in used)
    if rest:
        groups.append({"key": OTHER_GROUP[0], "title": OTHER_GROUP[1], "subjects": rest})
    return groups


def ordered_subjects(subjects) -> list:
    return [s for g in group_subjects(subjects) for s in g["subjects"]]


def subject_settings(db, user_id: int, subjects=None) -> dict:
    """Ämne -> {"enabled", "in_report"} för en elev. Saknas en sparad rad gäller standardvärdet."""
    subs = list(subjects) if subjects is not None else active_subjects(db)
    stored = {r["subject"]: r for r in db.execute(
        "SELECT subject, enabled, in_report FROM user_subjects WHERE user_id=?", (user_id,))}
    out = {}
    for s in subs:
        r = stored.get(s)
        out[s] = {"enabled": bool(r["enabled"]) if r else True,
                  "in_report": bool(r["in_report"]) if r else s not in LEISURE_SUBJECTS}
    return out


def subject_enabled(db, user_id: int, subject: str) -> bool:
    r = db.execute("SELECT enabled FROM user_subjects WHERE user_id=? AND subject=?", (user_id, subject)).fetchone()
    return bool(r["enabled"]) if r else True


def enabled_subjects(db, user_id: int) -> list:
    """De ämnen eleven får se och öva i, i gruppordning."""
    settings = subject_settings(db, user_id)
    return ordered_subjects(s for s, v in settings.items() if v["enabled"])


def report_subjects(db, user_id: int) -> list:
    """De ämnen som tas med i elevens rapport som standard."""
    settings = subject_settings(db, user_id)
    return ordered_subjects(s for s, v in settings.items() if v["in_report"])


def save_subject_settings(db, user_id: int, enabled, in_report, subjects) -> None:
    """Sparar ämnesval för alla `subjects`: de som finns i `enabled`/`in_report` slås på, övriga av."""
    enabled, in_report = set(enabled), set(in_report)
    for s in subjects:
        db.execute("INSERT OR REPLACE INTO user_subjects (user_id, subject, enabled, in_report) VALUES (?,?,?,?)",
                   (user_id, s, int(s in enabled), int(s in in_report)))


# ---------------------------------------------------------------- import

LEGACY_SUBJECTS = {
    "no": ("biologi", "fysik", "kemi", "teknik"),
    "so": ("geografi", "historia", "religionskunskap", "samhallskunskap"),
}


# En kvarvarande övning i no/so kan flyttas till vilket som helst av de åtta skolämnena (vattnets kretslopp
# kan till exempel höra hemma i geografi även om det låg i "no").
LEGACY_TARGETS = tuple(s for group in LEGACY_SUBJECTS.values() for s in group)


def adopt_legacy_exercises(db, data) -> int:
    """Flyttar gamla övningar i samlingsämnena no/so till rätt enskilt ämne (matchat på frågetexten),
    så att historik och svar följer med. Anropas före import av startmaterialet."""
    items = data if isinstance(data, list) else (data.get("exercises", []) if isinstance(data, dict) else [])
    moved = 0
    for d in items:
        if not isinstance(d, dict) or not d.get("question"):
            continue
        new = d.get("subject")
        if new not in [s for group in LEGACY_SUBJECTS.values() for s in group]:
            continue
        old = "no" if new in LEGACY_SUBJECTS["no"] else "so"
        cur = db.execute("UPDATE exercises SET subject=?, topic=? WHERE subject=? AND question=?",
                         (new, str(d.get("topic", ""))[:60] or "Övrigt", old, d["question"]))
        moved += cur.rowcount
    return moved


def migrate_legacy_levels(db) -> None:
    """Elevens nivå i no/so kopieras till de nya ämnena (befintliga nivåer rörs inte) och de gamla raderas.

    Görs först när det gamla ämnet inte längre har några aktiva övningar. Finns det kvar egna övningar i
    no/so visas ämnet fortfarande för eleven, och då ska nivån ligga kvar orörd – annars börjar eleven om med
    det inledande provet efter varje omstart av appen, och ett prov i det gamla ämnet skulle dessutom tyst
    sätta nivå i alla nya ämnen."""
    for old, news in LEGACY_SUBJECTS.items():
        if db.execute("SELECT 1 FROM exercises WHERE subject=? AND active=1 LIMIT 1", (old,)).fetchone():
            continue
        for r in db.execute("SELECT user_id, level FROM user_levels WHERE subject=?", (old,)).fetchall():
            for sub in news:
                db.execute("INSERT OR IGNORE INTO user_levels(user_id, subject, level, since_attempt_id) "
                           "SELECT ?, ?, ?, COALESCE(MAX(id), 0) FROM attempts WHERE user_id=?",
                           (r["user_id"], sub, r["level"], r["user_id"]))
        db.execute("DELETE FROM user_levels WHERE subject=?", (old,))


def move_legacy_exercise(db, ex_id: int, new_subject: str) -> str:
    """Flyttar en kvarvarande övning i no/so till ett av skolämnena i LEGACY_TARGETS. Returnerar "" om det gick, annars ett
    felmeddelande. Historik och svar följer med eftersom övningen behåller sitt id. När det gamla ämnet blir
    tomt flyttas elevernas nivåer över direkt (se migrate_legacy_levels)."""
    ex = db.execute("SELECT id, subject, question FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not ex:
        return "Övningen finns inte."
    if ex["subject"] not in LEGACY_SUBJECTS or new_subject not in LEGACY_TARGETS:
        return "Den övningen kan inte flyttas dit."
    if db.execute("SELECT 1 FROM exercises WHERE subject=? AND question=?", (new_subject, ex["question"])).fetchone():
        return f"Det finns redan en likadan fråga i {label(new_subject)}."
    db.execute("UPDATE exercises SET subject=? WHERE id=?", (new_subject, ex_id))
    migrate_legacy_levels(db)
    return ""


MEDIA_NAME = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


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
    image = d.get("image")
    if image:
        image = str(image).strip()
        if not MEDIA_NAME.match(image):
            return None, "image måste vara ett filnamn (bokstäver, siffror, punkt, bindestreck, understreck)"
    diagram = d.get("diagram")
    if diagram:
        err = diagrams.validate(diagram)
        if err:
            return None, err
    return {
        "subject": subject, "topic": topic, "level": level, "type": typ, "question": question,
        "options": json.dumps(options, ensure_ascii=False) if options else None,
        "answers": json.dumps(answers, ensure_ascii=False),
        "explanation": str(d.get("explanation", "")).strip(),
        "image": image or None,
        "diagram": json.dumps(diagram, ensure_ascii=False) if diagram else None,
    }, None


def import_bundle(db, data) -> dict:
    """Importerar en lista med övningar, eller ett objekt med {"exercises": [...], "words": [...]}."""
    from .words import import_words
    if isinstance(data, dict):
        res = import_exercises(db, data.get("exercises", []))
        w = import_words(db, data.get("words", []))
    else:
        res = import_exercises(db, data)
        w = {"added": 0, "skipped": 0, "errors": []}
    res["words_added"], res["words_skipped"] = w["added"], w["skipped"]
    res["errors"] = res["errors"] + w["errors"]
    return res


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
            """INSERT OR IGNORE INTO exercises(subject, topic, level, type, question, options, answers, explanation,
                                              image, diagram)
               VALUES (:subject, :topic, :level, :type, :question, :options, :answers, :explanation, :image, :diagram)""",
            row,
        )
        if cur.rowcount:
            added += 1
        else:
            skipped += 1
    db.commit()
    return {"added": added, "skipped": skipped, "errors": errors}
