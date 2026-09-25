"""Additive SQLite persistence for immutable briefing session snapshots."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from core.connectors.models import utc_now_iso
from core.briefings.models import (
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingSessionRecord,
    CanonicalBriefingArtifact,
    validate_snapshot_size,
)


class BriefingSessionStoreError(RuntimeError):
    """Base class for briefing-session persistence failures."""


class BriefingSessionNotFoundError(BriefingSessionStoreError):
    """A session is absent from the caller's partition."""


class BriefingSessionConflictError(BriefingSessionStoreError):
    """An idempotency key or immutable session transition conflicts."""


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _decode(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


class BriefingSessionStore:
    """Owns bounded session snapshots and first-presentation timestamps."""

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

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open the connection used by a multi-store admission or completion transaction."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            if self._memory_connection is not None:
                if self._owns_memory_connection:
                    self._memory_connection.close()
                self._memory_connection = None

    def initialize(self) -> None:
        with self._connection() as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions ("
                "domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version >= 1))"
            )
            row = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = 'briefing_sessions'"
            ).fetchone()
            if row is not None and int(row["version"]) > 1:
                raise BriefingSessionStoreError(
                    "Briefing session schema is newer than this APEX build."
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS briefing_sessions (
                    id TEXT PRIMARY KEY NOT NULL,
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                    idempotency_key TEXT NOT NULL,
                    conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id) ON DELETE CASCADE,
                    opening_message_id TEXT NOT NULL UNIQUE
                        REFERENCES conversation_messages(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL UNIQUE REFERENCES cortex_runs(id) ON DELETE CASCADE,
                    profile_id TEXT NOT NULL CHECK(profile_id IN ('daily', 'catch_up', 'deep')),
                    created_at TEXT NOT NULL,
                    presented_at TEXT,
                    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
                    configuration_json TEXT NOT NULL CHECK(json_valid(configuration_json)),
                    artifact_json TEXT CHECK(artifact_json IS NULL OR json_valid(artifact_json)),
                    evidence_json TEXT CHECK(evidence_json IS NULL OR json_valid(evidence_json)),
                    UNIQUE(partition, idempotency_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_briefing_sessions_partition_created "
                "ON briefing_sessions(partition, created_at DESC)"
            )
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('briefing_sessions', 1) "
                "ON CONFLICT(domain) DO UPDATE SET version = excluded.version"
            )

    @staticmethod
    def request_json(request: BriefingGenerationRequest) -> str:
        return _json(request.model_dump(mode="json"))

    def lookup_idempotency(
        self,
        partition: str,
        request: BriefingGenerationRequest,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> BriefingSessionRecord | None:
        if connection is None:
            with self._connection() as conn:
                return self.lookup_idempotency(partition, request, connection=conn)
        row = connection.execute(
            "SELECT s.*, r.status AS run_status FROM briefing_sessions s "
            "JOIN cortex_runs r ON r.id = s.run_id "
            "WHERE s.partition = ? AND s.idempotency_key = ?",
            (partition, str(request.idempotency_key)),
        ).fetchone()
        if row is None:
            return None
        if row["request_json"] != self.request_json(request):
            raise BriefingSessionConflictError(
                "Idempotency key was already used for a different briefing request."
            )
        return self._record(row)

    def insert_pending(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: UUID,
        partition: str,
        request: BriefingGenerationRequest,
        configuration: BriefingGenerationConfiguration,
        conversation_id: UUID,
        opening_message_id: UUID,
        run_id: UUID,
    ) -> BriefingSessionRecord:
        """Insert the session association after its conversation and run exist in the transaction."""
        now = utc_now_iso()
        try:
            connection.execute(
                """
                INSERT INTO briefing_sessions (
                    id, partition, idempotency_key, conversation_id, opening_message_id,
                    run_id, profile_id, created_at, presented_at, request_json,
                    configuration_json, artifact_json, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL)
                """,
                (
                    str(session_id), partition, str(request.idempotency_key),
                    str(conversation_id), str(opening_message_id), str(run_id),
                    request.profile_id, now, self.request_json(request),
                    _json(configuration.model_dump(mode="json")),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise BriefingSessionConflictError(
                "Briefing session identifiers or idempotency key already exist."
            ) from exc
        row = connection.execute(
            "SELECT s.*, r.status AS run_status FROM briefing_sessions s "
            "JOIN cortex_runs r ON r.id = s.run_id WHERE s.id = ?",
            (str(session_id),),
        ).fetchone()
        assert row is not None
        return self._record(row)

    def save_completed_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: UUID,
        partition: str,
        artifact: CanonicalBriefingArtifact,
        evidence: list[BriefingEvidence],
    ) -> None:
        """Save immutable output inside the same transaction as the opening message and run."""
        validate_snapshot_size(artifact, evidence)
        if artifact.session_id != session_id:
            raise BriefingSessionConflictError("Artifact identity does not match its session.")
        session = connection.execute(
            """
            SELECT s.artifact_json, r.status AS run_status
            FROM briefing_sessions s JOIN cortex_runs r ON r.id = s.run_id
            WHERE s.id = ? AND s.partition = ?
            """,
            (str(session_id), partition),
        ).fetchone()
        if session is None:
            raise BriefingSessionNotFoundError("Briefing session was not found.")
        if session["run_status"] != "running":
            raise BriefingSessionConflictError(
                "Only a running generation can save a completed artifact."
            )
        if session["artifact_json"] is not None:
            raise BriefingSessionConflictError("A completed briefing artifact is immutable.")
        cursor = connection.execute(
            "UPDATE briefing_sessions SET artifact_json = ?, evidence_json = ? "
            "WHERE id = ? AND partition = ? AND artifact_json IS NULL",
            (
                artifact.model_dump_json(),
                _json([item.model_dump(mode="json") for item in evidence]),
                str(session_id),
                partition,
            ),
        )
        if cursor.rowcount != 1:
            raise BriefingSessionConflictError("Briefing artifact was already finalized.")

    def get(
        self, session_id: UUID, partition: str
    ) -> BriefingSessionRecord:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT s.*, r.status AS run_status FROM briefing_sessions s "
                "JOIN cortex_runs r ON r.id = s.run_id "
                "WHERE s.id = ? AND s.partition = ?",
                (str(session_id), partition),
            ).fetchone()
        if row is None:
            raise BriefingSessionNotFoundError("Briefing session was not found.")
        return self._record(row)

    def find_by_conversation(
        self, conversation_id: UUID, partition: str
    ) -> BriefingSessionRecord | None:
        """Return the session that owns a conversation in the admitted partition."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT s.*, r.status AS run_status FROM briefing_sessions s "
                "JOIN cortex_runs r ON r.id = s.run_id "
                "WHERE s.conversation_id = ? AND s.partition = ?",
                (str(conversation_id), partition),
            ).fetchone()
        return self._record(row) if row is not None else None

    def list(
        self, partition: str, *, limit: int, offset: int
    ) -> list[BriefingSessionRecord]:
        bounded_limit = max(1, min(100, limit))
        bounded_offset = max(0, offset)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT s.*, r.status AS run_status FROM briefing_sessions s "
                "JOIN cortex_runs r ON r.id = s.run_id "
                "WHERE s.partition = ? ORDER BY s.created_at DESC, s.rowid DESC "
                "LIMIT ? OFFSET ?",
                (partition, bounded_limit, bounded_offset),
            ).fetchall()
        return [self._record(row) for row in rows]

    def evidence(
        self, session_id: UUID, partition: str, evidence_id: UUID
    ) -> BriefingEvidence:
        record = self.get(session_id, partition)
        if record.run_status != "completed" or record.artifact is None:
            raise BriefingSessionConflictError("Evidence is available only after a session completes.")
        for evidence in record.evidence:
            if evidence.id == evidence_id:
                return evidence
        raise BriefingSessionNotFoundError("Briefing evidence was not found.")

    def mark_presented(self, session_id: UUID, partition: str) -> BriefingSessionRecord:
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT s.artifact_json, s.presented_at, r.status AS run_status "
                "FROM briefing_sessions s JOIN cortex_runs r ON r.id = s.run_id "
                "WHERE s.id = ? AND s.partition = ?",
                (str(session_id), partition),
            ).fetchone()
            if row is None:
                raise BriefingSessionNotFoundError("Briefing session was not found.")
            if row["run_status"] != "completed" or row["artifact_json"] is None:
                raise BriefingSessionConflictError(
                    "Only a completed briefing session can be marked as presented."
                )
            conn.execute(
                "UPDATE briefing_sessions SET presented_at = COALESCE(presented_at, ?) "
                "WHERE id = ? AND partition = ?",
                (utc_now_iso(), str(session_id), partition),
            )
            updated = conn.execute(
                "SELECT s.*, r.status AS run_status FROM briefing_sessions s "
                "JOIN cortex_runs r ON r.id = s.run_id WHERE s.id = ?",
                (str(session_id),),
            ).fetchone()
            assert updated is not None
            return self._record(updated)

    @staticmethod
    def _record(row: sqlite3.Row) -> BriefingSessionRecord:
        request = BriefingGenerationRequest.model_validate(_decode(row["request_json"]))
        configuration = BriefingGenerationConfiguration.model_validate(
            _decode(row["configuration_json"])
        )
        artifact_value = _decode(row["artifact_json"])
        evidence_value = _decode(row["evidence_json"]) or []
        return BriefingSessionRecord(
            id=UUID(row["id"]),
            partition=row["partition"],
            idempotency_key=UUID(row["idempotency_key"]),
            conversation_id=UUID(row["conversation_id"]),
            opening_message_id=UUID(row["opening_message_id"]),
            run_id=UUID(row["run_id"]),
            request=request,
            configuration=configuration,
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            presented_at=(
                datetime.fromisoformat(row["presented_at"].replace("Z", "+00:00"))
                if row["presented_at"]
                else None
            ),
            artifact=(
                CanonicalBriefingArtifact.model_validate(artifact_value)
                if artifact_value is not None
                else None
            ),
            evidence=[BriefingEvidence.model_validate(item) for item in evidence_value],
            run_status=row["run_status"],
        )
