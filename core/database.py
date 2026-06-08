import json
import sqlite3
from datetime import datetime

DB_NAME = "apex_memory.db"


def initialize_db() -> None:
    """
    Initializes the database and creates the necessary tables.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, timestamp TEXT)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, note TEXT, is_read INTEGER DEFAULT 0)''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            briefing TEXT NOT NULL,
            digest_json TEXT NOT NULL
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_briefings_timestamp "
        "ON briefings(timestamp DESC)"
    )

    conn.commit()
    conn.close()


def get_last_run() -> datetime | None:
    """
    Retrieves the timestamp of the last run from the database.

    Returns None when the runs table has no rows (no prior run logged).
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM runs ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return datetime.fromisoformat(result[0]) if result else None


def log_run() -> None:
    """
    Logs the current timestamp to the database.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO runs (timestamp) VALUES (?)", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()


def save_reminder(note: str) -> int:
    """
    Persist a reminder note and return its SQLite row identifier.

    Args:
        note: Sanitized reminder text to store.

    Returns:
        The ``lastrowid`` assigned to the newly inserted reminder row.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (note) VALUES (?)", (note,))
    conn.commit()
    row_id = int(cursor.lastrowid)
    conn.close()
    return row_id


def fetch_unread_reminders() -> list[tuple[int, str]]:
    """
    Fetches all unread reminders from the database and returns them as a list of tuples.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, note FROM reminders WHERE is_read = 0")
    records = cursor.fetchall()

    conn.close()
    return records


def save_briefing(briefing: str, digest_dict: dict) -> None:
    """
    Persist a briefing run and its structured digest payload to the ledger.

    Args:
        briefing: Synthesized briefing text delivered to TTS.
        digest_dict: Serialized digest fields captured at run time.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    digest_json = json.dumps(digest_dict, separators=(",", ":"))
    cursor.execute(
        "INSERT INTO briefings (timestamp, briefing, digest_json) VALUES (?, ?, ?)",
        (datetime.now().isoformat(), briefing, digest_json),
    )
    conn.commit()
    conn.close()
    print("[SYSTEM]: Briefing run persisted to SQLite ledger.")


def prune_historical_ledger() -> None:
    """
    Retain only the 50 most recent briefing rows ordered by timestamp.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        cursor.execute(
            "DELETE FROM briefings WHERE id NOT IN "
            "(SELECT id FROM briefings ORDER BY timestamp DESC LIMIT 50)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("[SYSTEM]: Historical briefing ledger pruned to 50 rows.")


def mark_reminders_read(ids: list[int]) -> None:
    """
    Marks the reminders with the given IDs as read in the database.
    Args:
        ids (list[int]): The IDs of the reminders to mark as read.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for reminder_id in ids:
        cursor.execute("UPDATE reminders SET is_read = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()