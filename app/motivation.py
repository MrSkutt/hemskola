"""Poäng, märken och belöningar. Poäng och märken räknas ut från elevens svar, bara belöningarna lagras."""
from collections import Counter

from . import logic, tasks

POINTS_PER_CORRECT = 10    # per rätt svar i övning (inte i prov) i ett skolämne
CAP_PER_SUBJECT_DAY = 15   # så många rätta svar per ämne och dag ger poäng, så att man inte kan "pumpa" ett ämne
GOAL_BONUS = 20            # en gång per dag då dagsmålet nås
WEEK_BONUS = 50            # för varje 7 dagar i rad med nått dagsmål
LEVEL_BONUS = 50           # när eleven själv tar sig upp en nivå (en gång per ämne och nivå)
MAX_REQUEST_QTY = 20       # så många av en belöning kan eleven be om i taget

RULES = [
    (f"{POINTS_PER_CORRECT} poäng", f"för varje rätt svar när du övar, upp till {CAP_PER_SUBJECT_DAY} rätta per ämne och dag"),
    (f"{GOAL_BONUS} poäng", "bonus varje dag du når dagsmålet"),
    (f"{WEEK_BONUS} poäng", "bonus för varje vecka (7 dagar i rad) med nått dagsmål"),
    (f"{LEVEL_BONUS} poäng", "bonus varje gång du tar dig upp en nivå"),
    ("Uppgifter", "poängen står på uppgiften och du får dem när admin har godkänt den"),
]


def _marks(items) -> str:
    return ",".join("?" * len(items))


# ---------------------------------------------------------------- poäng

