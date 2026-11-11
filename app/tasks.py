"""Uppgifter: admin skapar uppgifter och ger dem till elever, eleven markerar dem som utförda och admin godkänner
eller avslår med en kommentar. Godkända uppgifter ger poäng (se motivation.points)."""
import http.client
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

TITLE_MAX = 100
BODY_MAX = 4000
NOTE_MAX = 500
COMMENT_MAX = 500
MAX_POINTS = 100000
MAX_IMAGE = 3_000_000
ALLOWED_PORTS = {80, 443}   # portar som en bildadress får använda

STATUS_LABELS = {
    "todo": "Att göra",
    "done": "Väntar på granskning",
    "approved": "Godkänd",
    "rejected": "Gör om",
}
OPEN = ("todo", "rejected")   # eleven har något att göra


def _clean(text, limit: int) -> str:
    return "\n".join(line.rstrip() for line in str(text or "").replace("\r\n", "\n").strip().split("\n"))[:limit]


def parse_task(title, body, points) -> tuple:
    """(title, body, points, fel). Fel är '' om allt är giltigt."""
    title = " ".join(str(title or "").split())[:TITLE_MAX]
    body = _clean(body, BODY_MAX)
    if not title:
        return "", "", 0, "Skriv en rubrik för uppgiften."
    try:
        pts = int(str(points).strip() or "0")
    except ValueError:
        return "", "", 0, "Poängen måste vara ett heltal."
    if not 0 <= pts <= MAX_POINTS:
        return "", "", 0, f"Poängen ska vara mellan 0 och {MAX_POINTS:,}.".replace(",", " ")
    return title, body, pts, ""


def create_task(db, title, body, points, image=None, in_report=False) -> tuple:
    """(id, fel). `in_report`: uppgiften visas på rapporten när den är godkänd."""
    title, body, pts, error = parse_task(title, body, points)
    if error:
        return 0, error
    cur = db.execute("INSERT INTO tasks(title, body, points, image, in_report) VALUES (?,?,?,?,?)",
                     (title, body, pts, image, 1 if in_report else 0))
    return cur.lastrowid, ""


def update_task(db, task_id: int, title, body, points, in_report=False) -> str:
    title, body, pts, error = parse_task(title, body, points)
    if error:
        return error
    db.execute("UPDATE tasks SET title=?, body=?, points=?, in_report=? WHERE id=?",
               (title, body, pts, 1 if in_report else 0, task_id))
    return ""


def list_tasks(db) -> list:
    """Alla uppgifter med antal tilldelningar per status, aktiva först."""
    out = []
    for t in db.execute("SELECT * FROM tasks ORDER BY active DESC, id DESC"):
        counts = {r["status"]: r["n"] for r in db.execute(
            "SELECT status, COUNT(*) AS n FROM task_assignments WHERE task_id=? GROUP BY status", (t["id"],))}
        parts = []
        if counts.get("todo"):
            parts.append(f"{counts['todo']} att göra")
        if counts.get("rejected"):
            parts.append(f"{counts['rejected']} ska göras om")
        if counts.get("done"):
            parts.append(f"{counts['done']} väntar på granskning")
        if counts.get("approved"):
            parts.append(f"{counts['approved']} godkänd" if counts["approved"] == 1 else f"{counts['approved']} godkända")
        out.append({**dict(t), "counts": counts, "total": sum(counts.values()), "summary": " · ".join(parts)})
    return out


def assign(db, task_id: int, user_ids) -> tuple:
    """Ger uppgiften till eleverna. Hoppar över de som redan har den som pågående (efter ett godkännande går
    den att ge igen). Returnerar (givna namn, överhoppade namn)."""
    given, skipped = [], []
    for uid in dict.fromkeys(user_ids):   # unika, i ordning
        u = db.execute("SELECT id, display_name FROM users WHERE id=? AND role='student' AND active=1", (uid,)).fetchone()
        if not u:
            continue
        if db.execute("SELECT 1 FROM task_assignments WHERE task_id=? AND user_id=? AND status!='approved'",
                      (task_id, u["id"])).fetchone():
            skipped.append(u["display_name"])
            continue
        db.execute("INSERT INTO task_assignments(task_id, user_id) VALUES (?,?)", (task_id, u["id"]))
        given.append(u["display_name"])
    return given, skipped


