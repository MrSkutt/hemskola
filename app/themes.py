"""Färgteman. Varje användare väljer sitt eget (lagras i users.theme) under 🎨 i menyn.

Själva färgerna ligger som CSS-variabler i static/style.css, ett block per tema (`html[data-theme="…"]`).
Det här är listan över vilka teman som finns, med namn, ikon och de fyra färger som används för förhandsvisningen
på temasidan. Ett test jämför förhandsfärgerna med CSS:en och kontrollerar kontrasten i varje tema.

"auto" är utseendet som alltid funnits (grönt, och mörkt när enheten är inställd på mörkt läge). Det är standard."""

DEFAULT = "auto"

_LIGHT = {"bg": "#f6f7f4", "card": "#ffffff", "text": "#1f2a24", "accent": "#2f7d5b", "on_accent": "#ffffff"}
_DARK = {"bg": "#14191a", "card": "#1d2426", "text": "#e6ece8", "accent": "#4fb98a", "on_accent": "#ffffff"}


def _p(bg, card, text, accent, on_accent):
    return {"bg": bg, "card": card, "text": text, "accent": accent, "on_accent": on_accent}


THEMES = [
    {"key": "auto", "name": "Standard", "emoji": "📚", "about": "Grönt. Blir mörkt när enheten är inställd på mörkt läge.",
     "preview": [_LIGHT, _DARK]},
    {"key": "ljust", "name": "Ljust", "emoji": "📘", "about": "Rent och vitt med blå knappar.",
     "preview": [_p("#f4f6fb", "#ffffff", "#1b2433", "#2563eb", "#ffffff")]},
    {"key": "morkt", "name": "Mörkt", "emoji": "🌙", "about": "Mörkt och skonsamt för ögonen på kvällen.",
     "preview": [_p("#0f1115", "#181b22", "#e8eaf0", "#7db1ff", "#0a1426")]},
    {"key": "lila", "name": "Lila", "emoji": "💜", "about": "Ljust med lila, för alla som älskar lila.",
     "preview": [_p("#f7f3fc", "#ffffff", "#2a1f3d", "#7c3aed", "#ffffff")]},
    {"key": "lilanatt", "name": "Lila natt", "emoji": "🔮", "about": "Mörkt med lila och ljus text.",
     "preview": [_p("#13101f", "#1d1830", "#eee8f8", "#b999f7", "#150d28")]},
    {"key": "hav", "name": "Hav", "emoji": "🌊", "about": "Ljust med havsblått.",
     "preview": [_p("#eef7f8", "#ffffff", "#12313a", "#0e7490", "#ffffff")]},
    {"key": "solnedgang", "name": "Solnedgång", "emoji": "🌅", "about": "Varmt och ljust, som en sen sommarkväll.",
     "preview": [_p("#fff6ec", "#fffdfa", "#3a2418", "#c2410c", "#ffffff")]},
]

BY_KEY = {t["key"]: t for t in THEMES}
KEYS = list(BY_KEY)


def clean(key) -> str:
    """Ett giltigt temanamn: det som angetts, annars standard."""
    return key if key in BY_KEY else DEFAULT


def get(key) -> dict:
    return BY_KEY[clean(key)]
