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
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, id);
CREATE INDEX IF NOT EXISTS idx_exercises_pick ON exercises(subject, level, active);
"""

# Kolumner som tillkommit efter första versionen. Läggs till i befintliga databaser utan att data tappas.
ADDED_COLUMNS = [
    ("exercises", "image", "TEXT"),
    ("exercises", "diagram", "TEXT"),
    ("exercises", "generator", "TEXT"),
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
