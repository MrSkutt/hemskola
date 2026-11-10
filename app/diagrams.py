"""Enkla SVG-diagram som ritas från en liten JSON-spec.

En övning kan ha ett fält "diagram", t.ex.
    {"type": "bar_chart", "labels": ["Mån", "Tis"], "values": [4, 7]}
Specen valideras av validate() vid import och ritas av render() när frågan visas.
Allt som skrivs ut är siffror eller escapad text, så SVG:n är säker att visa inline.
"""
import html
import math

W, H = 360, 240


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _num(x) -> str:
    """Tal med svensk decimalkomma, utan onödiga nollor."""
    f = float(x)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _f(x) -> str:
    return f"{x:.1f}"


def _svg(w, h, body, label) -> str:
    return (f'<svg class="diagram" viewBox="0 0 {w} {h}" role="img" aria-label="{_esc(label)}" '
            f'xmlns="http://www.w3.org/2000/svg">{body}</svg>')


def _text(x, y, s, cls="d-text", anchor="middle", size=None, extra="") -> str:
    fs = f' font-size="{size}"' if size else ""
    return f'<text class="{cls}" x="{_f(x)}" y="{_f(y)}" text-anchor="{anchor}"{fs}{extra}>{_esc(s)}</text>'


def _pos(spec, key, lo=0.0001, hi=1e9) -> float:
    v = float(spec[key])
    if not (lo <= v <= hi) or math.isnan(v):
        raise ValueError(f"{key} har ogiltigt värde")
    return v


def _label(spec, key, default) -> str:
    v = spec.get(key, default)
    s = str(v)
    if len(s) > 40:
        raise ValueError(f"{key} är för långt")
    return s


def _nice_step(m: float) -> float:
    if m <= 0:
        return 1
    raw = m / 6
    mag = 10 ** math.floor(math.log10(raw))
    for f in (1, 2, 5, 10):
        if raw <= f * mag:
            return f * mag
    return 10 * mag


# ------------------------------------------------------------------ diagram

def bar_chart(spec) -> str:
    labels = [str(x) for x in spec["labels"]]
    values = [float(v) for v in spec["values"]]
    n = len(labels)
    if not 1 <= n <= 10 or n != len(values) or any(v < 0 or math.isnan(v) for v in values):
        raise ValueError("bar_chart: labels/values ogiltiga")
    mx = max(values) or 1
    step = float(spec.get("step") or _nice_step(mx))
    top = float(spec.get("max") or math.ceil(mx / step) * step)
    if top < mx or top / step > 30:
        raise ValueError("bar_chart: max/step ogiltiga")
    left, right, topm, bot = 44, 12, 30, 46
    pw, ph = W - left - right, H - topm - bot
    out = []
    title = spec.get("title")
    if title:
        out.append(_text(W / 2, 16, _label(spec, "title", ""), "d-title"))
    k = 0
    while k * step <= top + 1e-9:
        v = k * step
        y = topm + ph - v / top * ph
        out.append(f'<line class="d-grid" x1="{left}" y1="{_f(y)}" x2="{W - right}" y2="{_f(y)}"/>')
        out.append(_text(left - 6, y + 4, _num(v), "d-axis", "end"))
        k += 1
    slot = pw / n
    bw = slot * 0.6
    small = 11 if n > 6 else 13
    for i, (lab, v) in enumerate(zip(labels, values)):
        x = left + i * slot + (slot - bw) / 2
        h = v / top * ph
        out.append(f'<rect class="d-bar" x="{_f(x)}" y="{_f(topm + ph - h)}" width="{_f(bw)}" height="{_f(h)}"/>')
        if spec.get("show_values"):
            out.append(_text(x + bw / 2, topm + ph - h - 5, _num(v), "d-text", size=12))
        out.append(_text(x + bw / 2, H - bot + 18, lab, "d-text", size=small))
    out.append(f'<line class="d-line" x1="{left}" y1="{topm}" x2="{left}" y2="{topm + ph}"/>')
    out.append(f'<line class="d-line" x1="{left}" y1="{topm + ph}" x2="{W - right}" y2="{topm + ph}"/>')
    if spec.get("unit"):
        out.append(_text(4, 16, _label(spec, "unit", ""), "d-axis", "start"))
    return _svg(W, H, "".join(out), title or "Stapeldiagram")


