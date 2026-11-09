"""Hemskola – FastAPI-app för hemmaövningar med adaptiv nivå."""
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db as database
from . import logic
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
        if os.environ.get("SEED_ON_START", "1") == "1" and not conn.execute(
            "SELECT 1 FROM exercises LIMIT 1"
        ).fetchone():
            for f in sorted((BASE / "seed").glob("*.json")):
                result = logic.import_exercises(conn, json.loads(f.read_text(encoding="utf-8")))
                print(f"Seed {f.name}: {result['added']} övningar", flush=True)
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
    subjects = []
    for s in logic.active_subjects(db):
        level = logic.get_level(db, user["id"], s)
        subjects.append({
            "key": s, "level": level,
            "dots": logic.window_results(db, user["id"], s),
        })
    streak, count_today = logic.streak_and_today(db, user["id"])
    open_test = db.execute(
        "SELECT id, subject FROM tests WHERE user_id=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1",
        (user["id"],),
    ).fetchone()
    return render(request, "home.html", subjects=subjects, streak=streak, count_today=count_today,
                  open_test=open_test)


@app.get("/practice/{subject}")
def practice(request: Request, subject: str, user=Depends(student_user), db=Depends(database.get_db)):
    level = logic.get_level(db, user["id"], subject)
    if level is None:
        return go("/home")
    ex_id = logic.pick_exercise(db, user["id"], subject)
    if ex_id is None:
        flash(request, "Det finns inga övningar i det här ämnet än.", "warn")
        return go("/home")
    ex = logic.exercise_row(db, ex_id)
    return render(request, "question.html", ex=ex, options=_options(ex), action=f"/practice/{subject}",
                  mode="practice", level=level, window=logic.window_results(db, user["id"], subject))


def _options(ex):
    if ex["type"] != "mc":
        return None
    import random
    opts = json.loads(ex["options"])
    random.shuffle(opts)
    return opts


@app.post("/practice/{subject}")
def practice_answer(subject: str, exercise_id: int = Form(...), given: str = Form(""),
                    user=Depends(student_user), db=Depends(database.get_db)):
    ex = logic.exercise_row(db, exercise_id)
    if not ex or ex["subject"] != subject or not given.strip():
        return go(f"/practice/{subject}")
    attempt_id, _, change = logic.record_attempt(db, user["id"], ex, given)
    return go(f"/answer/{attempt_id}" + (f"?change={change}" if change else ""))


@app.get("/answer/{attempt_id}")
def answer_page(request: Request, attempt_id: int, change: str = "", user=Depends(student_user),
                db=Depends(database.get_db)):
    a = db.execute("SELECT * FROM attempts WHERE id=? AND user_id=? AND test_id IS NULL",
                   (attempt_id, user["id"])).fetchone()
    if not a:
        raise HTTPException(404)
    ex = logic.exercise_row(db, a["exercise_id"])
    level = logic.get_level(db, user["id"], ex["subject"])
    return render(request, "answer.html", a=a, ex=ex, answers=json.loads(ex["answers"]),
                  change=change if change in ("up", "down") else "", level=level,
                  window=logic.window_results(db, user["id"], ex["subject"]))


# ---------------------------------------------------------------- prov

@app.post("/test/start/{subject}")
def test_start(request: Request, subject: str, user=Depends(student_user), db=Depends(database.get_db)):
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
    pos, ex = nxt
    return render(request, "question.html", ex=ex, options=_options(ex), action=f"/test/{test_id}",
                  mode="test", test=t, pos=pos)


@app.post("/test/{test_id}")
def test_answer(test_id: int, exercise_id: int = Form(...), given: str = Form(""),
                user=Depends(student_user), db=Depends(database.get_db)):
    t = _own_test(db, test_id, user)
    if t["finished_at"]:
        return go(f"/test/{test_id}/result")
    nxt = logic.next_test_item(db, test_id)
    if nxt and nxt[1]["id"] == exercise_id and given.strip():
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
        students.append({
            "u": s, "streak": streak, "today": count_today,
            "subjects": [logic.subject_summary(db, s["id"], sub) for sub in subjects],
        })
    return render(request, "admin_home.html", students=students)


@app.get("/admin/student/{student_id}")
def admin_student(request: Request, student_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    s = db.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if not s:
        raise HTTPException(404)
    subjects = logic.active_subjects(db)
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
        """SELECT a.created_at, a.given, a.correct, a.test_id, e.question, e.subject, e.topic, e.level, e.answers
           FROM attempts a JOIN exercises e ON e.id=a.exercise_id
           WHERE a.user_id=? ORDER BY a.id DESC LIMIT 40""", (student_id,)).fetchall()
    chart = logic.daily_chart(db, student_id)
    streak, count_today = logic.streak_and_today(db, student_id)
    return render(request, "admin_student.html", s=s, blocks=blocks, recent=recent, chart=chart,
                  chart_max=max([c["total"] for c in chart] + [1]), streak=streak, today=count_today,
                  json=json)


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
    sql += " GROUP BY e.id ORDER BY e.subject, e.level, e.topic, e.id"
    rows = db.execute(sql, params).fetchall()
    counts = db.execute(
        "SELECT subject, level, COUNT(*) AS n FROM exercises WHERE active=1 GROUP BY subject, level").fetchall()
    grid = {}
    for r in counts:
        grid.setdefault(r["subject"], {})[r["level"]] = r["n"]
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
    for r in db.execute("SELECT * FROM exercises ORDER BY subject, level, id"):
        d = {"subject": r["subject"], "topic": r["topic"], "level": r["level"], "type": r["type"],
             "question": r["question"], "answer": json.loads(r["answers"]), "explanation": r["explanation"]}
        if r["options"]:
            d["options"] = json.loads(r["options"])
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
        result = logic.import_exercises(db, json.loads(text))
    except (ValueError, json.JSONDecodeError) as e:
        flash(request, f"Kunde inte läsa JSON: {e}", "warn")
        return go("/admin/import")
    return render(request, "admin_import.html", result=result)
