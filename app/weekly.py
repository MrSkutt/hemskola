"""Veckosammanfattning per elev för admins startsida: de senaste sju dagarna (inklusive idag) mot sju dagarna före."""
from datetime import datetime, time as dtime, timedelta, timezone

from . import logic, missed

DAYS = 7
WEAK_MIN_ANSWERS = 4      # ett område måste ha minst så många svar under veckan för att räknas som svagt
WEAK_MAX_PCT = 60         # och högst så stor andel rätt
WEAK_SHOWN = 3


def _utc(day) -> str:
    """Början av en lokal dag som UTC-tid i databasens format."""
    return datetime.combine(day, dtime.min, logic.TZ).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _rate(correct, n):
    return round(100 * correct / n) if n else None


def week_summary(db, student_id: int, days: int = DAYS) -> dict:
    t = logic.today()
    start, prev_start, end = t - timedelta(days=days - 1), t - timedelta(days=2 * days - 1), t + timedelta(days=1)
    rows = db.execute(
        """SELECT a.created_at, a.correct, e.subject, e.topic FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? AND a.created_at>=? AND a.created_at<?""",
        (student_id, _utc(prev_start), _utc(end))).fetchall()
    this_from = _utc(start)
    week = [r for r in rows if r["created_at"] >= this_from]
    before = [r for r in rows if r["created_at"] < this_from]

    by_subject, by_topic, day_set = {}, {}, set()
    for r in week:
        s = by_subject.setdefault(r["subject"], [0, 0])
        s[0] += 1
        s[1] += r["correct"]
        tp = by_topic.setdefault((r["subject"], r["topic"]), [0, 0])
        tp[0] += 1
        tp[1] += r["correct"]
        day_set.add(logic.parse_ts(r["created_at"]).date())
    subjects = sorted(({"subject": k, "n": v[0], "pct": _rate(v[1], v[0])} for k, v in by_subject.items()),
                      key=lambda x: (-x["n"], x["subject"]))
    weak = sorted(({"subject": s, "topic": tp, "n": v[0], "pct": _rate(v[1], v[0])}
                   for (s, tp), v in by_topic.items()
                   if s not in logic.LEISURE_SUBJECTS and v[0] >= WEAK_MIN_ANSWERS
                   and 100 * v[1] / v[0] <= WEAK_MAX_PCT),
                  key=lambda x: (x["pct"], -x["n"], x["subject"], x["topic"]))[:WEAK_SHOWN]

    level_ups = [{"subject": r["subject"], "level": r["level"]} for r in db.execute(
        "SELECT subject, level FROM level_ups WHERE user_id=? AND created_at>=? ORDER BY created_at, subject, level",
        (student_id, this_from))]
    tests = [{"subject": r["subject"], "kind": r["kind"], "score": r["score"], "total": r["total"]} for r in db.execute(
        "SELECT subject, kind, score, total FROM tests WHERE user_id=? AND finished_at>=? ORDER BY finished_at, id",
        (student_id, this_from))]

    row = db.execute("SELECT daily_goal FROM user_prefs WHERE user_id=?", (student_id,)).fetchone()
    goal = row["daily_goal"] if row else 0      # ingen rad än: eleven har inte börjat, och inget skapas av en vy
    goal_days = None
    if goal > 0:
        first, last = start.isoformat(), t.isoformat()
        goal_days = db.execute("SELECT COUNT(*) AS n FROM goal_days WHERE user_id=? AND day>=? AND day<=?",
                               (student_id, first, last)).fetchone()["n"]

    n, correct = len(week), sum(r["correct"] for r in week)
    prev_n = len(before)
    return {
        "days": days, "n": n, "pct": _rate(correct, n), "active_days": len(day_set),
        "prev_n": prev_n, "prev_pct": _rate(sum(r["correct"] for r in before), prev_n),
        "trend": (n > prev_n) - (n < prev_n),
        "subjects": subjects, "weak": weak, "level_ups": level_ups, "tests": tests,
        "goal": goal, "goal_days": goal_days,
        "missed": len(missed.missed_items(db, student_id)),
    }