def pie_chart(spec) -> str:
    labels = [str(x) for x in spec["labels"]]
    values = [float(v) for v in spec["values"]]
    n = len(labels)
    if not 1 <= n <= 6 or n != len(values) or any(v <= 0 for v in values):
        raise ValueError("pie_chart: labels/values ogiltiga")
    total = sum(values)
    cx, cy, r = 115, 120, 95
    out = []
    ang = -90.0
    for i, v in enumerate(values):
        sweep = v / total * 360
        if n == 1:
            out.append(f'<circle class="d-c0 d-seg" cx="{cx}" cy="{cy}" r="{r}"/>')
        else:
            a0, a1 = math.radians(ang), math.radians(ang + sweep)
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            large = 1 if sweep > 180 else 0
            out.append(f'<path class="d-c{i % 6} d-seg" d="M{cx} {cy} L{_f(x0)} {_f(y0)} '
                       f'A{r} {r} 0 {large} 1 {_f(x1)} {_f(y1)} Z"/>')
        ang += sweep
    for i, (lab, v) in enumerate(zip(labels, values)):
        y = 60 + i * 26
        out.append(f'<rect class="d-c{i % 6} d-seg" x="228" y="{y - 11}" width="14" height="14"/>')
        txt = lab
        if spec.get("show_values"):
            txt += f" ({_num(v)})"
        elif spec.get("show_percent"):
            txt += f" ({_num(round(v / total * 100, 1))} %)"
        out.append(_text(250, y + 1, txt, "d-text", "start", 13))
    if spec.get("title"):
        out.append(_text(115, 14, _label(spec, "title", ""), "d-title"))
    return _svg(W, H, "".join(out), spec.get("title") or "Cirkeldiagram")


def clock(spec) -> str:
    h_s, m_s = str(spec["time"]).replace(".", ":").split(":")
    h, m = int(h_s) % 12, int(m_s)
    if not 0 <= m < 60:
        raise ValueError("clock: ogiltig tid")
    s, c, r = 240, 120, 104
    out = [f'<circle class="d-face" cx="{c}" cy="{c}" r="{r + 8}"/>']
    for i in range(60):
        a = math.radians(i * 6)
        long = i % 5 == 0
        r1 = r - (10 if long else 5)
        out.append(f'<line class="d-line" x1="{_f(c + r * math.sin(a))}" y1="{_f(c - r * math.cos(a))}" '
                   f'x2="{_f(c + r1 * math.sin(a))}" y2="{_f(c - r1 * math.cos(a))}" '
                   f'stroke-width="{3 if long else 1}"/>')
    ha = math.radians((h + m / 60) * 30)
    ma = math.radians(m * 6)
    out.append(f'<line class="d-hand" x1="{c}" y1="{c}" x2="{_f(c + 55 * math.sin(ha))}" y2="{_f(c - 55 * math.cos(ha))}" stroke-width="7"/>')
    out.append(f'<line class="d-hand" x1="{c}" y1="{c}" x2="{_f(c + 84 * math.sin(ma))}" y2="{_f(c - 84 * math.cos(ma))}" stroke-width="4"/>')
    for i in range(1, 13):
        a = math.radians(i * 30)
        out.append(_text(c + 76 * math.sin(a), c - 76 * math.cos(a) + 6, i, "d-num", size=19))
    out.append(f'<circle class="d-accent" cx="{c}" cy="{c}" r="6"/>')
    return _svg(s, s, "".join(out), "Analog klocka")


