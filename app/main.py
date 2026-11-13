"""Hemskola – FastAPI-app för hemmaövningar med adaptiv nivå."""
import json
import os
import random
import re
import secrets
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode, quote, unquote, urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import db as database
from . import backup, diagrams, facts, logic, missed, motivation, report, tasks, themes, version, weekly
from . import exercise_editor as editor
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
    if backup.enabled():   # innan databasen uppgraderas: en kopia av data som den nya koden inte har rört
        backup.snapshot_before_update(version.info()["signature"])
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
    scheduler = backup.start_scheduler()
    yield
    backup.stop_scheduler(scheduler)


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
templates.env.globals.update(label=logic.label, label_inline=logic.label_inline, LEVEL_HINTS=logic.LEVEL_HINTS, WINDOW=logic.WINDOW,
                             version=version.info())
templates.env.filters["fmt"] = facts.fmt
templates.env.filters["fromjson"] = lambda v: json.loads(v) if v else []
templates.env.filters["dt"] = lambda v: v.strftime("%Y-%m-%d %H:%M") if v else "–"
templates.env.filters["day"] = lambda v: v.strftime("%Y-%m-%d") if v else "–"
templates.env.filters["ts"] = lambda s: logic.parse_ts(s).strftime("%Y-%m-%d %H:%M") if s else "–"


THEME_COOKIE = "hs_theme"


def _theme_key(request: Request, user) -> str:
    """Inloggad användares eget tema; annars det som senast valdes på den här enheten (så att inloggningssidan matchar)."""
    if user is not None:
        return themes.clean(user["theme"] if "theme" in user.keys() else None)
    return themes.clean(request.cookies.get(THEME_COOKIE))


def _remember_theme(resp, key: str):
    resp.set_cookie(THEME_COOKIE, key, max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True,
                    secure=os.environ.get("COOKIE_SECURE", "0") == "1")
    return resp


