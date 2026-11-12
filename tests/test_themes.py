"""Tester för färgteman: listan, CSS:en, kontrast, val per användare och att inget går att skjuta in via temanamnet."""
import re
from pathlib import Path

from app import db as database
from app import themes

from .conftest import login
from .test_editor import _admin
from .test_features import _conn, _make_student

CSS = (Path(__file__).resolve().parent.parent / "app" / "static" / "style.css").read_text(encoding="utf-8")
VARS = ["bg", "card", "text", "muted", "line", "accent", "accent-d", "ok", "bad", "warn", "okbg", "badbg", "warnbg",
        "tint", "on-accent", "on-bad"]


def _vars(block: str) -> dict:
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+):\s*([^;]+);", block)}


def _theme_css() -> dict:
    return {m.group(1): m.group(2) for m in re.finditer(r'html\[data-theme="(\w+)"\]\s*\{(.*?)\n\}', CSS, re.S)}


def _lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ------------------------------------------------------------------ listan och CSS:en

def test_registry_is_sane():
    assert themes.DEFAULT == "auto" and themes.KEYS[0] == "auto"
    assert len(set(themes.KEYS)) == len(themes.KEYS) >= 4
    assert len({t["name"] for t in themes.THEMES}) == len(themes.THEMES)
    for t in themes.THEMES:
        assert re.fullmatch(r"[a-z]+", t["key"]) and t["name"] and t["emoji"] and t["about"] and t["preview"]
    assert themes.clean("morkt") == "morkt"
    for bad in (None, "", "nope", "MORKT", 5, '"><script>'):
        assert themes.clean(bad) == "auto"
    assert themes.get("hav")["name"] == "Hav" and themes.get(None)["key"] == "auto"


def test_there_is_a_light_and_a_dark_theme_besides_the_current_look():
    css = _theme_css()
    assert any("color-scheme: light" in b for b in css.values()) and any("color-scheme: dark" in b for b in css.values())
    assert {"ljust", "morkt"} <= set(css)


def test_every_theme_has_a_complete_css_block_and_no_extra_ones():
    css = _theme_css()
    assert set(css) == set(themes.KEYS) - {"auto"}
    for key, block in css.items():
        got = _vars(block)
        assert set(VARS) <= set(got), (key, set(VARS) - set(got))
        assert "color-scheme:" in block
        for v in VARS:
            assert re.fullmatch(r"#[0-9a-f]{6}", got[v]), (key, v, got[v])


def test_previews_show_the_real_colours():
    css = _theme_css()
    for t in themes.THEMES:
        if t["key"] == "auto":
            continue
        got = _vars(css[t["key"]])
        (p,) = t["preview"]
        assert (p["bg"], p["card"], p["text"], p["accent"], p["on_accent"]) == \
            (got["bg"], got["card"], got["text"], got["accent"], got["on-accent"]), t["key"]


def test_the_standard_theme_is_the_look_that_was_there_before():
    root = _vars(re.search(r":root \{(.*?)\n\}", CSS, re.S).group(1))
    dark = _vars(re.search(r"prefers-color-scheme: dark\) \{\s*:root \{(.*?)\n  \}", CSS, re.S).group(1))
    light_p, dark_p = themes.get("auto")["preview"]
    assert (light_p["bg"], light_p["card"], light_p["text"], light_p["accent"]) == \
        (root["bg"], root["card"], root["text"], root["accent"])
    assert (dark_p["bg"], dark_p["card"], dark_p["text"], dark_p["accent"]) == \
        (dark["bg"], dark["card"], dark["text"], dark["accent"])
    assert root["accent"] == "#2f7d5b" and root["bg"] == "#f6f7f4" and dark["bg"] == "#14191a"   # oförändrade
    assert "--on-accent" not in dark and root["on-accent"] == "#fff"                               # som förut: vit text
    assert root["tint"] == "var(--okbg)"                                                          # dekorfärgen följer som förut


def test_text_is_readable_in_every_theme():
    pairs = [("text", "bg"), ("text", "card"), ("muted", "bg"), ("muted", "card"), ("accent", "bg"), ("accent", "card"),
             ("accent", "tint"), ("on-accent", "accent"), ("on-accent", "accent-d"), ("on-bad", "bad"),
             ("ok", "okbg"), ("bad", "badbg"), ("warn", "warnbg"), ("ok", "card"), ("bad", "card"), ("warn", "card"),
             ("text", "tint"), ("accent-d", "tint"), ("text", "okbg"), ("muted", "tint")]
    for key, block in _theme_css().items():
        got = _vars(block)
        weak = [(a, b, round(_contrast(got[a], got[b]), 2)) for a, b in pairs if _contrast(got[a], got[b]) < 4.5]
        assert not weak, (key, weak)


def test_css_uses_the_button_text_colours_and_prints_plainly():
    assert re.search(r"\.btn, button \{[^}]*color: var\(--on-accent\)", CSS)
    assert re.search(r"\.btn\.danger, button\.danger \{[^}]*color: var\(--on-bad\)", CSS)
    printing = CSS[CSS.index("@media print {\n  :root, html[data-theme]"):]
    assert "--text: #000" in printing and "--card: #fff" in printing
    assert CSS.rindex("@media print") > CSS.rindex('html[data-theme="solnedgang"]')       # och kommer efter temana


def test_migration_adds_the_theme_column(client):
    conn = _conn()
    conn.execute("ALTER TABLE users DROP COLUMN theme")
    conn.commit()
    database.migrate(conn)
    conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    assert "theme" in cols
    assert conn.execute("SELECT COUNT(*) FROM users WHERE theme IS NOT NULL").fetchone()[0] == 0
    conn.close()


