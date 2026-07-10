import json
import sqlite3
from datetime import datetime
from typing import Any

from core.config import PROJECT_ROOT

DB_NAME = str(PROJECT_ROOT / "apex_memory.db")


def initialize_db() -> None:
    """
    Initializes the database and creates the necessary tables.
    """
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute('''CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, timestamp TEXT)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, note TEXT, is_read INTEGER DEFAULT 0)''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            briefing TEXT NOT NULL,
            digest_json TEXT NOT NULL,
            metadata_json TEXT
        )
    ''')
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_briefings_timestamp "
        "ON briefings(timestamp DESC)"
    )
    cursor.execute("PRAGMA table_info(briefings)")
    if "metadata_json" not in {str(row[1]) for row in cursor.fetchall()}:
        cursor.execute("ALTER TABLE briefings ADD COLUMN metadata_json TEXT")

    conn.commit()
    conn.close()


def get_last_run() -> datetime | None:
    """
    Retrieves the timestamp of the last run from the database.

    Returns None when the runs table has no rows (no prior run logged).
    """
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM runs ORDER BY id DESC LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    return datetime.fromisoformat(result[0]) if result else None


def log_run() -> None:
    """
    Logs the current timestamp to the database.
    """
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
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
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
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
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, note FROM reminders WHERE is_read = 0")
    records = cursor.fetchall()

    conn.close()
    return records


def save_briefing(
    briefing: str,
    digest_dict: dict,
    metadata_dict: dict | None = None,
) -> None:
    """
    Persist a briefing run and its structured digest payload to the ledger.

    Args:
        briefing: Synthesized briefing text delivered to TTS.
        digest_dict: Serialized digest fields captured at run time.
    """
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    cursor = conn.cursor()
    digest_json = json.dumps(digest_dict, separators=(",", ":"))
    metadata_json = (
        json.dumps(metadata_dict, separators=(",", ":"))
        if metadata_dict is not None
        else None
    )
    cursor.execute(
        "INSERT INTO briefings (timestamp, briefing, digest_json, metadata_json) "
        "VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), briefing, digest_json, metadata_json),
    )
    conn.commit()
    conn.close()
    print("[SYSTEM]: Briefing run persisted to SQLite ledger.")


def fetch_briefing_history(limit: int = 50) -> list[dict[str, Any]]:
    """
    Retrieve recent briefing ledger rows ordered by timestamp descending.

    Args:
        limit: Maximum number of rows to return.

    Returns:
        List of briefing records with parsed digest payloads.
    """
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, timestamp, briefing, digest_json, metadata_json "
        "FROM briefings ORDER BY timestamp DESC LIMIT ?",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed_digest = json.loads(row[3])
        except (json.JSONDecodeError, TypeError):
            parsed_digest = {}
        try:
            parsed_metadata = json.loads(row[4]) if row[4] else None
        except (json.JSONDecodeError, TypeError):
            parsed_metadata = None
        records.append(
            {
                "id": row[0],
                "timestamp": row[1],
                "briefing": row[2],
                "digest": parsed_digest,
                "metadata": parsed_metadata,
            }
        )
    return records


def prune_historical_ledger() -> None:
    """
    Retain only the 50 most recent briefing rows ordered by timestamp.
    """
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM briefings WHERE id NOT IN "
        "(SELECT id FROM briefings ORDER BY timestamp DESC LIMIT 50)"
    )
    conn.commit()
    conn.close()
    print("[SYSTEM]: Historical briefing ledger pruned to 50 rows.")


def mark_reminders_read(ids: list[int]) -> None:
    """
    Marks the reminders with the given IDs as read in the database.
    Args:
        ids (list[int]): The IDs of the reminders to mark as read.
    """
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    cursor = conn.cursor()
    for reminder_id in ids:
        cursor.execute("UPDATE reminders SET is_read = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
