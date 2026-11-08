import sqlite3
import logging
from pathlib import Path

# Own file on purpose: the old team-board app in the same folder uses jarvis.db
DB_PATH = Path(__file__).parent / "brain.db"

def _conn():
    return sqlite3.connect(DB_PATH)

def init():
    """Create the messages, reminders, and facts tables if they don't exist yet."""
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                role      TEXT NOT NULL,   -- 'user' or 'assistant'
                content   TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                due       REAL NOT NULL,
                text      TEXT NOT NULL,
                done      INTEGER DEFAULT 0
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                text      TEXT NOT NULL
            )
        """)
    logging.info("Memory initialised.")

def save(role: str, content: str):
    """Save one message to the database."""
    with _conn() as db:
        db.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content))

def get_history(limit: int = 20) -> list[dict]:
    """
    Return the last `limit` messages as a list of dicts.
    Oldest first — that's the order Gemini expects.
    """
    with _conn() as db:
        rows = db.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def add_reminder(due: float, text: str) -> int:
    """Add a reminder to the database and return its ID."""
    with _conn() as db:
        cursor = db.execute("INSERT INTO reminders (due, text) VALUES (?, ?)", (due, text))
        return cursor.lastrowid

def pending_reminders() -> list[tuple[int, float, str]]:
    """Return a list of pending reminders, ordered by due time."""
    with _conn() as db:
        rows = db.execute(
            "SELECT id, due, text FROM reminders WHERE done = 0 ORDER BY due"
        ).fetchall()
    return rows

def due_reminders(now: float) -> list[tuple[int, str]]:
    """Return a list of due reminders and mark them as done."""
    with _conn() as db:
        rows = db.execute(
            "SELECT id, text FROM reminders WHERE due <= ? AND done = 0 ORDER BY due", (now,)
        ).fetchall()
        # by id: a reminder added between the SELECT and here must not be marked done unseen
        db.executemany("UPDATE reminders SET done = 1 WHERE id = ?", [(r[0],) for r in rows])
    return rows

def cancel_reminders(words: str) -> int:
    """Cancel pending reminders whose text contains words; returns how many."""
    with _conn() as db:
        return db.execute("UPDATE reminders SET done = 1 WHERE done = 0 AND text LIKE ?", (f"%{words}%",)).rowcount

def add_fact(text: str):
    """Add a fact to the database."""
    with _conn() as db:
        db.execute("INSERT INTO facts (text) VALUES (?)", (text,))

def facts() -> list[str]:
    """Return a list of facts in insert order."""
    with _conn() as db:
        rows = db.execute("SELECT text FROM facts ORDER BY id").fetchall()
    return [row[0] for row in rows]

def forget_fact(words: str) -> int:
    """Delete facts containing the given words and return the number of deleted facts."""
    with _conn() as db:
        cursor = db.execute(
            "DELETE FROM facts WHERE text LIKE ?", (f"%{words}%",)
        )
        return cursor.rowcount
