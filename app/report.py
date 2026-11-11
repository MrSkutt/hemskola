"""PDF-rapport för en elev: sammanfattning, nivåer, prov och områden att öva på."""
import io
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import logic

GREEN = colors.HexColor("#2f7d57")
RED = colors.HexColor("#c0504d")
GREY = colors.HexColor("#666666")
LIGHT = colors.HexColor("#e9efe9")
PERIODS = {7: "senaste 7 dagarna", 30: "senaste 30 dagarna", 90: "senaste 90 dagarna", 0: "hela tiden"}
MIN_TOPIC_ANSWERS = 3


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=20, leading=24, textColor=GREEN, alignment=0, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=14, spaceBefore=12, spaceAfter=4, textColor=GREEN),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=10.5, spaceBefore=6, spaceAfter=2),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontSize=10, leading=13),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=8.5, leading=11, textColor=GREY),
        "cell": ParagraphStyle("c", parent=base["BodyText"], fontSize=9, leading=11),
    }


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def _since(days: int) -> str:
    if not days:
        return "1970-01-01 00:00:00"
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def collect(db, student, days: int) -> dict:
    uid = student["id"]
    since = _since(days)
    rows = db.execute(
        """SELECT a.created_at, a.correct, a.given, e.subject, e.topic, e.level, a.test_id,
                  COALESCE(g.question, e.question) AS question, COALESCE(g.answers, e.answers) AS answers
           FROM attempts a JOIN exercises e ON e.id=a.exercise_id LEFT JOIN generated g ON g.id=a.generated_id
           WHERE a.user_id=? AND a.created_at>=? ORDER BY a.id""", (uid, since)).fetchall()
    subjects = []
    for sub in logic.active_subjects(db):
        mine = [r for r in rows if r["subject"] == sub]
        level = logic.get_level(db, uid, sub)
        if not mine and not level:
            continue
        topics = {}
        for r in mine:
            t = topics.setdefault(r["topic"], [0, 0])
            t[0] += 1
            t[1] += r["correct"]
        topic_list = sorted(({"topic": k, "n": v[0], "pct": round(100 * v[1] / v[0])} for k, v in topics.items()),
                            key=lambda x: (x["pct"], -x["n"]))
        missed = [r for r in reversed(mine) if not r["correct"]]
        tests = db.execute(
            "SELECT * FROM tests WHERE user_id=? AND subject=? AND finished_at IS NOT NULL AND finished_at>=? ORDER BY id",
            (uid, sub, since)).fetchall()
        subjects.append({
            "subject": sub, "level": level, "n": len(mine), "correct": sum(r["correct"] for r in mine),
            "topics": topic_list, "missed": missed, "tests": tests,
        })
    streak, _ = logic.streak_and_today(db, uid)
    day_set = {logic.parse_ts(r["created_at"]).date() for r in rows}
    return {"rows": rows, "subjects": subjects, "streak": streak, "active_days": len(day_set), "days": days,
            "first_day": min(day_set) if day_set else None}


