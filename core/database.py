"""SQLite persistence for runs, reminders, and briefing history."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from core.config import PROJECT_ROOT
from core.connectors.models import utc_now_iso

DB_NAME = str(PROJECT_ROOT / "apex_memory.db")
_LOGGER = logging.getLogger(__name__)


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    """Open a short-lived SQLite connection with WAL enabled."""
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        yield conn
    finally:
        conn.close()


def _parse_stored_timestamp(raw: str) -> datetime:
    """
    Parse a stored ISO timestamp into an aware datetime.

    Timezone-aware UTC values are preserved. Legacy naive values are treated as
    local wall-clock time so cooldown comparisons remain correct.
    """
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        return parsed.replace(tzinfo=local_tz)
    return parsed


def initialize_db() -> None:
    """Initialize the database and create the necessary tables."""
    with _connection() as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS runs "
                "(id INTEGER PRIMARY KEY, timestamp TEXT)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS reminders "
                "(id INTEGER PRIMARY KEY, note TEXT, is_read INTEGER DEFAULT 0)"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS briefings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    briefing TEXT NOT NULL,
                    digest_json TEXT NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_briefings_timestamp "
                "ON briefings(timestamp DESC)"
            )
            cursor.execute("PRAGMA table_info(briefings)")
            if "metadata_json" not in {str(row[1]) for row in cursor.fetchall()}:
                cursor.execute("ALTER TABLE briefings ADD COLUMN metadata_json TEXT")


def probe_db() -> None:
    """
    Run a lightweight readiness query against SQLite.

    Raises:
        sqlite3.Error: When the database cannot be opened or queried.
    """
    with _connection() as conn:
        conn.execute("SELECT 1").fetchone()


def get_last_run() -> datetime | None:
    """
    Retrieve the timestamp of the last run from the database.

    Returns None when the runs table has no rows (no prior run logged).
    Returned datetimes are timezone-aware.
    """
    with _connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp FROM runs ORDER BY id DESC LIMIT 1")
        result = cursor.fetchone()
    if not result:
        return None
    return _parse_stored_timestamp(result[0])


def log_run() -> None:
    """Log the current UTC timestamp to the database."""
    with _connection() as conn:
        with conn:
            conn.execute(
                "INSERT INTO runs (timestamp) VALUES (?)",
                (utc_now_iso(),),
            )


def save_reminder(note: str) -> int:
    """
    Persist a reminder note and return its SQLite row identifier.

    Args:
        note: Sanitized reminder text to store.

    Returns:
        The ``lastrowid`` assigned to the newly inserted reminder row.
    """
    with _connection() as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO reminders (note) VALUES (?)", (note,))
            return int(cursor.lastrowid)


def fetch_unread_reminders() -> list[tuple[int, str]]:
    """Fetch all unread reminders as ``(id, note)`` tuples."""
    with _connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, note FROM reminders WHERE is_read = 0")
        return list(cursor.fetchall())


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
        metadata_dict: Optional runtime metadata for the run.
    """
    digest_json = json.dumps(digest_dict, separators=(",", ":"))
    metadata_json = (
        json.dumps(metadata_dict, separators=(",", ":"))
        if metadata_dict is not None
        else None
    )
    with _connection() as conn:
        with conn:
            conn.execute(
                "INSERT INTO briefings (timestamp, briefing, digest_json, metadata_json) "
                "VALUES (?, ?, ?, ?)",
                (utc_now_iso(), briefing, digest_json, metadata_json),
            )
    _LOGGER.info("Briefing run persisted to SQLite ledger.")


