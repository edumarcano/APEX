"""SQLite persistence for reminders and actions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.runtime_paths import get_runtime_paths
from core.persistence_schema import validate_table_columns

DB_NAME = str(get_runtime_paths().database_path)
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


def _init_db_schema(conn: sqlite3.Connection, *, include_actions: bool) -> None:
    validate_schema(conn, include_actions=include_actions)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reminders ("
        "id INTEGER PRIMARY KEY, note TEXT, is_read INTEGER DEFAULT 0, "
        "sync_state TEXT DEFAULT 'pending', sync_action_id TEXT, "
        "todo_list_id TEXT, todo_task_id TEXT)"
    )
    _initialize_reminder_schema(conn)
    if include_actions:
        # Local import keeps the action domain independent of global database state.
        from core.actions.store import initialize_action_schema

        initialize_action_schema(conn)


def initialize_db(
    *,
    include_actions: bool = True,
    connection: sqlite3.Connection | None = None,
) -> None:
    """Initialize local persistence; demo mode may deliberately skip action tables or use a shared connection."""
    if connection is not None:
        with connection:
            connection.execute("BEGIN")
            _init_db_schema(connection, include_actions=include_actions)
        return
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)
    with _connection() as conn:
        with conn:
            conn.execute("BEGIN")
            _init_db_schema(conn, include_actions=include_actions)


def validate_schema(
    conn: sqlite3.Connection, *, include_actions: bool = True
) -> None:
    """Reject incomplete reminder or action tables before bootstrap writes."""
    validate_table_columns(
        conn,
        table="reminders",
        columns=(
            "id", "note", "is_read", "sync_state", "sync_action_id", "todo_list_id", "todo_task_id",
        ),
    )
    validate_table_columns(
        conn,
        table="microsoft_todo_reminder_cache",
        columns=("list_id", "fetched_at", "tasks_json"),
    )
    if include_actions:
        from core.actions.store import ActionStoreError

        actions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='actions'"
        ).fetchone() is not None
        events = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='action_events'"
        ).fetchone() is not None
        if actions != events:
            raise ActionStoreError("Action persistence tables are incomplete.")
        validate_table_columns(
            conn,
            table="actions",
            columns=(
                "action_id", "agent_key", "capability_name", "arguments_json", "target", "risk",
                "summary", "proposed_at", "expires_at", "proposal_hash", "status", "version", "updated_at",
            ),
            error_type=ActionStoreError,
        )
        validate_table_columns(
            conn,
            table="action_events",
            columns=(
                "action_id", "sequence", "from_status", "to_status", "occurred_at", "actor",
                "result_code", "evidence_json",
            ),
            error_type=ActionStoreError,
        )


def probe_db() -> None:
    """
    Run a lightweight readiness query against SQLite.

    Raises:
        sqlite3.Error: When the database cannot be opened or queried.
    """
    with _connection() as conn:
        conn.execute("SELECT 1").fetchone()


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


def _initialize_reminder_schema(conn: sqlite3.Connection) -> None:
    """Create current reminder sync support without transforming existing rows."""
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