def _activity_chart(rows, days, width, height=90):
    today = logic.today()
    if days == 0 or days > 31:
        weeks = 13
        if days == 0 and rows:
            first = min(logic.parse_ts(r["created_at"]).date() for r in rows)
            weeks = max(4, min(26, (today - first).days // 7 + 2))
        start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
        buckets = [[start + timedelta(weeks=i), 0, 0] for i in range(weeks)]
        for r in rows:
            d = logic.parse_ts(r["created_at"]).date()
            i = (d - start).days // 7
            if 0 <= i < weeks:
                buckets[i][1] += 1
                buckets[i][2] += r["correct"]
        caption = "Svar per vecka"
    else:
        n = days
        buckets = [[today - timedelta(days=n - 1 - i), 0, 0] for i in range(n)]
        for r in rows:
            d = logic.parse_ts(r["created_at"]).date()
            i = (d - buckets[0][0]).days
            if 0 <= i < n:
                buckets[i][1] += 1
                buckets[i][2] += r["correct"]
        caption = "Svar per dag"
    peak = max([b[1] for b in buckets] + [1])
    d = Drawing(width, height + 22)
    left, bottom, top = 22, 16, height
    d.add(Line(left, bottom, width, bottom, strokeColor=colors.lightgrey))
    d.add(String(0, bottom + top - 8, str(peak), fontSize=7, fillColor=GREY))
    step = (width - left) / len(buckets)
    for i, (day, total, right) in enumerate(buckets):
        x = left + i * step + step * 0.12
        w = step * 0.76
        h_total = (total / peak) * (top - 10)
        h_right = (right / peak) * (top - 10)
        if total:
            d.add(Rect(x, bottom, w, h_total, fillColor=RED, strokeColor=None))
            d.add(Rect(x, bottom, w, h_right, fillColor=GREEN, strokeColor=None))
        weekly = days == 0 or days > 31
        if len(buckets) <= 14 or i % (3 if weekly else 5) == 0:
            d.add(String(x + w / 2, 5, day.strftime("%d/%m") if weekly else str(day.day),
                         fontSize=6.5, fillColor=GREY, textAnchor="middle"))
    return caption, d


def build_pdf(db, student, days: int = 30) -> bytes:
    data = collect(db, student, days)
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Rapport {student['display_name']}",
                            author="Hemskola")
    width = A4[0] - 36 * mm
    story = [_p("Hemskola – rapport", st["title"]),
             _p(f"{student['display_name']} · {PERIODS[days]} · skapad {logic.today().isoformat()}", st["p"]),
             Spacer(1, 6)]

    rows = data["rows"]
    total = len(rows)
    right = sum(r["correct"] for r in rows)
    pct = f"{round(100 * right / total)} %" if total else "–"
    box = Table([[ _p("Besvarade frågor", st["small"]), _p("Andel rätt", st["small"]),
                   _p("Dagar med övning", st["small"]), _p("Dagar i rad nu", st["small"])],
                 [_p(total, st["title"]), _p(pct, st["title"]), _p(data["active_days"], st["title"]),
                  _p(data["streak"], st["title"])]], colWidths=[width / 4] * 4)
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [box, Spacer(1, 8)]

    if total:
        caption, chart = _activity_chart(rows, days, width)
        story += [KeepTogether([_p(f"{caption} (grönt = rätt, rött = fel)", st["h3"]), chart])]
    else:
        story.append(_p("Inga besvarade frågor under perioden.", st["p"]))

    story.append(_p("Så läser du rapporten", st["h3"]))
    story.append(_p("Nivåerna 1–5 är en grov uppskattning av var eleven ligger i varje ämne, där 1 ungefär motsvarar åk 4–5 och 5 åk 9. "
                    "De är beräknade från elevens svar i övningsprogrammet och är inget betyg.", st["small"]))

    for s in data["subjects"]:
        label = logic.label(s["subject"])
        acc = f"{round(100 * s['correct'] / s['n'])} %" if s["n"] else "–"
        level = (f"Nivå {s['level']} av 5 ({logic.LEVEL_HINTS[s['level']]})." if s["level"]
                 else "Ännu inte nivåtestad.")
        block = [_p(label, st["h2"]), _p(f"{level} Under perioden: {s['n']} svar, {acc} rätt.", st["p"])]
        if s["tests"]:
            t = [[_p(h, st["small"]) for h in ("Datum", "Prov", "Resultat", "Uppskattad nivå")]]
            for x in s["tests"]:
                t.append([_p(logic.parse_ts(x["finished_at"]).strftime("%Y-%m-%d"), st["cell"]),
                          _p("Inledande" if x["kind"] == "placement" else "Statusprov", st["cell"]),
                          _p(f"{x['score']} av {x['total']}", st["cell"]), _p(x["estimated_level"], st["cell"])])
            tb = Table(t, colWidths=[width * .22, width * .28, width * .25, width * .25], hAlign="LEFT")
            tb.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), .5, colors.grey), ("TOPPADDING", (0, 0), (-1, -1), 2),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
            block += [_p("Prov", st["h3"]), tb]
        weak = [x for x in s["topics"] if x["n"] >= MIN_TOPIC_ANSWERS and x["pct"] < 70]
        strong = [x for x in reversed(s["topics"]) if x["n"] >= MIN_TOPIC_ANSWERS and x["pct"] >= 80]
        if weak:
            block += [_p("Behöver öva mer på", st["h3"]),
                      _p("; ".join(f"{x['topic']} ({x['pct']} % rätt av {x['n']} svar)" for x in weak[:6]), st["p"])]
        elif s["n"] >= MIN_TOPIC_ANSWERS:
            block += [_p("Behöver öva mer på", st["h3"]), _p("Inga tydliga svaga områden under perioden.", st["p"])]
        if strong:
            block += [_p("Går bra", st["h3"]), _p("; ".join(f"{x['topic']} ({x['pct']} %)" for x in strong[:6]), st["p"])]
        if s["missed"]:
            seen, items = set(), []
            for r in s["missed"]:
                q = " ".join(str(r["question"]).split())
                if q in seen:
                    continue
                seen.add(q)
                try:
                    import json
                    ans = json.loads(r["answers"])[0]
                except Exception:
                    ans = "?"
                items.append(f"{q[:140]} → rätt svar: {ans} (elevens svar: {r['given'][:40]})")
                if len(items) >= 5:
                    break
            block += [_p("Exempel på senaste felsvar", st["h3"])] + [_p("• " + i, st["cell"]) for i in items]
        story.append(KeepTogether(block[:3]))
        story += block[3:]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 9 * mm, f"Hemskola · {student['display_name']} · {PERIODS[days]}")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"Sida {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