def remove_assignment(db, assignment_id: int) -> str:
    a = db.execute("SELECT status FROM task_assignments WHERE id=?", (assignment_id,)).fetchone()
    if not a:
        return "Tilldelningen finns inte."
    if a["status"] == "approved":
        return "En godkänd uppgift går inte att ta bort eftersom eleven har fått poäng för den. Avslå den först om det är fel."
    db.execute("DELETE FROM task_assignments WHERE id=?", (assignment_id,))
    return ""


def assignment(db, assignment_id: int, user_id: int = None):
    """En tilldelning med uppgiftens fält (title, body, image, points) och elevens namn. None om den saknas
    eller (när user_id anges) inte tillhör eleven."""
    sql = """SELECT a.*, t.title, t.body, t.image, t.points, u.display_name AS student
             FROM task_assignments a JOIN tasks t ON t.id=a.task_id JOIN users u ON u.id=a.user_id WHERE a.id=?"""
    params = [assignment_id]
    if user_id is not None:
        sql += " AND a.user_id=?"
        params.append(user_id)
    return db.execute(sql, params).fetchone()


def _assignments(db, where: str, params, order: str) -> list:
    return db.execute(
        f"""SELECT a.*, t.title, t.body, t.image, t.points, u.display_name AS student
            FROM task_assignments a JOIN tasks t ON t.id=a.task_id JOIN users u ON u.id=a.user_id
            WHERE {where} ORDER BY {order}""", params).fetchall()


def for_task(db, task_id: int) -> list:
    return _assignments(db, "a.task_id=?", (task_id,), "u.display_name, a.id DESC")


def to_review(db) -> list:
    """Uppgifter som eleverna markerat som utförda, äldst först."""
    return _assignments(db, "a.status='done'", (), "a.done_at, a.id")


def for_student(db, user_id: int) -> dict:
    """Elevens uppgifter i tre grupper: att göra (inkl. de som ska göras om), väntar på granskning, godkända."""
    rows = _assignments(db, "a.user_id=?", (user_id,), "a.id DESC")
    return {
        "open": [r for r in rows if r["status"] in OPEN],
        "waiting": [r for r in rows if r["status"] == "done"],
        "approved": sorted((r for r in rows if r["status"] == "approved"), key=lambda r: r["reviewed_at"] or "", reverse=True),
    }


def mark_done(db, assignment_id: int, user_id: int, note="") -> str:
    a = db.execute("SELECT status FROM task_assignments WHERE id=? AND user_id=?", (assignment_id, user_id)).fetchone()
    if not a:
        return "Uppgiften finns inte."
    if a["status"] not in OPEN:
        return "Den här uppgiften är redan markerad som klar."
    db.execute("UPDATE task_assignments SET status='done', student_note=?, done_at=datetime('now'), result_seen=1 "
               "WHERE id=?", (_clean(note, NOTE_MAX), assignment_id))
    return ""


def mark_seen(db, assignment_id: int, user_id: int) -> bool:
    """Eleven har öppnat uppgiften och sett admins svar. True om det fanns ett nytt svar att markera."""
    return db.execute("UPDATE task_assignments SET result_seen=1 WHERE id=? AND user_id=? AND result_seen=0",
                      (assignment_id, user_id)).rowcount > 0


def review(db, assignment_id: int, approve: bool, comment="") -> str:
    """Admin godkänner eller avslår. Går att ändra i efterhand (poängen följer med). Avslag kräver en kommentar."""
    a = db.execute("SELECT a.status, t.points FROM task_assignments a JOIN tasks t ON t.id=a.task_id WHERE a.id=?",
                   (assignment_id,)).fetchone()
    if not a:
        return "Tilldelningen finns inte."
    if a["status"] == "todo":
        return "Eleven har inte markerat uppgiften som klar än."
    comment = _clean(comment, COMMENT_MAX)
    if not approve and not comment:
        return "Skriv en kommentar så eleven vet vad som behöver göras om."
    if approve:
        # poängen sparas första gången uppgiften godkänns; ett nytt godkännande ändrar dem inte
        awarded = db.execute("SELECT points_awarded FROM task_assignments WHERE id=?", (assignment_id,)).fetchone()[0] \
            if a["status"] == "approved" else a["points"]
        db.execute("UPDATE task_assignments SET status='approved', admin_comment=?, points_awarded=?, "
                   "reviewed_at=datetime('now'), result_seen=0 WHERE id=?", (comment, awarded, assignment_id))
    else:
        db.execute("UPDATE task_assignments SET status='rejected', admin_comment=?, points_awarded=0, "
                   "reviewed_at=datetime('now'), result_seen=0 WHERE id=?", (comment, assignment_id))
    return ""


