"""SQLite-anslutning, schema och migrering."""
import os
import sqlite3

DB_PATH = os.environ.get("DB_PATH", "data/hemskola.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'student')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5),
    type TEXT NOT NULL CHECK (type IN ('mc', 'text')),
    question TEXT NOT NULL,
    options TEXT,
    answers TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    image TEXT,
    diagram TEXT,
    generator TEXT,
    UNIQUE (subject, question)
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL,
    pos TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5),
    data TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (word, pos)
);

CREATE TABLE IF NOT EXISTS generated (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id),
    user_id INTEGER,
    type TEXT NOT NULL,
    question TEXT NOT NULL,
    options TEXT,
    answers TEXT NOT NULL,
    explanation TEXT NOT NULL DEFAULT '',
    diagram TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_levels (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 5),
    since_attempt_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, subject)
);

CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('placement', 'status')),
    total INTEGER NOT NULL DEFAULT 0,
    score INTEGER,
    estimated_level INTEGER,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS test_items (
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id),
    generated_id INTEGER REFERENCES generated(id),
    PRIMARY KEY (test_id, position)
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id),
    test_id INTEGER REFERENCES tests(id) ON DELETE CASCADE,
    given TEXT NOT NULL,
    correct INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    generated_id INTEGER REFERENCES generated(id)
);
-- Ämnesval per elev: saknas en rad gäller standard (ämnet visas, och tas med i rapporten utom fritidsämnen).
CREATE TABLE IF NOT EXISTS user_subjects (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    in_report INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, subject)
);
-- Motivation per elev: dagsmål, poäng, märken och val av område. Saknas raden gäller standardvärdena.
-- points_since: poäng räknas från den här tidpunkten (UTC), märken räknas bakåt på all historik.
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    areas_on INTEGER NOT NULL DEFAULT 1,
    daily_goal INTEGER NOT NULL DEFAULT 15,
    points_on INTEGER NOT NULL DEFAULT 1,
    badges_on INTEGER NOT NULL DEFAULT 1,
    points_since TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Dagar då dagsmålet nåddes (sparas när det händer, så att ett ändrat mål inte ändrar historiken).
CREATE TABLE IF NOT EXISTS goal_days (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    PRIMARY KEY (user_id, day)
);
-- Nivåer eleven själv tagit sig upp till (ger bonuspoäng en gång per ämne och nivå).
CREATE TABLE IF NOT EXISTS level_ups (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    level INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, subject, level)
);
-- Belöningar som admin lägger in. Kostar poäng och markeras som utdelade av admin.
CREATE TABLE IF NOT EXISTS rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    cost INTEGER NOT NULL CHECK (cost > 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    given_at TEXT,                              -- när belöningen senast delades ut
    repeatable INTEGER NOT NULL DEFAULT 0,      -- 1 = kan tas ut flera gånger tills admin tar bort den
    times_given INTEGER NOT NULL DEFAULT 0,     -- antal utdelningar (för en engångsbelöning 0 eller 1); poängen dras per utdelning
    retired INTEGER NOT NULL DEFAULT 0          -- 1 = borttagen men utdelad, så använda poäng räknas fortfarande
);
-- Förfrågningar där eleven ber om en belöning (för en som kan tas ut flera gånger: ett antal). Poängen reserveras medan
-- förfrågan väntar och dras på riktigt först när admin godkänner (då ökar rewards.times_given).
CREATE TABLE IF NOT EXISTS reward_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reward_id INTEGER NOT NULL REFERENCES rewards(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'declined')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    handled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rreq_user ON reward_requests(user_id, status);
-- Uppgifter som admin skapar (fritext, valfri bild, poäng vid godkänt). active=0 betyder arkiverad (kan inte ges till fler).
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    image TEXT,
    points INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    in_report INTEGER NOT NULL DEFAULT 0     -- 1 = visas på rapporten när uppgiften är godkänd
);
-- En uppgift given till en elev. status: todo (ska göras), done (eleven är klar, väntar på admin),
-- approved (godkänd, poängen är utdelade), rejected (avslagen, eleven får göra om den).
-- points_awarded sparas vid godkännande så att senare ändring av uppgiftens poäng inte ändrar historiken.
CREATE TABLE IF NOT EXISTS task_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'done', 'approved', 'rejected')),
    student_note TEXT NOT NULL DEFAULT '',
    admin_comment TEXT NOT NULL DEFAULT '',
    points_awarded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    done_at TEXT,
    reviewed_at TEXT,
    result_seen INTEGER NOT NULL DEFAULT 1   -- 0 = eleven har inte sett senaste godkännandet/avslaget än
);
CREATE INDEX IF NOT EXISTS idx_assign_user ON task_assignments(user_id, status);
CREATE INDEX IF NOT EXISTS idx_assign_task ON task_assignments(task_id);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, id);
CREATE INDEX IF NOT EXISTS idx_exercises_pick ON exercises(subject, level, active);
"""

# Kolumner som tillkommit efter första versionen. Läggs till i befintliga databaser utan att data tappas.
ADDED_COLUMNS = [
    ("exercises", "image", "TEXT"),
    ("exercises", "diagram", "TEXT"),
    ("exercises", "generator", "TEXT"),
    ("task_assignments", "result_seen", "INTEGER NOT NULL DEFAULT 1"),
    ("tasks", "in_report", "INTEGER NOT NULL DEFAULT 0"),
    ("rewards", "repeatable", "INTEGER NOT NULL DEFAULT 0"),
    ("rewards", "times_given", "INTEGER NOT NULL DEFAULT 0"),
    ("rewards", "retired", "INTEGER NOT NULL DEFAULT 0"),
    ("attempts", "generated_id", "INTEGER REFERENCES generated(id)"),
    ("test_items", "generated_id", "INTEGER REFERENCES generated(id)"),
]
LATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_attempts_generated ON attempts(generated_id)",
    "CREATE INDEX IF NOT EXISTS idx_generated_exercise ON generated(exercise_id)",
]


def connect() -> sqlite3.Connection:
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _columns(conn, table: str) -> set:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn) -> None:
    for table, col, ddl in ADDED_COLUMNS:
        if col not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    # Belöningar som delats ut före räknaren fanns räknas som utdelade en gång (ofarligt att köra om)
    conn.execute("UPDATE rewards SET times_given=1 WHERE given_at IS NOT NULL AND times_given=0")
    for stmt in LATE_INDEXES:
        conn.execute(stmt)


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        migrate(conn)
        conn.commit()
    finally:
        conn.close()


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
