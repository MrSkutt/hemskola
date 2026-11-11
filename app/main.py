"""Hemskola – FastAPI-app för hemmaövningar med adaptiv nivå."""
import json
import os
import random
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db as database
from . import facts, logic, report
from . import words as wordlist
from .security import hash_password, verify_password

BASE = Path(__file__).parent


# ---------------------------------------------------------------- start

def _secret_key() -> str:
    env = os.environ.get("SECRET_KEY")
    if env:
        return env
    path = Path(os.environ.get("SECRET_FILE", Path(database.DB_PATH).parent / "secret.key"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    os.chmod(path, 0o600)
    return key


def bootstrap() -> None:
    database.init_db()
    conn = database.connect()
    try:
        if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            name = os.environ.get("ADMIN_USER", "admin")
            password = os.environ.get("ADMIN_PASSWORD")
            if not password:
                password = secrets.token_urlsafe(9)
                print(f"\n*** Adminkonto skapat. Användare: {name}  Lösenord: {password} ***\n", flush=True)
            conn.execute(
                "INSERT INTO users(username, display_name, password_hash, role) VALUES (?,?,?,'admin')",
                (name, "Admin", hash_password(password)),
            )
            conn.commit()
        if os.environ.get("SEED_ON_START", "1") == "1":
            # Idempotent: redan inlagda övningar och ord hoppas över, så nya startmaterial kommer med vid uppgradering.
            seeds = sorted((BASE / "seed").glob("*.json"))
            for f in seeds:
                logic.adopt_legacy_exercises(conn, json.loads(f.read_text(encoding="utf-8")))
            logic.migrate_legacy_levels(conn)
            conn.commit()
            for f in seeds:
                result = logic.import_bundle(conn, json.loads(f.read_text(encoding="utf-8")))
                if result["added"] or result["words_added"]:
                    print(f"Seed {f.name}: {result['added']} övningar, {result['words_added']} ord", flush=True)
        logic.ensure_generator_exercises(conn)
        logic.cleanup_generated(conn)
        install_seed_media()
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    yield


app = FastAPI(title="Hemskola", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=_secret_key(),
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=os.environ.get("COOKIE_SECURE", "0") == "1",
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(label=logic.label, LEVEL_HINTS=logic.LEVEL_HINTS, WINDOW=logic.WINDOW)
templates.env.filters["fmt"] = facts.fmt
templates.env.filters["dt"] = lambda v: v.strftime("%Y-%m-%d %H:%M") if v else "–"
templates.env.filters["day"] = lambda v: v.strftime("%Y-%m-%d") if v else "–"
templates.env.filters["ts"] = lambda s: logic.parse_ts(s).strftime("%Y-%m-%d %H:%M") if s else "–"


def render(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx["flash"] = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def flash(request: Request, text: str, kind: str = "ok") -> None:
    request.session["flash"] = {"text": text, "kind": kind}


def go(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- auth

class LoginRequired(Exception):
    pass


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return go("/login")


def current_user(request: Request, db=Depends(database.get_db)):
    uid = request.session.get("uid")
    row = db.execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone() if uid else None
    if not row:
        request.session.clear()
        raise LoginRequired()
    request.state.user = row
    return row


def student_user(user=Depends(current_user)):
    if user["role"] != "student":
        raise HTTPException(403, "Bara för elever")
    return user


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Bara för admin")
    return user


_failed: dict = {}


def _too_many(ip: str) -> bool:
    now = time.time()
    _failed[ip] = [t for t in _failed.get(ip, []) if now - t < 600]
    return len(_failed[ip]) >= 10


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/login")
def login_form(request: Request):
    return render(request, "login.html", user=None)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db=Depends(database.get_db)):
    ip = request.client.host if request.client else "?"
    if _too_many(ip):
        return render(request, "login.html", status_code=429, user=None,
                      error="För många felaktiga försök. Vänta en stund och försök igen.")
    row = db.execute("SELECT * FROM users WHERE username=? AND active=1", (username.strip(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        _failed.setdefault(ip, []).append(time.time())
        return render(request, "login.html", status_code=401, user=None, error="Fel användarnamn eller lösenord.")
    request.session.clear()
    request.session["uid"] = row["id"]
    return go("/")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return go("/login")


@app.get("/")
def index(user=Depends(current_user)):
    return go("/admin" if user["role"] == "admin" else "/home")


# ---------------------------------------------------------------- elev

@app.get("/home")
def home(request: Request, user=Depends(student_user), db=Depends(database.get_db)):
    shown = [s for s in logic.enabled_subjects(db, user["id"]) if s in logic.active_subjects(db)]
    groups = logic.group_subjects(shown)
    for g in groups:
        g["items"] = [{"key": s, "level": logic.get_level(db, user["id"], s),
                       "dots": logic.window_results(db, user["id"], s)} for s in g["subjects"]]
    streak, count_today = logic.streak_and_today(db, user["id"])
    open_test = None
    for t in db.execute(
            "SELECT id, subject FROM tests WHERE user_id=? AND finished_at IS NULL ORDER BY id DESC", (user["id"],)):
        if logic.subject_enabled(db, user["id"], t["subject"]):   # prov i avstängda ämnen visas inte
            open_test = t
            break
    return render(request, "home.html", groups=groups, streak=streak, count_today=count_today,
                  open_test=open_test, has_facts=facts.available())


@app.get("/practice/{subject}")
def practice(request: Request, subject: str, user=Depends(student_user), db=Depends(database.get_db)):
    if not logic.subject_enabled(db, user["id"], subject):
        flash(request, "Det här ämnet är inte på just nu.", "warn")
        return go("/home")
    level = logic.get_level(db, user["id"], subject)
    if level is None:
        return go("/home")
    item = logic.next_item(db, user["id"], subject)
    if item is None:
        flash(request, "Det finns inga övningar i det här ämnet än.", "warn")
        return go("/home")
    return render(request, "question.html", ex=item, options=_shuffled(item), action=f"/practice/{subject}",
                  mode="practice", level=level, window=logic.window_results(db, user["id"], subject),
                  facts_subject=subject if facts.exists(subject) else None)


def _shuffled(item):
    if not item["options"]:
        return None
    opts = list(item["options"])
    random.shuffle(opts)
    return opts


@app.post("/practice/{subject}")
def practice_answer(subject: str, exercise_id: int = Form(...), generated_id: str = Form(""), given: str = Form(""),
                    user=Depends(student_user), db=Depends(database.get_db)):
    if not logic.subject_enabled(db, user["id"], subject):
        return go("/home")
    item = logic.resolve_item(db, user["id"], exercise_id, int(generated_id) if generated_id.isdigit() else None)
    if not item or item["subject"] != subject or not given.strip():
        return go(f"/practice/{subject}")
    attempt_id, _, change = logic.record_attempt(db, user["id"], item, given)
    return go(f"/answer/{attempt_id}" + (f"?change={change}" if change else ""))


@app.get("/answer/{attempt_id}")
def answer_page(request: Request, attempt_id: int, change: str = "", user=Depends(student_user),
                db=Depends(database.get_db)):
    a = db.execute("SELECT * FROM attempts WHERE id=? AND user_id=? AND test_id IS NULL",
                   (attempt_id, user["id"])).fetchone()
    if not a:
        raise HTTPException(404)
    item = (logic.item_from_generated(db, a["generated_id"]) if a["generated_id"]
            else logic.item_from_exercise(logic.exercise_row(db, a["exercise_id"])))
    level = logic.get_level(db, user["id"], item["subject"])
    return render(request, "answer.html", a=a, ex=item, answers=item["answers"],
                  change=change if change in ("up", "down") else "", level=level,
                  window=logic.window_results(db, user["id"], item["subject"]))


# ---------------------------------------------------------------- fakta

def _fact_subjects(db, user) -> list:
    """Ämnen med faktasida som användaren får se (elever: bara de ämnen som är påslagna för dem)."""
    have = facts.available()
    if user["role"] == "student":
        return [s for s in logic.enabled_subjects(db, user["id"]) if s in have]
    return logic.ordered_subjects(have)


@app.get("/fakta")
def facts_index(request: Request, user=Depends(current_user), db=Depends(database.get_db)):
    groups = logic.group_subjects(_fact_subjects(db, user))
    for g in groups:
        g["items"] = []
        for s in g["subjects"]:
            page = facts.load(s)
            g["items"].append({"key": s, "intro": page["intro"], "sections": page["sections"]})
    return render(request, "facts_index.html", groups=groups)


@app.get("/fakta/{subject}")
def facts_page(request: Request, subject: str, user=Depends(current_user), db=Depends(database.get_db)):
    if subject not in _fact_subjects(db, user):
        raise HTTPException(404)
    return render(request, "facts_page.html", subject=subject, page=facts.load(subject))


# ---------------------------------------------------------------- prov

@app.post("/test/start/{subject}")
def test_start(request: Request, subject: str, user=Depends(student_user), db=Depends(database.get_db)):
    if not logic.subject_enabled(db, user["id"], subject):
        flash(request, "Det här ämnet är inte på just nu.", "warn")
        return go("/home")
    open_test = db.execute(
        "SELECT id FROM tests WHERE user_id=? AND subject=? AND finished_at IS NULL",
        (user["id"], subject),
    ).fetchone()
    if open_test:
        return go(f"/test/{open_test['id']}")
    test_id = logic.create_test(db, user["id"], subject)
    if test_id is None:
        flash(request, "Det finns inga övningar i det här ämnet än.", "warn")
        return go("/home")
    return go(f"/test/{test_id}")


def _own_test(db, test_id, user):
    t = db.execute("SELECT * FROM tests WHERE id=? AND user_id=?", (test_id, user["id"])).fetchone()
    if not t:
        raise HTTPException(404)
    return t


@app.get("/test/{test_id}")
def test_page(request: Request, test_id: int, user=Depends(student_user), db=Depends(database.get_db)):
    t = _own_test(db, test_id, user)
    if t["finished_at"]:
        return go(f"/test/{test_id}/result")
    nxt = logic.next_test_item(db, test_id)
    if not nxt:
        logic.finish_test(db, test_id)
        return go(f"/test/{test_id}/result")
    pos, item = nxt
    return render(request, "question.html", ex=item, options=_shuffled(item), action=f"/test/{test_id}",
                  mode="test", test=t, pos=pos)


@app.post("/test/{test_id}")
def test_answer(test_id: int, exercise_id: int = Form(...), generated_id: str = Form(""), given: str = Form(""),
                user=Depends(student_user), db=Depends(database.get_db)):
    t = _own_test(db, test_id, user)
    if t["finished_at"]:
        return go(f"/test/{test_id}/result")
    nxt = logic.next_test_item(db, test_id)
    gid = int(generated_id) if generated_id.isdigit() else None
    if nxt and nxt[1]["id"] == exercise_id and nxt[1]["generated_id"] == gid and given.strip():
        logic.record_attempt(db, user["id"], nxt[1], given, test_id=test_id)
    return go(f"/test/{test_id}")


@app.get("/test/{test_id}/result")
def test_result(request: Request, test_id: int, user=Depends(student_user), db=Depends(database.get_db)):
    t = _own_test(db, test_id, user)
    if not t["finished_at"]:
        return go(f"/test/{test_id}")
    return render(request, "test_result.html", t=t, per=logic.test_breakdown(db, test_id),
                  review=logic.test_review(db, test_id), admin_view=False)


# ---------------------------------------------------------------- admin

@app.get("/admin")
def admin_home(request: Request, user=Depends(admin_user), db=Depends(database.get_db)):
    subjects = logic.active_subjects(db)
    students = []
    for s in db.execute("SELECT * FROM users WHERE role='student' ORDER BY active DESC, display_name"):
        streak, count_today = logic.streak_and_today(db, s["id"])
        settings = logic.subject_settings(db, s["id"], subjects)
        groups = logic.group_subjects(sub for sub in subjects if settings[sub]["enabled"])
        for g in groups:
            g["rows"] = [logic.subject_summary(db, s["id"], sub) for sub in g["subjects"]]
        students.append({
            "u": s, "streak": streak, "today": count_today, "groups": groups,
            "off": [sub for sub in logic.ordered_subjects(subjects) if not settings[sub]["enabled"]],
        })
    return render(request, "admin_home.html", students=students)


@app.get("/admin/student/{student_id}")
def admin_student(request: Request, student_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    s = db.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if not s:
        raise HTTPException(404)
    subjects = logic.ordered_subjects(logic.active_subjects(db))
    settings = logic.subject_settings(db, student_id, subjects)
    groups = logic.group_subjects(subjects)
    for g in groups:
        g["all_enabled"] = all(settings[x]["enabled"] for x in g["subjects"])
        g["all_report"] = all(settings[x]["in_report"] for x in g["subjects"])
    blocks = []
    for sub in subjects:
        tests = db.execute(
            "SELECT * FROM tests WHERE user_id=? AND subject=? AND finished_at IS NOT NULL ORDER BY id DESC",
            (student_id, sub)).fetchall()
        blocks.append({
            "subject": sub,
            "summary": logic.subject_summary(db, student_id, sub),
            "topics": logic.topic_stats(db, student_id, sub),
            "tests": tests,
        })
    recent = db.execute(
        """SELECT a.created_at, a.given, a.correct, a.test_id, COALESCE(g.question, e.question) AS question,
                  e.subject, e.topic, e.level, COALESCE(g.answers, e.answers) AS answers
           FROM attempts a JOIN exercises e ON e.id=a.exercise_id LEFT JOIN generated g ON g.id=a.generated_id
           WHERE a.user_id=? ORDER BY a.id DESC LIMIT 40""", (student_id,)).fetchall()
    chart = logic.daily_chart(db, student_id)
    streak, count_today = logic.streak_and_today(db, student_id)
    return render(request, "admin_student.html", s=s, blocks=blocks, recent=recent, chart=chart,
                  chart_max=max([c["total"] for c in chart] + [1]), streak=streak, today=count_today,
                  json=json, groups=groups, settings=settings, bmap={b["subject"]: b for b in blocks})


@app.get("/admin/student/{student_id}/report.pdf")
def admin_student_report(student_id: int, days: int = 30, subjects: list[str] = Query(default=None),
                         user=Depends(admin_user), db=Depends(database.get_db)):
    s = db.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if not s:
        raise HTTPException(404)
    if days not in report.PERIODS:
        days = 30
    chosen = None   # utan val i formuläret gäller elevens sparade rapportval
    if subjects:
        known = set(logic.active_subjects(db))
        chosen = logic.ordered_subjects(x for x in set(subjects) if x in known) or None
    pdf = report.build_pdf(db, s, days, chosen)
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", s["username"]) or "elev"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="rapport_{name}_{logic.today().isoformat()}.pdf"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.post("/admin/student/{student_id}/subjects")
def admin_set_subjects(request: Request, student_id: int, enabled: list[str] = Form(default=[]),
                       report_in: list[str] = Form(default=[], alias="report"),
                       user=Depends(admin_user), db=Depends(database.get_db)):
    if not db.execute("SELECT 1 FROM users WHERE id=? AND role='student'", (student_id,)).fetchone():
        raise HTTPException(404)
    subjects = logic.active_subjects(db)
    logic.save_subject_settings(db, student_id, enabled, report_in, subjects)
    db.commit()
    flash(request, "Ämnesvalen är sparade.")
    return go(f"/admin/student/{student_id}")


@app.post("/admin/student/{student_id}/level")
def admin_set_level(request: Request, student_id: int, subject: str = Form(...), level: int = Form(...),
                    user=Depends(admin_user), db=Depends(database.get_db)):
    if not db.execute("SELECT 1 FROM users WHERE id=? AND role='student'", (student_id,)).fetchone():
        raise HTTPException(404)
    logic.set_level(db, student_id, subject, level)
    db.commit()
    flash(request, f"Nivån i {logic.label(subject)} satt till {level}.")
    return go(f"/admin/student/{student_id}")


@app.get("/admin/test/{test_id}")
def admin_test(request: Request, test_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    t = db.execute("SELECT * FROM tests WHERE id=?", (test_id,)).fetchone()
    if not t or not t["finished_at"]:
        raise HTTPException(404)
    return render(request, "test_result.html", t=t, per=logic.test_breakdown(db, test_id),
                  review=logic.test_review(db, test_id), admin_view=True)


@app.get("/admin/users")
def admin_users(request: Request, user=Depends(admin_user), db=Depends(database.get_db)):
    users = db.execute("SELECT * FROM users ORDER BY role, display_name").fetchall()
    return render(request, "admin_users.html", users=users)


@app.post("/admin/users/new")
def admin_user_new(request: Request, username: str = Form(...), display_name: str = Form(...),
                   password: str = Form(...), role: str = Form("student"),
                   user=Depends(admin_user), db=Depends(database.get_db)):
    username, display_name = username.strip(), display_name.strip()
    if role not in ("student", "admin") or not username or not display_name or len(password) < 6:
        flash(request, "Fyll i alla fält. Lösenordet måste vara minst 6 tecken.", "warn")
        return go("/admin/users")
    try:
        db.execute("INSERT INTO users(username, display_name, password_hash, role) VALUES (?,?,?,?)",
                   (username, display_name, hash_password(password), role))
        db.commit()
    except Exception:
        flash(request, "Användarnamnet är redan taget.", "warn")
        return go("/admin/users")
    flash(request, f"Användaren {display_name} skapad.")
    return go("/admin/users")


@app.post("/admin/users/{uid}/password")
def admin_user_password(request: Request, uid: int, password: str = Form(...),
                        user=Depends(admin_user), db=Depends(database.get_db)):
    if len(password) < 6:
        flash(request, "Lösenordet måste vara minst 6 tecken.", "warn")
    else:
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), uid))
        db.commit()
        flash(request, "Lösenordet ändrat.")
    return go("/admin/users")


@app.post("/admin/users/{uid}/active")
def admin_user_active(request: Request, uid: int, user=Depends(admin_user), db=Depends(database.get_db)):
    if uid == user["id"]:
        flash(request, "Du kan inte stänga av dig själv.", "warn")
    else:
        db.execute("UPDATE users SET active = 1 - active WHERE id=?", (uid,))
        db.commit()
    return go("/admin/users")


@app.get("/admin/exercises")
def admin_exercises(request: Request, subject: str = "", level: int = 0, user=Depends(admin_user),
                    db=Depends(database.get_db)):
    sql = """SELECT e.*, COUNT(a.id) AS n, COALESCE(SUM(a.correct), 0) AS c
             FROM exercises e LEFT JOIN attempts a ON a.exercise_id=e.id WHERE 1=1"""
    params = []
    if subject:
        sql += " AND e.subject=?"
        params.append(subject)
    if level:
        sql += " AND e.level=?"
        params.append(level)
    sql += " GROUP BY e.id ORDER BY e.subject, e.level, e.generator IS NOT NULL, e.topic, e.id"
    rows = db.execute(sql, params).fetchall()
    counts = db.execute(
        """SELECT subject, level, generator IS NOT NULL AS gen, COUNT(*) AS n FROM exercises
           WHERE active=1 GROUP BY subject, level, gen""").fetchall()
    grid = {}
    for r in counts:
        cell = grid.setdefault(r["subject"], {}).setdefault(r["level"], {"static": 0, "gen": 0})
        cell["gen" if r["gen"] else "static"] = r["n"]
    return render(request, "admin_exercises.html", rows=rows, grid=grid, subject=subject, level=level,
                  subjects=logic.active_subjects(db))


@app.post("/admin/exercises/{ex_id}/active")
def admin_exercise_active(ex_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    db.execute("UPDATE exercises SET active = 1 - active WHERE id=?", (ex_id,))
    db.commit()
    return go("/admin/exercises")


@app.get("/admin/exercises/export.json")
def admin_export(user=Depends(admin_user), db=Depends(database.get_db)):
    out = []
    for r in db.execute("SELECT * FROM exercises WHERE generator IS NULL ORDER BY subject, level, id"):
        d = {"subject": r["subject"], "topic": r["topic"], "level": r["level"], "type": r["type"],
             "question": r["question"], "answer": json.loads(r["answers"]), "explanation": r["explanation"]}
        if r["options"]:
            d["options"] = json.loads(r["options"])
        if r["image"]:
            d["image"] = r["image"]
        if r["diagram"]:
            d["diagram"] = json.loads(r["diagram"])
        out.append(d)
    return JSONResponse(out, headers={"Content-Disposition": "attachment; filename=hemskola-ovningar.json"})


@app.get("/admin/import")
def admin_import_form(request: Request, user=Depends(admin_user)):
    return render(request, "admin_import.html")


@app.post("/admin/import")
async def admin_import(request: Request, pasted: str = Form(""), upload: UploadFile = File(None),
                       user=Depends(admin_user), db=Depends(database.get_db)):
    text = pasted.strip()
    if upload and upload.filename:
        text = (await upload.read(2_000_000)).decode("utf-8", errors="replace")
    if not text:
        flash(request, "Klistra in JSON eller välj en fil.", "warn")
        return go("/admin/import")
    try:
        result = logic.import_bundle(db, json.loads(text))
    except (ValueError, json.JSONDecodeError) as e:
        flash(request, f"Kunde inte läsa JSON: {e}", "warn")
        return go("/admin/import")
    return render(request, "admin_import.html", result=result)


# ---------------------------------------------------------------- ordlista

@app.get("/admin/words")
def admin_words(request: Request, pos: str = "", level: int = 0, user=Depends(admin_user),
                db=Depends(database.get_db)):
    sql, params = "SELECT * FROM words WHERE 1=1", []
    if pos:
        sql += " AND pos=?"
        params.append(pos)
    if level:
        sql += " AND level=?"
        params.append(level)
    rows = [dict(r, d=json.loads(r["data"])) for r in db.execute(sql + " ORDER BY pos, level, word", params)]
    counts = db.execute("SELECT pos, COUNT(*) AS n FROM words WHERE active=1 GROUP BY pos ORDER BY pos").fetchall()
    return render(request, "admin_words.html", rows=rows, counts=counts, pos=pos, level=level, POS=wordlist.POS)


@app.post("/admin/words/{word_id}/active")
def admin_word_active(word_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    db.execute("UPDATE words SET active = 1 - active WHERE id=?", (word_id,))
    db.commit()
    return go("/admin/words")


# ---------------------------------------------------------------- bilder

MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".svg": "image/svg+xml"}
MAX_UPLOAD = 3_000_000


def media_dir() -> Path:
    d = Path(os.environ.get("MEDIA_DIR") or Path(database.DB_PATH).parent / "media")
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_seed_media() -> None:
    """Kopierar medföljande exempelbilder till mediamappen. Befintliga filer skrivs aldrig över."""
    src = BASE / "seed" / "media"
    if not src.is_dir():
        return
    dest = media_dir()
    for f in src.iterdir():
        target = dest / f.name
        if f.is_file() and logic.MEDIA_NAME.match(f.name) and not target.exists():
            target.write_bytes(f.read_bytes())


def _looks_like(ext: str, data: bytes) -> bool:
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return data[:3] == b"\xff\xd8\xff"
    if ext == ".gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    if ext == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if ext == ".svg":
        low = data[:200000].lower()
        return b"<svg" in low[:2000] and not any(x in low for x in (b"<script", b"javascript:", b"onload", b"onerror", b"<foreignobject"))
    return False


@app.get("/media/{name}")
def media(name: str, user=Depends(current_user)):
    if not logic.MEDIA_NAME.match(name):
        raise HTTPException(404)
    path = media_dir() / name
    ctype = MEDIA_TYPES.get(path.suffix.lower())
    if not ctype or not path.is_file() or path.resolve().parent != media_dir().resolve():
        raise HTTPException(404)
    return FileResponse(path, media_type=ctype, headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})


@app.get("/admin/media")
def admin_media(request: Request, user=Depends(admin_user), db=Depends(database.get_db)):
    files = []
    for f in sorted(media_dir().iterdir()):
        if f.is_file() and f.suffix.lower() in MEDIA_TYPES:
            used = db.execute("SELECT COUNT(*) AS n FROM exercises WHERE image=?", (f.name,)).fetchone()["n"]
            files.append({"name": f.name, "size": f.stat().st_size // 1024, "used": used})
    return render(request, "admin_media.html", files=files)


@app.post("/admin/media")
async def admin_media_upload(request: Request, files: list[UploadFile] = File(default=[]), user=Depends(admin_user)):
    saved, problems = [], []
    for up in files:
        if not up.filename:
            continue
        ext = Path(up.filename).suffix.lower()
        name = re.sub(r"[^A-Za-z0-9._-]", "-", Path(up.filename).name.lower()).lstrip(".")[:100]
        data = await up.read(MAX_UPLOAD + 1)
        if ext not in MEDIA_TYPES or not name:
            problems.append(f"{up.filename}: filtypen stöds inte (png, jpg, gif, webp, svg)")
        elif len(data) > MAX_UPLOAD:
            problems.append(f"{up.filename}: filen är större än 3 MB")
        elif not _looks_like(ext, data):
            problems.append(f"{up.filename}: innehållet ser inte ut som {ext[1:]}")
        else:
            (media_dir() / name).write_bytes(data)
            saved.append(name)
    if saved:
        flash(request, "Uppladdat: " + ", ".join(saved) + ". Använd filnamnet i fältet \"image\" i övningar.")
    if problems:
        flash(request, " · ".join(problems), "warn")
    return go("/admin/media")


@app.post("/admin/media/{name}/delete")
def admin_media_delete(request: Request, name: str, user=Depends(admin_user), db=Depends(database.get_db)):
    if not logic.MEDIA_NAME.match(name):
        raise HTTPException(404)
    path = media_dir() / name
    if path.is_file() and path.resolve().parent == media_dir().resolve():
        used = db.execute("SELECT COUNT(*) AS n FROM exercises WHERE image=?", (name,)).fetchone()["n"]
        path.unlink()
        flash(request, f"{name} borttagen." + (f" Obs: {used} övningar hänvisade till bilden." if used else ""))
    return go("/admin/media")
