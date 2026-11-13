"""Tester för "Lägg till på hemskärmen": ikoner, manifest och metataggar."""
import re
import struct
import zlib
from pathlib import Path

from .conftest import login
from .test_features import _make_student

ICONS = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"


def _png_info(data: bytes):
    """(bredd, höjd, färgtyp) ur en PNG-fil. Färgtyp 2 = RGB utan genomskinlighet, 6 = RGBA."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, depth, color = struct.unpack(">IIBB", data[16:26])
    return width, height, color


def test_icon_files_have_the_right_sizes_and_no_transparency():
    for name, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192), ("icon-512.png", 512), ("favicon-32.png", 32)):
        w, h, color = _png_info((ICONS / name).read_bytes())
        assert (w, h) == (size, size), name
        assert color in (0, 2, 3), f"{name} har genomskinlighet (iOS fyller den med svart)"   # gråskala, RGB eller palett


def test_ico_file_is_valid():
    data = (ICONS / "favicon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count >= 1


def test_the_icon_is_not_a_blank_square():
    """Ikonen ska ha både bakgrund och ett motiv, inte en enfärgad ruta."""
    data = (ICONS / "apple-touch-icon.png").read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    assert len(set(raw)) > 20


def test_pages_link_the_icon_and_manifest_and_ask_for_fullscreen(client):
    page = client.get("/login").text
    assert '<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">' in page
    assert '<link rel="manifest" href="/manifest.webmanifest">' in page
    assert re.search(r'<link rel="icon"[^>]*href="/static/icons/favicon-32.png"', page)
    assert '<meta name="apple-mobile-web-app-capable" content="yes">' in page
    assert '<meta name="apple-mobile-web-app-title" content="Hemskola">' in page
    assert client.get(re.search(r'rel="apple-touch-icon" href="([^"]+)"', page).group(1)).status_code == 200


def test_every_logged_in_page_has_them_too(client):
    _make_student(client)
    login(client, "mia", "hemligt1")
    for url in ("/home", "/tema", "/uppgifter"):
        assert "apple-touch-icon" in client.get(url).text, url


def test_manifest(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["name"] == "Hemskola" and m["short_name"] == "Hemskola" and m["lang"] == "sv"
    assert m["start_url"] == "/" and m["scope"] == "/" and m["display"] == "standalone"
    assert re.fullmatch(r"#[0-9a-f]{6}", m["theme_color"]) and re.fullmatch(r"#[0-9a-f]{6}", m["background_color"])
    purposes = sorted((i["sizes"], i["purpose"]) for i in m["icons"])
    assert purposes == [("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")]
    for icon in m["icons"]:
        got = client.get(icon["src"])
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        w, h, _ = _png_info(got.content)
        assert f"{w}x{h}" == icon["sizes"]


def test_manifest_and_icons_need_no_login(client):
    """Telefonen hämtar dem utan inloggning, och de ska inte skicka någon till inloggningssidan."""
    for url in ("/manifest.webmanifest", "/favicon.ico", "/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"):
        r = client.get(url, follow_redirects=False)
        assert r.status_code == 200, url


def test_default_icon_paths_serve_the_icons(client):
    r = client.get("/apple-touch-icon.png")
    assert r.headers["content-type"] == "image/png" and r.content == (ICONS / "apple-touch-icon.png").read_bytes()
    r = client.get("/favicon.ico")
    assert r.headers["content-type"] == "image/x-icon" and r.content == (ICONS / "favicon.ico").read_bytes()
