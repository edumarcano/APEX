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

from core.activity.models import ActivityContextReviewLink, ActivityReport, ActivityReportContent, ActivitySubmissionReceipt
from core.connectors.models import utc_now_iso

_SCHEMA_VERSION = 2
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
                if existing is None or int(existing[0]) < 2:
                    conn.execute("""CREATE TABLE IF NOT EXISTS activity_context_review_links (
                        report_id TEXT NOT NULL REFERENCES activity_reports(id),
                        partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                        finding_reference TEXT NOT NULL,
                        proposal_hash TEXT NOT NULL,
                        review_id TEXT NOT NULL UNIQUE,
                        action_id TEXT NOT NULL UNIQUE,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY(report_id, finding_reference, proposal_hash)
                    )""")
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

    def set_disposition(
        self, report_id: UUID, *, partition: str, disposition: str,
    ) -> ActivityReport:
        """Change only the operator's reversible inbox state for one receipt."""
        if partition not in _PARTITIONS:
            raise ActivityStoreError("partition_invalid")
        if disposition not in _DISPOSITIONS:
            raise ActivityStoreError("disposition_invalid")
        with self._connection() as conn, conn:
            result = conn.execute(
                "UPDATE activity_reports SET disposition=? WHERE id=? AND partition=?",
                (disposition, str(report_id), partition),
            )
            if result.rowcount != 1:
                raise ActivityNotFoundError("activity_not_found")
            row = conn.execute(
                "SELECT id,partition,client_id,client_display_name,principal,submission_key,received_at,disposition,content_json,content_hash FROM activity_reports WHERE id=? AND partition=?",
                (str(report_id), partition),
            ).fetchone()
        assert row is not None
        return self._report(row)

    def context_review_links(
        self, report_id: UUID, *, partition: str,
    ) -> list[ActivityContextReviewLink]:
        """Return durable review associations for one report in its partition."""
        with self._connection() as conn:
            report = conn.execute(
                "SELECT 1 FROM activity_reports WHERE id=? AND partition=?",
                (str(report_id), partition),
            ).fetchone()
            if report is None:
                raise ActivityNotFoundError("activity_not_found")
            rows = conn.execute(
                "SELECT report_id,partition,finding_reference,proposal_hash,review_id,action_id "
                "FROM activity_context_review_links WHERE report_id=? AND partition=? "
                "ORDER BY created_at DESC",
                (str(report_id), partition),
            ).fetchall()
        return [
            ActivityContextReviewLink(
                UUID(str(row[0])), str(row[1]), str(row[2]), str(row[3]),
                UUID(str(row[4])), str(row[5]),
            )
            for row in rows
        ]

    def reserve_context_review_link(
        self, *, report_id: UUID, partition: str, finding_reference: str,
        proposal_hash: str, review_id: UUID, action_id: str,
    ) -> tuple[ActivityContextReviewLink, bool]:
        """Reserve a stable review/action identity before a retried proposal is built."""
        if partition not in _PARTITIONS or not finding_reference or not proposal_hash:
            raise ActivityStoreError("context_review_link_invalid")
        with self._connection() as conn, conn:
            existing = conn.execute(
                "SELECT report_id,partition,finding_reference,proposal_hash,review_id,action_id "
                "FROM activity_context_review_links WHERE report_id=? AND finding_reference=? AND proposal_hash=?",
                (str(report_id), finding_reference, proposal_hash),
            ).fetchone()
            if existing is None:
                try:
                    conn.execute(
                        "INSERT INTO activity_context_review_links(report_id,partition,finding_reference,proposal_hash,review_id,action_id,created_at) VALUES (?,?,?,?,?,?,?)",
                        (str(report_id), partition, finding_reference, proposal_hash, str(review_id), action_id, utc_now_iso()),
                    )
                except sqlite3.IntegrityError:
                    existing = conn.execute(
                        "SELECT report_id,partition,finding_reference,proposal_hash,review_id,action_id "
                        "FROM activity_context_review_links WHERE report_id=? AND finding_reference=? AND proposal_hash=?",
                        (str(report_id), finding_reference, proposal_hash),
                    ).fetchone()
                    if existing is None:
                        raise
                else:
                    return ActivityContextReviewLink(
                        report_id, partition, finding_reference, proposal_hash, review_id, action_id,
                    ), True
            assert existing is not None
            link = ActivityContextReviewLink(
                UUID(str(existing[0])), str(existing[1]), str(existing[2]), str(existing[3]),
                UUID(str(existing[4])), str(existing[5]),
            )
            if link.partition != partition:
                raise ActivityNotFoundError("activity_not_found")
            return link, False

    def context_review_link(
        self, *, report_id: UUID, partition: str, finding_reference: str, proposal_hash: str,
    ) -> ActivityContextReviewLink | None:
        """Read a prior proposal link without taking a new review snapshot."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT report_id,partition,finding_reference,proposal_hash,review_id,action_id "
                "FROM activity_context_review_links WHERE report_id=? AND finding_reference=? AND proposal_hash=? AND partition=?",
                (str(report_id), finding_reference, proposal_hash, partition),
            ).fetchone()
        if row is None:
            return None
        return ActivityContextReviewLink(
            UUID(str(row[0])), str(row[1]), str(row[2]), str(row[3]), UUID(str(row[4])), str(row[5]),
        )

    def rebind_context_review_link(
        self, *, report_id: UUID, partition: str, finding_reference: str,
        proposal_hash: str, expected_review_id: UUID, review_id: UUID, action_id: str,
    ) -> ActivityContextReviewLink:
        """Move a retry identity to a deliberately refreshed review exactly once."""
        if partition not in _PARTITIONS or not finding_reference or not proposal_hash or not action_id:
            raise ActivityStoreError("context_review_link_invalid")
        with self._connection() as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                "SELECT report_id,partition,finding_reference,proposal_hash,review_id,action_id "
                "FROM activity_context_review_links WHERE report_id=? AND finding_reference=? "
                "AND proposal_hash=? AND partition=?",
                (str(report_id), finding_reference, proposal_hash, partition),
            ).fetchone()
            if current is None:
                raise ActivityNotFoundError("activity_not_found")
            if str(current[4]) == str(review_id):
                return ActivityContextReviewLink(
                    UUID(str(current[0])), str(current[1]), str(current[2]), str(current[3]),
                    UUID(str(current[4])), str(current[5]),
                )
            if str(current[4]) == str(expected_review_id):
                conn.execute(
                    "UPDATE activity_context_review_links SET review_id=?,action_id=? "
                    "WHERE report_id=? AND finding_reference=? AND proposal_hash=? AND partition=? AND review_id=?",
                    (str(review_id), action_id, str(report_id), finding_reference, proposal_hash,
                     partition, str(expected_review_id)),
                )
                current = conn.execute(
                    "SELECT report_id,partition,finding_reference,proposal_hash,review_id,action_id "
                    "FROM activity_context_review_links WHERE report_id=? AND finding_reference=? "
                    "AND proposal_hash=? AND partition=?",
                    (str(report_id), finding_reference, proposal_hash, partition),
                ).fetchone()
            assert current is not None
            return ActivityContextReviewLink(
                UUID(str(current[0])), str(current[1]), str(current[2]), str(current[3]),
                UUID(str(current[4])), str(current[5]),
            )
