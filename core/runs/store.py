"""SQLite persistence for durable Cortex runs."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from core.connectors.models import utc_now_iso
from core.runs.models import (
    RunCompletionEvidence,
    RunError,
    RunLimitSnapshot,
    RunPartition,
    RunRecord,
    RunRuntimeMeasurements,
    RunStatus,
    RunStopReason,
    UsageQuality,
)

_RUN_SCHEMA_VERSION = 2
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class RunStoreError(RuntimeError):
    """Base exception for run persistence failures."""


class RunNotFoundError(RunStoreError):
    """Raised when a requested run does not exist in the specified partition."""


class RunConflictError(RunStoreError):
    """Raised on conflicting state mutations or invalid idempotent re-entry."""


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _parse_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


_VALID_STATUSES = frozenset(
    {"queued", "running", "cancelling", "completed", "failed", "cancelled", "interrupted"}
)
_VALID_STOP_REASONS = frozenset(
    {
        "end_turn",
        "operator_cancelled",
        "max_elapsed_seconds",
        "max_total_tokens",
        "max_retries",
        "max_model_turns",
        "max_tool_calls",
        "provider_error",
        "tool_error",
        "runtime_error",
        "resource_exhaustion",
        "interrupted_by_restart",
        "internal_error",
    }
)
_VALID_USAGE_QUALITIES = frozenset({"reported", "estimated", "unavailable"})
_VALID_PARTITIONS = frozenset({"production", "sandbox"})


class RunStore:
    """Manages transactional durability and queries for Cortex runs."""

    def __init__(
        self,
        db_path: Path | str | None,
        *,
        connection: sqlite3.Connection | None = None,
        lock: threading.RLock | None = None,
    ) -> None:
        self._db_path = str(db_path) if db_path is not None else None
        self._lock = lock or threading.RLock()
        self._owns_memory_connection = connection is None and db_path is None
        self._memory_connection = connection or (
            sqlite3.connect(":memory:", check_same_thread=False)
            if db_path is None
            else None
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._memory_connection is not None:
                conn = self._memory_connection
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                yield conn
                return
            assert self._db_path is not None
            conn = sqlite3.connect(self._db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        with self._lock:
            if self._memory_connection is not None:
                if self._owns_memory_connection:
                    self._memory_connection.close()
                self._memory_connection = None

    def initialize(self) -> None:
        """Initialize the cortex_runs schema domain in apex_memory.db."""
        with self._connection() as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions ("
                "domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version >= 1))"
            )
            row = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = 'cortex_runs'"
            ).fetchone()
            if row is not None and int(row["version"]) > _RUN_SCHEMA_VERSION:
                raise RunStoreError("Run schema is newer than this APEX build.")
            if row is not None and int(row["version"]) != _RUN_SCHEMA_VERSION:
                raise RunStoreError(
                    "The pre-release run ledger is incompatible with this APEX build. "
                    "Delete cortex_runs and its schema_versions entry before starting beta.2."
                )

            self._create_schema(conn)
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('cortex_runs', ?) "
                "ON CONFLICT(domain) DO UPDATE SET version = excluded.version",
                (_RUN_SCHEMA_VERSION,),
            )

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        """Create the current run-ledger table and supporting indexes."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cortex_runs (
                id TEXT PRIMARY KEY NOT NULL,
                conversation_id TEXT NOT NULL,
                partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                user_message_id TEXT NOT NULL,
                agent_message_id TEXT NOT NULL UNIQUE,
                requested_model TEXT NOT NULL,
                resolved_model TEXT,
                provider TEXT,
                runtime TEXT,
                status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'cancelling', 'completed', 'failed', 'cancelled', 'interrupted')),
                stop_reason TEXT CHECK(stop_reason IS NULL OR stop_reason IN (
                    'end_turn', 'operator_cancelled', 'max_elapsed_seconds', 'max_total_tokens',
                    'max_retries', 'max_model_turns', 'max_tool_calls', 'provider_error',
                    'tool_error', 'runtime_error', 'resource_exhaustion', 'interrupted_by_restart',
                    'internal_error'
                )),
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                limit_snapshot_json TEXT NOT NULL CHECK(json_valid(limit_snapshot_json)),
                turns_count INTEGER NOT NULL DEFAULT 0 CHECK(turns_count >= 0),
                tool_calls_count INTEGER NOT NULL DEFAULT 0 CHECK(tool_calls_count >= 0),
                retries_count INTEGER NOT NULL DEFAULT 0 CHECK(retries_count >= 0),
                total_tokens INTEGER NOT NULL DEFAULT 0 CHECK(total_tokens >= 0),
                elapsed_seconds REAL NOT NULL DEFAULT 0.0 CHECK(elapsed_seconds >= 0.0),
                usage_quality TEXT NOT NULL CHECK(usage_quality IN ('reported', 'estimated', 'unavailable')),
                runtime_measurements_json TEXT CHECK(runtime_measurements_json IS NULL OR json_valid(runtime_measurements_json)),
                final_message_status TEXT CHECK(final_message_status IS NULL OR final_message_status IN ('completed', 'failed', 'interrupted')),
                answer_persisted INTEGER NOT NULL DEFAULT 0 CHECK(answer_persisted IN (0, 1)),
                tool_outcome_counts_json TEXT CHECK(tool_outcome_counts_json IS NULL OR json_valid(tool_outcome_counts_json)),
                action_ids_json TEXT CHECK(action_ids_json IS NULL OR json_valid(action_ids_json)),
                trace_id TEXT CHECK(trace_id IS NULL OR (length(trace_id) = 32 AND trace_id NOT GLOB '*[^0-9a-f]*')),
                error_code TEXT,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                FOREIGN KEY(conversation_id, user_message_id) REFERENCES conversation_messages(conversation_id, id) ON DELETE CASCADE,
                FOREIGN KEY(conversation_id, agent_message_id) REFERENCES conversation_messages(conversation_id, id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cortex_runs_partition_created "
            "ON cortex_runs(partition, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cortex_runs_partition_status "
            "ON cortex_runs(partition, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cortex_runs_conversation "
            "ON cortex_runs(conversation_id, created_at DESC)"
        )
    @staticmethod
    def _record(row: sqlite3.Row) -> RunRecord:
        limits_dict = _parse_json(row["limit_snapshot_json"]) or {}
        measurements_dict = _parse_json(row["runtime_measurements_json"]) or {}
        tool_outcomes_dict = _parse_json(row["tool_outcome_counts_json"]) or {}
        action_ids_list = _parse_json(row["action_ids_json"]) or []

        evidence = RunCompletionEvidence(
            final_message_status=str(row["final_message_status"]) if row["final_message_status"] else None,
            answer_persisted=bool(row["answer_persisted"]),
            tool_outcome_counts=tool_outcomes_dict,
            action_ids=action_ids_list,
        )

        error = None
        if row["error_code"] is not None:
            error = RunError(code=row["error_code"])

        return RunRecord(
            id=UUID(str(row["id"])),
            conversation_id=UUID(str(row["conversation_id"])),
            partition=row["partition"],
            user_message_id=UUID(str(row["user_message_id"])),
            agent_message_id=UUID(str(row["agent_message_id"])),
            requested_model=str(row["requested_model"]),
            resolved_model=str(row["resolved_model"]) if row["resolved_model"] else None,
            provider=str(row["provider"]) if row["provider"] else None,
            runtime=str(row["runtime"]) if row["runtime"] else None,
            status=row["status"],
            stop_reason=row["stop_reason"] if row["stop_reason"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]),
            limit_snapshot=RunLimitSnapshot(**limits_dict),
            turns_count=int(row["turns_count"]),
            tool_calls_count=int(row["tool_calls_count"]),
            retries_count=int(row["retries_count"]),
            total_tokens=int(row["total_tokens"]),
            elapsed_seconds=float(row["elapsed_seconds"]),
            usage_quality=row["usage_quality"],
            runtime_measurements=RunRuntimeMeasurements(**measurements_dict),
            evidence=evidence,
            trace_id=str(row["trace_id"]) if row["trace_id"] else None,
            error=error,
        )

    def create_run(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        partition: RunPartition,
        user_message_id: UUID,
        agent_message_id: UUID,
        requested_model: str,
        limit_snapshot: RunLimitSnapshot,
        trace_id: str | None = None,
    ) -> tuple[RunRecord, bool]:
        """
        Create a new run record or return an identical existing run by agent_message_id.

        Returns:
            A tuple of (RunRecord, replayed: bool).

        Raises:
            RunNotFoundError: If conversation or message references do not exist in partition.
            RunConflictError: If conversation is archived or parameters conflict with existing agent_message_id.
        """
        if partition not in _VALID_PARTITIONS:
            raise RunConflictError(f"Invalid partition: {partition}")
        if trace_id is not None and not _TRACE_ID_PATTERN.fullmatch(trace_id):
            raise RunConflictError("Trace ID must be a 32-character lowercase hexadecimal value.")

        now = utc_now_iso()
        snapshot_json = _json(limit_snapshot.model_dump())

        with self._connection() as conn, conn:
            conv_row = conn.execute(
                "SELECT archived_at FROM conversations WHERE id = ? AND partition = ?",
                (str(conversation_id), partition),
            ).fetchone()
            if conv_row is None:
                raise RunNotFoundError("Conversation was not found in partition.")
            if conv_row["archived_at"] is not None:
                raise RunConflictError("Archived conversations cannot start runs.")

            user_msg = conn.execute(
                "SELECT role FROM conversation_messages WHERE id = ? AND conversation_id = ?",
                (str(user_message_id), str(conversation_id)),
            ).fetchone()
            if user_msg is None:
                raise RunNotFoundError("User message was not found in this conversation.")
            if user_msg["role"] != "user":
                raise RunConflictError("User message ID must refer to a user message.")

            agent_msg = conn.execute(
                "SELECT role, status FROM conversation_messages WHERE id = ? AND conversation_id = ?",
                (str(agent_message_id), str(conversation_id)),
            ).fetchone()
            if agent_msg is None:
                raise RunNotFoundError("Agent message was not found in this conversation.")
            if agent_msg["role"] != "agent":
                raise RunConflictError("Agent message ID must refer to an agent message.")
            if agent_msg["status"] != "pending":
                raise RunConflictError("Agent message must be pending when a run starts.")

            existing = conn.execute(
                "SELECT * FROM cortex_runs WHERE agent_message_id = ?",
                (str(agent_message_id),),
            ).fetchone()
            if existing is not None:
                record = self._record(existing)
                if (
                    record.conversation_id != conversation_id
                    or record.user_message_id != user_message_id
                    or record.requested_model != requested_model
                    or record.partition != partition
                ):
                    raise RunConflictError(
                        "Agent message ID cannot be reused with conflicting run parameters."
                    )
                return record, True

            conn.execute(
                """
                INSERT INTO cortex_runs (
                    id, conversation_id, partition, user_message_id, agent_message_id,
                    requested_model, resolved_model, provider, runtime, status, stop_reason,
                    created_at, started_at, completed_at, updated_at, limit_snapshot_json,
                    turns_count, tool_calls_count, retries_count, total_tokens, elapsed_seconds,
                    usage_quality, runtime_measurements_json, final_message_status,
                    answer_persisted, tool_outcome_counts_json, action_ids_json, trace_id,
                    error_code
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, NULL, NULL, NULL, 'queued', NULL,
                    ?, NULL, NULL, ?, ?,
                    0, 0, 0, 0, 0.0,
                    'unavailable', NULL, NULL,
                    0, NULL, NULL, ?,
                    NULL
                )
                """,
                (
                    str(run_id),
                    str(conversation_id),
                    partition,
                    str(user_message_id),
                    str(agent_message_id),
                    requested_model,
                    now,
                    now,
                    snapshot_json,
                    trace_id,
                ),
            )
            created = conn.execute(
                "SELECT * FROM cortex_runs WHERE id = ?",
                (str(run_id),),
            ).fetchone()
            assert created is not None
            return self._record(created), False

    def get_run(self, run_id: UUID, partition: str) -> RunRecord:
        """Fetch run record by ID within a specific partition."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cortex_runs WHERE id = ? AND partition = ?",
                (str(run_id), partition),
            ).fetchone()
            if row is None:
                raise RunNotFoundError(f"Run {run_id} not found in partition {partition}.")
            return self._record(row)

    def get_run_by_agent_message_id(
        self, agent_message_id: UUID, partition: str
    ) -> RunRecord | None:
        """Fetch run record by agent_message_id within a partition."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM cortex_runs WHERE agent_message_id = ? AND partition = ?",
                (str(agent_message_id), partition),
            ).fetchone()
            return self._record(row) if row is not None else None

    def list_runs(
        self,
        partition: str,
        *,
        status: RunStatus | None = None,
        conversation_id: UUID | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[RunRecord]:
        """List runs in partition, newest first, bounded by limit."""
        if partition not in _VALID_PARTITIONS:
            raise RunConflictError(f"Invalid partition: {partition}")

        bounded_limit = max(1, min(100, limit))
        bounded_offset = max(0, offset)

        clauses = ["partition = ?"]
        params: list[Any] = [partition]

        if status is not None:
            if status not in _VALID_STATUSES:
                raise RunConflictError(f"Invalid status filter: {status}")
            clauses.append("status = ?")
            params.append(status)

        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            params.append(str(conversation_id))

        where = " AND ".join(clauses)
        params.extend([bounded_limit, bounded_offset])

        query = (
            f"SELECT * FROM cortex_runs "
            f"WHERE {where} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?"
        )
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._record(row) for row in rows]

    def start_run(
        self,
        run_id: UUID,
        *,
        partition: str,
        resolved_model: str,
        provider: str,
        runtime: str,
        trace_id: str | None = None,
    ) -> RunRecord:
        """Transition run from queued to running with resolved model and runtime."""
        if trace_id is not None and not _TRACE_ID_PATTERN.fullmatch(trace_id):
            raise RunConflictError(f"Invalid trace_id format: {trace_id}")
        now = utc_now_iso()
        with self._connection() as conn, conn:
            res = conn.execute(
                """
                UPDATE cortex_runs
                SET status = 'running', resolved_model = ?, provider = ?, runtime = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?,
                    trace_id = COALESCE(?, trace_id)
                WHERE id = ? AND partition = ? AND status = 'queued'
                """,
                (resolved_model, provider, runtime, now, now, trace_id, str(run_id), partition),
            )
            if res.rowcount != 1:
                row = conn.execute(
                    "SELECT status FROM cortex_runs WHERE id = ? AND partition = ?",
                    (str(run_id), partition),
                ).fetchone()
                if row is None:
                    raise RunNotFoundError(f"Run {run_id} was not found.")
                raise RunConflictError(
                    f"Run {run_id} cannot transition to running from status '{row['status']}'."
                )
            row = conn.execute(
                "SELECT * FROM cortex_runs WHERE id = ?",
                (str(run_id),),
            ).fetchone()
            assert row is not None
            return self._record(row)

    def update_progress(
        self,
        run_id: UUID,
        *,
        partition: str,
        turns_count: int | None = None,
        tool_calls_count: int | None = None,
        retries_count: int | None = None,
        total_tokens: int | None = None,
        elapsed_seconds: float | None = None,
        usage_quality: UsageQuality | None = None,
        runtime_measurements: RunRuntimeMeasurements | dict[str, Any] | None = None,
    ) -> RunRecord:
        """Increment or update cumulative execution metrics on active runs only."""
        updates: list[str] = []
        params: list[Any] = []

        if turns_count is not None:
            updates.append("turns_count = ?")
            params.append(turns_count)
        if tool_calls_count is not None:
            updates.append("tool_calls_count = ?")
            params.append(tool_calls_count)
        if retries_count is not None:
            updates.append("retries_count = ?")
            params.append(retries_count)
        if total_tokens is not None:
            updates.append("total_tokens = ?")
            params.append(total_tokens)
        if elapsed_seconds is not None:
            updates.append("elapsed_seconds = ?")
            params.append(elapsed_seconds)
        if usage_quality is not None:
            if usage_quality not in _VALID_USAGE_QUALITIES:
                raise RunConflictError(f"Invalid usage_quality: {usage_quality}")
            updates.append("usage_quality = ?")
            params.append(usage_quality)
        if runtime_measurements is not None:
            if isinstance(runtime_measurements, dict):
                measurements_obj = RunRuntimeMeasurements(**runtime_measurements)
            else:
                measurements_obj = runtime_measurements
            updates.append("runtime_measurements_json = ?")
            params.append(_json(measurements_obj.model_dump(exclude_unset=True)))

        if not updates:
            return self.get_run(run_id, partition)

        now = utc_now_iso()
        updates.append("updated_at = ?")
        params.append(now)
        params.extend([str(run_id), partition])

        with self._connection() as conn, conn:
            set_clause = ", ".join(updates)
            res = conn.execute(
                f"UPDATE cortex_runs SET {set_clause} WHERE id = ? AND partition = ? AND status IN ('running', 'cancelling')",
                params,
            )
            if res.rowcount != 1:
                row = conn.execute(
                    "SELECT status FROM cortex_runs WHERE id = ? AND partition = ?",
                    (str(run_id), partition),
                ).fetchone()
                if row is None:
                    raise RunNotFoundError(f"Run {run_id} was not found in partition {partition}.")
                raise RunConflictError(
                    f"Run {run_id} is in status '{row['status']}' and cannot accept progress updates."
                )
            row = conn.execute(
                "SELECT * FROM cortex_runs WHERE id = ?",
                (str(run_id),),
            ).fetchone()
            assert row is not None
            return self._record(row)

    def set_cancelling(self, run_id: UUID, *, partition: str) -> RunRecord:
        """Mark an active run as cancelling."""
        now = utc_now_iso()
        with self._connection() as conn, conn:
            res = conn.execute(
                """
                UPDATE cortex_runs
                SET status = 'cancelling', updated_at = ?
                WHERE id = ? AND partition = ? AND status IN ('queued', 'running')
                """,
                (now, str(run_id), partition),
            )
            if res.rowcount != 1:
                row = conn.execute(
                    "SELECT status FROM cortex_runs WHERE id = ? AND partition = ?",
                    (str(run_id), partition),
                ).fetchone()
                if row is None:
                    raise RunNotFoundError(f"Run {run_id} was not found.")
                # Idempotently return existing state
            row = conn.execute(
                "SELECT * FROM cortex_runs WHERE id = ?",
                (str(run_id),),
            ).fetchone()
            assert row is not None
            return self._record(row)

    def finalize_run(
        self,
        run_id: UUID,
        *,
        partition: str,
        status: RunStatus,
        stop_reason: RunStopReason,
        evidence: RunCompletionEvidence,
        error: RunError | None = None,
    ) -> RunRecord:
        """Transition run to a terminal state (completed, failed, cancelled, interrupted)."""
        if status not in {"completed", "failed", "cancelled", "interrupted"}:
            raise RunConflictError(f"Cannot finalize with non-terminal status: {status}")
        if stop_reason not in _VALID_STOP_REASONS:
            raise RunConflictError(f"Invalid stop reason: {stop_reason}")

        # Enforce rule: Only completed means a final answer was persisted
        persisted = 1 if (status == "completed" and evidence.answer_persisted) else 0

        now = utc_now_iso()
        err_code = error.code if error else None
        tool_outcomes = _json(evidence.tool_outcome_counts) if evidence.tool_outcome_counts else None
        action_ids = _json(evidence.action_ids) if evidence.action_ids else None

        with self._connection() as conn, conn:
            res = conn.execute(
                """
                UPDATE cortex_runs
                SET status = ?, stop_reason = ?, completed_at = ?, updated_at = ?,
                    final_message_status = ?, answer_persisted = ?,
                    tool_outcome_counts_json = ?, action_ids_json = ?,
                    error_code = ?
                WHERE id = ? AND partition = ? AND status IN ('queued', 'running', 'cancelling')
                """,
                (
                    status,
                    stop_reason,
                    now,
                    now,
                    evidence.final_message_status,
                    persisted,
                    tool_outcomes,
                    action_ids,
                    err_code,
                    str(run_id),
                    partition,
                ),
            )
            if res.rowcount != 1:
                row = conn.execute(
                    "SELECT status FROM cortex_runs WHERE id = ? AND partition = ?",
                    (str(run_id), partition),
                ).fetchone()
                if row is None:
                    raise RunNotFoundError(f"Run {run_id} was not found in partition {partition}.")
                raise RunConflictError(
                    f"Run {run_id} is already in terminal state '{row['status']}'."
                )
            row = conn.execute(
                "SELECT * FROM cortex_runs WHERE id = ?",
                (str(run_id),),
            ).fetchone()
            assert row is not None
            return self._record(row)

    def recover_interrupted(self) -> int:
        """
        Transition any unfinished runs to interrupted state at startup.

        Runs in queued, running, or cancelling become interrupted with stop_reason
        'interrupted_by_restart' and a predefined safe error message.
        """
        now = utc_now_iso()
        with self._connection() as conn, conn:
            res = conn.execute(
                """
                UPDATE cortex_runs
                SET status = 'interrupted',
                    stop_reason = 'interrupted_by_restart',
                    completed_at = ?,
                    updated_at = ?,
                    final_message_status = 'interrupted',
                    answer_persisted = 0,
                    error_code = 'interrupted_by_restart'
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (now, now),
            )
            return res.rowcount

    def has_active_runs(self, conversation_id: UUID) -> bool:
        """Check whether a conversation has any run currently queued, running, or cancelling."""
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM cortex_runs
                WHERE conversation_id = ? AND status IN ('queued', 'running', 'cancelling')
                LIMIT 1
                """,
                (str(conversation_id),),
            ).fetchone()
            return row is not None
