"""Utveckling över tid: andel rätt per vecka, för alla ämnen tillsammans och för varje ämne.

Veckorna är lokala (måndag–söndag) och numreras som i skolan. Den vecka som pågår är med, men den är inte slut än.
Veckor med få svar är osäkra: en vecka med två svar och båda rätt är inte 100 % kunnande, så de ritas som ringar.
Diagrammen är vanlig SVG som ritas på servern (ingen JavaScript), och färgerna kommer från temats CSS-variabler."""
from datetime import timedelta
from html import escape

from markupsafe import Markup

from . import logic

CHOICES = (8, 12, 26, 52)        # val av antal veckor bakåt
DEFAULT_WEEKS = 12
MIN_SHOWN = 4                    # minst så många veckor på axeln, även när eleven är ny
UNSURE_BELOW = 5                 # veckor med färre svar än så ritas som osäkra
COMPARE_MIN = 10                 # så många svar måste varje halva ha för att vi ska jämföra dem
FLAT_WITHIN = 3                  # skillnader mindre än så här (procentenheter) kallas "ungefär lika"


def week_start(day):
    return day - timedelta(days=day.weekday())


def clean_weeks(value) -> int:
    """Antal veckor från ett formulär eller en länk: bara de tillåtna värdena, annars standard."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WEEKS
    return value if value in CHOICES else DEFAULT_WEEKS


def _pct(correct, n):
    return round(100 * correct / n) if n else None


def _range_label(weeks, i, j):
    """'v40–v43' (eller 'v40' om det är en enda vecka) för vecka i till och med vecka j."""
    a, b = weeks[i]["label"], weeks[j]["label"]
    return a if a == b else f"{a}–{b}"


def _change(series, weeks):
    """Jämför första och sista halvan av perioden. None om någon halva har för få svar för att jämföra."""
    half = len(series) // 2
    if half == 0:
        return None
    first, last = series[:half], series[len(series) - half:]
    n1, n2 = sum(p["n"] for p in first), sum(p["n"] for p in last)
    if n1 < COMPARE_MIN or n2 < COMPARE_MIN:
        return None
    p1, p2 = _pct(sum(p["correct"] for p in first), n1), _pct(sum(p["correct"] for p in last), n2)
    diff = p2 - p1
    return {"first": p1, "last": p2, "diff": diff, "first_n": n1, "last_n": n2,
            "direction": 0 if abs(diff) < FLAT_WITHIN else (1 if diff > 0 else -1),
            "first_weeks": _range_label(weeks, 0, half - 1),
            "last_weeks": _range_label(weeks, len(series) - half, len(series) - 1)}


def _latest(series, weeks):
    """Den senaste veckan med tillräckligt många svar för att vara en riktig mätpunkt. Finns ingen sådan vecka tas den
    senaste veckan med några svar alls (och då är `unsure` sant). None om det inte finns några svar."""
    with_data = [i for i, p in enumerate(series) if p["n"]]
    if not with_data:
        return None
    reliable = [i for i in with_data if series[i]["n"] >= UNSURE_BELOW]
    i = (reliable or with_data)[-1]
    return {"index": i, "label": weeks[i]["label"], "pct": series[i]["pct"], "n": series[i]["n"],
            "current": weeks[i]["current"], "unsure": series[i]["n"] < UNSURE_BELOW}


def _tip(week, point):
    when = f"vecka {week['num']}, {week['start'].day}/{week['start'].month}"
    if not point["n"]:
        return f"{when}: inga svar"
    text = f"{when}: {point['pct']} % rätt ({point['correct']} av {point['n']} svar)"
    if point["n"] < UNSURE_BELOW:
        text += ", få svar så det är osäkert"
    if week["current"]:
        text += ", veckan pågår"
    return text


def _svg(name, series, weeks, *, big: bool, mark=None) -> Markup:
    """Ett linjediagram: andel rätt per vecka (0–100 %). Det stora diagrammet har dessutom staplar med antal svar."""
    W, H = (480, 232) if big else (300, 150)
    left, right, top = (54 if big else 36), 12, 14
    bottom = 24
    vol_h = 40 if big else 0
    gap = 10 if big else 0
    plot_h = H - top - bottom - vol_h - gap
    plot_w = W - left - right
    count = len(series)
    step = plot_w / count
    r = 4.5 if step > 16 else (3.5 if step > 9 else 2.8)

    def x(i):
        return left + step * (i + .5)

    def y(p):
        return top + plot_h * (1 - p / 100)

    out = [f'<svg class="trsvg{" big" if big else ""}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(name)}: andel rätt per vecka, '
           f'{escape(_range_label(weeks, 0, count - 1))}. Siffrorna finns i tabellen under diagrammet.">']
    for p in (0, 50, 100):
        out.append(f'<line class="tr-grid{" tr-axis" if p == 0 else ""}" x1="{left}" x2="{W - right}" y1="{y(p):.1f}" y2="{y(p):.1f}"/>')
        out.append(f'<text class="tr-text" x="{left - 6}" y="{y(p) + 4:.1f}" text-anchor="end">{p}{" %" if big else ""}</text>')

    # staplar med antal svar under diagrammet (bara det stora)
    if big:
        base = H - bottom
        peak = max(p["n"] for p in series) or 1
        out.append(f'<line class="tr-grid tr-axis" x1="{left}" x2="{W - right}" y1="{base}" y2="{base}"/>')
        out.append(f'<text class="tr-text" x="{left - 6}" y="{base}" text-anchor="end">svar</text>')
        bw = max(2.0, min(step * .6, 26))
        for i, pt in enumerate(series):
            if not pt["n"]:
                continue
            h = max(2.0, (vol_h - 13) * pt["n"] / peak)
            out.append(f'<rect class="tr-vol" x="{x(i) - bw / 2:.1f}" y="{base - h:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="1.5">'
                       f'<title>{escape(_tip(weeks[i], pt))}</title></rect>')
            if count <= 14:
                out.append(f'<text class="tr-num" x="{x(i):.1f}" y="{base - h - 3:.1f}" text-anchor="middle">{pt["n"]}</text>')

    # linjen: veckor utan svar bryter den, så att vi inte påstår något om dem. Stycken som rör en osäker vecka (få svar)
    # ritas streckade och svagare, så att en enstaka tur med två svar inte ser ut som ett ras eller ett lyft.
    for i in range(count - 1):
        a, b = series[i], series[i + 1]
        if a["n"] and b["n"]:
            low = " low" if min(a["n"], b["n"]) < UNSURE_BELOW else ""
            out.append(f'<line class="tr-seg{low}" x1="{x(i):.1f}" y1="{y(a["pct"]):.1f}" x2="{x(i + 1):.1f}" y2="{y(b["pct"]):.1f}"/>')

    for i, pt in enumerate(series):
        if pt["n"]:
            low = " low" if pt["n"] < UNSURE_BELOW else ""
            out.append(f'<circle class="tr-dot{low}" cx="{x(i):.1f}" cy="{y(pt["pct"]):.1f}" r="{r}">'
                       f'<title>{escape(_tip(weeks[i], pt))}</title></circle>')

    # värdet för den vecka som sammanfattningen ovanför diagrammet talar om skrivs ut vid punkten (bara i det stora)
    if big and mark is not None:
        py = y(series[mark]["pct"])
        below = py - 10 < top
        out.append(f'<text class="tr-value" x="{min(x(mark), W - right - 14):.1f}" y="{py + (19 if below else -9):.1f}" '
                   f'text-anchor="middle">{series[mark]["pct"]} %</text>')

    # veckonummer under axeln, så få att de får plats (räknat från sista veckan)
    every = -(-count // (10 if big else 6))
    for i in range(count):
        if (count - 1 - i) % every == 0:
            out.append(f'<text class="tr-text" x="{x(i):.1f}" y="{H - 7}" text-anchor="middle">{weeks[i]["label"]}</text>')
    out.append("</svg>")
    return Markup("".join(out))


def _entry(key, name, series, weeks, *, big=False):
    latest = _latest(series, weeks)
    return {"key": key, "label": name, "series": series, "n": sum(p["n"] for p in series),
            "change": _change(series, weeks), "latest": latest,
            "svg": _svg(name, series, weeks, big=big, mark=latest["index"] if latest else None)}


def build(db, student_id: int, subjects, counted=None, weeks: int = DEFAULT_WEEKS) -> dict:
    """Utveckling för en elev.

    subjects: de ämnen som får visas. counted: de av dem som räknas in i "Alla ämnen" (standard: alla).
    weeks: hur många veckor bakåt som högst visas. Axeln börjar vid elevens första svar (men aldrig kortare än MIN_SHOWN veckor)."""
    weeks = weeks if weeks in CHOICES else DEFAULT_WEEKS
    subjects = list(subjects)
    counted = set(subjects if counted is None else counted) & set(subjects)
    this_week = week_start(logic.today())
    first = db.execute("SELECT MIN(created_at) AS t FROM attempts WHERE user_id=?", (student_id,)).fetchone()["t"]
    start = max(this_week - timedelta(weeks=weeks - 1), week_start(logic.parse_ts(first).date()) if first else this_week)
    start = min(start, this_week - timedelta(weeks=MIN_SHOWN - 1))
    count = (this_week - start).days // 7 + 1
    week_list = []
    for i in range(count):
        d = start + timedelta(weeks=i)
        week_list.append({"start": d, "num": d.isocalendar()[1], "label": f"v{d.isocalendar()[1]}", "current": i == count - 1})

    per = {s: [[0, 0] for _ in range(count)] for s in subjects}     # ämne -> [[svar, rätt] per vecka]
    rows = db.execute(
        """SELECT a.created_at, a.correct, e.subject FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? AND a.created_at>=?""", (student_id, logic.utc_start(start))).fetchall()
    for row in rows:
        if row["subject"] not in per:
            continue
        i = (logic.parse_ts(row["created_at"]).date() - start).days // 7
        if 0 <= i < count:
            per[row["subject"]][i][0] += 1
            per[row["subject"]][i][1] += row["correct"]

    def series_of(pairs):
        return [{"n": n, "correct": c, "pct": _pct(c, n)} for n, c in pairs]

    total = [[sum(per[s][i][0] for s in counted), sum(per[s][i][1] for s in counted)] for i in range(count)]
    everything = _entry("alla", "Alla ämnen tillsammans", series_of(total), week_list, big=True)
    with_data = [s for s in subjects if any(n for n, _ in per[s])]
    entries = sorted((_entry(s, logic.label(s), series_of(per[s]), week_list) for s in with_data),
                     key=lambda e: (-e["n"], e["label"]))
    table_head = ["Vecka", "Alla ämnen"] + [e["label"] for e in entries]
    table = []
    for i, wk in reversed(list(enumerate(week_list))):
        def cell(pt):
            return f"{pt['pct']} % ({pt['n']})" if pt["n"] else "–"
        table.append({"week": wk["label"] + (" (pågår)" if wk["current"] else ""), "from": wk["start"],
                      "cells": [cell(everything["series"][i])] + [cell(e["series"][i]) for e in entries]})
    return {
        "weeks": week_list, "count": count, "asked": weeks, "choices": CHOICES, "unsure_below": UNSURE_BELOW,
        "ever": first is not None, "has_data": bool(everything["n"] or entries), "all": everything, "subjects": entries,
        "left_out": [e["label"] for e in entries if e["key"] not in counted],
        "table_head": table_head, "table": table,
    }


def for_student(db, student_id: int, weeks=DEFAULT_WEEKS, *, only_enabled: bool = True) -> dict:
    """Utveckling för en elev, med de ämnen som räknas som standard i rapporten i "Alla ämnen".

    Eleven själv ser bara de ämnen som är påslagna för henne (only_enabled). Admin ser alla ämnen som hon har svarat i."""
    if only_enabled:
        subjects = logic.enabled_subjects(db, student_id)
    else:
        subjects = logic.ordered_subjects(r["subject"] for r in db.execute(
            """SELECT DISTINCT e.subject FROM attempts a JOIN exercises e ON e.id=a.exercise_id WHERE a.user_id=?""",
            (student_id,)))
    settings = logic.subject_settings(db, student_id, subjects)
    counted = [s for s in subjects if settings[s]["in_report"]]
    return build(db, student_id, subjects, counted, clean_weeks(weeks))