def render(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx["flash"] = request.session.pop("flash", None)
    ctx["theme"] = themes.get(_theme_key(request, ctx["user"]))
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
    request.state.task_badge = tasks.badge_count(db, row)
    request.state.reward_badge = motivation.pending_count(db) if row["role"] == "admin" else 0
    request.state.exercise_badge = editor.review_count(db) if row["role"] == "admin" else 0
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
    v = version.info()
    return {"ok": True, "version": v["release"], "signature": v["signature"]}


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
    return _remember_theme(go("/"), _theme_key(request, row))


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return go("/login")


# ---------------------------------------------------------------- app-ikon (Lägg till på hemskärmen)

ICONS = BASE / "static" / "icons"


@app.get("/manifest.webmanifest")
def web_manifest():
    """Gör att Hemskola kan läggas på hemskärmen som en app, med egen ikon och utan webbläsarens adressfält."""
    icon = lambda size, purpose: {"src": f"/static/icons/icon-{size}.png", "sizes": f"{size}x{size}",
                                  "type": "image/png", "purpose": purpose}
    return JSONResponse({
        "name": "Hemskola", "short_name": "Hemskola", "lang": "sv", "description": "Hemskola – övningar och uppgifter",
        "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#f6f7f4", "theme_color": "#2f7d5b",
        "icons": [icon(192, "any"), icon(512, "any"), icon(512, "maskable")],
    }, media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(ICONS / "favicon.ico", media_type="image/x-icon", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    """iOS frågar efter den här adressen om sidan saknar en egen länk, till exempel på felsidor."""
    return FileResponse(ICONS / "apple-touch-icon.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/tema")
def theme_page(request: Request, user=Depends(current_user)):
    return render(request, "tema.html", all_themes=themes.THEMES, current=_theme_key(request, user))


@app.post("/tema")
def theme_save(request: Request, theme: str = Form(""), user=Depends(current_user), db=Depends(database.get_db)):
    if theme not in themes.BY_KEY:
        flash(request, "Det temat finns inte.", "warn")
        return go("/tema")
    db.execute("UPDATE users SET theme=? WHERE id=?", (theme, user["id"]))
    db.commit()
    flash(request, f"Utseendet är nu {themes.get(theme)['name']}.")
    return _remember_theme(go("/tema"), theme)


@app.get("/")
def index(user=Depends(current_user)):
    return go("/admin" if user["role"] == "admin" else "/home")


# ---------------------------------------------------------------- elev

@app.get("/home")
def home(request: Request, user=Depends(student_user), db=Depends(database.get_db)):
    shown = [s for s in logic.enabled_subjects(db, user["id"]) if s in logic.active_subjects(db)]
    groups = logic.group_subjects(shown)
    prefs = logic.get_prefs(db, user["id"])
    for g in groups:
        g["items"] = [{"key": s, "level": logic.get_level(db, user["id"], s),
                       "dots": logic.window_results(db, user["id"], s),
                       "areas": logic.subject_areas(db, s) if prefs["areas_on"] else []} for s in g["subjects"]]
    streak, count_today = logic.streak_and_today(db, user["id"])
    open_test = None
    for t in db.execute(
            "SELECT id, subject FROM tests WHERE user_id=? AND finished_at IS NULL ORDER BY id DESC", (user["id"],)):
        if logic.subject_enabled(db, user["id"], t["subject"]):   # prov i avstängda ämnen visas inte
            open_test = t
            break
    left = missed.counts(db, user["id"])
    return render(request, "home.html", groups=groups, streak=streak, count_today=count_today,
                  open_test=open_test, has_facts=facts.available(), prog=_progress(db, user["id"], prefs),
                  missed_total=sum(left.values()), missed_by=sorted(left.items()))


def _progress(db, user_id: int, prefs: dict) -> dict:
    """Dagsmål, poäng, belöningar och märken som eleven ska se (det som är avstängt blir None)."""
    out = {"goal": None, "points": None, "rewards": None, "next": None, "badges": None, "earned": 0}
    if prefs["daily_goal"] > 0:
        out["goal"] = logic.goal_status(db, user_id, prefs)
    if prefs["points_on"]:
        out["points"] = motivation.points(db, user_id, prefs)
        out["rewards"] = motivation.reward_list(db, user_id, out["points"]["available"])
        out["next"] = motivation.next_reward(out["rewards"])
    if prefs["badges_on"]:
        out["badges"] = motivation.badges(db, user_id)
        out["earned"] = sum(1 for b in out["badges"] if b["earned"])
    out["any"] = bool(out["goal"] or out["points"] or out["badges"])
    return out


def _area_qs(area: str) -> str:
    return f"?omrade={quote(area)}" if area else ""


def _resolve_area(db, user_id: int, subject: str, wanted: str) -> str:
    """Det område eleven valt, om valet är på och området finns. 'svagast' blir elevens svagaste område."""
    if not wanted or not logic.get_prefs(db, user_id)["areas_on"]:
        return ""
    if wanted == "svagast":
        return logic.weakest_area(db, user_id, subject) or ""
    return wanted if wanted in {a["name"] for a in logic.subject_areas(db, subject)} else ""


@app.get("/practice/{subject}")
def practice(request: Request, subject: str, omrade: str = "", user=Depends(student_user),
             db=Depends(database.get_db)):
    if not logic.subject_enabled(db, user["id"], subject):
        flash(request, "Det här ämnet är inte på just nu.", "warn")
        return go("/home")
    level = logic.get_level(db, user["id"], subject)
    if level is None:
        return go("/home")
    area = _resolve_area(db, user["id"], subject, omrade)
    if omrade == "svagast" and not area:
        flash(request, "Du har inte svarat på tillräckligt många frågor för att hitta ditt svagaste område än. Här är alla områden.")
    item = logic.next_item(db, user["id"], subject, area or None)
    if item is None and area:
        flash(request, "Det finns inga frågor i det området än, så här är alla områden.", "warn")
        return go(f"/practice/{subject}")
    if item is None:
        flash(request, "Det finns inga övningar i det här ämnet än.", "warn")
        return go("/home")
    return render(request, "question.html", ex=item, options=_shuffled(item),
                  action=f"/practice/{subject}{_area_qs(area)}", mode="practice", level=level, area=area,
                  window=logic.window_results(db, user["id"], subject),
                  facts_subject=subject if facts.exists(subject) else None)


def _shuffled(item):
    if not item["options"]:
        return None
    opts = list(item["options"])
    random.shuffle(opts)
    return opts


@app.post("/practice/{subject}")
def practice_answer(subject: str, exercise_id: int = Form(...), generated_id: str = Form(""), given: str = Form(""),
                    omrade: str = Query(""), user=Depends(student_user), db=Depends(database.get_db)):
    if not logic.subject_enabled(db, user["id"], subject):
        return go("/home")
    item = logic.resolve_item(db, user["id"], exercise_id, int(generated_id) if generated_id.isdigit() else None)
    if not item or item["subject"] != subject or not given.strip():
        return go(f"/practice/{subject}{_area_qs(omrade)}")
    attempt_id, _, change = logic.record_attempt(db, user["id"], item, given)
    params = ([f"change={change}"] if change else []) + ([f"omrade={quote(omrade)}"] if omrade else [])
    return go(f"/answer/{attempt_id}" + ("?" + "&".join(params) if params else ""))


def _missed_subject(db, user_id: int, wanted: str) -> str:
    """Ämnet eleven valt att repetera, men bara om hon har det påslaget (annars alla ämnen)."""
    return wanted if wanted in logic.enabled_subjects(db, user_id) else ""


@app.get("/missat")
def missed_page(request: Request, amne: str = "", user=Depends(student_user), db=Depends(database.get_db)):
    """Öva på det jag missat: en fråga i taget ur det eleven svarat fel på, tills hon klarat dem."""
    amne = _missed_subject(db, user["id"], amne)
    state = missed.next_missed(db, user["id"], amne)
    item = state["item"]
    if item is None:
        return render(request, "missed_done.html", remaining=state["remaining"], paused=state["paused"], amne=amne)
    return render(request, "question.html", ex=item, options=_shuffled(item), mode="missed",
                  action="/missat" + (f"?amne={quote(amne)}" if amne else ""), level=logic.get_level(db, user["id"], item["subject"]),
                  area="", remaining=state["remaining"], window=[],
                  facts_subject=item["subject"] if facts.exists(item["subject"]) else None)


@app.post("/missat")
def missed_answer(exercise_id: int = Form(...), generated_id: str = Form(""), given: str = Form(""),
                  amne: str = Query(""), user=Depends(student_user), db=Depends(database.get_db)):
    amne = _missed_subject(db, user["id"], amne)
    item = logic.resolve_item(db, user["id"], exercise_id, int(generated_id) if generated_id.isdigit() else None)
    back = "/missat" + (f"?amne={quote(amne)}" if amne else "")
    if not item or not logic.subject_enabled(db, user["id"], item["subject"]) or not given.strip():
        return go(back)
    attempt_id, _, change = logic.record_attempt(db, user["id"], item, given)
    params = ([f"change={change}"] if change else []) + ["fran=missat"] + ([f"amne={quote(amne)}"] if amne else [])
    return go(f"/answer/{attempt_id}?" + "&".join(params))


@app.get("/answer/{attempt_id}")
def answer_page(request: Request, attempt_id: int, change: str = "", omrade: str = "", fran: str = "",
                amne: str = "", user=Depends(student_user), db=Depends(database.get_db)):
    a = db.execute("SELECT * FROM attempts WHERE id=? AND user_id=? AND test_id IS NULL",
                   (attempt_id, user["id"])).fetchone()
    if not a:
        raise HTTPException(404)
    item = (logic.item_from_generated(db, a["generated_id"]) if a["generated_id"]
            else logic.item_from_exercise(logic.exercise_row(db, a["exercise_id"])))
    level = logic.get_level(db, user["id"], item["subject"])
    from_missed = fran == "missat"
    amne = _missed_subject(db, user["id"], amne)
    return render(request, "answer.html", a=a, ex=item, answers=item["answers"],
                  change=change if change in ("up", "down") else "", level=level, area=omrade[:80],
                  window=logic.window_results(db, user["id"], item["subject"]),
                  from_missed=from_missed, amne=amne,
                  remaining=len(missed.missed_items(db, user["id"], amne)) if from_missed else 0)


@app.get("/framsteg")
def progress_page(request: Request, user=Depends(student_user), db=Depends(database.get_db)):
    prog = _progress(db, user["id"], logic.get_prefs(db, user["id"]))
    if not prog["any"]:
        return go("/home")
    return render(request, "progress.html", prog=prog, rules=motivation.RULES)


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
            "week": weekly.week_summary(db, s["id"]) if s["active"] else None,
            "off": [sub for sub in logic.ordered_subjects(subjects) if not settings[sub]["enabled"]],
        })
    return render(request, "admin_home.html", students=students, reward_requests=motivation.pending_requests(db),
                  backup_stale=backup.stale())


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
    prefs = logic.get_prefs(db, student_id)
    pts = motivation.points(db, student_id, prefs)
    rewards = motivation.reward_list(db, student_id, pts["balance"])
    return render(request, "admin_student.html", s=s, blocks=blocks, recent=recent, chart=chart,
                  prefs=prefs, pts=pts, rewards=rewards,
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


def _require_student(db, student_id: int) -> None:
    if not db.execute("SELECT 1 FROM users WHERE id=? AND role='student'", (student_id,)).fetchone():
        raise HTTPException(404)


@app.post("/admin/student/{student_id}/prefs")
def admin_set_prefs(request: Request, student_id: int, daily_goal: str = Form("0"), areas_on: str = Form(""),
                    points_on: str = Form(""), badges_on: str = Form(""),
                    user=Depends(admin_user), db=Depends(database.get_db)):
    _require_student(db, student_id)
    goal = int(daily_goal) if daily_goal.strip().isdigit() else 0
    logic.save_prefs(db, student_id, bool(areas_on), goal, bool(points_on), bool(badges_on))
    db.commit()
    flash(request, "Inställningarna är sparade.")
    return go(f"/admin/student/{student_id}#motivation")


@app.post("/framsteg/belonning/{reward_id}/be-om")
def student_request_reward(request: Request, reward_id: int, quantity: str = Form("1"),
                           user=Depends(student_user), db=Depends(database.get_db)):
    if not logic.get_prefs(db, user["id"])["points_on"]:
        raise HTTPException(403, "Poäng och belöningar är avstängda")
    error = motivation.request_reward(db, user["id"], reward_id, quantity)
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        flash(request, "Din förfrågan är skickad! När admin godkänt den dras poängen.")
    return go("/framsteg#belonningar")


@app.post("/framsteg/forfragan/{request_id}/ta-tillbaka")
def student_cancel_request(request: Request, request_id: int, user=Depends(student_user),
                           db=Depends(database.get_db)):
    error = motivation.cancel_request(db, user["id"], request_id)
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        flash(request, "Du tog tillbaka förfrågan. Poängen är dina igen.")
    return go("/framsteg#belonningar")


@app.post("/admin/belonningar/{request_id}/{action}")
def admin_handle_reward_request(request: Request, request_id: int, action: str, back: str = Form(""),
                                user=Depends(admin_user), db=Depends(database.get_db)):
    if action not in ("godkann", "avsla"):
        raise HTTPException(404)
    q = db.execute(
        "SELECT q.quantity, r.title, r.cost, u.display_name FROM reward_requests q JOIN rewards r ON r.id=q.reward_id "
        "JOIN users u ON u.id=q.user_id WHERE q.id=?", (request_id,)).fetchone()
    if not q:
        raise HTTPException(404, "Förfrågan finns inte")
    if action == "godkann":
        error = motivation.approve_request(db, request_id)
        done = (f"Godkänt. {q['display_name']} fick {q['quantity']} × {q['title']} och {q['cost'] * q['quantity']} poäng drogs."
                if q["quantity"] > 1 else f"Godkänt. {q['display_name']} fick {q['title']} och {q['cost']} poäng drogs.")
    else:
        error = motivation.decline_request(db, request_id)
        done = f"Avslagen. {q['display_name']} fick inte {q['title']} den här gången. Poängen är tillgängliga igen."
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        flash(request, done)
    return go(_back(back, "/admin", prefix="/admin"))


@app.post("/admin/student/{student_id}/rewards")
def admin_add_reward(request: Request, student_id: int, title: str = Form(""), cost: str = Form(""),
                     repeatable: str = Form(""), user=Depends(admin_user), db=Depends(database.get_db)):
    _require_student(db, student_id)
    error = motivation.add_reward(db, student_id, title, cost, repeatable=bool(repeatable))
    db.commit()
    flash(request, error or "Belöningen är tillagd.", "warn" if error else "ok")
    return go(f"/admin/student/{student_id}#motivation")


@app.post("/admin/student/{student_id}/rewards/{reward_id}")
def admin_reward_action(request: Request, student_id: int, reward_id: int, action: str = Form(...),
                        user=Depends(admin_user), db=Depends(database.get_db)):
    _require_student(db, student_id)
    error = ""
    if action == "give":
        error = motivation.give_reward(db, student_id, reward_id)
    elif action == "undo":
        motivation.undo_reward(db, student_id, reward_id)
    elif action == "delete":
        kept = motivation.delete_reward(db, student_id, reward_id)
        if kept:
            flash(request, f"Belöningen är borttagen. De {kept} poäng som redan använts på den dras fortfarande av.")
            db.commit()
            return go(f"/admin/student/{student_id}#motivation")
    else:
        raise HTTPException(400)
    db.commit()
    flash(request, error or "Klart.", "warn" if error else "ok")
    return go(f"/admin/student/{student_id}#motivation")


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


def _list_url(request: Request) -> str:
    """Den här listsidan med sina filter, så att man kommer tillbaka till samma ställe efter en ändring."""
    q = request.url.query
    return request.url.path + ("?" + q if q else "")


@app.get("/admin/exercises")
def admin_exercises(request: Request, subject: str = "", level: int = 0, topic: str = "", kind: str = "",
                    state: str = "", q: str = "", stat: str = "", sort: str = "", page: int = 1,
                    user=Depends(admin_user), db=Depends(database.get_db)):
    result = editor.search(db, q=q, subject=subject, level=level, topic=topic, kind=kind, state=state, page=page,
                           stat=stat, sort=sort)
    counts = db.execute(
        """SELECT subject, level, generator IS NOT NULL AS gen, COUNT(*) AS n FROM exercises
           WHERE active=1 GROUP BY subject, level, gen""").fetchall()
    grid = {}
    for r in counts:
        cell = grid.setdefault(r["subject"], {}).setdefault(r["level"], {"static": 0, "gen": 0})
        cell["gen" if r["gen"] else "static"] = r["n"]
    filters = {"q": q, "subject": subject, "level": level or "", "topic": topic if subject else "", "kind": kind,
               "state": state, "stat": stat, "sort": sort}
    base = urlencode({k: v for k, v in filters.items() if v})
    topics = editor.topics_by_subject(db).get(subject, []) if subject else []
    return render(request, "admin_exercises.html", result=result, grid=grid, subject=subject, level=level, q=q,
                  topic=topic if subject else "", kind=kind, state=state, kinds=editor.KINDS, topics=topics,
                  stat=stat, sort=sort, stats=editor.STATS, sorts=editor.SORTS, is_hard=editor.is_hard,
                  base=base, here=_list_url(request), subjects=[r["subject"] for r in db.execute(
                      "SELECT DISTINCT subject FROM exercises ORDER BY subject")], legacy=logic.LEGACY_SUBJECTS)


@app.post("/admin/exercises/{ex_id}/active")
def admin_exercise_active(ex_id: int, back: str = Form(""), user=Depends(admin_user),
                          db=Depends(database.get_db)):
    db.execute("UPDATE exercises SET active = 1 - active, review = 0 WHERE id=?", (ex_id,))
    db.commit()
    return go(_back(back, "/admin/exercises", prefix="/admin/exercises"))


@app.post("/admin/exercises/{ex_id}/approve")
def admin_exercise_approve(request: Request, ex_id: int, back: str = Form(""), user=Depends(admin_user),
                           db=Depends(database.get_db)):
    """Godkänner en importerad övning, så att eleverna kan få den."""
    if editor.approve(db, ex_id):
        db.commit()
    return go(_back(back, "/admin/exercises?state=review", prefix="/admin/exercises"))


@app.post("/admin/exercises/approve-all")
def admin_exercises_approve_all(request: Request, back: str = Form(""), subject: str = Form(""),
                                level: int = Form(0), topic: str = Form(""), kind: str = Form(""),
                                q: str = Form(""), user=Depends(admin_user), db=Depends(database.get_db)):
    """Godkänner alla övningar som väntar på granskning och matchar listans filter (alla sidor)."""
    n = editor.approve_matching(db, q=q, subject=subject, level=level, topic=topic, kind=kind)
    db.commit()
    flash(request, f"{n} övningar är godkända och syns nu för eleverna." if n else "Inget att godkänna.")
    return go(_back(back, "/admin/exercises?state=review", prefix="/admin/exercises"))


@app.post("/admin/exercises/{ex_id}/subject")
def admin_exercise_subject(request: Request, ex_id: int, subject: str = Form(""),
                           user=Depends(admin_user), db=Depends(database.get_db)):
    ex = db.execute("SELECT subject, question FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not ex:
        raise HTTPException(404, "Övningen finns inte")
    old = ex["subject"]
    error = logic.move_legacy_exercise(db, ex_id, subject)
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        flash(request, f"Flyttade övningen till {logic.label(subject)}.")
    left = db.execute("SELECT 1 FROM exercises WHERE subject=? LIMIT 1", (old,)).fetchone()
    return go(f"/admin/exercises?subject={old}" if left else "/admin/exercises")


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


# ---------------------------------------------------------------- säkerhetskopior

@app.get("/admin/backups")
def admin_backups(request: Request, user=Depends(admin_user)):
    items = backup.listing()
    return render(request, "admin_backups.html", items=items, enabled=backup.enabled(), stale=backup.stale(),
                  folder=str(backup.backup_dir()), keep=backup.KEEP, media_count=sum(1 for f in media_dir().iterdir() if f.is_file()),
                  night_hour=backup.NIGHT_HOUR)


@app.post("/admin/backups/now")
async def admin_backup_now(request: Request, user=Depends(admin_user)):
    try:
        dest = await run_in_threadpool(backup.make, "manuell")
    except Exception as e:
        flash(request, f"Det gick inte att ta någon säkerhetskopia: {e}", "warn")
    else:
        flash(request, f"Säkerhetskopian {dest.name} är tagen.")
    return go("/admin/backups")


@app.get("/admin/backups/helt.zip")
async def admin_backup_zip(user=Depends(admin_user)):
    """Databas och bilder i en zip, till exempel för att flytta systemet eller fylla en testmiljö."""
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "hemskola.zip"
    try:
        await run_in_threadpool(backup.full_zip, path, media_dir())
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return FileResponse(path, media_type="application/zip", filename=f"hemskola-allt-{time.strftime('%Y-%m-%d')}.zip",
                        background=BackgroundTask(shutil.rmtree, tmp, True))


@app.get("/admin/backups/{name}")
def admin_backup_download(name: str, user=Depends(admin_user)):
    path = backup.backup_dir() / name
    if not backup.NAME_RE.match(name) or not path.is_file():
        raise HTTPException(404, "Säkerhetskopian finns inte")
    return FileResponse(path, media_type="application/octet-stream", filename=name)


# ---------------------------------------------------------------- övningsredigerare

def _known_subjects(db) -> set:
    return {r["subject"] for r in db.execute("SELECT DISTINCT subject FROM exercises")}


def _exercise_page(request: Request, db, form: dict, ex=None, errors=None, dup=None, back: str = "",
                   status_code: int = 200):
    n = c = 0
    if ex:
        r = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(correct), 0) AS c FROM attempts WHERE exercise_id=?",
                       (ex["id"],)).fetchone()
        n, c = r["n"], r["c"]
    subjects = sorted(_known_subjects(db) | ({form["subject"]} if form["subject"] not in ("", editor.NEW_SUBJECT) else set()))
    return render(request, "admin_exercise.html", form=form, ex=ex, errors=errors or [], dup=dup, back=back,
                  subjects=subjects, topics=editor.topics_by_subject(db), media=_media_names(),
                  examples=diagrams.EXAMPLES, type_labels=diagrams.TYPE_LABELS, new_subject=editor.NEW_SUBJECT,
                  answered=n, percent=round(100 * c / n) if n else 0, status_code=status_code,
                  recent=editor.recent_attempts(db, ex["id"]) if ex else [])


@app.get("/admin/exercises/new")
def admin_exercise_new(request: Request, similar: int = 0, back: str = "", user=Depends(admin_user),
                       db=Depends(database.get_db)):
    form = editor.blank_form()
    src = db.execute("SELECT subject, level, topic, type FROM exercises WHERE id=?", (similar,)).fetchone() if similar else None
    if src:   # "Skapa en liknande": samma ämne, nivå, område och typ
        form.update(subject=src["subject"], level=src["level"], topic=src["topic"], type=src["type"])
    return _exercise_page(request, db, form, back=_back(back, "", prefix="/admin/exercises"))


@app.get("/admin/exercises/{ex_id}/edit")
def admin_exercise_edit(request: Request, ex_id: int, back: str = "", user=Depends(admin_user),
                        db=Depends(database.get_db)):
    ex = db.execute("SELECT * FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not ex:
        raise HTTPException(404, "Övningen finns inte")
    if ex["generator"]:
        flash(request, "Generatorer är kod och kan inte redigeras här. Du kan dölja dem.", "warn")
        return go(_back(back, "/admin/exercises", prefix="/admin/exercises"))
    return _exercise_page(request, db, editor.form_from_row(ex), ex=ex, back=_back(back, "", prefix="/admin/exercises"))


async def _save_exercise(request: Request, db, ex=None):
    data = await request.form()
    form = editor.form_from_post(data)
    back = _back(str(data.get("back", "")), "", prefix="/admin/exercises")
    if data.get("remove_image"):
        form["image"] = ""
    if data.get("approve"):          # "Spara och godkänn": övningen blir synlig för eleverna
        form["active"] = True
    upload = data.get("image_file")
    current = ex["image"] or "" if ex else ""
    # En bild som övningen redan har kontrolleras inte mot disken igen, så att övriga ändringar går att spara
    # även om bildfilen har tagits bort ur bildmappen.
    name, image_error = await _image_from_form(
        upload if getattr(upload, "filename", "") else None, str(data.get("image_url") or ""),
        "" if form["image"] == current else form["image"], prefix="ovning")
    if name:
        form["image"] = name
    row, errors = editor.build(form, _known_subjects(db))
    if image_error:
        row, errors = None, [image_error] + errors
    if errors:
        return _exercise_page(request, db, form, ex=ex, errors=errors, back=back, status_code=400)
    answered = editor.answer_count(db, ex["id"]) if ex else 0
    if ex is None:
        new_id, err, dup = editor.create_exercise(db, row, form["active"])
        done = "Övningen är sparad."
    elif data.get("replace") and answered:
        new_id, err, dup = editor.replace_exercise(db, ex["id"], row)
        done = "Den nya övningen är sparad och den gamla är dold."
    else:
        err, dup = editor.update_exercise(db, ex["id"], row, form["active"])
        new_id, done = ex["id"], "Ändringarna är sparade."
    if err:
        db.rollback()
        return _exercise_page(request, db, form, ex=ex, errors=[err], dup=dup, back=back, status_code=400)
    db.commit()
    if data.get("after") == "next":
        flash(request, done + " Här är nästa, med samma ämne, nivå och område.")
        return go(f"/admin/exercises/new?similar={new_id}" + (f"&back={quote(back)}" if back else ""))
    flash(request, done)
    return go(back or f"/admin/exercises?subject={quote(row['subject'])}&level={row['level']}")


@app.post("/admin/exercises/new")
async def admin_exercise_create(request: Request, user=Depends(admin_user), db=Depends(database.get_db)):
    return await _save_exercise(request, db)


@app.post("/admin/exercises/{ex_id}/edit")
async def admin_exercise_update(request: Request, ex_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    ex = db.execute("SELECT * FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not ex:
        raise HTTPException(404, "Övningen finns inte")
    if ex["generator"]:
        raise HTTPException(400, "Generatorer kan inte redigeras")
    return await _save_exercise(request, db, ex)


@app.post("/admin/exercises/{ex_id}/delete")
def admin_exercise_delete(request: Request, ex_id: int, back: str = Form(""), user=Depends(admin_user),
                          db=Depends(database.get_db)):
    error = editor.delete_exercise(db, ex_id)
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        flash(request, "Övningen är borttagen.")
    return go(_back(back, "/admin/exercises", prefix="/admin/exercises"))


@app.post("/admin/exercises/preview")
async def admin_exercise_preview(request: Request, user=Depends(admin_user), db=Depends(database.get_db)):
    """Övningen som eleven ser den, och eventuella fel. Svarar med en bit HTML som sidan lägger in (ingenting sparas)."""
    data = await request.form()
    form = editor.form_from_post(data)
    upload = data.get("image_file")
    row, errors = editor.build(form, _known_subjects(db))
    return templates.TemplateResponse(request, "_exercise_preview.html", {
        "item": editor.preview_item(row) if row else None, "errors": errors,
        "new_image": bool(getattr(upload, "filename", "") or str(data.get("image_url") or "").strip())})


@app.get("/admin/import")
def admin_import_form(request: Request, user=Depends(admin_user)):
    return render(request, "admin_import.html")


@app.post("/admin/import")
async def admin_import(request: Request, pasted: str = Form(""), upload: UploadFile = File(None),
                       review: str = Form(""), user=Depends(admin_user), db=Depends(database.get_db)):
    text = pasted.strip()
    if upload and upload.filename:
        text = (await upload.read(2_000_000)).decode("utf-8", errors="replace")
    if not text:
        flash(request, "Klistra in JSON eller välj en fil.", "warn")
        return go("/admin/import")
    try:
        result = logic.import_bundle(db, json.loads(text), review=bool(review))
    except (ValueError, json.JSONDecodeError) as e:
        flash(request, f"Kunde inte läsa JSON: {e}", "warn")
        return go("/admin/import")
    request.state.exercise_badge = editor.review_count(db)   # siffran i menyn ska stämma redan på den här sidan
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
            used_tasks = db.execute("SELECT COUNT(*) AS n FROM tasks WHERE image=?", (f.name,)).fetchone()["n"]
            files.append({"name": f.name, "size": f.stat().st_size // 1024, "used": used, "used_tasks": used_tasks})
    return render(request, "admin_media.html", files=files)


def _free_media_name(wanted: str, ext: str) -> str:
    """Ett ledigt filnamn i mediamappen av ett önskat namn (utan eller med filändelse) och den riktiga ändelsen.
    Befintliga filer skrivs aldrig över: är namnet upptaget läggs fyra slumpbokstäver till."""
    stem = Path(wanted).stem if Path(wanted).suffix.lower() in MEDIA_TYPES else wanted
    base = re.sub(r"[^A-Za-z0-9._-]", "-", stem.lower()).strip(".-_")[:80] or "bild"
    name = f"{base}{ext}"
    if (media_dir() / name).exists():
        name = f"{base}-{secrets.token_hex(2)}{ext}"
    return name


@app.post("/admin/media/url")
async def admin_media_from_url(request: Request, image_url: str = Form(""), name: str = Form(""),
                               user=Depends(admin_user)):
    url = image_url.strip()
    if not url:
        flash(request, "Klistra in en webbadress till en bild.", "warn")
        return go("/admin/media")
    try:
        ext, data = await run_in_threadpool(tasks.fetch_image, url)
    except ValueError as e:
        flash(request, str(e), "warn")
        return go("/admin/media")
    try:
        from_url = unquote(Path(urlsplit(url).path).name)
    except ValueError:
        from_url = ""
    wanted = name.strip() or from_url
    saved = _free_media_name(wanted, ext)
    (media_dir() / saved).write_bytes(data)
    flash(request, f"Hämtade bilden och sparade den som {saved}. Använd filnamnet i fältet \"image\" i övningar.")
    return go("/admin/media")


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
        used_tasks = db.execute("UPDATE tasks SET image=NULL WHERE image=?", (name,)).rowcount
        db.commit()
        path.unlink()
        notes = [f"{n} {one if n == 1 else many}" for n, one, many in ((used, "övning", "övningar"), (used_tasks, "uppgift", "uppgifter")) if n]
        flash(request, f"{name} borttagen." + (" Obs: bilden användes av " + " och ".join(notes) + "." if notes else ""))
    return go("/admin/media")


# ---------------------------------------------------------------- uppgifter

def _store_task_image(ext: str, data: bytes, prefix: str = "uppgift") -> str:
    name = f"{prefix}-{secrets.token_hex(5)}{ext}"
    (media_dir() / name).write_bytes(data)
    return name


def _drop_task_image(db, name) -> None:
    """Tar bort en uppladdad uppgiftsbild från disk när ingen uppgift använder den längre."""
    if not name or not name.startswith("uppgift-") or not logic.MEDIA_NAME.match(name):
        return
    if db.execute("SELECT 1 FROM tasks WHERE image=?", (name,)).fetchone() or \
            db.execute("SELECT 1 FROM exercises WHERE image=?", (name,)).fetchone():
        return   # bilden används fortfarande (bilder i mediamappen kan återanvändas)
    path = media_dir() / name
    if path.is_file() and path.resolve().parent == media_dir().resolve():
        path.unlink()


def _media_names() -> list:
    """Alla bilder i mediamappen (filnamn), för bildväljaren."""
    return sorted(f.name for f in media_dir().iterdir()
                  if f.is_file() and f.suffix.lower() in MEDIA_TYPES and logic.MEDIA_NAME.match(f.name))


async def _image_from_form(upload, url: str, existing: str = "", prefix: str = "uppgift") -> tuple:
    """(filnamn, fel). Filnamnet är '' om ingen bild angavs. Prioritet: uppladdad fil, webbadress, befintlig bild.
    En befintlig bild delas (ingen kopia görs), så den kan användas av flera uppgifter och övningar."""
    if upload is not None and upload.filename:
        ext = Path(upload.filename).suffix.lower()
        data = await upload.read(MAX_UPLOAD + 1)
        if ext not in MEDIA_TYPES:
            return "", "Bildens filtyp stöds inte (png, jpg, gif, webp, svg)."
        if len(data) > MAX_UPLOAD:
            return "", "Bilden är större än 3 MB."
        if not _looks_like(ext, data):
            return "", f"Filen ser inte ut som en {ext[1:]}-bild."
        return _store_task_image(ext, data, prefix), ""
    if url.strip():
        try:
            ext, data = await run_in_threadpool(tasks.fetch_image, url)
        except ValueError as e:
            return "", str(e)
        return _store_task_image(ext, data, prefix), ""
    existing = existing.strip()
    if existing:
        path = media_dir() / existing
        if not logic.MEDIA_NAME.match(existing) or path.suffix.lower() not in MEDIA_TYPES or not path.is_file() \
                or path.resolve().parent != media_dir().resolve():
            return "", "Den valda bilden finns inte längre."
        return existing, ""
    return "", ""


def _back(back: str, default: str, prefix: str = "/admin/uppgifter") -> str:
    """En återvändsadress från ett formulär, bara om den pekar inom admindelen (aldrig till en annan webbplats)."""
    return back if back.startswith(prefix) and "//" not in back and "\\" not in back else default


def _tasks_page(request: Request, db, form=None, status_code: int = 200):
    return render(request, "admin_tasks.html", queue=tasks.to_review(db), task_list=tasks.list_tasks(db),
                  form=form, media=_media_names(), status_code=status_code)


def _task_page(request: Request, db, task_id: int, form=None, status_code: int = 200):
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Uppgiften finns inte")
    rows = tasks.for_task(db, task_id)
    students = db.execute("SELECT id, display_name FROM users WHERE role='student' AND active=1 "
                          "ORDER BY display_name").fetchall()
    busy = {r["user_id"] for r in rows if r["status"] != "approved"}
    return render(request, "admin_task.html", task=task, rows=rows, students=students, busy=busy,
                  labels=tasks.STATUS_LABELS, form=form, media=_media_names(), status_code=status_code)


@app.get("/admin/uppgifter")
def admin_tasks(request: Request, user=Depends(admin_user), db=Depends(database.get_db)):
    return _tasks_page(request, db)


@app.post("/admin/uppgifter/ny")
async def admin_task_new(request: Request, title: str = Form(""), body: str = Form(""), points: str = Form("0"),
                         image_url: str = Form(""), image_existing: str = Form(""), in_report: str = Form(""),
                         image: UploadFile | None = File(None),
                         user=Depends(admin_user), db=Depends(database.get_db)):
    form = {"title": title, "body": body, "points": points, "image_url": image_url, "in_report": bool(in_report)}
    error = tasks.parse_task(title, body, points)[3]
    name = ""
    if not error:
        name, error = await _image_from_form(image, image_url, image_existing)
    if error:
        flash(request, error, "warn")
        return _tasks_page(request, db, form=form, status_code=400)
    task_id, _ = tasks.create_task(db, title, body, points, image=name or None, in_report=bool(in_report))
    db.commit()
    flash(request, "Uppgiften är skapad. Välj nedan vilka elever som ska få den.")
    return go(f"/admin/uppgifter/{task_id}")


@app.get("/admin/uppgifter/{task_id}")
def admin_task(request: Request, task_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    return _task_page(request, db, task_id)


@app.post("/admin/uppgifter/{task_id}")
async def admin_task_edit(request: Request, task_id: int, title: str = Form(""), body: str = Form(""),
                          points: str = Form("0"), image_url: str = Form(""), image_existing: str = Form(""),
                          remove_image: str = Form(""), in_report: str = Form(""),
                          image: UploadFile | None = File(None),
                          user=Depends(admin_user), db=Depends(database.get_db)):
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Uppgiften finns inte")
    form = {"title": title, "body": body, "points": points, "image_url": image_url, "in_report": bool(in_report)}
    error = tasks.parse_task(title, body, points)[3]
    name = ""
    if not error:
        name, error = await _image_from_form(image, image_url, image_existing)
    if error:
        flash(request, error, "warn")
        return _task_page(request, db, task_id, form=form, status_code=400)
    tasks.update_task(db, task_id, title, body, points, in_report=bool(in_report))
    old = task["image"]
    if name:
        db.execute("UPDATE tasks SET image=? WHERE id=?", (name, task_id))
    elif remove_image:
        db.execute("UPDATE tasks SET image=NULL WHERE id=?", (task_id,))
    db.commit()
    if old and old != name and (name or remove_image):
        _drop_task_image(db, old)
    flash(request, "Uppgiften är sparad. Redan givna uppgifter behåller de poäng de fick när de godkändes.")
    return go(f"/admin/uppgifter/{task_id}")


@app.post("/admin/uppgifter/{task_id}/tilldela")
def admin_task_assign(request: Request, task_id: int, students: list[int] = Form(default=[]),
                      user=Depends(admin_user), db=Depends(database.get_db)):
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Uppgiften finns inte")
    if not task["active"]:
        flash(request, "Uppgiften är arkiverad. Visa den igen om du vill ge den till fler.", "warn")
    elif not students:
        flash(request, "Välj minst en elev.", "warn")
    else:
        given, skipped = tasks.assign(db, task_id, students)
        db.commit()
        msg = ("Uppgiften gavs till " + ", ".join(given) + ". ") if given else ""
        if skipped:
            msg += "Hoppade över " + ", ".join(skipped) + " som redan har den."
        flash(request, msg.strip() or "Ingen elev fick uppgiften.", "ok" if given else "warn")
    return go(f"/admin/uppgifter/{task_id}")


@app.post("/admin/uppgifter/{task_id}/arkiv")
def admin_task_archive(task_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    db.execute("UPDATE tasks SET active = 1 - active WHERE id=?", (task_id,))
    db.commit()
    return go(f"/admin/uppgifter/{task_id}")


@app.post("/admin/uppgifter/{task_id}/ta-bort")
def admin_task_delete(request: Request, task_id: int, user=Depends(admin_user), db=Depends(database.get_db)):
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(404, "Uppgiften finns inte")
    if db.execute("SELECT 1 FROM task_assignments WHERE task_id=?", (task_id,)).fetchone():
        flash(request, "Uppgiften har getts till elever och kan inte tas bort. Arkivera den i stället.", "warn")
        return go(f"/admin/uppgifter/{task_id}")
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    db.commit()
    _drop_task_image(db, task["image"])
    flash(request, "Uppgiften är borttagen.")
    return go("/admin/uppgifter")


@app.post("/admin/uppgifter/tilldelning/{aid}/granska")
def admin_task_review(request: Request, aid: int, decision: str = Form(""), comment: str = Form(""),
                      back: str = Form(""), user=Depends(admin_user), db=Depends(database.get_db)):
    a = tasks.assignment(db, aid)
    if not a:
        raise HTTPException(404, "Tilldelningen finns inte")
    if decision not in ("approve", "reject"):
        raise HTTPException(400, "Välj godkänn eller avslå")
    error = tasks.review(db, aid, decision == "approve", comment)
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        if decision == "approve":
            flash(request, f"Godkänd. {a['student']} behåller sina poäng." if a["status"] == "approved"
                  else f"Godkänd. {a['student']} fick {a['points']} poäng.")
        else:
            flash(request, f"Avslagen. {a['student']} ser din kommentar och kan göra om uppgiften.")
    return go(_back(back, f"/admin/uppgifter/{a['task_id']}"))


@app.post("/admin/uppgifter/tilldelning/{aid}/ta-bort")
def admin_task_unassign(request: Request, aid: int, back: str = Form(""),
                        user=Depends(admin_user), db=Depends(database.get_db)):
    a = tasks.assignment(db, aid)
    if not a:
        raise HTTPException(404, "Tilldelningen finns inte")
    error = tasks.remove_assignment(db, aid)
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        flash(request, f"Uppgiften togs bort från {a['student']}.")
    return go(_back(back, f"/admin/uppgifter/{a['task_id']}"))


@app.get("/uppgifter")
def student_tasks(request: Request, user=Depends(student_user), db=Depends(database.get_db)):
    return render(request, "tasks.html", groups=tasks.for_student(db, user["id"]), labels=tasks.STATUS_LABELS,
                  show_points=bool(logic.get_prefs(db, user["id"])["points_on"]))


@app.get("/uppgifter/{aid}")
def student_task(request: Request, aid: int, user=Depends(student_user), db=Depends(database.get_db)):
    a = tasks.assignment(db, aid, user["id"])
    if not a:
        raise HTTPException(404, "Uppgiften finns inte")
    if tasks.mark_seen(db, aid, user["id"]):
        db.commit()
        request.state.task_badge = tasks.badge_count(db, user)   # siffran i fliken ska stämma redan på den här sidan
    return render(request, "task.html", a=a, labels=tasks.STATUS_LABELS, note_max=tasks.NOTE_MAX,
                  show_points=bool(logic.get_prefs(db, user["id"])["points_on"]))


@app.post("/uppgifter/{aid}/klar")
def student_task_done(request: Request, aid: int, note: str = Form(""),
                      user=Depends(student_user), db=Depends(database.get_db)):
    error = tasks.mark_done(db, aid, user["id"], note)
    if error:
        flash(request, error, "warn")
    else:
        db.commit()
        flash(request, "Bra jobbat! Din uppgift är markerad som klar. Nu tittar admin på den.")
    return go(f"/uppgifter/{aid}")
