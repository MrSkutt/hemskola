"""Ritar Hemskola-ikonen: en uppslagen bok med en gnista på grön botten. Ritas i 2048 px och skalas ner för mjuka kanter.
Körs bara när ikonen ska ändras (kräver Pillow, som inte behövs för att köra appen):
    python tools/make_icons.py app/static/icons"""
import math, sys
from PIL import Image, ImageDraw, ImageFilter

S = 2048
OUT = sys.argv[1]


def bez(p0, p1, p2, p3, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        a = (1 - t) ** 3; b = 3 * (1 - t) ** 2 * t; c = 3 * (1 - t) * t ** 2; d = t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


# bakgrund: lodrät toning, helt ogenomskinlig (iOS fyller annars genomskinligt med svart)
img = Image.new("RGB", (S, S))
px = ImageDraw.Draw(img)
top, bot = (56, 148, 108), (36, 106, 76)
for y in range(S):
    px.line([(0, y), (S, y)], fill=lerp(top, bot, y / S))

cx, cy = S / 2, S * 0.57          # bokens mitt
W = S * 0.30                      # en sidas bredd
H = S * 0.27                      # sidans höjd
dip = S * 0.035                   # hur mycket sidorna sjunker mot ryggen


def page(sign, shift=0, color=(255, 255, 255)):
    """En sida: sign=-1 vänster, +1 höger."""
    sp = (cx, cy - H / 2 + dip + shift)                 # ryggen, överkant
    sb = (cx, cy + H / 2 + dip + shift)                 # ryggen, nederkant
    ot = (cx + sign * W, cy - H / 2 - dip + shift)      # ytterkant, överkant
    ob = (cx + sign * W, cy + H / 2 - dip + shift)      # ytterkant, nederkant
    top_edge = bez(sp, (cx + sign * W * 0.25, cy - H / 2 - dip * 1.6 + shift), (cx + sign * W * 0.7, cy - H / 2 - dip * 1.5 + shift), ot)
    bottom_edge = bez(ob, (cx + sign * W * 0.7, cy + H / 2 - dip * 0.4 + shift), (cx + sign * W * 0.25, cy + H / 2 + dip * 0.2 + shift), sb)
    return top_edge + bottom_edge, color


# mjuk skugga under boken
shadow = Image.new("L", (S, S), 0)
sd = ImageDraw.Draw(shadow)
for sign in (-1, 1):
    pts, _ = page(sign, shift=S * 0.035)
    sd.polygon(pts, fill=120)
shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.02))
img.paste((18, 70, 48), (0, 0), shadow)

d = ImageDraw.Draw(img)
# sidtjocklek (en ljusgrön kant under) och själva sidorna
for sign in (-1, 1):
    pts, _ = page(sign, shift=S * 0.022)
    d.polygon(pts, fill=(205, 236, 220))
for sign in (-1, 1):
    pts, col = page(sign)
    d.polygon(pts, fill=col)
# rygg
d.line([(cx, cy - H / 2 + dip), (cx, cy + H / 2 + dip)], fill=(190, 222, 206), width=int(S * 0.012))
# textrader på sidorna
line_col = (150, 200, 176)
for sign in (-1, 1):
    for i, frac in enumerate((0.30, 0.47, 0.64)):
        y = cy - H / 2 + H * frac + dip * (0.2 - 0.9 * 0)
        x0 = cx + sign * W * 0.16
        x1 = cx + sign * W * (0.80 if i != 2 else 0.58)
        d.rounded_rectangle([min(x0, x1), y - S * 0.0085, max(x0, x1), y + S * 0.0085], radius=S * 0.0085, fill=line_col)

# gnista (fyruddig stjärna) uppe till höger
def star(x, y, r, color, k=0.28):
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rr = r if i % 2 == 0 else r * k
        pts.append((x + rr * math.cos(ang), y + rr * math.sin(ang)))
    d.polygon(pts, fill=color)

star(cx + W * 0.62, cy - H * 0.92, S * 0.115, (255, 214, 107))
star(cx + W * 1.0, cy - H * 0.52, S * 0.045, (255, 232, 160))
star(cx + W * 0.2, cy - H * 1.12, S * 0.032, (255, 232, 160))

for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512), ("favicon-32.png", 32)):
    img.resize((size, size), Image.LANCZOS).save(f"{OUT}/{name}", optimize=True)
img.resize((48, 48), Image.LANCZOS).save(f"{OUT}/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
print("klart")