def task_points(db, user_id: int, since: str) -> int:
    """Poäng från godkända uppgifter sedan `since` (UTC, samma format som i databasen)."""
    return db.execute(
        "SELECT COALESCE(SUM(points_awarded), 0) AS s FROM task_assignments "
        "WHERE user_id=? AND status='approved' AND reviewed_at>=?", (user_id, since)).fetchone()["s"]


def badge_count(db, user) -> int:
    """Siffran i fliken. Admin: uppgifter att granska. Elev: uppgifter att göra (även de som ska göras om) och
    godkännanden som eleven inte har sett än. Ett avslag räknas som något att göra tills uppgiften är klar igen."""
    if user["role"] == "admin":
        return db.execute("SELECT COUNT(*) AS c FROM task_assignments WHERE status='done'").fetchone()["c"]
    return db.execute(
        "SELECT COUNT(*) AS c FROM task_assignments WHERE user_id=? AND "
        "(status IN ('todo','rejected') OR (status='approved' AND result_seen=0))", (user["id"],)).fetchone()["c"]


# ---------------------------------------------------------------- bild från webbadress

def sniff_image(data: bytes) -> str:
    """Filändelse för en rasterbild (png, jpg, gif, webp) efter innehållet, annars ''."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ""


def _public_ip(host: str, port: int) -> str:
    """Löser upp adressen och kräver att den är en publik internetadress, så att servern inte kan användas för att
    nå hemnätet eller tjänster på själva servern."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("Webbadressen går inte att nå.") from None
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise ValueError("Webbadressen pekar på en intern adress och kan inte användas.")
        ips.append(str(ip))
    if not ips:
        raise ValueError("Webbadressen går inte att nå.")
    return ips[0]


class _PinnedHTTP(http.client.HTTPConnection):
    """Ansluter till en redan kontrollerad IP-adress (så att namnet inte kan lösas upp till något annat efteråt)."""

    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._pin_ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._pin_ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._pin_ip = ip

    def connect(self):
        sock = socket.create_connection((self._pin_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_image(url: str, timeout: float = 8, total: float = 15) -> tuple:
    """Hämtar en bild från en http(s)-adress. Returnerar (filändelse, bytes) eller reser ValueError med ett
    meddelande på svenska. Bara vanliga portar, bara publika adresser (även efter omdirigeringar), högst 3 MB."""
    url = str(url or "").strip()
    deadline = time.monotonic() + total
    for _ in range(4):   # första adressen + upp till tre omdirigeringar
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise ValueError("Webbadressen ser inte ut att vara giltig.") from None
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("Skriv en hel webbadress som börjar med http:// eller https://")
        https = parts.scheme == "https"
        if port is not None and port not in ALLOWED_PORTS:
            raise ValueError("Bara vanliga webbportar kan användas.")
        port = port or (443 if https else 80)
        ip = _public_ip(parts.hostname, port)
        conn = (_PinnedHTTPS if https else _PinnedHTTP)(parts.hostname, ip, port, timeout)
        try:
            path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
            conn.request("GET", path, headers={"User-Agent": "Hemskola/1.0", "Accept": "image/*"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    raise ValueError("Adressen omdirigerar men säger inte vart.")
                url = urljoin(url, location)
                continue
            if resp.status != 200:
                raise ValueError(f"Servern svarade med fel ({resp.status}).")
            data = b""
            while len(data) <= MAX_IMAGE:
                chunk = resp.read(65536)
                if not chunk:
                    break
                data += chunk
                if time.monotonic() > deadline:
                    raise ValueError("Det tog för lång tid att hämta bilden.")
        except (OSError, http.client.HTTPException):
            raise ValueError("Kunde inte hämta bilden från adressen.") from None
        finally:
            conn.close()
        if len(data) > MAX_IMAGE:
            raise ValueError("Bilden är större än 3 MB.")
        ext = sniff_image(data)
        if not ext:
            raise ValueError("Adressen gav ingen bild (png, jpg, gif eller webp).")
        return ext, data
    raise ValueError("Adressen omdirigerar för många gånger.")