def points(db, user_id: int, prefs=None) -> dict:
    prefs = prefs or logic.get_prefs(db, user_id)
    since = prefs["points_since"]
    subs = logic.school_subjects(db)
    per = Counter()
    if subs:
        for r in db.execute(
            f"""SELECT a.created_at, e.subject FROM attempts a JOIN exercises e ON e.id=a.exercise_id
                WHERE a.user_id=? AND a.correct=1 AND a.test_id IS NULL AND a.created_at>=?
                AND e.subject IN ({_marks(subs)})""", (user_id, since, *subs)):
            per[(r["subject"], logic.parse_ts(r["created_at"]).date())] += 1
    answer_pts = sum(min(n, CAP_PER_SUBJECT_DAY) for n in per.values()) * POINTS_PER_CORRECT
    since_day = logic.parse_ts(since).date().isoformat()
    days = [r["day"] for r in db.execute("SELECT day FROM goal_days WHERE user_id=? AND day>=?", (user_id, since_day))]
    goal_pts = len(days) * GOAL_BONUS
    week_pts = sum(run // 7 for run in logic.day_runs(days)) * WEEK_BONUS
    level_pts = db.execute("SELECT COUNT(*) AS c FROM level_ups WHERE user_id=? AND created_at>=?",
                           (user_id, since)).fetchone()["c"] * LEVEL_BONUS
    task_pts = tasks.task_points(db, user_id, since)
    total = answer_pts + goal_pts + week_pts + level_pts + task_pts
    spent = db.execute("SELECT COALESCE(SUM(cost * times_given), 0) AS s FROM rewards WHERE user_id=?",
                       (user_id,)).fetchone()["s"]   # inklusive borttagna (retired) belöningar som redan delats ut
    balance = max(0, total - spent)
    reserved = reserved_points(db, user_id)
    return {"answers": answer_pts, "goal": goal_pts, "week": week_pts, "levels": level_pts,
            "tasks": task_pts, "total": total, "spent": spent, "balance": balance,
            "reserved": reserved, "available": max(0, balance - reserved)}


# ---------------------------------------------------------------- belöningar

def reserved_points(db, user_id: int) -> int:
    """Poäng som är reserverade av förfrågningar som väntar på admin. De dras först när admin godkänner."""
    return db.execute(
        "SELECT COALESCE(SUM(r.cost * q.quantity), 0) AS s FROM reward_requests q JOIN rewards r ON r.id=q.reward_id "
        "WHERE q.user_id=? AND q.status='pending' AND r.retired=0", (user_id,)).fetchone()["s"]


def reward_list(db, user_id: int, balance: int) -> list:
    """Elevens belöningar. `balance` är de poäng som jämförs med priset: admin ser de riktiga poängen, eleven de poäng som
    är kvar efter reserverade förfrågningar. En engångsbelöning är "given" när den delats ut. En belöning som kan tas
    ut flera gånger är aldrig "given", utan kan delas ut igen (times_given visar hur många gånger).
    `pending` är antalet som eleven bett om och som väntar på admin (`request_id` är förfrågan), `can_request` om hon kan
    be om den nu och `max_qty` hur många hon i så fall kan be om."""
    pend = {r["reward_id"]: r for r in db.execute(
        "SELECT id, reward_id, quantity FROM reward_requests WHERE user_id=? AND status='pending'", (user_id,))}
    out = []
    for r in db.execute(
            "SELECT * FROM rewards WHERE user_id=? AND retired=0 "
            "ORDER BY (repeatable=0 AND times_given>0), cost, id", (user_id,)):
        given = not r["repeatable"] and r["times_given"] > 0
        req = pend.get(r["id"])
        ready = not given and balance >= r["cost"]
        can_request = ready and (bool(r["repeatable"]) or req is None)
        out.append({
            "id": r["id"], "title": r["title"], "cost": r["cost"], "given": given, "given_at": r["given_at"],
            "repeatable": bool(r["repeatable"]), "times_given": r["times_given"],
            "ready": ready,
            "missing": 0 if given else max(0, r["cost"] - balance),
            "pct": 100 if given else min(100, round(100 * balance / r["cost"])),
            "pending": req["quantity"] if req else 0, "request_id": req["id"] if req else None,
            "can_request": can_request,
            "max_qty": max(1, min(MAX_REQUEST_QTY, balance // r["cost"])) if r["repeatable"] else 1,
        })
    return out


def next_reward(rewards: list):
    """Närmaste belöning eleven inte fått än (den billigaste), eller None. Belöningar som kan tas ut flera gånger
    räknas alltid som något eleven kan sikta mot."""
    open_ = [r for r in rewards if not r["given"]]
    return open_[0] if open_ else None


def add_reward(db, user_id: int, title: str, cost, repeatable=False) -> str:
    """Returnerar ett felmeddelande, eller '' om belöningen lades till."""
    title = " ".join(str(title).split())[:80]
    try:
        cost = int(cost)
    except (TypeError, ValueError):
        return "Poängen måste vara ett heltal."
    if not title:
        return "Skriv vad belöningen är."
    if not 1 <= cost <= 100000:
        return "Poängen ska vara mellan 1 och 100 000."
    db.execute("INSERT INTO rewards(user_id, title, cost, repeatable) VALUES (?,?,?,?)",
               (user_id, title, cost, 1 if repeatable else 0))
    return ""


def give_reward(db, user_id: int, reward_id: int) -> str:
    r = db.execute("SELECT * FROM rewards WHERE id=? AND user_id=? AND retired=0", (reward_id, user_id)).fetchone()
    if not r:
        return "Belöningen finns inte."
    if not r["repeatable"] and r["times_given"] > 0:
        return "Den är redan utdelad."
    if points(db, user_id)["balance"] < r["cost"]:
        return "Eleven har inte tillräckligt med poäng än."
    db.execute("UPDATE rewards SET times_given = times_given + 1, given_at=datetime('now') WHERE id=?", (reward_id,))
    if not r["repeatable"]:   # delar admin ut en engångsbelöning direkt är en väntande förfrågan på den därmed hanterad
        db.execute("UPDATE reward_requests SET status='approved', handled_at=datetime('now') "
                   "WHERE reward_id=? AND status='pending'", (reward_id,))
    return ""


def undo_reward(db, user_id: int, reward_id: int) -> None:
    """Ångrar den senaste utdelningen (poängen för den ges tillbaka)."""
    db.execute("UPDATE rewards SET times_given = times_given - 1, "
               "given_at = CASE WHEN times_given - 1 <= 0 THEN NULL ELSE given_at END "
               "WHERE id=? AND user_id=? AND times_given > 0 AND retired=0", (reward_id, user_id))


def delete_reward(db, user_id: int, reward_id: int) -> int:
    """Tar bort en belöning. Har den delats ut döljs den i stället för att raderas, så att poängen som redan
    använts på den fortsätter dras av (annars skulle borttagningen ge tillbaka poängen). Returnerar de poäng som
    fortfarande räknas som använda på den, eller 0 om den raderades helt."""
    r = db.execute("SELECT cost, times_given FROM rewards WHERE id=? AND user_id=? AND retired=0",
                   (reward_id, user_id)).fetchone()
    if not r:
        return 0
    if r["times_given"] > 0:
        db.execute("UPDATE rewards SET retired=1 WHERE id=?", (reward_id,))
        db.execute("UPDATE reward_requests SET status='declined', handled_at=datetime('now') "
                   "WHERE reward_id=? AND status='pending'", (reward_id,))
        return r["cost"] * r["times_given"]
    db.execute("DELETE FROM rewards WHERE id=?", (reward_id,))
    return 0


def request_reward(db, user_id: int, reward_id: int, quantity=1) -> str:
    """Eleven ber om en belöning (för en som kan tas ut flera gånger: ett antal). Poängen reserveras tills admin
    hanterat förfrågan. Returnerar ett felmeddelande, eller '' om det gick."""
    r = db.execute("SELECT * FROM rewards WHERE id=? AND user_id=? AND retired=0", (reward_id, user_id)).fetchone()
    if not r:
        return "Belöningen finns inte."
    if not r["repeatable"]:
        quantity = 1
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return "Antalet måste vara ett heltal."
    if not 1 <= quantity <= MAX_REQUEST_QTY:
        return f"Du kan be om mellan 1 och {MAX_REQUEST_QTY} åt gången."
    if not r["repeatable"] and r["times_given"] > 0:
        return "Du har redan fått den."
    pending = db.execute("SELECT id FROM reward_requests WHERE reward_id=? AND user_id=? AND status='pending'",
                         (reward_id, user_id)).fetchone()
    if pending and not r["repeatable"]:
        return "Du har redan bett om den. Admin tittar på det."
    available = points(db, user_id)["available"]
    if available < r["cost"] * quantity:
        can = available // r["cost"]
        return ("Du har inte tillräckligt med poäng för det." +
                (f" Just nu räcker de till {can} st." if can and r["repeatable"] else ""))
    if pending:   # fler av samma belöning läggs på den förfrågan som redan väntar
        db.execute("UPDATE reward_requests SET quantity = quantity + ? WHERE id=?", (quantity, pending["id"]))
    else:
        db.execute("INSERT INTO reward_requests(reward_id, user_id, quantity) VALUES (?,?,?)",
                   (reward_id, user_id, quantity))
    return ""


def cancel_request(db, user_id: int, request_id: int) -> str:
    """Eleven tar tillbaka en förfrågan som väntar. Poängen blir tillgängliga igen."""
    cur = db.execute("DELETE FROM reward_requests WHERE id=? AND user_id=? AND status='pending'", (request_id, user_id))
    return "" if cur.rowcount else "Förfrågan finns inte eller är redan hanterad."


def pending_requests(db) -> list:
    """Förfrågningar som väntar på admin, äldst först, med elevens riktiga poängsaldo."""
    out, balances = [], {}
    for q in db.execute(
            """SELECT q.id, q.user_id, q.quantity, q.created_at, r.id AS reward_id, r.title, r.cost, r.repeatable,
                      u.display_name AS student
               FROM reward_requests q JOIN rewards r ON r.id=q.reward_id JOIN users u ON u.id=q.user_id
               WHERE q.status='pending' AND r.retired=0 ORDER BY q.created_at, q.id"""):
        if q["user_id"] not in balances:
            balances[q["user_id"]] = points(db, q["user_id"])["balance"]
        total = q["cost"] * q["quantity"]
        out.append({**dict(q), "total": total, "balance": balances[q["user_id"]],
                    "enough": balances[q["user_id"]] >= total})
    return out


def pending_count(db) -> int:
    return db.execute("SELECT COUNT(*) AS c FROM reward_requests q JOIN rewards r ON r.id=q.reward_id "
                      "WHERE q.status='pending' AND r.retired=0").fetchone()["c"]


def approve_request(db, request_id: int) -> str:
    """Admin godkänner: belöningen delas ut och poängen dras på riktigt. Returnerar ett felmeddelande eller ''."""
    q = db.execute(
        """SELECT q.id, q.user_id, q.quantity, q.status, r.id AS reward_id, r.cost, r.repeatable, r.times_given, r.retired
           FROM reward_requests q JOIN rewards r ON r.id=q.reward_id WHERE q.id=?""", (request_id,)).fetchone()
    if not q or q["status"] != "pending" or q["retired"]:
        return "Förfrågan finns inte eller är redan hanterad."
    if not q["repeatable"] and q["times_given"] > 0:
        return "Belöningen är redan utdelad. Avslå förfrågan om den inte behövs."
    total = q["cost"] * q["quantity"]
    balance = points(db, q["user_id"])["balance"]
    if balance < total:
        return f"Eleven har inte tillräckligt med poäng längre ({balance} av {total}). Avslå förfrågan eller vänta."
    db.execute("UPDATE rewards SET times_given = times_given + ?, given_at=datetime('now') WHERE id=?",
               (q["quantity"], q["reward_id"]))
    db.execute("UPDATE reward_requests SET status='approved', handled_at=datetime('now') WHERE id=?", (request_id,))
    return ""


def decline_request(db, request_id: int) -> str:
    cur = db.execute("UPDATE reward_requests SET status='declined', handled_at=datetime('now') "
                     "WHERE id=? AND status='pending'", (request_id,))
    return "" if cur.rowcount else "Förfrågan finns inte eller är redan hanterad."


# ---------------------------------------------------------------- märken

def _longest(seq_runs) -> int:
    return max(seq_runs, default=0)


def stats(db, user_id: int) -> dict:
    subs = logic.school_subjects(db)
    if not subs:
        return {"answers": 0, "day_run": 0, "correct_run": 0, "goal_days": 0, "goal_run": 0, "subjects": 0,
                "max_level": 0, "level_ups": 0, "tests": 0, "perfect_tests": 0, "enabled": 0}
    m = _marks(subs)
    answers = db.execute(
        f"SELECT COUNT(*) AS c FROM attempts a JOIN exercises e ON e.id=a.exercise_id WHERE a.user_id=? "
        f"AND e.subject IN ({m})", (user_id, *subs)).fetchone()["c"]
    day_run = _longest(logic.day_runs({d for d, _ in logic.attempt_days(db, user_id, days=3650, subjects=subs)}))
    best = run = 0
    for r in db.execute(
        f"""SELECT a.correct FROM attempts a JOIN exercises e ON e.id=a.exercise_id
            WHERE a.user_id=? AND a.test_id IS NULL AND e.subject IN ({m}) ORDER BY a.id""", (user_id, *subs)):
        run = run + 1 if r["correct"] else 0
        best = max(best, run)
    goal_days = [r["day"] for r in db.execute("SELECT day FROM goal_days WHERE user_id=?", (user_id,))]
    seen = db.execute(
        f"""SELECT COUNT(DISTINCT e.subject) AS c FROM attempts a JOIN exercises e ON e.id=a.exercise_id
            WHERE a.user_id=? AND e.subject IN ({m})""", (user_id, *subs)).fetchone()["c"]
    max_level = db.execute(f"SELECT COALESCE(MAX(level), 0) AS l FROM user_levels WHERE user_id=? AND subject IN ({m})",
                           (user_id, *subs)).fetchone()["l"]
    level_ups = db.execute("SELECT COUNT(*) AS c FROM level_ups WHERE user_id=?", (user_id,)).fetchone()["c"]
    tests = db.execute(
        f"SELECT COUNT(*) AS c, COALESCE(SUM(CASE WHEN score = total AND total > 0 THEN 1 ELSE 0 END), 0) AS p "
        f"FROM tests WHERE user_id=? AND finished_at IS NOT NULL AND subject IN ({m})", (user_id, *subs)).fetchone()
    enabled = [s for s in logic.enabled_subjects(db, user_id) if s in subs]
    answered = {r["subject"] for r in db.execute(
        f"""SELECT DISTINCT e.subject FROM attempts a JOIN exercises e ON e.id=a.exercise_id
            WHERE a.user_id=? AND e.subject IN ({m})""", (user_id, *subs))}
    return {"answers": answers, "day_run": day_run, "correct_run": best, "goal_days": len(set(goal_days)),
            "goal_run": _longest(logic.day_runs(goal_days)), "subjects": seen, "max_level": max_level,
            "level_ups": level_ups, "tests": tests["c"], "perfect_tests": tests["p"], "enabled": len(enabled),
            "all_enabled_done": bool(enabled) and len(enabled) >= 3 and set(enabled) <= answered}


# (nyckel, symbol, namn, hur man får det, villkor)
BADGES = [
    ("forsta", "🌱", "Första steget", "Svara på din första fråga", lambda s: s["answers"] >= 1),
    ("svar100", "💯", "100 svar", "Svara på 100 frågor", lambda s: s["answers"] >= 100),
    ("svar500", "🚀", "500 svar", "Svara på 500 frågor", lambda s: s["answers"] >= 500),
    ("svar1000", "🏆", "1000 svar", "Svara på 1000 frågor", lambda s: s["answers"] >= 1000),
    ("rad3", "🔥", "3 dagar i rad", "Öva tre dagar i rad", lambda s: s["day_run"] >= 3),
    ("rad7", "🔥", "En hel vecka", "Öva sju dagar i rad", lambda s: s["day_run"] >= 7),
    ("rad30", "🌋", "30 dagar i rad", "Öva trettio dagar i rad", lambda s: s["day_run"] >= 30),
    ("mal1", "🎯", "Dagsmålet nått", "Nå dagsmålet en gång", lambda s: s["goal_days"] >= 1),
    ("mal10", "🎖️", "Målmedveten", "Nå dagsmålet tio dagar", lambda s: s["goal_days"] >= 10),
    ("malvecka", "📅", "Veckohjälte", "Nå dagsmålet sju dagar i rad", lambda s: s["goal_run"] >= 7),
    ("ratt5", "⚡", "5 rätt i rad", "Svara rätt på fem frågor i rad när du övar", lambda s: s["correct_run"] >= 5),
    ("ratt10", "✨", "10 rätt i rad", "Svara rätt på tio frågor i rad när du övar", lambda s: s["correct_run"] >= 10),
    ("utforskare", "🧭", "Utforskare", "Svara på frågor i fem olika ämnen", lambda s: s["subjects"] >= 5),
    ("allround", "🌍", "Allroundern", "Svara på frågor i alla dina ämnen", lambda s: s.get("all_enabled_done", False)),
    ("uppat", "⬆️", "Uppåt!", "Ta dig upp en nivå", lambda s: s["level_ups"] >= 1),
    ("niva4", "⭐", "Nivå 4", "Nå nivå 4 i något ämne", lambda s: s["max_level"] >= 4),
    ("niva5", "🌟", "Nivå 5", "Nå nivå 5 i något ämne", lambda s: s["max_level"] >= 5),
    ("prov1", "📝", "Första provet", "Gör ett prov", lambda s: s["tests"] >= 1),
    ("fullt", "🥇", "Fullt hus", "Få alla rätt på ett prov", lambda s: s["perfect_tests"] >= 1),
]


def badges(db, user_id: int) -> list:
    st = stats(db, user_id)
    return [{"key": k, "icon": icon, "title": title, "hint": hint, "earned": bool(test(st))}
            for k, icon, title, hint, test in BADGES]
