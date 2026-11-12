"""Öva på det jag missat: eleven repeterar frågor hon svarat fel på, tills hon klarar dem.

En övning räknas som missad när elevens senaste svar på den var fel (i övning eller prov). Att svara rätt på den
tar bort den från listan, att svara fel igen lämnar den kvar. En genererad övning (med slumptal) kommer tillbaka
som en ny uppgift av samma sort, eftersom det är sättet att räkna som ska sitta och inte just de talen.
Samma fråga kommer inte direkt efter att den besvarats, så att eleven inte bara svarar på det hon nyss såg."""
import random

from . import logic

GAP = 3          # så många andra frågor ska helst komma emellan innan en fråga kommer tillbaka


def missed_items(db, user_id: int, subject: str = "") -> list:
    """Missade övningar i de ämnen eleven har påslagna, äldsta missen först."""
    subjects = set(logic.enabled_subjects(db, user_id))
    if subject:
        subjects &= {subject}
    if not subjects:
        return []
    rows = db.execute(
        """SELECT e.id, e.subject, e.topic, e.level, e.generator, a.id AS attempt_id
           FROM exercises e JOIN attempts a ON a.exercise_id = e.id
           WHERE a.user_id=? AND e.active=1 AND a.correct=0
             AND a.id = (SELECT MAX(id) FROM attempts WHERE user_id=a.user_id AND exercise_id=e.id)
           ORDER BY a.id""", (user_id,)).fetchall()
    return [r for r in rows if r["subject"] in subjects]


def counts(db, user_id: int) -> dict:
    """{ämne: antal missade} för de ämnen som har några."""
    out = {}
    for r in missed_items(db, user_id):
        out[r["subject"]] = out.get(r["subject"], 0) + 1
    return out


def next_missed(db, user_id: int, subject: str = "") -> dict:
    """Nästa fråga att repetera. Svarar {"item", "remaining", "paused"}:
    remaining = hur många som är kvar att klara, paused = det finns kvar men inget som inte nyss besvarats."""
    items = missed_items(db, user_id, subject)
    remaining = len(items)
    if not remaining:
        return {"item": None, "remaining": 0, "paused": False}
    gap = max(1, min(GAP, remaining - 1))
    recent = {r["exercise_id"] for r in db.execute(
        "SELECT exercise_id FROM attempts WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, gap))}
    eligible = [r for r in items if r["id"] not in recent]
    random.shuffle(eligible)
    for r in eligible:
        item = logic.present(db, logic.exercise_row(db, r["id"]), user_id)
        if item:
            return {"item": item, "remaining": remaining, "paused": False}
    return {"item": None, "remaining": remaining, "paused": True}