def fraction(spec) -> str:
    shape = spec.get("shape", "circle")
    n, k = int(spec["parts"]), int(spec["shaded"])
    if not 1 <= n <= 24 or not 0 <= k <= n:
        raise ValueError("fraction: ogiltigt antal delar")
    out = []
    if shape == "circle":
        cx = cy = 100
        r = 90
        if n == 1:
            out.append(f'<circle class="{"d-shade" if k else "d-empty"}" cx="{cx}" cy="{cy}" r="{r}"/>')
        else:
            for i in range(n):
                a0 = math.radians(-90 + i * 360 / n)
                a1 = math.radians(-90 + (i + 1) * 360 / n)
                x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
                x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
                out.append(f'<path class="{"d-shade" if i < k else "d-empty"}" d="M{cx} {cy} L{_f(x0)} {_f(y0)} '
                           f'A{r} {r} 0 0 1 {_f(x1)} {_f(y1)} Z"/>')
        return _svg(200, 200, "".join(out), "Cirkel indelad i lika stora delar")
    if shape == "bar":
        x0, w, h = 20, 320, 70
        seg = w / n
        for i in range(n):
            out.append(f'<rect class="{"d-shade" if i < k else "d-empty"}" x="{_f(x0 + i * seg)}" y="20" width="{_f(seg)}" height="{h}"/>')
        return _svg(360, 110, "".join(out), "Rektangel indelad i lika stora delar")
    raise ValueError("fraction: shape måste vara circle eller bar")


def rectangle(spec) -> str:
    w, h = _pos(spec, "w"), _pos(spec, "h")
    unit = _label(spec, "unit", "")
    ratio = max(0.4, min(2.5, w / h))
    bw, bh = (230.0, 230.0 / ratio) if ratio >= 230 / 140 else (140.0 * ratio, 140.0)
    x0, y0 = (W - bw) / 2, 30 + (140 - bh) / 2
    wl = _label(spec, "w_label", f"{_num(w)} {unit}".strip())
    hl = _label(spec, "h_label", f"{_num(h)} {unit}".strip())
    out = [f'<rect class="d-shade" x="{_f(x0)}" y="{_f(y0)}" width="{_f(bw)}" height="{_f(bh)}"/>',
           _text(x0 + bw / 2, y0 + bh + 22, wl, size=15),
           _text(x0 + bw + 10, y0 + bh / 2 + 5, hl, anchor="start", size=15)]
    if spec.get("center_label"):
        out.append(_text(x0 + bw / 2, y0 + bh / 2 + 5, _label(spec, "center_label", ""), size=15))
    return _svg(W, 220, "".join(out), "Rektangel")


def right_triangle(spec) -> str:
    a, b = _pos(spec, "a"), _pos(spec, "b")     # bara för proportionerna
    bl = _label(spec, "bottom_label", "")
    ll = _label(spec, "left_label", "")
    hl = _label(spec, "hyp_label", "")
    s = min(230 / a, 150 / b)
    pa, pb = max(70.0, a * s), max(70.0, b * s)
    x0, y0 = 60.0, 195.0 - (150 - pb) / 2 - 10
    A, B, C = (x0, y0), (x0 + pa, y0), (x0, y0 - pb)
    sq = 14
    out = [f'<polygon class="d-shade" points="{_f(A[0])},{_f(A[1])} {_f(B[0])},{_f(B[1])} {_f(C[0])},{_f(C[1])}"/>',
           f'<polyline class="d-line" points="{_f(A[0])},{_f(A[1] - sq)} {_f(A[0] + sq)},{_f(A[1] - sq)} {_f(A[0] + sq)},{_f(A[1])}"/>']
    out.append(_text((A[0] + B[0]) / 2, A[1] + 22, bl, size=15))
    out.append(_text(A[0] - 10, (A[1] + C[1]) / 2 + 5, ll, anchor="end", size=15))
    mx, my = (B[0] + C[0]) / 2, (B[1] + C[1]) / 2
    dx, dy = mx - A[0], my - A[1]
    d = math.hypot(dx, dy) or 1
    out.append(_text(mx + dx / d * 22, my + dy / d * 18 + 5, hl, size=15))
    return _svg(W, 230, "".join(out), "Rätvinklig triangel")


