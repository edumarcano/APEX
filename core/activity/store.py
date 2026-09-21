"""SQLite persistence for immutable external activity reports."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import UUID, uuid4

from core.activity.models import ActivityReport, ActivityReportContent, ActivitySubmissionReceipt
from core.connectors.models import utc_now_iso

_SCHEMA_VERSION = 1
_PARTITIONS = {"production", "sandbox"}
_DISPOSITIONS = {"new", "reviewed", "dismissed"}
_MAX_REPORT_BYTES = 256 * 1024


class ActivityStoreError(RuntimeError):
    pass


class ActivityConflictError(ActivityStoreError):
    pass


class ActivityNotFoundError(ActivityStoreError):
    pass


def canonical_content(content: ActivityReportContent) -> tuple[str, str]:
    """Return bounded canonical JSON and its stable content hash."""
    encoded = json.dumps(
        content.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded.encode("utf-8")) > _MAX_REPORT_BYTES:
        raise ActivityStoreError("report_too_large")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ActivityStore:
    """Owns report receipts and reversible inbox dispositions only."""

    def __init__(self, db_path: Path | str | None, *, connection: sqlite3.Connection | None = None, lock: threading.RLock | None = None) -> None:
        self._db_path = str(db_path) if db_path is not None else None
        self._lock = lock or threading.RLock()
        self._owns_memory_connection = connection is None and db_path is None
        self._memory_connection = connection or (sqlite3.connect(":memory:", check_same_thread=False) if db_path is None else None)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._memory_connection is not None:
                self._memory_connection.execute("PRAGMA foreign_keys=ON")
                yield self._memory_connection
                return
            assert self._db_path is not None
            conn = sqlite3.connect(self._db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        with self._lock:
            if self._memory_connection is not None and self._owns_memory_connection:
                self._memory_connection.close()
            self._memory_connection = None

    def initialize(self) -> None:
        with self._connection() as conn:
            try:
                conn.execute("BEGIN")
                conn.execute("CREATE TABLE IF NOT EXISTS schema_versions (domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version >= 1))")
                existing = conn.execute("SELECT version FROM schema_versions WHERE domain = 'activity'").fetchone()
                if existing is not None and int(existing[0]) > _SCHEMA_VERSION:
                    raise ActivityStoreError("Activity schema is newer than this APEX build.")
                conn.execute("""CREATE TABLE IF NOT EXISTS activity_reports (
                    id TEXT PRIMARY KEY NOT NULL,
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                    client_id TEXT NOT NULL,
                    client_display_name TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    submission_key TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    disposition TEXT NOT NULL DEFAULT 'new' CHECK(disposition IN ('new', 'reviewed', 'dismissed')),
                    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
                    content_hash TEXT NOT NULL,
                    UNIQUE(client_id, partition, submission_key)
                )""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_reports_partition_received ON activity_reports(partition, received_at DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_reports_client_partition ON activity_reports(client_id, partition, received_at DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_reports_disposition ON activity_reports(partition, disposition, received_at DESC)")
                conn.execute("INSERT INTO schema_versions(domain, version) VALUES ('activity', ?) ON CONFLICT(domain) DO UPDATE SET version=excluded.version", (_SCHEMA_VERSION,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _report(row: sqlite3.Row | tuple[object, ...]) -> ActivityReport:
        content = ActivityReportContent.model_validate_json(str(row[8]))
        return ActivityReport(
            id=UUID(str(row[0])), partition=str(row[1]), client_id=str(row[2]),
            client_display_name=str(row[3]), principal=str(row[4]), received_at=str(row[6]),
            disposition=str(row[7]), content=content,
        )

    def submit(self, *, partition: str, client_id: str, client_display_name: str, principal: str, content: ActivityReportContent) -> ActivitySubmissionReceipt:
        if partition not in _PARTITIONS:
            raise ActivityStoreError("partition_invalid")
        content_json, content_hash = canonical_content(content)
        with self._connection() as conn, conn:
            existing = conn.execute(
                "SELECT id,partition,client_id,client_display_name,principal,submission_key,received_at,disposition,content_json,content_hash FROM activity_reports WHERE client_id=? AND partition=? AND submission_key=?",
                (client_id, partition, content.submission_key),
            ).fetchone()
            if existing is not None:
                if str(existing[9]) != content_hash:
                    raise ActivityConflictError("submission_key_conflict")
                return ActivitySubmissionReceipt(report=self._report(existing), duplicate=True)
            report_id = uuid4()
            received_at = utc_now_iso()
            try:
                conn.execute(
                    "INSERT INTO activity_reports(id,partition,client_id,client_display_name,principal,submission_key,received_at,disposition,content_json,content_hash) VALUES (?,?,?,?,?,?,?,'new',?,?)",
                    (str(report_id), partition, client_id, client_display_name, principal, content.submission_key, received_at, content_json, content_hash),
                )
            except sqlite3.IntegrityError:
                raced = conn.execute(
                    "SELECT id,partition,client_id,client_display_name,principal,submission_key,received_at,disposition,content_json,content_hash FROM activity_reports WHERE client_id=? AND partition=? AND submission_key=?",
                    (client_id, partition, content.submission_key),
                ).fetchone()
                if raced is None:
                    raise
                if str(raced[9]) != content_hash:
                    raise ActivityConflictError("submission_key_conflict")
                return ActivitySubmissionReceipt(report=self._report(raced), duplicate=True)
            created = conn.execute(
                "SELECT id,partition,client_id,client_display_name,principal,submission_key,received_at,disposition,content_json,content_hash FROM activity_reports WHERE id=?", (str(report_id),)
            ).fetchone()
            assert created is not None
            return ActivitySubmissionReceipt(report=self._report(created), duplicate=False)

    def list(self, *, partition: str, client_id: str | None = None, disposition: str | None = None, limit: int = 50) -> list[ActivityReport]:
        if partition not in _PARTITIONS:
            raise ActivityStoreError("partition_invalid")
        if disposition is not None and disposition not in _DISPOSITIONS:
            raise ActivityStoreError("disposition_invalid")
        clauses = ["partition=?"]
        parameters: list[object] = [partition]
        if client_id is not None:
            clauses.append("client_id=?")
            parameters.append(client_id)
        if disposition is not None:
            clauses.append("disposition=?")
            parameters.append(disposition)
        parameters.append(max(1, min(100, limit)))
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id,partition,client_id,client_display_name,principal,submission_key,received_at,disposition,content_json,content_hash FROM activity_reports WHERE " + " AND ".join(clauses) + " ORDER BY received_at DESC, rowid DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [self._report(row) for row in rows]

    def get(self, report_id: UUID, *, partition: str) -> ActivityReport:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id,partition,client_id,client_display_name,principal,submission_key,received_at,disposition,content_json,content_hash FROM activity_reports WHERE id=? AND partition=?", (str(report_id), partition)
            ).fetchone()
        if row is None:
            raise ActivityNotFoundError("activity_not_found")
        return self._report(row)
