"""Additive SQLite persistence for immutable briefing session snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from core.connectors.models import utc_now_iso
from core.runs.models import SAFE_ERROR_MESSAGES
from core.briefings.models import (
    BriefingComparison,
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingHistorySelection,
    BriefingSessionHistory,
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
            if row is not None and int(row["version"]) > 2:
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
                    history_json TEXT CHECK(history_json IS NULL OR json_valid(history_json)),
                    artifact_json TEXT CHECK(artifact_json IS NULL OR json_valid(artifact_json)),
                    evidence_json TEXT CHECK(evidence_json IS NULL OR json_valid(evidence_json)),
                    UNIQUE(partition, idempotency_key)
                )
                """
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(briefing_sessions)")
            }
            if "history_json" not in columns:
                conn.execute(
                    "ALTER TABLE briefing_sessions ADD COLUMN history_json TEXT "
                    "CHECK(history_json IS NULL OR json_valid(history_json))"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_briefing_sessions_partition_created "
                "ON briefing_sessions(partition, created_at DESC)"
            )
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('briefing_sessions', 2) "
                "ON CONFLICT(domain) DO UPDATE SET version = excluded.version"
            )
            speech_version = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = 'briefing_speech'"
            ).fetchone()
            if speech_version is not None and int(speech_version["version"]) > 1:
                raise BriefingSessionStoreError(
                    "Briefing speech schema is newer than this APEX build."
                )
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS briefing_speech (
                    session_id TEXT PRIMARY KEY NOT NULL
                        REFERENCES briefing_sessions(id) ON DELETE CASCADE,
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                    request_id TEXT,
                    artifact_sha256 TEXT NOT NULL CHECK(length(artifact_sha256) = 64),
                    status TEXT NOT NULL CHECK(status IN ('preparing', 'ready', 'unavailable', 'cancelled')),
                    script_json TEXT CHECK(script_json IS NULL OR json_valid(script_json)),
                    requested_engine TEXT CHECK(requested_engine IN ('google', 'kokoro', 'pyttsx3')),
                    engine TEXT CHECK(engine IN ('google', 'kokoro', 'pyttsx3')),
                    voice_gender TEXT CHECK(voice_gender IN ('female', 'male')),
                    error_code TEXT,
                    duration_seconds REAL CHECK(duration_seconds IS NULL OR duration_seconds >= 0),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS briefing_speech_audio_chunks (
                    session_id TEXT NOT NULL REFERENCES briefing_speech(session_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                    content_type TEXT NOT NULL CHECK(content_type IN ('audio/mpeg', 'audio/wav')),
                    engine TEXT NOT NULL CHECK(engine IN ('google', 'kokoro', 'pyttsx3')),
                    duration_seconds REAL NOT NULL CHECK(duration_seconds > 0),
                    audio_blob BLOB NOT NULL CHECK(length(audio_blob) > 0),
                    PRIMARY KEY(session_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_briefing_speech_partition_status
                    ON briefing_speech(partition, status);
                """
            )
            conn.execute(
                "UPDATE briefing_speech SET status = 'unavailable', request_id = NULL, "
                "error_code = 'speech_interrupted', updated_at = ? WHERE status = 'preparing'",
                (utc_now_iso(),),
            )
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('briefing_speech', 1) "
                "ON CONFLICT(domain) DO UPDATE SET version = excluded.version"
            )

    @staticmethod
    def _speech_artifact_hash(raw_artifact: str) -> str:
        artifact = CanonicalBriefingArtifact.model_validate_json(raw_artifact)
        return hashlib.sha256(artifact.model_dump_json().encode("utf-8")).hexdigest()

    @classmethod
    def _require_speech_session(
        cls,
        connection: sqlite3.Connection,
        *,
        session_id: UUID,
        partition: str,
        artifact_sha256: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT s.artifact_json, r.status AS run_status FROM briefing_sessions s "
            "JOIN cortex_runs r ON r.id = s.run_id WHERE s.id = ? AND s.partition = ?",
            (str(session_id), partition),
        ).fetchone()
        if row is None:
            raise BriefingSessionNotFoundError("Briefing session was not found.")
        if row["run_status"] != "completed" or row["artifact_json"] is None:
            raise BriefingSessionConflictError(
                "Speech is available only for a completed briefing."
            )
        if cls._speech_artifact_hash(row["artifact_json"]) != artifact_sha256:
            raise BriefingSessionConflictError(
                "Speech must remain bound to the persisted briefing artifact."
            )
        return row

    def begin_speech_preparation(
        self,
        *,
        session_id: UUID,
        partition: str,
        artifact_sha256: str,
        request_id: UUID,
        requested_engine: str,
        voice_gender: str,
    ) -> None:
        if requested_engine not in {"google", "kokoro", "pyttsx3"}:
            raise BriefingSessionConflictError("The selected speech engine is invalid.")
        if voice_gender not in {"female", "male"}:
            raise BriefingSessionConflictError("The selected speech voice is invalid.")
        with self.transaction() as conn:
            self._require_speech_session(
                conn,
                session_id=session_id,
                partition=partition,
                artifact_sha256=artifact_sha256,
            )
            current = conn.execute(
                "SELECT status FROM briefing_speech WHERE session_id = ? AND partition = ?",
                (str(session_id), partition),
            ).fetchone()
            if current is not None and current["status"] == "preparing":
                raise BriefingSessionConflictError("Speech preparation is already running.")
            conn.execute(
                "DELETE FROM briefing_speech_audio_chunks WHERE session_id = ?",
                (str(session_id),),
            )
            conn.execute(
                """
                INSERT INTO briefing_speech (
                    session_id, partition, request_id, artifact_sha256, status,
                    script_json, requested_engine, engine, voice_gender, error_code,
                    duration_seconds, updated_at
                ) VALUES (?, ?, ?, ?, 'preparing', NULL, ?, NULL, ?, NULL, NULL, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    partition = excluded.partition,
                    request_id = excluded.request_id,
                    artifact_sha256 = excluded.artifact_sha256,
                    status = 'preparing',
                    script_json = NULL,
                    requested_engine = excluded.requested_engine,
                    engine = NULL,
                    voice_gender = excluded.voice_gender,
                    error_code = NULL,
                    duration_seconds = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    str(session_id), partition, str(request_id), artifact_sha256,
                    requested_engine, voice_gender, utc_now_iso(),
                ),
            )

    def complete_speech_preparation(
        self,
        *,
        session_id: UUID,
        partition: str,
        request_id: UUID,
        artifact_sha256: str,
        script_json: str,
        engine: str,
        duration_seconds: float,
        chunks: list[dict[str, Any]],
    ) -> bool:
        if engine not in {"google", "kokoro", "pyttsx3"}:
            raise BriefingSessionConflictError("The resolved speech engine is invalid.")
        if not chunks or len(chunks) > 16:
            raise BriefingSessionConflictError("Prepared speech audio has an invalid chunk count.")
        if not math.isfinite(duration_seconds) or not 0 < duration_seconds <= 180:
            raise BriefingSessionConflictError("Prepared speech audio exceeds its duration bound.")
        total_bytes = 0
        normalized: list[tuple[int, str, str, float, bytes]] = []
        for ordinal, chunk in enumerate(chunks):
            audio = chunk.get("audio")
            content_type = chunk.get("content_type")
            chunk_engine = chunk.get("engine")
            duration = chunk.get("duration_seconds")
            if not isinstance(audio, bytes) or not audio or len(audio) > 4 * 1024 * 1024:
                raise BriefingSessionConflictError("Prepared speech audio chunk is invalid.")
            if content_type not in {"audio/mpeg", "audio/wav"}:
                raise BriefingSessionConflictError("Prepared speech audio type is invalid.")
            if chunk_engine != engine:
                raise BriefingSessionConflictError("Speech chunks must use one resolved engine.")
            if not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= 60:
                raise BriefingSessionConflictError("Prepared speech chunk duration is invalid.")
            total_bytes += len(audio)
            normalized.append((ordinal, content_type, chunk_engine, float(duration), audio))
        if total_bytes > 12 * 1024 * 1024:
            raise BriefingSessionConflictError("Prepared speech audio exceeds its storage bound.")
        with self.transaction() as conn:
            self._require_speech_session(
                conn,
                session_id=session_id,
                partition=partition,
                artifact_sha256=artifact_sha256,
            )
            current = conn.execute(
                "SELECT request_id, status FROM briefing_speech "
                "WHERE session_id = ? AND partition = ?",
                (str(session_id), partition),
            ).fetchone()
            if (
                current is None
                or current["status"] != "preparing"
                or current["request_id"] != str(request_id)
            ):
                return False
            conn.execute(
                "DELETE FROM briefing_speech_audio_chunks WHERE session_id = ?",
                (str(session_id),),
            )
            conn.executemany(
                "INSERT INTO briefing_speech_audio_chunks "
                "(session_id, ordinal, content_type, engine, duration_seconds, audio_blob) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (str(session_id), ordinal, content_type, chunk_engine, duration, audio)
                    for ordinal, content_type, chunk_engine, duration, audio in normalized
                ],
            )
            conn.execute(
                "UPDATE briefing_speech SET request_id = NULL, status = 'ready', "
                "script_json = ?, engine = ?, error_code = NULL, duration_seconds = ?, updated_at = ? "
                "WHERE session_id = ? AND partition = ? AND request_id = ?",
                (
                    script_json, engine, duration_seconds, utc_now_iso(), str(session_id),
                    partition, str(request_id),
                ),
            )
            return True

    def fail_speech_preparation(
        self,
        *,
        session_id: UUID,
        partition: str,
        request_id: UUID,
        artifact_sha256: str,
        error_code: str,
    ) -> bool:
        return self._finish_speech_preparation(
            session_id=session_id,
            partition=partition,
            request_id=request_id,
            artifact_sha256=artifact_sha256,
            status="unavailable",
            error_code=error_code,
        )

    def cancel_speech_preparation(
        self,
        *,
        session_id: UUID,
        partition: str,
        request_id: UUID,
        artifact_sha256: str,
        error_code: str = "speech_cancelled",
    ) -> bool:
        return self._finish_speech_preparation(
            session_id=session_id,
            partition=partition,
            request_id=request_id,
            artifact_sha256=artifact_sha256,
            status="cancelled",
            error_code=error_code,
        )

    def _finish_speech_preparation(
        self,
        *,
        session_id: UUID,
        partition: str,
        request_id: UUID,
        artifact_sha256: str,
        status: str,
        error_code: str,
    ) -> bool:
        with self.transaction() as conn:
            self._require_speech_session(
                conn,
                session_id=session_id,
                partition=partition,
                artifact_sha256=artifact_sha256,
            )
            cursor = conn.execute(
                "UPDATE briefing_speech SET request_id = NULL, status = ?, error_code = ?, "
                "updated_at = ? WHERE session_id = ? AND partition = ? "
                "AND request_id = ? AND status = 'preparing'",
                (
                    status, error_code[:64], utc_now_iso(), str(session_id),
                    partition, str(request_id),
                ),
            )
            if cursor.rowcount:
                conn.execute(
                    "DELETE FROM briefing_speech_audio_chunks WHERE session_id = ?",
                    (str(session_id),),
                )
            return cursor.rowcount == 1

    def get_speech_status(self, session_id: UUID, partition: str) -> dict[str, Any]:
        with self._connection() as conn:
            session = conn.execute(
                "SELECT 1 FROM briefing_sessions WHERE id = ? AND partition = ?",
                (str(session_id), partition),
            ).fetchone()
            if session is None:
                raise BriefingSessionNotFoundError("Briefing session was not found.")
            row = conn.execute(
                "SELECT * FROM briefing_speech WHERE session_id = ? AND partition = ?",
                (str(session_id), partition),
            ).fetchone()
        if row is None:
            return {"status": "not_requested", "artifact_sha256": None}
        return {
            "status": row["status"],
            "artifact_sha256": row["artifact_sha256"],
            "error_code": row["error_code"],
            "engine": row["engine"],
            "requested_engine": row["requested_engine"],
            "voice_gender": row["voice_gender"],
            "script_json": row["script_json"],
            "duration_seconds": row["duration_seconds"],
        }

    def get_speech_audio(self, session_id: UUID, partition: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            session = conn.execute(
                "SELECT 1 FROM briefing_sessions WHERE id = ? AND partition = ?",
                (str(session_id), partition),
            ).fetchone()
            if session is None:
                raise BriefingSessionNotFoundError("Briefing session was not found.")
            speech = conn.execute(
                "SELECT * FROM briefing_speech WHERE session_id = ? AND partition = ?",
                (str(session_id), partition),
            ).fetchone()
            if speech is None:
                return None
            chunks = conn.execute(
                "SELECT ordinal, content_type, engine, duration_seconds, audio_blob "
                "FROM briefing_speech_audio_chunks WHERE session_id = ? ORDER BY ordinal",
                (str(session_id),),
            ).fetchall()
        result = dict(speech)
        result["chunks"] = [
            {
                "ordinal": chunk["ordinal"],
                "content_type": chunk["content_type"],
                "engine": chunk["engine"],
                "duration_seconds": chunk["duration_seconds"],
                "audio": bytes(chunk["audio_blob"]),
            }
            for chunk in chunks
        ]
        return result

    def set_speech_playback_error(
        self,
        session_id: UUID,
        partition: str,
        artifact_sha256: str,
        error_code: str | None,
    ) -> None:
        with self.transaction() as conn:
            self._require_speech_session(
                conn,
                session_id=session_id,
                partition=partition,
                artifact_sha256=artifact_sha256,
            )
            conn.execute(
                "UPDATE briefing_speech SET error_code = ?, updated_at = ? "
                "WHERE session_id = ? AND partition = ? AND artifact_sha256 = ? AND status = 'ready'",
                (error_code[:64] if error_code else None, utc_now_iso(), str(session_id), partition, artifact_sha256),
            )

    def capture_history_selection(
        self, connection: sqlite3.Connection, partition: str
    ) -> BriefingHistorySelection:
        """Freeze the newest presented completed sessions within the admission transaction."""
        rows = connection.execute(
            """
            SELECT s.id
            FROM briefing_sessions s
            JOIN cortex_runs r ON r.id = s.run_id
            WHERE s.partition = ? AND s.presented_at IS NOT NULL
                AND r.status = 'completed'
                AND s.artifact_json IS NOT NULL
            ORDER BY s.created_at DESC, s.rowid DESC
            LIMIT 100
            """,
            (partition,),
        ).fetchall()
        return BriefingHistorySelection(
            captured_at=datetime.fromisoformat(utc_now_iso().replace("Z", "+00:00")),
            session_ids=[UUID(row["id"]) for row in rows],
        )

    @staticmethod
    def _history_json(history: BriefingSessionHistory) -> str:
        return _json(history.model_dump(mode="json"))

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
            "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code FROM briefing_sessions s "
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
        history_selection: BriefingHistorySelection,
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
                    configuration_json, history_json, artifact_json, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, NULL, NULL)
                """,
                (
                    str(session_id), partition, str(request.idempotency_key),
                    str(conversation_id), str(opening_message_id), str(run_id),
                    request.profile_id, now, self.request_json(request),
                    _json(configuration.model_dump(mode="json")),
                    self._history_json(BriefingSessionHistory(selection=history_selection)),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise BriefingSessionConflictError(
                "Briefing session identifiers or idempotency key already exist."
            ) from exc
        row = connection.execute(
            "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code FROM briefing_sessions s "
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
            SELECT s.artifact_json, s.history_json, r.status AS run_status
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
        history_value = _decode(session["history_json"])
        if history_value is None:
            raise BriefingSessionConflictError("Briefing history selection is missing.")
        history = BriefingSessionHistory.model_validate(history_value).model_copy(
            update={"comparison": artifact.comparison}
        )
        cursor = connection.execute(
            "UPDATE briefing_sessions SET artifact_json = ?, evidence_json = ?, history_json = ? "
            "WHERE id = ? AND partition = ? AND artifact_json IS NULL",
            (
                artifact.model_dump_json(),
                _json([item.model_dump(mode="json") for item in evidence]),
                self._history_json(history),
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
                "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code FROM briefing_sessions s "
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
                "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code FROM briefing_sessions s "
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
                "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code FROM briefing_sessions s "
                "JOIN cortex_runs r ON r.id = s.run_id "
                "WHERE s.partition = ? ORDER BY s.created_at DESC, s.rowid DESC "
                "LIMIT ? OFFSET ?",
                (partition, bounded_limit, bounded_offset),
            ).fetchall()
        return [self._record(row) for row in rows]

    def get_many(
        self,
        session_ids: list[UUID],
        partition: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[UUID, BriefingSessionRecord]:
        """Load a bounded history batch without per-session queries."""
        if not session_ids:
            return {}
        if connection is None:
            with self._connection() as conn:
                return self.get_many(session_ids, partition, connection=conn)
        unique_ids = list(dict.fromkeys(session_ids))[:100]
        placeholders = ",".join("?" for _ in unique_ids)
        rows = connection.execute(
            "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code "
            "FROM briefing_sessions s JOIN cortex_runs r ON r.id = s.run_id "
            f"WHERE s.partition = ? AND s.id IN ({placeholders})",
            (partition, *(str(session_id) for session_id in unique_ids)),
        ).fetchall()
        return {
            UUID(row["id"]): self._record(row)
            for row in rows
        }

    def history_candidates(
        self, session_id: UUID, partition: str
    ) -> tuple[BriefingHistorySelection, list[BriefingSessionRecord]]:
        """Read a run's frozen admission selection and its available history snapshots."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code "
                "FROM briefing_sessions s JOIN cortex_runs r ON r.id = s.run_id "
                "WHERE s.id = ? AND s.partition = ?",
                (str(session_id), partition),
            ).fetchone()
            if row is None:
                raise BriefingSessionNotFoundError("Briefing session was not found.")
            current = self._record(row)
            if current.history is None:
                return BriefingHistorySelection(captured_at=current.created_at), []
            records = self.get_many(
                current.history.selection.session_ids,
                partition,
                connection=conn,
            )
        ordered = [
            records[identifier]
            for identifier in current.history.selection.session_ids
            if identifier in records
        ]
        return current.history.selection, ordered

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
                "SELECT s.*, r.status AS run_status, r.error_code AS run_error_code FROM briefing_sessions s "
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
            history=(
                BriefingSessionHistory.model_validate(_decode(row["history_json"]))
                if row["history_json"] is not None
                else None
            ),
            artifact=(
                CanonicalBriefingArtifact.model_validate(artifact_value)
                if artifact_value is not None
                else None
            ),
            evidence=[BriefingEvidence.model_validate(item) for item in evidence_value],
            run_status=row["run_status"],
            run_error_code=(
                row["run_error_code"]
                if row["run_error_code"] in SAFE_ERROR_MESSAGES
                else None
            ),
        )