def number_line(spec) -> str:
    lo, hi = float(spec["min"]), float(spec["max"])
    step = float(spec.get("step", 1))
    if hi <= lo or step <= 0 or (hi - lo) / step > 60:
        raise ValueError("number_line: ogiltigt intervall")
    lab_step = float(spec.get("label_step", hi - lo))
    marks = spec.get("marks", [])
    if len(marks) > 5:
        raise ValueError("number_line: för många markeringar")
    x0, x1, y = 30.0, 330.0, 110.0

    def px(v):
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)

    out = [f'<line class="d-line" x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke-width="3"/>']
    n = int(round((hi - lo) / step))
    per_label = max(1, int(round(lab_step / step)))
    for i in range(n + 1):
        v = lo + i * step
        longt = i % per_label == 0
        t = 10 if longt else 6
        out.append(f'<line class="d-line" x1="{_f(px(v))}" y1="{y - t}" x2="{_f(px(v))}" y2="{y + t}"/>')
        if longt:
            out.append(_text(px(v), y + 30, _num(v), size=14))
    for mk in marks:
        v = float(mk["value"])
        if not lo <= v <= hi:
            raise ValueError("number_line: markering utanför linjen")
        out.append(f'<circle class="d-accent" cx="{_f(px(v))}" cy="{y}" r="7"/>')
        if mk.get("label") is not None:
            out.append(_text(px(v), y - 20, _label(mk, "label", ""), "d-title", size=16))
    return _svg(W, 160, "".join(out), "Tallinje")


def coordinate(spec) -> str:
    xmin, xmax = int(spec["xmin"]), int(spec["xmax"])
    ymin, ymax = int(spec["ymin"]), int(spec["ymax"])
    if xmax <= xmin or ymax <= ymin or xmax - xmin > 24 or ymax - ymin > 24:
        raise ValueError("coordinate: ogiltigt intervall")
    pts = spec.get("points", [])
    if len(pts) > 8:
        raise ValueError("coordinate: för många punkter")
    size, m = 320, 30
    sx = (size - 2 * m) / (xmax - xmin)
    sy = (size - 2 * m) / (ymax - ymin)

    def px(x):
        return m + (x - xmin) * sx

    def py(y):
        return size - m - (y - ymin) * sy

    out = []
    for x in range(xmin, xmax + 1):
        out.append(f'<line class="d-grid" x1="{_f(px(x))}" y1="{m}" x2="{_f(px(x))}" y2="{size - m}"/>')
    for y in range(ymin, ymax + 1):
        out.append(f'<line class="d-grid" x1="{m}" y1="{_f(py(y))}" x2="{size - m}" y2="{_f(py(y))}"/>')
    ax = min(max(0, xmin), xmax)
    ay = min(max(0, ymin), ymax)
    out.append(f'<line class="d-line" x1="{m}" y1="{_f(py(ay))}" x2="{size - m}" y2="{_f(py(ay))}" stroke-width="2.5"/>')
    out.append(f'<line class="d-line" x1="{_f(px(ax))}" y1="{m}" x2="{_f(px(ax))}" y2="{size - m}" stroke-width="2.5"/>')
    lab_every = 1 if (xmax - xmin) <= 12 else 2
    for x in range(xmin, xmax + 1):
        if x != 0 and x % lab_every == 0:
            out.append(_text(px(x), py(ay) + 16, x, "d-axis", size=11))
    lab_every = 1 if (ymax - ymin) <= 12 else 2
    for y in range(ymin, ymax + 1):
        if y != 0 and y % lab_every == 0:
            out.append(_text(px(ax) - 6, py(y) + 4, y, "d-axis", "end", 11))
    line = spec.get("line")
    if line:
        k, b = float(line["k"]), float(line["m"])
        cand = []
        for x in (xmin, xmax):
            y = k * x + b
            if ymin - 1e-9 <= y <= ymax + 1e-9:
                cand.append((x, y))
        if k != 0:
            for y in (ymin, ymax):
                x = (y - b) / k
                if xmin - 1e-9 <= x <= xmax + 1e-9:
                    cand.append((x, y))
        cand = sorted(set((round(x, 6), round(y, 6)) for x, y in cand))
        if len(cand) >= 2:
            (x1, y1), (x2, y2) = cand[0], cand[-1]
            out.append(f'<line class="d-func" x1="{_f(px(x1))}" y1="{_f(py(y1))}" x2="{_f(px(x2))}" y2="{_f(py(y2))}"/>')
    for p in pts:
        x, y = float(p["x"]), float(p["y"])
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            raise ValueError("coordinate: punkt utanför rutnätet")
        out.append(f'<circle class="d-accent" cx="{_f(px(x))}" cy="{_f(py(y))}" r="5.5"/>')
        if p.get("label") is not None:
            out.append(_text(px(x) + 9, py(y) - 8, _label(p, "label", ""), "d-title", "start", 14))
    return _svg(size, size, "".join(out), "Koordinatsystem")