def fetch_briefing_history(limit: int = 50) -> list[dict[str, Any]]:
    """
    Retrieve recent briefing ledger rows ordered by timestamp descending.

    Args:
        limit: Maximum number of rows to return.

    Returns:
        List of briefing records with parsed digest payloads. Malformed JSON is
        replaced with empty defaults and annotated with parse-error categories.
    """
    with _connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, briefing, digest_json, metadata_json "
            "FROM briefings ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()

    records: list[dict[str, Any]] = []
    for row in rows:
        record_id = int(row[0])
        digest_error: str | None = None
        metadata_error: str | None = None
        try:
            parsed_digest = json.loads(row[3])
            if not isinstance(parsed_digest, dict):
                digest_error = "digest_type_error"
                parsed_digest = {}
                _LOGGER.warning(
                    "Malformed briefing history digest: record_id=%s category=%s",
                    record_id,
                    digest_error,
                )
        except (json.JSONDecodeError, TypeError):
            digest_error = "digest_json_error"
            parsed_digest = {}
            _LOGGER.warning(
                "Malformed briefing history digest: record_id=%s category=%s",
                record_id,
                digest_error,
            )
        try:
            if row[4]:
                parsed_metadata = json.loads(row[4])
                if parsed_metadata is not None and not isinstance(parsed_metadata, dict):
                    metadata_error = "metadata_type_error"
                    parsed_metadata = None
                    _LOGGER.warning(
                        "Malformed briefing history metadata: record_id=%s category=%s",
                        record_id,
                        metadata_error,
                    )
            else:
                parsed_metadata = None
        except (json.JSONDecodeError, TypeError):
            metadata_error = "metadata_json_error"
            parsed_metadata = None
            _LOGGER.warning(
                "Malformed briefing history metadata: record_id=%s category=%s",
                record_id,
                metadata_error,
            )
        records.append(
            {
                "id": record_id,
                "timestamp": row[1],
                "briefing": row[2],
                "digest": parsed_digest,
                "metadata": parsed_metadata,
                "digest_parse_error": digest_error,
                "metadata_parse_error": metadata_error,
            }
        )
    return records


def fetch_briefing_by_id(briefing_id: int) -> dict[str, Any] | None:
    """
    Retrieve a single briefing ledger row by primary key.

    Returns:
        The briefing record with parsed digest/metadata, or None when missing.
    """
    with _connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, briefing, digest_json, metadata_json "
            "FROM briefings WHERE id = ?",
            (briefing_id,),
        )
        row = cursor.fetchone()

    if row is None:
        return None

    record_id = int(row[0])
    digest_error: str | None = None
    metadata_error: str | None = None
    try:
        parsed_digest = json.loads(row[3])
        if not isinstance(parsed_digest, dict):
            digest_error = "digest_type_error"
            parsed_digest = {}
    except (json.JSONDecodeError, TypeError):
        digest_error = "digest_json_error"
        parsed_digest = {}
    try:
        if row[4]:
            parsed_metadata = json.loads(row[4])
            if parsed_metadata is not None and not isinstance(parsed_metadata, dict):
                metadata_error = "metadata_type_error"
                parsed_metadata = None
        else:
            parsed_metadata = None
    except (json.JSONDecodeError, TypeError):
        metadata_error = "metadata_json_error"
        parsed_metadata = None

    return {
        "id": record_id,
        "timestamp": row[1],
        "briefing": row[2],
        "digest": parsed_digest,
        "metadata": parsed_metadata,
        "digest_parse_error": digest_error,
        "metadata_parse_error": metadata_error,
    }


def prune_historical_ledger() -> None:
    """Retain only the 50 most recent briefing rows ordered by timestamp."""
    with _connection() as conn:
        with conn:
            conn.execute(
                "DELETE FROM briefings WHERE id NOT IN "
                "(SELECT id FROM briefings ORDER BY timestamp DESC LIMIT 50)"
            )
    _LOGGER.info("Historical briefing ledger pruned to 50 rows.")


def mark_reminders_read(ids: list[int]) -> None:
    """
    Mark the reminders with the given IDs as read.

    Args:
        ids: The IDs of the reminders to mark as read.
    """
    with _connection() as conn:
        with conn:
            cursor = conn.cursor()
            for reminder_id in ids:
                cursor.execute(
                    "UPDATE reminders SET is_read = 1 WHERE id = ?",
                    (reminder_id,),
                )
