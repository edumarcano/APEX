"""SQLite persistence for runs, reminders, briefing history, and actions."""

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
        conn.execute("PRAGMA foreign_keys=ON;")
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


def initialize_db(*, include_actions: bool = True) -> None:
    """Initialize local persistence; demo mode may deliberately skip action tables."""
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
            _initialize_reminder_schema(conn)
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
            if include_actions:
                # Local import keeps the action domain independent of global database state.
                from core.actions.store import initialize_action_schema

                initialize_action_schema(conn)


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
            cursor.execute(
                "INSERT INTO reminders (note, is_read, sync_state) VALUES (?, 0, 'pending')",
                (note,),
            )
            return int(cursor.lastrowid)


def fetch_unread_reminders() -> list[tuple[int, str]]:
    """Fetch all unread reminders as ``(id, note)`` tuples."""
    with _connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, note FROM reminders "
            "WHERE is_read = 0 AND sync_state IN ('pending', 'unknown') ORDER BY id"
        )
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
                    "UPDATE reminders SET is_read = 1, sync_state = 'dismissed' WHERE id = ?",
                    (reminder_id,),
                )


def _initialize_reminder_schema(conn: sqlite3.Connection) -> None:
    """Apply the small additive reminder cutover migration without data loss."""
    existing = {str(row[1]) for row in conn.execute("PRAGMA table_info(reminders)")}
    for name, declaration in (
        ("sync_state", "TEXT"),
        ("sync_action_id", "TEXT"),
        ("todo_list_id", "TEXT"),
        ("todo_task_id", "TEXT"),
    ):
        if name not in existing:
            conn.execute(f"ALTER TABLE reminders ADD COLUMN {name} {declaration}")
    conn.execute(
        "UPDATE reminders SET sync_state = CASE WHEN is_read = 1 THEN 'dismissed' "
        "ELSE 'pending' END WHERE sync_state IS NULL "
        "OR sync_state NOT IN ('pending', 'unknown', 'synced', 'dismissed')"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS microsoft_todo_reminder_cache ("
        "list_id TEXT PRIMARY KEY NOT NULL, fetched_at TEXT NOT NULL, "
        "tasks_json TEXT NOT NULL CHECK (json_valid(tasks_json)))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reminders_active_sync "
        "ON reminders(is_read, sync_state, id)"
    )


def fetch_local_reminders() -> list[dict[str, Any]]:
    """Return active local pending/unknown outbox records in stable order."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, note, sync_state, sync_action_id, todo_list_id, todo_task_id "
            "FROM reminders WHERE is_read = 0 AND sync_state IN ('pending', 'unknown') "
            "ORDER BY id"
        ).fetchall()
    return [
        {
            "id": int(row[0]), "note": str(row[1]), "sync_state": str(row[2]),
            "sync_action_id": row[3], "todo_list_id": row[4], "todo_task_id": row[5],
        }
        for row in rows
    ]


def get_local_reminder(reminder_id: int) -> dict[str, Any] | None:
    """Load one local reminder including its durable action linkage."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT id, note, is_read, sync_state, sync_action_id, todo_list_id, todo_task_id "
            "FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row[0]), "note": str(row[1]), "is_read": bool(row[2]),
        "sync_state": str(row[3]), "sync_action_id": row[4],
        "todo_list_id": row[5], "todo_task_id": row[6],
    }


def fetch_linked_reminders() -> list[dict[str, Any]]:
    """Return active local rows that may need action-state reconciliation."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, note, is_read, sync_state, sync_action_id, todo_list_id, todo_task_id "
            "FROM reminders WHERE sync_action_id IS NOT NULL AND is_read = 0"
        ).fetchall()
    return [
        {
            "id": int(row[0]), "note": str(row[1]), "is_read": bool(row[2]),
            "sync_state": str(row[3]), "sync_action_id": str(row[4]),
            "todo_list_id": row[5], "todo_task_id": row[6],
        }
        for row in rows
    ]


def link_reminder_action(reminder_id: int, action_id: str) -> bool:
    """Atomically link a pending local row before an external action is approved."""
    with _connection() as conn:
        with conn:
            cursor = conn.execute(
                "UPDATE reminders SET sync_action_id = ? "
                "WHERE id = ? AND is_read = 0 AND sync_state = 'pending'",
                (action_id, reminder_id),
            )
            return cursor.rowcount == 1


def mark_reminder_synced(
    reminder_id: int, *, list_id: str, task_id: str, action_id: str
) -> bool:
    """Archive the still-linked pending row after verified remote creation."""
    with _connection() as conn:
        with conn:
            cursor = conn.execute(
                "UPDATE reminders SET is_read = 1, sync_state = 'synced', "
                "todo_list_id = ?, todo_task_id = ? "
                "WHERE id = ? AND is_read = 0 AND sync_state = 'pending' "
                "AND sync_action_id = ?",
                (list_id, task_id, reminder_id, action_id),
            )
            return cursor.rowcount == 1


def set_reminder_sync_state(reminder_id: int, state: str) -> None:
    """Set a valid local reminder state without discarding its audit linkage."""
    if state not in {"pending", "unknown", "dismissed"}:
        raise ValueError("Reminder state is invalid.")
    with _connection() as conn:
        with conn:
            conn.execute(
                "UPDATE reminders SET sync_state = ?, is_read = ? WHERE id = ?",
                (state, 1 if state == "dismissed" else 0, reminder_id),
            )


def replace_microsoft_todo_reminder_cache(
    list_id: str, *, fetched_at: str, tasks: list[dict[str, str]]
) -> None:
    """Atomically replace one bounded selected-list task snapshot."""
    payload = json.dumps(tasks[:50], separators=(",", ":"), ensure_ascii=False)
    with _connection() as conn:
        with conn:
            conn.execute(
                "INSERT INTO microsoft_todo_reminder_cache(list_id, fetched_at, tasks_json) "
                "VALUES (?, ?, ?) ON CONFLICT(list_id) DO UPDATE SET "
                "fetched_at=excluded.fetched_at, tasks_json=excluded.tasks_json",
                (list_id, fetched_at, payload),
            )


def fetch_microsoft_todo_reminder_cache(list_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Return the selected list's cached task snapshot, never another list's."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT fetched_at, tasks_json FROM microsoft_todo_reminder_cache WHERE list_id = ?",
            (list_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        tasks = json.loads(row[1])
    except (TypeError, json.JSONDecodeError):
        return None
    return (str(row[0]), tasks if isinstance(tasks, list) else [])