# ------------------------------------------------------------------ valet

def _html_tag(page):
    return re.search(r"<html[^>]*>", page).group(0)


def test_the_theme_page_requires_login(client):
    r = client.get("/tema", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.post("/tema", data={"theme": "morkt"}, follow_redirects=False).status_code == 303


def test_default_is_the_current_look_without_a_theme_attribute(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    page = client.get("/home").text
    assert "data-theme" not in _html_tag(page) and "theme-color" not in page and "📚 Hemskola" in page


def test_theme_page_lists_all_themes_and_marks_the_current(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    page = client.get("/tema").text
    for t in themes.THEMES:
        assert f'value="{t["key"]}"' in page and t["name"] in page
    assert page.count("✔ valt") == 1 and re.search(r'class="themecard on"[^>]*value="auto"', page)
    assert 'href="/tema"' in page                                       # 🎨-knappen finns i menyn


def test_choosing_a_theme_saves_it_for_that_user_only(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    r = client.post("/tema", data={"theme": "morkt"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/tema"
    assert _conn().execute("SELECT theme FROM users WHERE username='mia'").fetchone()[0] == "morkt"
    assert _conn().execute("SELECT theme FROM users WHERE username='admin'").fetchone()[0] is None
    page = client.get("/tema").text
    assert 'data-theme="morkt"' in _html_tag(page) and "Utseendet är nu Mörkt." in page
    assert '<meta name="theme-color" content="#181b22">' in page and "🌙 Hemskola" in page
    assert 'data-theme="morkt"' in _html_tag(client.get("/home").text)   # och på alla andra sidor
    client.post("/logout")
    _admin(client)
    assert "data-theme" not in _html_tag(client.get("/admin").text)     # admin har sitt eget val


def test_admin_can_choose_too(client):
    _admin(client)
    client.post("/tema", data={"theme": "lilanatt"})
    assert 'data-theme="lilanatt"' in _html_tag(client.get("/admin").text)
    assert "🔮 Hemskola" in client.get("/admin/exercises").text


def test_choosing_standard_again_removes_the_attribute(client):
    _admin(client)
    client.post("/tema", data={"theme": "hav"})
    client.post("/tema", data={"theme": "auto"})
    assert "data-theme" not in _html_tag(client.get("/admin").text)
    assert _conn().execute("SELECT theme FROM users WHERE username='admin'").fetchone()[0] == "auto"


def test_every_theme_can_be_chosen_and_renders(client):
    _admin(client)
    for t in themes.THEMES:
        client.post("/tema", data={"theme": t["key"]})
        page = client.get("/admin").text
        assert page.count(t["emoji"] + " Hemskola") == 1
        assert ('data-theme="%s"' % t["key"] in page) == (t["key"] != "auto")


def test_unknown_theme_is_refused(client):
    _admin(client)
    client.post("/tema", data={"theme": "hav"})
    for bad in ("finns-inte", "", '"><script>alert(1)</script>', "MORKT"):
        r = client.post("/tema", data={"theme": bad}, follow_redirects=False)
        assert r.status_code == 303
    assert _conn().execute("SELECT theme FROM users WHERE username='admin'").fetchone()[0] == "hav"
    assert "Det temat finns inte." in client.get("/tema").text


def test_a_strange_value_in_the_database_is_harmless(client):
    _admin(client)
    conn = _conn()
    conn.execute("UPDATE users SET theme=? WHERE username='admin'", ('"><script>alert(1)</script>',))
    conn.commit()
    conn.close()
    page = client.get("/admin").text
    assert "<script>alert(1)" not in page and "data-theme" not in _html_tag(page)


# ------------------------------------------------------------------ inloggningssidan och kakan

def test_login_page_follows_the_theme_last_used_on_the_device(client):
    _make_student(client)
    assert "data-theme" not in _html_tag(client.get("/login").text)
    login(client, "mia", "hemligt1")
    client.post("/tema", data={"theme": "solnedgang"})
    assert client.cookies.get("hs_theme") == "solnedgang"
    client.post("/logout")
    page = client.get("/login").text
    assert 'data-theme="solnedgang"' in _html_tag(page) and "🌅 Hemskola" in page


def test_logging_in_sets_the_cookie_to_that_users_theme(client):
    _make_student(client)
    conn = _conn()
    conn.execute("UPDATE users SET theme='lila' WHERE username='mia'")
    conn.commit()
    conn.close()
    r = client.post("/login", data={"username": "mia", "password": "hemligt1"}, follow_redirects=False)
    assert r.status_code == 303
    assert "hs_theme=lila" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    assert "SameSite=lax" in r.headers["set-cookie"]


def test_a_forged_cookie_cannot_inject_anything(client):
    client.cookies.set("hs_theme", '"><script>alert(1)</script>')
    page = client.get("/login").text
    assert "<script>alert(1)" not in page and "data-theme" not in _html_tag(page)
    client.cookies.set("hs_theme", "morkt")
    assert 'data-theme="morkt"' in _html_tag(client.get("/login").text)


def test_a_logged_in_user_ignores_the_device_cookie(client):
    _make_student(client)
    client.cookies.set("hs_theme", "hav")
    login(client, "mia", "hemligt1")                      # inloggningen skriver om kakan till Mias tema (standard)
    assert "data-theme" not in _html_tag(client.get("/home").text)


def test_failed_login_page_keeps_the_device_theme(client):
    client.cookies.set("hs_theme", "morkt")
    r = client.post("/login", data={"username": "nobody", "password": "x"})
    assert r.status_code == 401 and 'data-theme="morkt"' in _html_tag(r.text)
