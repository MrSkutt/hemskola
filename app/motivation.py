"""Poäng, märken och belöningar. Poäng och märken räknas ut från elevens svar, bara belöningarna lagras."""
from collections import Counter

from . import logic, tasks

POINTS_PER_CORRECT = 10    # per rätt svar i övning (inte i prov) i ett skolämne
CAP_PER_SUBJECT_DAY = 15   # så många rätta svar per ämne och dag ger poäng, så att man inte kan "pumpa" ett ämne
GOAL_BONUS = 20            # en gång per dag då dagsmålet nås
WEEK_BONUS = 50            # för varje 7 dagar i rad med nått dagsmål
LEVEL_BONUS = 50           # när eleven själv tar sig upp en nivå (en gång per ämne och nivå)

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
    spent = db.execute("SELECT COALESCE(SUM(cost), 0) AS s FROM rewards WHERE user_id=? AND given_at IS NOT NULL",
                       (user_id,)).fetchone()["s"]
    return {"answers": answer_pts, "goal": goal_pts, "week": week_pts, "levels": level_pts,
            "tasks": task_pts, "total": total, "spent": spent, "balance": max(0, total - spent)}


# ---------------------------------------------------------------- belöningar

def reward_list(db, user_id: int, balance: int) -> list:
    out = []
    for r in db.execute(
            "SELECT * FROM rewards WHERE user_id=? ORDER BY given_at IS NOT NULL, cost, id", (user_id,)):
        given = r["given_at"] is not None
        out.append({
            "id": r["id"], "title": r["title"], "cost": r["cost"], "given": given, "given_at": r["given_at"],
            "ready": not given and balance >= r["cost"],
            "missing": 0 if given else max(0, r["cost"] - balance),
            "pct": 100 if given else min(100, round(100 * balance / r["cost"])),
        })
    return out


def next_reward(rewards: list):
    """Närmaste belöning eleven inte fått än (den billigaste), eller None."""
    open_ = [r for r in rewards if not r["given"]]
    return open_[0] if open_ else None


def add_reward(db, user_id: int, title: str, cost) -> str:
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
    db.execute("INSERT INTO rewards(user_id, title, cost) VALUES (?,?,?)", (user_id, title, cost))
    return ""


def give_reward(db, user_id: int, reward_id: int) -> str:
    r = db.execute("SELECT * FROM rewards WHERE id=? AND user_id=?", (reward_id, user_id)).fetchone()
    if not r:
        return "Belöningen finns inte."
    if r["given_at"]:
        return "Den är redan utdelad."
    if points(db, user_id)["balance"] < r["cost"]:
        return "Eleven har inte tillräckligt med poäng än."
    db.execute("UPDATE rewards SET given_at=datetime('now') WHERE id=?", (reward_id,))
    return ""


def undo_reward(db, user_id: int, reward_id: int) -> None:
    db.execute("UPDATE rewards SET given_at=NULL WHERE id=? AND user_id=?", (reward_id, user_id))


def delete_reward(db, user_id: int, reward_id: int) -> None:
    db.execute("DELETE FROM rewards WHERE id=? AND user_id=?", (reward_id, user_id))


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