def angle(spec) -> str:
    deg = _pos(spec, "degrees", 1, 180)
    label = _label(spec, "label", f"{_num(deg)}°")
    vx, vy, L = 50.0, 195.0, 170.0
    a = math.radians(deg)
    r = 44
    out = [f'<line class="d-line" x1="{vx}" y1="{vy}" x2="{vx + L}" y2="{vy}" stroke-width="3"/>',
           f'<line class="d-line" x1="{vx}" y1="{vy}" x2="{_f(vx + L * math.cos(a))}" y2="{_f(vy - L * math.sin(a))}" stroke-width="3"/>']
    if abs(deg - 90) < 0.01:
        out.append(f'<polyline class="d-line" points="{vx},{vy - 18} {vx + 18},{vy - 18} {vx + 18},{vy}"/>')
    else:
        large = 1 if deg > 180 else 0
        out.append(f'<path class="d-line" d="M{_f(vx + r)} {vy} A{r} {r} 0 {large} 0 '
                   f'{_f(vx + r * math.cos(a))} {_f(vy - r * math.sin(a))}"/>')
    mid = a / 2
    out.append(_text(vx + (r + 28) * math.cos(mid), vy - (r + 28) * math.sin(mid) + 5, label, "d-title", size=16))
    return _svg(W, 220, "".join(out), "Vinkel")


TYPES = {
    "bar_chart": bar_chart, "pie_chart": pie_chart, "clock": clock, "fraction": fraction,
    "rectangle": rectangle, "right_triangle": right_triangle, "number_line": number_line,
    "coordinate": coordinate, "angle": angle,
}


def render(spec):
    """Returnerar SVG-text eller None om specen är ogiltig."""
    try:
        return TYPES[spec["type"]](spec)
    except (KeyError, ValueError, TypeError, AttributeError, ZeroDivisionError):
        return None


def validate(spec):
    """Returnerar None om specen är ok, annars ett felmeddelande."""
    if not isinstance(spec, dict) or "type" not in spec:
        return "diagram måste vara ett objekt med 'type'"
    if spec["type"] not in TYPES:
        return f"okänd diagramtyp '{spec['type']}' (giltiga: {', '.join(sorted(TYPES))})"
    try:
        TYPES[spec["type"]](spec)
    except (KeyError, ValueError, TypeError, AttributeError, ZeroDivisionError) as e:
        return f"diagrammet kunde inte ritas ({type(e).__name__}: {e})"
    return None
