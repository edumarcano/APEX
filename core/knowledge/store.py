"""SQLite persistence for immutable knowledge evidence and temporal records."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from uuid import UUID, uuid4

from core.connectors.models import utc_now_iso
from core.knowledge.models import (
    Entity,
    KnowledgeHistoryEvent,
    KnowledgeRecord,
    KnowledgeRecordDetail,
    KnowledgeRecordSource,
    KnowledgeReview,
    KnowledgeSource,
)
from core.retrieval.models import RetrievalItem
from core.retrieval.store import sync_namespace_in_transaction

_KINDS = {"idea", "preference", "decision", "goal", "fact", "constraint", "note", "observation"}
_STATUSES = {"active", "conflicting", "superseded", "retracted"}
_SOURCE_KINDS = {"conversation_message", "manual"}
_SOURCE_ORIGINS = {"operator_input", "connected_service", "external_tool", "unknown"}
_DERIVATIONS = {"direct", "model_interpretation", "unknown"}
_PARTITIONS = {"production", "sandbox"}
_KNOWLEDGE_SCHEMA_VERSION = 9
_SOURCE_SELECT = "id,kind,partition,locator,original_text,content_hash,created_at,origin,occurred_at"
_RECORD_SELECT = (
    "id,partition,kind,text,status,subject_entity_id,predicate,object_entity_id,object_value,"
    "effective_at,supersedes_record_id,created_at,updated_at"
)
_SOURCE_SELECT_S = "s." + _SOURCE_SELECT.replace(",", ",s.")
_RECORD_SELECT_R = "r." + _RECORD_SELECT.replace(",", ",r.")
_TRANSITIONS = {
    "active": {"conflicting", "superseded", "retracted"},
    "conflicting": {"active", "superseded", "retracted"},
    "retracted": {"active"},
    "superseded": set(),
}


class KnowledgeStoreError(RuntimeError):
    pass


class KnowledgeNotFoundError(KnowledgeStoreError):
    pass


class KnowledgeConflictError(KnowledgeStoreError):
    pass


def normalize_alias(value: str) -> str:
    return " ".join(value.split()).casefold()


def _required_text(value: str, field: str, *, limit: int = 10_000) -> str:
    normalized = " ".join(value.split()) if field in {"predicate", "name"} else value.strip()
    if not normalized or len(normalized) > limit:
        raise KnowledgeStoreError(f"{field}_invalid")
    return normalized


def _source_origin_for_kind(kind: str) -> str:
    if kind in {"conversation_message", "manual"}:
        return "operator_input"
    raise KnowledgeStoreError("source_invalid")


def _optional_timestamp(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise KnowledgeStoreError(f"{field}_invalid") from exc
    return value


class KnowledgeStore:
    """Owns canonical knowledge writes and their derived retrieval rows."""

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
            sqlite3.connect(":memory:", check_same_thread=False) if db_path is None else None
        )

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

    @contextmanager
    def _write_connection(self, connection: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
        """Use a caller-owned transaction or create one for a standalone write."""
        if connection is not None:
            yield connection
            return
        with self._connection() as conn, conn:
            yield conn

    def close(self) -> None:
        with self._lock:
            if self._memory_connection is not None:
                if self._owns_memory_connection:
                    self._memory_connection.close()
                self._memory_connection = None

    def initialize(self) -> None:
        with self._connection() as conn:
            try:
                conn.execute("BEGIN")
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_versions ("
                    "domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version >= 1))"
                )
                row = conn.execute("SELECT version FROM schema_versions WHERE domain = 'knowledge'").fetchone()
                version = int(row[0]) if row is not None else 0
                if version > _KNOWLEDGE_SCHEMA_VERSION:
                    raise KnowledgeStoreError("Knowledge schema is newer than this APEX build.")
                self._create_schema(conn)
                if "merged_into_entity_id" not in {str(column[1]) for column in conn.execute("PRAGMA table_info(entities)")}:
                    conn.execute("ALTER TABLE entities ADD COLUMN merged_into_entity_id TEXT REFERENCES entities(id)")
                if version < 4:
                    self._migrate_to_v4(conn)
                if version < _KNOWLEDGE_SCHEMA_VERSION or not self._has_review_schema(conn):
                    self._migrate_to_v6(conn)
                self._migrate_to_v8(conn)
                self._migrate_to_v9(conn)
                if version <= _KNOWLEDGE_SCHEMA_VERSION:
                    conn.execute(
                        "INSERT INTO schema_versions(domain, version) VALUES ('knowledge', ?) "
                        "ON CONFLICT(domain) DO UPDATE SET version = excluded.version",
                        (_KNOWLEDGE_SCHEMA_VERSION,),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS knowledge_sources (
                id TEXT PRIMARY KEY NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('conversation_message', 'manual')),
                partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                locator TEXT NOT NULL,
                original_text TEXT NOT NULL CHECK(length(trim(original_text)) > 0),
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT 'unknown' CHECK(origin IN ('operator_input', 'connected_service', 'external_tool', 'unknown')),
                occurred_at TEXT,
                UNIQUE(kind, partition, locator, content_hash)
            )""",
            """CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY NOT NULL,
                name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                normalized_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS entity_aliases (
                normalized_alias TEXT PRIMARY KEY NOT NULL,
                entity_id TEXT NOT NULL REFERENCES entities(id),
                alias TEXT NOT NULL CHECK(length(trim(alias)) > 0),
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_records (
                id TEXT PRIMARY KEY NOT NULL,
                partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                kind TEXT NOT NULL CHECK(kind IN ('idea', 'preference', 'decision', 'goal', 'fact', 'constraint', 'note', 'observation')),
                text TEXT NOT NULL CHECK(length(trim(text)) > 0),
                status TEXT NOT NULL CHECK(status IN ('active', 'conflicting', 'superseded', 'retracted')),
                subject_entity_id TEXT REFERENCES entities(id), predicate TEXT,
                object_entity_id TEXT REFERENCES entities(id), object_value TEXT, effective_at TEXT,
                supersedes_record_id TEXT REFERENCES knowledge_records(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                CHECK((subject_entity_id IS NULL AND predicate IS NULL AND object_entity_id IS NULL AND object_value IS NULL)
                   OR (subject_entity_id IS NOT NULL AND predicate IS NOT NULL AND (object_entity_id IS NOT NULL OR object_value IS NOT NULL))),
                CHECK(NOT (object_entity_id IS NOT NULL AND object_value IS NOT NULL))
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_record_sources (
                record_id TEXT NOT NULL REFERENCES knowledge_records(id), source_id TEXT NOT NULL REFERENCES knowledge_sources(id),
                action_id TEXT, linked_at TEXT NOT NULL,
                derivation TEXT NOT NULL DEFAULT 'unknown' CHECK(derivation IN ('direct', 'model_interpretation', 'unknown')),
                PRIMARY KEY(record_id, source_id)
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_record_predecessors (
                record_id TEXT NOT NULL REFERENCES knowledge_records(id), predecessor_record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                relation TEXT NOT NULL CHECK(relation IN ('supersedes', 'conflict_resolution')),
                linked_at TEXT NOT NULL,
                PRIMARY KEY(record_id, predecessor_record_id), CHECK(record_id <> predecessor_record_id)
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_history (
                id TEXT PRIMARY KEY NOT NULL, record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                operation TEXT NOT NULL, actor TEXT NOT NULL, reason_code TEXT NOT NULL,
                related_record_id TEXT REFERENCES knowledge_records(id), source_id TEXT REFERENCES knowledge_sources(id),
                action_id TEXT, review_id TEXT, created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_action_effects (
                action_id TEXT PRIMARY KEY NOT NULL, record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                source_id TEXT NOT NULL REFERENCES knowledge_sources(id),
                outcome TEXT NOT NULL CHECK(outcome IN ('created', 'confirmed', 'conflicting')), created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_reconciliation_effects (
                action_id TEXT PRIMARY KEY NOT NULL, operation TEXT NOT NULL, target_id TEXT NOT NULL,
                outcome TEXT NOT NULL, created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_reviews (
                id TEXT PRIMARY KEY NOT NULL,
                partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                operation TEXT NOT NULL,
                proposal_json TEXT NOT NULL CHECK(json_valid(proposal_json)),
                evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
                expected_revisions_json TEXT NOT NULL CHECK(json_valid(expected_revisions_json)),
                reason_codes_json TEXT NOT NULL CHECK(json_valid(reason_codes_json)),
                decision TEXT NOT NULL CHECK(decision IN ('pending', 'accepted', 'rejected', 'stale')),
                action_id TEXT UNIQUE,
                decision_at TEXT,
                created_at TEXT NOT NULL,
                idempotency_key TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_review_actions (
                review_id TEXT NOT NULL REFERENCES knowledge_reviews(id),
                action_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                PRIMARY KEY(review_id, action_id)
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_submission_keys (
                partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                idempotency_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                action_id TEXT NOT NULL,
                result_json TEXT,
                PRIMARY KEY(partition, idempotency_key)
            )""",
            """CREATE TABLE IF NOT EXISTS knowledge_partition_revisions (
                partition TEXT PRIMARY KEY NOT NULL CHECK(partition IN ('production', 'sandbox')),
                revision INTEGER NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_records_partition_status ON knowledge_records(partition, status, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_records_subject ON knowledge_records(partition, subject_entity_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_records_object ON knowledge_records(partition, object_entity_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_record_sources_source ON knowledge_record_sources(source_id)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_predecessors_predecessor ON knowledge_record_predecessors(predecessor_record_id)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_history_record ON knowledge_history(record_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_reviews_partition_pending ON knowledge_reviews(partition, decision, created_at DESC)",
        )
        for statement in statements:
            conn.execute(statement)
        columns = {str(column[1]) for column in conn.execute("PRAGMA table_info(knowledge_reviews)")}
        if "idempotency_key" in columns:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_reviews_idempotency "
                "ON knowledge_reviews(partition,idempotency_key) WHERE idempotency_key IS NOT NULL"
            )

    @staticmethod
    def _has_review_schema(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_reviews'"
        ).fetchone() is not None

    @staticmethod
    def _migrate_to_v6(conn: sqlite3.Connection) -> None:
        """Create review storage without inventing history for existing records."""
        # _create_schema is intentionally idempotent; version-five development
        # databases have the provenance layout but not necessarily this table.
        KnowledgeStore._create_schema(conn)
        columns = {str(column[1]) for column in conn.execute("PRAGMA table_info(knowledge_reviews)")}
        if "idempotency_key" not in columns:
            conn.execute("ALTER TABLE knowledge_reviews ADD COLUMN idempotency_key TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_reviews_idempotency "
            "ON knowledge_reviews(partition,idempotency_key) WHERE idempotency_key IS NOT NULL"
        )

    @staticmethod
    def _migrate_to_v8(conn: sqlite3.Connection) -> None:
        columns = {str(column[1]) for column in conn.execute("PRAGMA table_info(knowledge_submission_keys)")}
        if "result_json" not in columns:
            conn.execute("ALTER TABLE knowledge_submission_keys ADD COLUMN result_json TEXT")
        for partition in _PARTITIONS:
            conn.execute(
                "INSERT INTO knowledge_partition_revisions(partition,revision) VALUES (?,0) ON CONFLICT(partition) DO NOTHING",
                (partition,),
            )
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_review_actions(review_id,action_id,created_at) "
            "SELECT id,action_id,created_at FROM knowledge_reviews WHERE action_id IS NOT NULL"
        )

    @staticmethod
    def _migrate_to_v9(conn: sqlite3.Connection) -> None:
        """Scope review retry keys to their partition without losing attempts."""
        indexes = conn.execute("PRAGMA index_list(knowledge_reviews)").fetchall()
        has_global_retry_key = any(
            bool(index[2])
            and [str(column[2]) for column in conn.execute(f"PRAGMA index_info({index[1]})").fetchall()]
            == ["idempotency_key"]
            for index in indexes
        )
        if not has_global_retry_key:
            return
        conn.execute("ALTER TABLE knowledge_review_actions RENAME TO knowledge_review_actions_v8")
        conn.execute("ALTER TABLE knowledge_reviews RENAME TO knowledge_reviews_v8")
        conn.execute(
            "CREATE TABLE knowledge_reviews ("
            "id TEXT PRIMARY KEY NOT NULL,"
            "partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),"
            "operation TEXT NOT NULL,"
            "proposal_json TEXT NOT NULL CHECK(json_valid(proposal_json)),"
            "evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),"
            "expected_revisions_json TEXT NOT NULL CHECK(json_valid(expected_revisions_json)),"
            "reason_codes_json TEXT NOT NULL CHECK(json_valid(reason_codes_json)),"
            "decision TEXT NOT NULL CHECK(decision IN ('pending', 'accepted', 'rejected', 'stale')),"
            "action_id TEXT UNIQUE, decision_at TEXT, created_at TEXT NOT NULL, idempotency_key TEXT)"
        )
        conn.execute(
            "INSERT INTO knowledge_reviews(id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at,idempotency_key) "
            "SELECT id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at,idempotency_key FROM knowledge_reviews_v8"
        )
        conn.execute(
            "CREATE TABLE knowledge_review_actions ("
            "review_id TEXT NOT NULL REFERENCES knowledge_reviews(id),"
            "action_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,"
            "PRIMARY KEY(review_id, action_id))"
        )
        conn.execute(
            "INSERT INTO knowledge_review_actions(review_id,action_id,created_at) "
            "SELECT review_id,action_id,created_at FROM knowledge_review_actions_v8"
        )
        conn.execute("DROP TABLE knowledge_review_actions_v8")
        conn.execute("DROP TABLE knowledge_reviews_v8")
        conn.execute(
            "CREATE UNIQUE INDEX idx_knowledge_reviews_idempotency "
            "ON knowledge_reviews(partition,idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_reviews_partition_pending "
            "ON knowledge_reviews(partition, decision, created_at DESC)"
        )

    @staticmethod
    def _migrate_to_v4(conn: sqlite3.Connection) -> None:
        source_columns = {str(column[1]) for column in conn.execute("PRAGMA table_info(knowledge_sources)")}
        if "origin" not in source_columns:
            conn.execute(
                "ALTER TABLE knowledge_sources ADD COLUMN origin TEXT NOT NULL DEFAULT 'unknown' "
                "CHECK(origin IN ('operator_input', 'connected_service', 'external_tool', 'unknown'))"
            )
        if "occurred_at" not in source_columns:
            conn.execute("ALTER TABLE knowledge_sources ADD COLUMN occurred_at TEXT")
        link_columns = {str(column[1]) for column in conn.execute("PRAGMA table_info(knowledge_record_sources)")}
        if "derivation" not in link_columns:
            conn.execute(
                "ALTER TABLE knowledge_record_sources ADD COLUMN derivation TEXT NOT NULL DEFAULT 'unknown' "
                "CHECK(derivation IN ('direct', 'model_interpretation', 'unknown'))"
            )
        now = utc_now_iso()
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_record_predecessors(record_id,predecessor_record_id,relation,linked_at) "
            "SELECT id,supersedes_record_id,'supersedes',created_at FROM knowledge_records WHERE supersedes_record_id IS NOT NULL"
        )
        for (record_id,) in conn.execute("SELECT id FROM knowledge_records").fetchall():
            exists = conn.execute(
                "SELECT 1 FROM knowledge_history WHERE record_id=? AND operation='baseline' AND reason_code='migration_baseline'",
                (str(record_id),),
            ).fetchone()
            if exists is None:
                conn.execute(
                    "INSERT INTO knowledge_history(id,record_id,operation,actor,reason_code,related_record_id,source_id,action_id,review_id,created_at) "
                    "VALUES (?, ?, 'baseline', 'system', 'migration_baseline', NULL, NULL, NULL, NULL, ?)",
                    (str(uuid4()), str(record_id), now),
                )

    @staticmethod
    def _source(row: Sequence[object]) -> KnowledgeSource:
        return KnowledgeSource(
            id=UUID(str(row[0])), kind=str(row[1]), partition=str(row[2]), locator=str(row[3]),
            original_text=str(row[4]), content_hash=str(row[5]), created_at=str(row[6]),
            origin=str(row[7]), occurred_at=str(row[8]) if row[8] else None,
        )

    @staticmethod
    def _history(row: Sequence[object]) -> KnowledgeHistoryEvent:
        return KnowledgeHistoryEvent(
            id=UUID(str(row[0])), record_id=UUID(str(row[1])), operation=str(row[2]), actor=str(row[3]),
            reason_code=str(row[4]), related_record_id=UUID(str(row[5])) if row[5] else None,
            source_id=UUID(str(row[6])) if row[6] else None, action_id=str(row[7]) if row[7] else None,
            review_id=str(row[8]) if row[8] else None, created_at=str(row[9]),
        )

    @staticmethod
    def _record_history(
        conn: sqlite3.Connection, *, record_id: UUID | str, operation: str, actor: str = "system",
        reason_code: str, related_record_id: UUID | str | None = None, action_id: str | None = None,
        source_id: UUID | str | None = None, review_id: str | None = None, created_at: str,
    ) -> None:
        conn.execute(
            "INSERT INTO knowledge_history(id,record_id,operation,actor,reason_code,related_record_id,source_id,action_id,review_id,created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), str(record_id), operation, actor, reason_code,
             str(related_record_id) if related_record_id else None, str(source_id) if source_id else None,
             action_id, review_id, created_at),
        )

    @staticmethod
    def _link_predecessor(
        conn: sqlite3.Connection, *, record_id: UUID | str, predecessor_record_id: UUID | str,
        relation: str, linked_at: str,
    ) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO knowledge_record_predecessors VALUES (?, ?, ?, ?)",
            (str(record_id), str(predecessor_record_id), relation, linked_at),
        )

    @staticmethod
    def _entity(row: Sequence[object]) -> Entity:
        return Entity(
            id=UUID(str(row[0])), name=str(row[1]), normalized_name=str(row[2]),
            created_at=str(row[3]),
            merged_into_entity_id=UUID(str(row[4])) if len(row) > 4 and row[4] else None,
        )

    @staticmethod
    def _record(row: Sequence[object]) -> KnowledgeRecord:
        return KnowledgeRecord(
            id=UUID(str(row[0])), partition=str(row[1]), kind=str(row[2]), text=str(row[3]), status=str(row[4]),
            subject_entity_id=UUID(str(row[5])) if row[5] else None, predicate=str(row[6]) if row[6] else None,
            object_entity_id=UUID(str(row[7])) if row[7] else None, object_value=str(row[8]) if row[8] else None,
            effective_at=str(row[9]) if row[9] else None,
            supersedes_record_id=UUID(str(row[10])) if row[10] else None,
            created_at=str(row[11]), updated_at=str(row[12]),
        )

    def create_source(
        self, *, kind: str, partition: str, locator: str, original_text: str,
        origin: str | None = None, occurred_at: str | None = None, source_id: UUID | None = None,
    ) -> KnowledgeSource:
        if kind not in _SOURCE_KINDS or partition not in _PARTITIONS:
            raise KnowledgeStoreError("source_invalid")
        origin = origin or _source_origin_for_kind(kind)
        if origin not in _SOURCE_ORIGINS:
            raise KnowledgeStoreError("source_invalid")
        occurred_at = _optional_timestamp(occurred_at, "occurred_at")
        locator = _required_text(locator, "locator")
        original_text = _required_text(original_text, "original_text")
        digest = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
        identifier = source_id or uuid4()
        now = utc_now_iso()
        with self._connection() as conn, conn:
            existing = conn.execute(
                f"SELECT {_SOURCE_SELECT} FROM knowledge_sources "
                "WHERE kind = ? AND partition = ? AND locator = ? AND content_hash = ?",
                (kind, partition, locator, digest),
            ).fetchone()
            if existing is not None:
                return self._source(existing)
            try:
                conn.execute(
                    "INSERT INTO knowledge_sources(id,kind,partition,locator,original_text,content_hash,created_at,origin,occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(identifier), kind, partition, locator, original_text, digest, now, origin, occurred_at),
                )
            except sqlite3.IntegrityError as exc:
                raise KnowledgeConflictError("source_conflict") from exc
        return KnowledgeSource(identifier, kind, partition, locator, original_text, digest, now, origin, occurred_at)

    def create_entity(self, name: str, *, entity_id: UUID | None = None) -> Entity:
        name = _required_text(name, "name", limit=240)
        normalized = normalize_alias(name)
        if not normalized:
            raise KnowledgeStoreError("name_invalid")
        identifier, now = entity_id or uuid4(), utc_now_iso()
        with self._connection() as conn, conn:
            row = conn.execute("SELECT id,name,normalized_name,created_at,merged_into_entity_id FROM entities WHERE normalized_name = ?", (normalized,)).fetchone()
            if row is not None:
                return self._entity(row)
            try:
                conn.execute("INSERT INTO entities(id,name,normalized_name,created_at) VALUES (?, ?, ?, ?)", (str(identifier), name, normalized, now))
                conn.execute("INSERT INTO entity_aliases VALUES (?, ?, ?, ?)", (normalized, str(identifier), name, now))
            except sqlite3.IntegrityError as exc:
                raise KnowledgeConflictError("entity_conflict") from exc
        return Entity(identifier, name, normalized, now)

    def add_alias(self, entity_id: UUID, alias: str) -> Entity:
        alias = _required_text(alias, "name", limit=240)
        normalized = normalize_alias(alias)
        now = utc_now_iso()
        with self._connection() as conn, conn:
            entity = conn.execute("SELECT id,name,normalized_name,created_at,merged_into_entity_id FROM entities WHERE id = ?", (str(entity_id),)).fetchone()
            if entity is None:
                raise KnowledgeNotFoundError("entity_not_found")
            existing = conn.execute("SELECT entity_id FROM entity_aliases WHERE normalized_alias = ?", (normalized,)).fetchone()
            if existing is not None and str(existing[0]) != str(entity_id):
                raise KnowledgeConflictError("alias_conflict")
            inserted = conn.execute(
                "INSERT INTO entity_aliases VALUES (?, ?, ?, ?) ON CONFLICT(normalized_alias) DO NOTHING",
                (normalized, str(entity_id), alias, now),
            )
            if inserted.rowcount:
                conn.execute(
                    "UPDATE knowledge_records SET updated_at=? WHERE subject_entity_id=? OR object_entity_id=?",
                    (now, str(entity_id), str(entity_id)),
                )
            return self._entity(entity)

    def resolve_entity(self, alias: str) -> Entity | None:
        normalized = normalize_alias(alias)
        if not normalized:
            return None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT e.id,e.name,e.normalized_name,e.created_at,e.merged_into_entity_id FROM entity_aliases a "
                "JOIN entities e ON e.id = a.entity_id WHERE a.normalized_alias = ?",
                (normalized,),
            ).fetchone()
        return self._entity(row) if row is not None else None

    def get_entity(self, entity_id: UUID, *, include_merged: bool = False) -> Entity:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id,name,normalized_name,created_at,merged_into_entity_id FROM entities WHERE id = ?",
                (str(entity_id),),
            ).fetchone()
        if row is None:
            raise KnowledgeNotFoundError("entity_not_found")
        entity = self._entity(row)
        if entity.merged_into_entity_id is not None and not include_merged:
            raise KnowledgeNotFoundError("entity_not_found")
        return entity

    def list_entities(self, *, query: str = "", limit: int = 50) -> list[Entity]:
        limit = max(1, min(int(limit), 100))
        normalized = normalize_alias(query)
        with self._connection() as conn:
            if normalized:
                rows = conn.execute(
                    "SELECT DISTINCT e.id,e.name,e.normalized_name,e.created_at,e.merged_into_entity_id "
                    "FROM entities e LEFT JOIN entity_aliases a ON a.entity_id=e.id "
                    "WHERE e.merged_into_entity_id IS NULL AND "
                    "(instr(e.normalized_name, ?) > 0 OR instr(a.normalized_alias, ?) > 0) "
                    "ORDER BY e.name COLLATE NOCASE,e.id LIMIT ?",
                    (normalized, normalized, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id,name,normalized_name,created_at,merged_into_entity_id FROM entities "
                    "WHERE merged_into_entity_id IS NULL ORDER BY name COLLATE NOCASE,id LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._entity(row) for row in rows]

    def aliases_for_entity(self, entity_id: UUID) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT alias FROM entity_aliases WHERE entity_id = ? ORDER BY normalized_alias",
                (str(entity_id),),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def entity_in_partition(self, entity_id: UUID, *, partition: str) -> bool:
        if partition not in _PARTITIONS:
            raise KnowledgeStoreError("record_filter_invalid")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM knowledge_records WHERE partition=? AND "
                "(subject_entity_id=? OR object_entity_id=?) LIMIT 1",
                (partition, str(entity_id), str(entity_id)),
            ).fetchone()
        return row is not None

    def list_entities_in_partition(self, *, partition: str, query: str = "", limit: int = 50) -> list[Entity]:
        if partition not in _PARTITIONS:
            raise KnowledgeStoreError("record_filter_invalid")
        limit = max(1, min(int(limit), 100))
        normalized = normalize_alias(query)
        clauses = ["e.merged_into_entity_id IS NULL", "EXISTS (SELECT 1 FROM knowledge_records r WHERE r.partition=? AND (r.subject_entity_id=e.id OR r.object_entity_id=e.id))"]
        params: list[object] = [partition]
        if normalized:
            if partition == "sandbox":
                clauses.append("instr(e.normalized_name, ?) > 0")
                params.append(normalized)
            else:
                clauses.append("(instr(e.normalized_name, ?) > 0 OR instr(a.normalized_alias, ?) > 0)")
                params.extend((normalized, normalized))
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT e.id,e.name,e.normalized_name,e.created_at,e.merged_into_entity_id "
                "FROM entities e LEFT JOIN entity_aliases a ON a.entity_id=e.id WHERE "
                + " AND ".join(clauses) + " ORDER BY e.name COLLATE NOCASE,e.id LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [self._entity(row) for row in rows]

    def entities_mentioned_in(self, text: str, *, limit: int = 8) -> list[Entity]:
        """Return exact saved aliases that occur in normalized operator text."""
        normalized = normalize_alias(text)
        if not normalized:
            return []
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT e.id,e.name,e.normalized_name,e.created_at,e.merged_into_entity_id FROM entity_aliases a "
                "JOIN entities e ON e.id=a.entity_id WHERE instr(?, a.normalized_alias) > 0 AND e.merged_into_entity_id IS NULL "
                "GROUP BY e.id,e.name,e.normalized_name,e.created_at,e.merged_into_entity_id "
                "ORDER BY max(length(a.normalized_alias)) DESC, e.id LIMIT ?",
                (normalized, max(1, min(limit, 32))),
            ).fetchall()
        return [self._entity(row) for row in rows]

    def create_record(
        self,
        *,
        partition: str,
        kind: str,
        text: str,
        source_ids: Sequence[UUID],
        status: str = "active",
        subject_entity_id: UUID | None = None,
        predicate: str | None = None,
        object_entity_id: UUID | None = None,
        object_value: str | None = None,
        effective_at: str | None = None,
        supersedes_record_id: UUID | None = None,
        supersedes_record_ids: Sequence[UUID] | None = None,
        action_id: str | None = None,
        source_derivations: Mapping[UUID, str] | None = None,
        record_id: UUID | None = None,
    ) -> KnowledgeRecord:
        if partition not in _PARTITIONS or kind not in _KINDS or status not in _STATUSES:
            raise KnowledgeStoreError("record_invalid")
        text = _required_text(text, "text")
        if not source_ids:
            raise KnowledgeStoreError("record_source_required")
        structured = any(value is not None for value in (subject_entity_id, predicate, object_entity_id, object_value))
        if structured and (subject_entity_id is None or predicate is None or (object_entity_id is None and object_value is None) or (object_entity_id is not None and object_value is not None)):
            raise KnowledgeStoreError("record_structure_invalid")
        if predicate is not None:
            predicate = _required_text(predicate, "predicate", limit=240)
        if object_value is not None:
            object_value = _required_text(object_value, "object_value", limit=1_000)
        predecessor_ids = list(dict.fromkeys(supersedes_record_ids or ()))
        if supersedes_record_id is not None:
            if supersedes_record_id not in predecessor_ids:
                predecessor_ids.append(supersedes_record_id)
        derivations = source_derivations or {}
        if any(source_id not in source_ids or derivation not in _DERIVATIONS for source_id, derivation in derivations.items()):
            raise KnowledgeStoreError("record_source_invalid")
        identifier, now = record_id or uuid4(), utc_now_iso()
        with self._connection() as conn, conn:
            source_rows = conn.execute(
                "SELECT id FROM knowledge_sources WHERE id IN (%s)" % ",".join("?" for _ in source_ids),
                tuple(str(source_id) for source_id in source_ids),
            ).fetchall()
            if len(source_rows) != len(set(source_ids)):
                raise KnowledgeNotFoundError("source_not_found")
            source_partitions = conn.execute(
                "SELECT DISTINCT partition FROM knowledge_sources WHERE id IN (%s)" % ",".join("?" for _ in source_ids),
                tuple(str(source_id) for source_id in source_ids),
            ).fetchall()
            if {str(row[0]) for row in source_partitions} != {partition}:
                raise KnowledgeConflictError("source_partition_conflict")
            for predecessor_id in predecessor_ids:
                prior = conn.execute("SELECT status,partition FROM knowledge_records WHERE id = ?", (str(predecessor_id),)).fetchone()
                if prior is None:
                    raise KnowledgeNotFoundError("superseded_record_not_found")
                if str(prior[1]) != partition or str(prior[0]) not in {"active", "conflicting"}:
                    raise KnowledgeConflictError("supersession_invalid")
                conn.execute("UPDATE knowledge_records SET status = 'superseded', updated_at = ? WHERE id = ?", (now, str(predecessor_id)))
            try:
                conn.execute(
                    "INSERT INTO knowledge_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(identifier), partition, kind, text, status, str(subject_entity_id) if subject_entity_id else None,
                     predicate, str(object_entity_id) if object_entity_id else None, object_value, effective_at,
                     str(predecessor_ids[0]) if predecessor_ids else None, now, now),
                )
                conn.executemany(
                    "INSERT INTO knowledge_record_sources(record_id,source_id,action_id,linked_at,derivation) VALUES (?, ?, ?, ?, ?)",
                    ((str(identifier), str(source_id), action_id, now, derivations.get(source_id, "unknown")) for source_id in dict.fromkeys(source_ids)),
                )
            except sqlite3.IntegrityError as exc:
                raise KnowledgeConflictError("record_conflict") from exc
            for predecessor_id in predecessor_ids:
                self._link_predecessor(conn, record_id=identifier, predecessor_record_id=predecessor_id, relation="supersedes", linked_at=now)
                self._record_history(conn, record_id=predecessor_id, operation="superseded", reason_code="record_replacement", related_record_id=identifier, action_id=action_id, created_at=now)
            self._record_history(conn, record_id=identifier, operation="created", reason_code="record_created", action_id=action_id, created_at=now)
            for source_id in dict.fromkeys(source_ids):
                self._record_history(conn, record_id=identifier, operation="source_linked", reason_code=derivations.get(source_id, "unknown"), source_id=source_id, action_id=action_id, created_at=now)
            self._sync_retrieval(conn)
            row = conn.execute(f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id = ?", (str(identifier),)).fetchone()
        assert row is not None
        return self._record(row)

    def set_status(self, record_id: UUID, *, partition: str, status: str) -> KnowledgeRecord:
        if partition not in _PARTITIONS or status not in _STATUSES:
            raise KnowledgeStoreError("record_invalid")
        now = utc_now_iso()
        with self._connection() as conn, conn:
            row = conn.execute(f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id = ? AND partition = ?", (str(record_id), partition)).fetchone()
            if row is None:
                raise KnowledgeNotFoundError("record_not_found")
            current = str(row[4])
            if current == status:
                return self._record(row)
            if status not in _TRANSITIONS[current]:
                raise KnowledgeConflictError("status_transition_invalid")
            conn.execute("UPDATE knowledge_records SET status = ?, updated_at = ? WHERE id = ?", (status, now, str(record_id)))
            self._record_history(conn, record_id=record_id, operation="status_changed", reason_code=f"status_{status}", created_at=now)
            self._sync_retrieval(conn)
            updated = conn.execute(f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id = ?", (str(record_id),)).fetchone()
        assert updated is not None
        return self._record(updated)

    def get_record(self, record_id: UUID, *, partition: str) -> KnowledgeRecordDetail:
        with self._connection() as conn:
            row = conn.execute(f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id = ? AND partition = ?", (str(record_id), partition)).fetchone()
            if row is None:
                raise KnowledgeNotFoundError("record_not_found")
            sources = conn.execute(
                f"SELECT {_SOURCE_SELECT_S},l.derivation,l.action_id,l.linked_at "
                "FROM knowledge_record_sources l JOIN knowledge_sources s ON s.id = l.source_id "
                "WHERE l.record_id = ? ORDER BY s.created_at, s.id",
                (str(record_id),),
            ).fetchall()
            children = conn.execute(
                "SELECT record_id FROM knowledge_record_predecessors WHERE predecessor_record_id=? ORDER BY linked_at,record_id",
                (str(record_id),),
            ).fetchall()
            predecessors = conn.execute(
                "SELECT predecessor_record_id FROM knowledge_record_predecessors WHERE record_id=? ORDER BY linked_at,predecessor_record_id",
                (str(record_id),),
            ).fetchall()
            history = conn.execute(
                "SELECT id,record_id,operation,actor,reason_code,related_record_id,source_id,action_id,review_id,created_at "
                "FROM knowledge_history WHERE record_id=? ORDER BY created_at,rowid",
                (str(record_id),),
            ).fetchall()
        source_links = tuple(
            KnowledgeRecordSource(self._source(source[:9]), str(source[9]), str(source[10]) if source[10] else None, str(source[11]))
            for source in sources
        )
        return KnowledgeRecordDetail(
            self._record(row), tuple(link.source for link in source_links), source_links,
            tuple(UUID(str(child[0])) for child in children), tuple(UUID(str(item[0])) for item in predecessors),
            tuple(self._history(event) for event in history),
        )

    def list_records(
        self, *, partition: str, statuses: Sequence[str] = ("active",),
        kind: str | None = None, entity_id: UUID | None = None, query: str = "",
        limit: int = 100,
    ) -> list[KnowledgeRecord]:
        if partition not in _PARTITIONS or not statuses or any(status not in _STATUSES for status in statuses):
            raise KnowledgeStoreError("record_filter_invalid")
        limit = max(1, min(int(limit), 100))
        clauses, params = ["r.partition = ?", "r.status IN (%s)" % ",".join("?" for _ in statuses)], [partition, *statuses]
        if kind is not None:
            if kind not in _KINDS:
                raise KnowledgeStoreError("record_filter_invalid")
            clauses.append("r.kind = ?")
            params.append(kind)
        if entity_id is not None:
            clauses.append("(r.subject_entity_id = ? OR r.object_entity_id = ?)")
            params.extend((str(entity_id), str(entity_id)))
        normalized_query = normalize_alias(query)
        if normalized_query:
            clauses.append(
                "(instr(lower(r.text), ?) > 0 OR instr(lower(coalesce(subject.name, '')), ?) > 0 "
                "OR instr(lower(coalesce(object_entity.name, '')), ?) > 0 OR instr(lower(coalesce(r.predicate, '')), ?) > 0 "
                "OR instr(lower(coalesce(r.object_value, '')), ?) > 0)"
            )
            params.extend([normalized_query] * 5)
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_RECORD_SELECT_R} FROM knowledge_records r "
                "LEFT JOIN entities subject ON subject.id=r.subject_entity_id "
                "LEFT JOIN entities object_entity ON object_entity.id=r.object_entity_id WHERE "
                + " AND ".join(clauses) + " ORDER BY r.updated_at DESC,r.id LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [self._record(row) for row in rows]

    def one_hop_relationships(self, entity_id: UUID, *, partition: str) -> list[KnowledgeRecord]:
        return self.list_records(partition=partition, statuses=("active", "conflicting"), entity_id=entity_id)

    def affected_revisions(self, record_id: UUID, *, partition: str) -> dict[str, str]:
        """Return the complete current structured group without UI list limits."""
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?",
                (str(record_id), partition),
            ).fetchone()
            if row is None:
                raise KnowledgeNotFoundError("record_not_found")
            result = {str(row[0]): str(row[12])}
            if row[5] and row[6]:
                peers = conn.execute(
                    "SELECT id,updated_at FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? AND status IN ('active','conflicting')",
                    (partition, str(row[5]), str(row[6])),
                ).fetchall()
                result.update({str(item[0]): str(item[1]) for item in peers})
        return result

    def reconcile(
        self,
        *, action_id: str, operation: str, partition: str, arguments: dict[str, Any],
        connection: sqlite3.Connection | None = None, evidence: Mapping[str, object] | None = None,
    ) -> dict[str, str]:
        """Apply one approval-gated context mutation exactly once."""
        if partition not in _PARTITIONS:
            raise KnowledgeStoreError("reconciliation_invalid")
        now = utc_now_iso()
        with self._write_connection(connection) as conn:
            prior = conn.execute(
                "SELECT operation,target_id,outcome FROM knowledge_reconciliation_effects WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if prior is not None:
                return {"operation": str(prior[0]), "target_id": str(prior[1]), "outcome": str(prior[2])}

            def record(identifier: str) -> sqlite3.Row | tuple[object, ...]:
                row = conn.execute(
                    f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?", (identifier, partition)
                ).fetchone()
                if row is None:
                    raise KnowledgeNotFoundError("record_not_found")
                expected = str(arguments.get("expected_updated_at", ""))
                if expected and str(row[12]) != expected:
                    raise KnowledgeConflictError("record_changed")
                return row

            target_id = str(arguments.get("record_id") or arguments.get("entity_id") or arguments.get("source_entity_id") or "")
            if operation == "retract":
                row = record(target_id)
                if str(row[4]) not in {"active", "conflicting"}:
                    raise KnowledgeConflictError("retraction_invalid")
                conn.execute("UPDATE knowledge_records SET status='retracted',updated_at=? WHERE id=?", (now, target_id))
                self._record_history(conn, record_id=target_id, operation="status_changed", actor="operator", reason_code="status_retracted", action_id=action_id, created_at=now)
                outcome = "retracted"
                self._sync_retrieval(conn)
            elif operation == "restore":
                row = record(target_id)
                if str(row[4]) != "retracted":
                    raise KnowledgeConflictError("restore_invalid")
                restored_status = "active"
                if row[5] and row[6]:
                    sibling = conn.execute(
                        "SELECT 1 FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? "
                        "AND status IN ('active','conflicting') LIMIT 1",
                        (partition, str(row[5]), str(row[6])),
                    ).fetchone()
                    if sibling is not None:
                        restored_status = "conflicting"
                conn.execute("UPDATE knowledge_records SET status=?,updated_at=? WHERE id=?", (restored_status, now, target_id))
                self._record_history(conn, record_id=target_id, operation="status_changed", actor="operator", reason_code=f"status_{restored_status}", action_id=action_id, created_at=now)
                outcome = restored_status
                self._sync_retrieval(conn)
            elif operation == "set_current":
                row = record(target_id)
                if str(row[4]) != "conflicting" or not row[5] or not row[6]:
                    raise KnowledgeConflictError("conflict_resolution_invalid")
                rows = conn.execute(
                    "SELECT id FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? "
                    "AND status IN ('active','conflicting')",
                    (partition, str(row[5]), str(row[6])),
                ).fetchall()
                conn.execute("UPDATE knowledge_records SET status='active',updated_at=? WHERE id=?", (now, target_id))
                others = [str(item[0]) for item in rows if str(item[0]) != target_id]
                if others:
                    conn.execute(
                        "UPDATE knowledge_records SET status='superseded',updated_at=? "
                        "WHERE id IN (%s)" % ",".join("?" for _ in others),
                        (now, *others),
                    )
                    for predecessor_id in others:
                        self._link_predecessor(conn, record_id=target_id, predecessor_record_id=predecessor_id, relation="conflict_resolution", linked_at=now)
                        self._record_history(conn, record_id=predecessor_id, operation="superseded", actor="operator", reason_code="conflict_resolved", related_record_id=target_id, action_id=action_id, created_at=now)
                self._record_history(conn, record_id=target_id, operation="status_changed", actor="operator", reason_code="status_active", action_id=action_id, created_at=now)
                self._record_history(conn, record_id=target_id, operation="conflict_resolved", actor="operator", reason_code="selected_current", action_id=action_id, created_at=now)
                outcome = "current"
                self._sync_retrieval(conn)
            elif operation == "add_alias":
                entity_id = str(arguments.get("entity_id", ""))
                alias = _required_text(str(arguments.get("alias", "")), "name", limit=240)
                entity = conn.execute(
                    "SELECT merged_into_entity_id FROM entities WHERE id=?", (entity_id,)
                ).fetchone()
                in_partition = conn.execute(
                    "SELECT 1 FROM knowledge_records WHERE partition=? AND (subject_entity_id=? OR object_entity_id=?) LIMIT 1",
                    (partition, entity_id, entity_id),
                ).fetchone()
                outside_partition = conn.execute(
                    "SELECT 1 FROM knowledge_records WHERE partition<>? AND (subject_entity_id=? OR object_entity_id=?) LIMIT 1",
                    (partition, entity_id, entity_id),
                ).fetchone()
                if entity is None or entity[0] is not None or in_partition is None or outside_partition is not None:
                    raise KnowledgeNotFoundError("entity_not_found")
                normalized = normalize_alias(alias)
                existing = conn.execute(
                    "SELECT entity_id FROM entity_aliases WHERE normalized_alias=?", (normalized,)
                ).fetchone()
                if existing is not None and str(existing[0]) != entity_id:
                    raise KnowledgeConflictError("alias_conflict")
                inserted = conn.execute(
                    "INSERT INTO entity_aliases VALUES (?, ?, ?, ?) ON CONFLICT(normalized_alias) DO NOTHING",
                    (normalized, entity_id, alias, now),
                )
                if inserted.rowcount:
                    affected_records = conn.execute(
                        "SELECT id FROM knowledge_records WHERE partition=? AND (subject_entity_id=? OR object_entity_id=?)",
                        (partition, entity_id, entity_id),
                    ).fetchall()
                    conn.execute(
                        "UPDATE knowledge_records SET updated_at=? WHERE partition=? AND (subject_entity_id=? OR object_entity_id=?)",
                        (now, partition, entity_id, entity_id),
                    )
                    for (record_id,) in affected_records:
                        self._record_history(conn, record_id=str(record_id), operation="entity_alias_added", actor="operator", reason_code="entity_alias", action_id=action_id, created_at=now)
                target_id, outcome = entity_id, "alias_added"
            elif operation == "merge_entities":
                source_id = str(arguments.get("source_entity_id", ""))
                target_entity_id = str(arguments.get("target_entity_id", ""))
                if not source_id or source_id == target_entity_id:
                    raise KnowledgeConflictError("entity_merge_invalid")
                source = conn.execute("SELECT merged_into_entity_id FROM entities WHERE id=?", (source_id,)).fetchone()
                target = conn.execute("SELECT merged_into_entity_id FROM entities WHERE id=?", (target_entity_id,)).fetchone()
                source_in_partition = conn.execute("SELECT 1 FROM knowledge_records WHERE partition=? AND (subject_entity_id=? OR object_entity_id=?) LIMIT 1", (partition, source_id, source_id)).fetchone()
                source_outside_partition = conn.execute("SELECT 1 FROM knowledge_records WHERE partition<>? AND (subject_entity_id=? OR object_entity_id=?) LIMIT 1", (partition, source_id, source_id)).fetchone()
                target_outside_partition = conn.execute("SELECT 1 FROM knowledge_records WHERE partition<>? AND (subject_entity_id=? OR object_entity_id=?) LIMIT 1", (partition, target_entity_id, target_entity_id)).fetchone()
                if source is None or target is None or source[0] is not None or target[0] is not None or source_in_partition is None or source_outside_partition is not None or target_outside_partition is not None:
                    raise KnowledgeConflictError("entity_merge_invalid")
                affected_records = conn.execute(
                    "SELECT id FROM knowledge_records WHERE partition=? AND (subject_entity_id=? OR object_entity_id=?)",
                    (partition, source_id, source_id),
                ).fetchall()
                conn.execute("UPDATE knowledge_records SET subject_entity_id=? WHERE subject_entity_id=?", (target_entity_id, source_id))
                conn.execute("UPDATE knowledge_records SET object_entity_id=? WHERE object_entity_id=?", (target_entity_id, source_id))
                conn.execute("UPDATE entity_aliases SET entity_id=? WHERE entity_id=?", (target_entity_id, source_id))
                conn.execute("UPDATE entities SET merged_into_entity_id=? WHERE id=?", (target_entity_id, source_id))
                conn.execute(
                    "UPDATE knowledge_records SET updated_at=? WHERE partition=? AND (subject_entity_id=? OR object_entity_id=?)",
                    (now, partition, target_entity_id, target_entity_id),
                )
                for (record_id,) in affected_records:
                    self._record_history(conn, record_id=str(record_id), operation="entity_reassigned", actor="operator", reason_code="entity_merged", action_id=action_id, created_at=now)
                target_id, outcome = source_id, "merged"
                self._sync_retrieval(conn)
            elif operation == "correct":
                row = record(target_id)
                if str(row[4]) != "active":
                    raise KnowledgeConflictError("correction_invalid")
                capture = arguments.get("capture")
                if not isinstance(capture, dict):
                    raise KnowledgeStoreError("correction_invalid")
                kind = str(capture.get("kind", ""))
                text = _required_text(str(capture.get("text", "")), "text")
                from core.knowledge.capture import reject_secret_text, validate_effective_at

                reject_secret_text(text)
                validate_effective_at(capture.get("effective_at"))
                if kind not in _KINDS:
                    raise KnowledgeStoreError("record_invalid")
                subject = capture.get("subject")
                predicate = capture.get("predicate")
                object_entity = capture.get("object_entity")
                object_value = capture.get("object_value")
                structured = any(value is not None for value in (subject, predicate, object_entity, object_value))
                if structured and (not subject or not predicate or bool(object_entity) == bool(object_value)):
                    raise KnowledgeStoreError("record_structure_invalid")
                source_id = uuid4()
                frozen = dict(evidence or {})
                source_text = _required_text(str(frozen.get("original_text", text)), "original_text")
                reject_secret_text(source_text)
                locator = _required_text(str(frozen.get("locator", f"manual/action/{action_id}")), "locator")
                source_kind = str(frozen.get("source_kind", "manual"))
                source_origin = str(frozen.get("source_origin", "operator_input"))
                derivation = str(frozen.get("derivation", "direct"))
                occurred_at = _optional_timestamp(frozen.get("occurred_at"), "occurred_at")
                if source_kind not in _SOURCE_KINDS or source_origin not in _SOURCE_ORIGINS or derivation not in _DERIVATIONS:
                    raise KnowledgeStoreError("correction_provenance_invalid")
                digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
                conn.execute(
                    "INSERT INTO knowledge_sources(id,kind,partition,locator,original_text,content_hash,created_at,origin,occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(source_id), source_kind, partition, locator, source_text, digest, now, source_origin, occurred_at),
                )
                subject_id = object_id = None
                if structured:
                    subject_id = self._resolve_or_create_entity_in_transaction(conn, str(subject), now)
                    if object_entity:
                        object_id = self._resolve_or_create_entity_in_transaction(conn, str(object_entity), now)
                    predicate = _required_text(str(predicate), "predicate", limit=240)
                    if object_value:
                        object_value = _required_text(str(object_value), "object_value", limit=1_000)
                conn.execute("UPDATE knowledge_records SET status='superseded',updated_at=? WHERE id=?", (now, target_id))
                created = self._insert_record_in_transaction(
                    conn, partition=partition, kind=kind, text=text, status="active", now=now,
                    subject_entity_id=subject_id, predicate=predicate, object_entity_id=object_id,
                    object_value=object_value, effective_at=capture.get("effective_at"),
                )
                conn.execute("UPDATE knowledge_records SET supersedes_record_id=? WHERE id=?", (target_id, str(created.id)))
                self._link_predecessor(conn, record_id=created.id, predecessor_record_id=target_id, relation="supersedes", linked_at=now)
                conn.execute(
                    "INSERT INTO knowledge_record_sources(record_id,source_id,action_id,linked_at,derivation) VALUES (?, ?, ?, ?, ?)",
                    (str(created.id), str(source_id), action_id, now, derivation),
                )
                self._record_history(conn, record_id=target_id, operation="superseded", actor="operator", reason_code="record_correction", related_record_id=created.id, action_id=action_id, created_at=now)
                self._record_history(conn, record_id=created.id, operation="created", actor="operator", reason_code="correction_created", related_record_id=target_id, action_id=action_id, created_at=now)
                self._record_history(conn, record_id=created.id, operation="source_linked", actor="operator", reason_code=derivation, source_id=source_id, action_id=action_id, created_at=now)
                target_id, outcome = str(created.id), "corrected"
                self._sync_retrieval(conn)
            else:
                raise KnowledgeStoreError("reconciliation_invalid")
            conn.execute(
                "INSERT INTO knowledge_reconciliation_effects VALUES (?, ?, ?, ?, ?)",
                (action_id, operation, target_id, outcome, now),
            )
        return {"operation": operation, "target_id": target_id, "outcome": outcome}

    def reconciliation_effect(self, action_id: str) -> dict[str, str] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT operation,target_id,outcome FROM knowledge_reconciliation_effects WHERE action_id=?",
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        return {"operation": str(row[0]), "target_id": str(row[1]), "outcome": str(row[2])}

    @staticmethod
    def _review(row: Sequence[object]) -> KnowledgeReview:
        return KnowledgeReview(
            id=UUID(str(row[0])), partition=str(row[1]), operation=str(row[2]),
            proposal=json.loads(str(row[3])), evidence=json.loads(str(row[4])),
            expected_revisions=json.loads(str(row[5])), reason_codes=tuple(json.loads(str(row[6]))),
            decision=str(row[7]), action_id=str(row[8]) if row[8] else None,
            decision_at=str(row[9]) if row[9] else None, created_at=str(row[10]),
        )

    @staticmethod
    def _validate_review_content(operation: str, proposal: Mapping[str, object], evidence: Mapping[str, object]) -> None:
        """Apply the secret boundary before frozen evidence reaches SQLite."""
        from core.knowledge.capture import reject_secret_text, validate_effective_at

        capture: Mapping[str, object]
        if operation == "correct":
            candidate = proposal.get("capture")
            if not isinstance(candidate, Mapping):
                raise KnowledgeStoreError("correction_invalid")
            capture = candidate
        else:
            capture = proposal
        if operation in {"capture", "correct"}:
            reject_secret_text(str(capture.get("text", "")))
            validate_effective_at(capture.get("effective_at"))
            if evidence.get("original_text") is not None:
                reject_secret_text(str(evidence["original_text"]))

    def create_review(
        self, *, partition: str, operation: str, proposal: Mapping[str, object],
        evidence: Mapping[str, object], expected_revisions: Mapping[str, str],
        reason_codes: Sequence[str], action_id: str | None = None, idempotency_key: str | None = None,
    ) -> KnowledgeReview:
        """Persist a proposal and its source snapshot before it can be approved."""
        if partition not in _PARTITIONS or not operation or not reason_codes:
            raise KnowledgeStoreError("review_invalid")
        self._validate_review_content(operation, proposal, evidence)
        identifier, now = uuid4(), utc_now_iso()
        payloads = (
            json.dumps(dict(proposal), sort_keys=True, separators=(",", ":")),
            json.dumps(dict(evidence), sort_keys=True, separators=(",", ":")),
            json.dumps(dict(expected_revisions), sort_keys=True, separators=(",", ":")),
            json.dumps(list(dict.fromkeys(reason_codes)), separators=(",", ":")),
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if action_id or idempotency_key:
                    existing = conn.execute(
                        "SELECT id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at "
                        "FROM knowledge_reviews WHERE action_id=? OR (partition=? AND idempotency_key=?)",
                        (action_id, partition, idempotency_key),
                    ).fetchone()
                    if existing is not None:
                        prior = self._review(existing)
                        if (
                            prior.operation != operation or prior.proposal != dict(proposal)
                            or prior.evidence != dict(evidence) or prior.partition != partition
                            or prior.expected_revisions != dict(expected_revisions)
                            or prior.reason_codes != tuple(dict.fromkeys(reason_codes))
                        ):
                            raise KnowledgeConflictError("idempotency_key_reused")
                        conn.commit()
                        return prior
                conn.execute(
                    "INSERT INTO knowledge_reviews(id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at,idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, ?, ?)",
                    (str(identifier), partition, operation, *payloads, action_id, now, idempotency_key),
                )
                if action_id is not None:
                    conn.execute(
                        "INSERT INTO knowledge_review_actions(review_id,action_id,created_at) VALUES (?, ?, ?)",
                        (str(identifier), action_id, now),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return KnowledgeReview(identifier, partition, operation, dict(proposal), dict(evidence), dict(expected_revisions), tuple(dict.fromkeys(reason_codes)), "pending", action_id, None, now)

    def get_review(self, review_id: UUID, *, partition: str) -> KnowledgeReview:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at FROM knowledge_reviews WHERE id=? AND partition=?",
                (str(review_id), partition),
            ).fetchone()
        if row is None:
            raise KnowledgeNotFoundError("review_not_found")
        return self._review(row)

    def review_for_action(self, action_id: str, *, partition: str) -> KnowledgeReview | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT r.id,r.partition,r.operation,r.proposal_json,r.evidence_json,r.expected_revisions_json,r.reason_codes_json,r.decision,r.action_id,r.decision_at,r.created_at "
                "FROM knowledge_reviews r JOIN knowledge_review_actions a ON a.review_id=r.id WHERE a.action_id=? AND r.partition=?",
                (action_id, partition),
            ).fetchone()
        return self._review(row) if row else None

    def link_review_action(self, review_id: UUID, *, partition: str, action_id: str) -> KnowledgeReview:
        """Replace an expired review attempt without discarding the review itself."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT decision FROM knowledge_reviews WHERE id=? AND partition=?", (str(review_id), partition)).fetchone()
                if row is None:
                    raise KnowledgeNotFoundError("review_not_found")
                if str(row[0]) != "pending":
                    raise KnowledgeConflictError("review_decided")
                conn.execute("UPDATE knowledge_reviews SET action_id=? WHERE id=?", (action_id, str(review_id)))
                conn.execute(
                    "INSERT INTO knowledge_review_actions(review_id,action_id,created_at) VALUES (?, ?, ?)",
                    (str(review_id), action_id, utc_now_iso()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_review(review_id, partition=partition)

    def reserve_review_attempt(
        self, review_id: UUID, *, partition: str, action_id: str, replace: bool = False,
    ) -> KnowledgeReview:
        """Atomically select the one action attempt allowed to execute a review."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at FROM knowledge_reviews WHERE id=? AND partition=?",
                    (str(review_id), partition),
                ).fetchone()
                if row is None:
                    raise KnowledgeNotFoundError("review_not_found")
                review = self._review(row)
                if review.decision != "pending":
                    conn.commit()
                    return review
                if self._review_snapshot_in_transaction(conn, review) != review.expected_revisions:
                    raise KnowledgeConflictError("review_refresh_required")
                if review.action_id and not replace:
                    conn.commit()
                    return review
                conn.execute("UPDATE knowledge_reviews SET action_id=? WHERE id=? AND decision='pending'", (action_id, str(review_id)))
                conn.execute(
                    "INSERT INTO knowledge_review_actions(review_id,action_id,created_at) VALUES (?, ?, ?)",
                    (str(review_id), action_id, utc_now_iso()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_review(review_id, partition=partition)

    def prepare_review_decision(
        self, review_id: UUID, *, partition: str, expected_revisions: Mapping[str, str],
    ) -> KnowledgeReview:
        """Validate the caller's frozen view before any action lifecycle change."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at FROM knowledge_reviews WHERE id=? AND partition=?",
                    (str(review_id), partition),
                ).fetchone()
                if row is None:
                    raise KnowledgeNotFoundError("review_not_found")
                review = self._review(row)
                if dict(expected_revisions) != review.expected_revisions:
                    raise KnowledgeConflictError("review_refresh_required")
                if review.decision == "pending" and self._review_snapshot_in_transaction(conn, review) != review.expected_revisions:
                    raise KnowledgeConflictError("review_refresh_required")
                conn.commit()
                return review
            except Exception:
                conn.rollback()
                raise

    def list_reviews(self, *, partition: str, decisions: Sequence[str] = ("pending",), limit: int = 50) -> list[KnowledgeReview]:
        allowed = {"pending", "accepted", "rejected", "stale"}
        if partition not in _PARTITIONS or not decisions or any(item not in allowed for item in decisions):
            raise KnowledgeStoreError("review_filter_invalid")
        limit = max(1, min(int(limit), 100))
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at FROM knowledge_reviews "
                "WHERE partition=? AND decision IN (%s) ORDER BY created_at DESC,id LIMIT ?" % ",".join("?" for _ in decisions),
                (partition, *decisions, limit),
            ).fetchall()
        return [self._review(row) for row in rows]

    def pending_reviews_for_record(self, record_id: UUID, *, partition: str) -> list[UUID]:
        # Expected revisions name every current claim whose state was reviewed.
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id,expected_revisions_json FROM knowledge_reviews WHERE partition=? AND decision='pending' ORDER BY created_at",
                (partition,),
            ).fetchall()
        return [UUID(str(row[0])) for row in rows if str(record_id) in json.loads(str(row[1]))]

    def reject_review(self, review_id: UUID, *, partition: str) -> KnowledgeReview:
        now = utc_now_iso()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                review = self.get_review(review_id, partition=partition)
                if review.decision == "rejected":
                    conn.commit()
                    return review
                if review.decision != "pending":
                    raise KnowledgeConflictError("review_decided")
                if self._review_snapshot_in_transaction(conn, review) != review.expected_revisions:
                    raise KnowledgeConflictError("review_refresh_required")
                conn.execute("UPDATE knowledge_reviews SET decision='rejected',decision_at=? WHERE id=?", (now, str(review_id)))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_review(review_id, partition=partition)

    def _review_snapshot_in_transaction(
        self, conn: sqlite3.Connection, review: KnowledgeReview,
    ) -> dict[str, str]:
        """Recompute every record a decision can affect under the writer lock."""
        proposal = dict(review.proposal)
        try:
            return self._proposal_snapshot_in_transaction(
                conn, partition=review.partition, operation=review.operation, proposal=proposal,
            )
        except KnowledgeConflictError as exc:
            if review.operation != "correct" or str(exc) != "record_changed":
                raise
            target = conn.execute(
                f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?",
                (str(proposal.get("record_id", "")), review.partition),
            ).fetchone()
            if target is None or str(target[4]) != "active":
                return {}
            proposal["expected_updated_at"] = str(target[12])
            return self._proposal_snapshot_in_transaction(
                conn, partition=review.partition, operation=review.operation, proposal=proposal,
            )

    def review_snapshot(
        self, *, partition: str, operation: str, proposal: Mapping[str, object],
    ) -> dict[str, str]:
        """Return the complete optimistic snapshot for a proposed review."""
        if partition not in _PARTITIONS:
            raise KnowledgeStoreError("review_invalid")
        with self._connection() as conn:
            return self._proposal_snapshot_in_transaction(
                conn, partition=partition, operation=operation, proposal=proposal,
            )

    def _proposal_snapshot_in_transaction(
        self, conn: sqlite3.Connection, *, partition: str, operation: str, proposal: Mapping[str, object],
    ) -> dict[str, str]:
        proposal = dict(proposal)
        if operation == "capture":
            return dict(self.capture_decision(partition=partition, connection=conn, **proposal)["expected_revisions"])
        if operation == "correct":
            capture = proposal.get("capture")
            if not isinstance(capture, Mapping):
                raise KnowledgeStoreError("correction_invalid")
            return dict(self._correction_decision_in_transaction(
                conn, partition=partition, record_id=str(proposal.get("record_id", "")),
                expected_updated_at=str(proposal.get("expected_updated_at", "")), values=capture,
                sensitive=False,
            )["expected_revisions"])
        if operation == "add_alias":
            entity_id = str(proposal.get("entity_id", ""))
            return {
                **self._record_revisions_in_transaction(conn, partition=partition, entity_ids=(entity_id,)),
                **self._entity_snapshot_in_transaction(
                    conn, partition=partition, entity_ids=(entity_id,), aliases=(str(proposal.get("alias", "")),),
                ),
            }
        if operation == "merge_entities":
            entity_ids = (str(proposal.get("source_entity_id", "")), str(proposal.get("target_entity_id", "")))
            return {
                **self._record_revisions_in_transaction(conn, partition=partition, entity_ids=entity_ids),
                **self._entity_snapshot_in_transaction(conn, partition=partition, entity_ids=entity_ids),
            }
        target_id = str(proposal.get("record_id", ""))
        target = conn.execute(
            f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?",
            (target_id, partition),
        ).fetchone()
        if target is None:
            return {}
        result = {str(target[0]): str(target[12])}
        entity_ids = [str(item) for item in (target[5], target[7]) if item]
        if target[5] and target[6]:
            result.update({
                str(row[0]): str(row[1])
                for row in conn.execute(
                    "SELECT id,updated_at FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? "
                    "AND status IN ('active','conflicting')",
                    (partition, str(target[5]), str(target[6])),
                ).fetchall()
            })
        return {**result, **self._entity_snapshot_in_transaction(conn, partition=partition, entity_ids=entity_ids)}

    def refresh_review(
        self, review_id: UUID, *, partition: str,
        expected_revisions: Mapping[str, str] | None = None,
    ) -> KnowledgeReview:
        """Freeze a new current snapshot after a stale review is deliberately revisited."""
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at FROM knowledge_reviews WHERE id=? AND partition=?",
                    (str(review_id), partition),
                ).fetchone()
                if row is None:
                    raise KnowledgeNotFoundError("review_not_found")
                review = self._review(row)
                if review.decision != "pending":
                    raise KnowledgeConflictError("review_decided")
                if expected_revisions is not None and dict(expected_revisions) != review.expected_revisions:
                    raise KnowledgeConflictError("review_refresh_required")
                proposal = dict(review.proposal)
                if review.operation == "correct":
                    target = conn.execute(
                        f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?",
                        (str(proposal.get("record_id", "")), partition),
                    ).fetchone()
                    if target is None:
                        raise KnowledgeConflictError("record_changed")
                    proposal["expected_updated_at"] = str(target[12])
                refreshed = self._create_review_in_transaction(
                    conn, partition=partition, operation=review.operation,
                    proposal=proposal, evidence=review.evidence,
                    expected_revisions=self._proposal_snapshot_in_transaction(
                        conn, partition=partition, operation=review.operation, proposal=proposal,
                    ),
                    reason_codes=tuple(dict.fromkeys((*review.reason_codes, "refresh_revalidated"))),
                )
                conn.execute(
                    "UPDATE knowledge_reviews SET decision='stale',decision_at=? WHERE id=? AND decision='pending'",
                    (utc_now_iso(), str(review_id)),
                )
                conn.commit()
                return refreshed
            except Exception:
                conn.rollback()
                raise

    def accept_review(self, review_id: UUID, *, partition: str, action_id: str | None = None) -> KnowledgeReview:
        """Apply the frozen proposal once; stale snapshots never write knowledge."""
        review = self.get_review(review_id, partition=partition)
        if review.decision == "accepted":
            return review
        if review.decision != "pending":
            raise KnowledgeConflictError("review_decided")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                state = conn.execute("SELECT decision FROM knowledge_reviews WHERE id=? AND partition=?", (str(review_id), partition)).fetchone()
                if state is None:
                    raise KnowledgeNotFoundError("review_not_found")
                if str(state[0]) == "accepted":
                    conn.commit()
                    return self.get_review(review_id, partition=partition)
                if str(state[0]) != "pending":
                    raise KnowledgeConflictError("review_decided")
                fresh_revisions = self._review_snapshot_in_transaction(conn, review)
                if fresh_revisions != review.expected_revisions:
                    raise KnowledgeConflictError("review_refresh_required")
                effect_id = action_id or review.action_id or f"review-{review.id}"
                if review.operation == "capture":
                    values, source = dict(review.proposal), dict(review.evidence)
                    record, _source, _outcome = self.apply_capture(
                        action_id=effect_id, partition=partition, source_kind=str(source["source_kind"]),
                        locator=str(source["locator"]), original_text=str(source["original_text"]),
                        source_origin=str(source.get("source_origin", "operator_input")),
                        source_occurred_at=source.get("occurred_at"), derivation=str(source.get("derivation", "unknown")),
                        connection=conn, **values,
                    )
                    affected = [record.id]
                    if "known_conflict" in review.reason_codes and record.subject_entity_id and record.predicate:
                        peers = conn.execute(
                            "SELECT id FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? AND status IN ('active','conflicting')",
                            (partition, str(record.subject_entity_id), record.predicate),
                        ).fetchall()
                        predecessors = [str(row[0]) for row in peers if str(row[0]) != str(record.id)]
                        conn.execute("UPDATE knowledge_records SET status='active',updated_at=? WHERE id=?", (utc_now_iso(), str(record.id)))
                        if predecessors:
                            conn.execute(
                                "UPDATE knowledge_records SET status='superseded',updated_at=? WHERE id IN (%s)" % ",".join("?" for _ in predecessors),
                                (utc_now_iso(), *predecessors),
                            )
                            for predecessor in predecessors:
                                self._link_predecessor(conn, record_id=record.id, predecessor_record_id=predecessor, relation="conflict_resolution", linked_at=utc_now_iso())
                                self._record_history(conn, record_id=predecessor, operation="superseded", actor="operator", reason_code="review_replacement", related_record_id=record.id, action_id=effect_id, review_id=str(review_id), created_at=utc_now_iso())
                            affected.extend(UUID(identifier) for identifier in predecessors)
                        self._sync_retrieval(conn)
                else:
                    outcome = self.reconcile(
                        action_id=effect_id, operation=review.operation, partition=partition,
                        arguments=dict(review.proposal), connection=conn, evidence=review.evidence,
                    )
                    affected = [UUID(str(outcome["target_id"]))] if review.operation in {"correct", "retract", "restore", "set_current"} else []
                    if review.operation == "correct":
                        selected = conn.execute(
                            f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?",
                            (outcome["target_id"], partition),
                        ).fetchone()
                        assert selected is not None
                        if selected[5] and selected[6]:
                            peers = conn.execute(
                                "SELECT id FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? AND status IN ('active','conflicting')",
                                (partition, str(selected[5]), str(selected[6])),
                            ).fetchall()
                            predecessors = [str(row[0]) for row in peers if str(row[0]) != str(selected[0])]
                            if predecessors:
                                now = utc_now_iso()
                                conn.execute(
                                    "UPDATE knowledge_records SET status='superseded',updated_at=? WHERE id IN (%s)" % ",".join("?" for _ in predecessors),
                                    (now, *predecessors),
                                )
                                for predecessor in predecessors:
                                    self._link_predecessor(
                                        conn, record_id=str(selected[0]), predecessor_record_id=predecessor,
                                        relation="conflict_resolution", linked_at=now,
                                    )
                                    self._record_history(
                                        conn, record_id=predecessor, operation="superseded", actor="operator",
                                        reason_code="review_replacement", related_record_id=str(selected[0]),
                                        action_id=effect_id, review_id=str(review_id), created_at=now,
                                    )
                                affected.extend(UUID(identifier) for identifier in predecessors)
                                self._sync_retrieval(conn)
                    affected.extend(
                        UUID(identifier)
                        for identifier in review.expected_revisions
                        if not identifier.startswith(("entity:", "alias:"))
                    )
                now = utc_now_iso()
                for record_id in dict.fromkeys(affected):
                    self._record_history(conn, record_id=record_id, operation="review_accepted", actor="operator", reason_code="review_accepted", action_id=effect_id, review_id=str(review_id), created_at=now)
                conn.execute("UPDATE knowledge_reviews SET decision='accepted',decision_at=? WHERE id=? AND decision='pending'", (now, str(review_id)))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_review(review_id, partition=partition)

    @staticmethod
    def _entity_snapshot_in_transaction(
        conn: sqlite3.Connection, *, partition: str, entity_ids: Sequence[str] = (), aliases: Sequence[str] = (),
    ) -> dict[str, str]:
        """Freeze entity identity and alias resolution alongside record revisions."""
        snapshot: dict[str, str] = {}
        for entity_id in dict.fromkeys(str(item) for item in entity_ids if item):
            entity = conn.execute(
                "SELECT id,name,normalized_name,merged_into_entity_id FROM entities WHERE id=?", (entity_id,)
            ).fetchone()
            entity_aliases = conn.execute(
                "SELECT normalized_alias,alias,created_at FROM entity_aliases WHERE entity_id=? ORDER BY normalized_alias",
                (entity_id,),
            ).fetchall()
            snapshot[f"entity:{entity_id}"] = json.dumps(
                [list(entity) if entity else None, [list(item) for item in entity_aliases]],
                separators=(",", ":"),
            )
        for alias in dict.fromkeys(normalize_alias(str(item)) for item in aliases if str(item).strip()):
            row = conn.execute(
                "SELECT entity_id,alias,created_at FROM entity_aliases WHERE normalized_alias=?", (alias,)
            ).fetchone()
            snapshot[f"alias:{alias}"] = json.dumps(list(row) if row else None, separators=(",", ":"))
        return snapshot

    @staticmethod
    def _record_revisions_in_transaction(
        conn: sqlite3.Connection, *, partition: str, entity_ids: Sequence[str] = (), record_ids: Sequence[str] = (),
    ) -> dict[str, str]:
        clauses: list[str] = []
        params: list[str] = [partition]
        identifiers = list(dict.fromkeys(str(item) for item in record_ids if item))
        if identifiers:
            clauses.append("id IN (%s)" % ",".join("?" for _ in identifiers))
            params.extend(identifiers)
        entities = list(dict.fromkeys(str(item) for item in entity_ids if item))
        if entities:
            clauses.append(
                "(subject_entity_id IN (%s) OR object_entity_id IN (%s))"
                % (",".join("?" for _ in entities), ",".join("?" for _ in entities))
            )
            params.extend((*entities, *entities))
        if not clauses:
            return {}
        rows = conn.execute(
            "SELECT id,updated_at FROM knowledge_records WHERE partition=? AND (" + " OR ".join(clauses) + ")",
            params,
        ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def _capture_snapshot_in_transaction(
        self, conn: sqlite3.Connection, *, partition: str, subject: object, object_entity: object,
        record_revisions: Mapping[str, str],
    ) -> dict[str, str]:
        aliases = [str(subject)] if subject else []
        if object_entity:
            aliases.append(str(object_entity))
        entity_ids: list[str] = []
        for alias in aliases:
            row = conn.execute("SELECT entity_id FROM entity_aliases WHERE normalized_alias=?", (normalize_alias(alias),)).fetchone()
            if row is not None:
                entity_ids.append(str(row[0]))
        return {
            **dict(record_revisions),
            **self._entity_snapshot_in_transaction(conn, partition=partition, entity_ids=entity_ids, aliases=aliases),
        }

    def capture_decision(
        self, *, partition: str, kind: object, text: object, subject: object = None,
        predicate: object = None, object_entity: object = None, object_value: object = None,
        effective_at: object = None, sensitive: object = False,
        connection: sqlite3.Connection | None = None, **_ignored: object,
    ) -> dict[str, object]:
        """Classify a capture without writing it or guessing entity identity."""
        if partition not in _PARTITIONS or str(kind) not in _KINDS:
            raise KnowledgeStoreError("capture_invalid")
        value = _required_text(str(text), "text")
        timestamp = str(effective_at) if effective_at is not None else None
        _optional_timestamp(timestamp, "effective_at")
        structured = any(item is not None for item in (subject, predicate, object_entity, object_value))
        expected: dict[str, str] = {}
        reasons: list[str] = []
        with self._write_connection(connection) as conn:
            if structured:
                if not subject or not predicate or bool(object_entity) == bool(object_value):
                    raise KnowledgeStoreError("record_structure_invalid")
                subject_row = conn.execute("SELECT entity_id FROM entity_aliases WHERE normalized_alias=?", (normalize_alias(str(subject)),)).fetchone()
                rows = [] if subject_row is None else conn.execute(
                    "SELECT id,kind,object_entity_id,object_value,effective_at,updated_at FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? AND status IN ('active','conflicting')",
                    (partition, str(subject_row[0]), _required_text(str(predicate), "predicate", limit=240)),
                ).fetchall()
                object_row = conn.execute("SELECT entity_id FROM entity_aliases WHERE normalized_alias=?", (normalize_alias(str(object_entity)),)).fetchone() if object_entity else None
                desired_entity = str(object_row[0]) if object_row else None
                exact = [row for row in rows if str(row[1]) == str(kind) and str(row[2] or '') == str(desired_entity or '') and str(row[3] or '') == str(object_value or '') and (str(row[4]) if row[4] else None) == timestamp]
                if exact and len(exact) == len(rows):
                    expected = self._capture_snapshot_in_transaction(
                        conn, partition=partition, subject=subject, object_entity=object_entity,
                        record_revisions={str(row[0]): str(row[5]) for row in exact},
                    )
                    return {"requires_review": bool(sensitive), "expected_revisions": expected, "reason_codes": ("sensitive",) if sensitive else (), "duplicate": True}
                if rows:
                    expected = {str(row[0]): str(row[5]) for row in rows}
                    reasons.append("known_conflict")
                expected = self._capture_snapshot_in_transaction(
                    conn, partition=partition, subject=subject, object_entity=object_entity,
                    record_revisions=expected,
                )
            else:
                rows = conn.execute(
                    "SELECT id,kind,text,effective_at,updated_at FROM knowledge_records "
                    "WHERE partition=? AND status IN ('active','conflicting') "
                    "AND subject_entity_id IS NULL AND predicate IS NULL "
                    "AND object_entity_id IS NULL AND object_value IS NULL",
                    (partition,),
                ).fetchall()
                exact = [row for row in rows if str(row[1]) == str(kind) and normalize_alias(str(row[2])) == normalize_alias(value) and (str(row[3]) if row[3] else None) == timestamp]
                if exact:
                    return {"requires_review": bool(sensitive), "expected_revisions": {str(row[0]): str(row[4]) for row in exact}, "reason_codes": ("sensitive",) if sensitive else (), "duplicate": True}
        if sensitive:
            reasons.append("sensitive")
        return {"requires_review": bool(reasons), "expected_revisions": expected, "reason_codes": tuple(reasons), "duplicate": bool(structured and exact)}

    @staticmethod
    def _submission_hash(payload: Mapping[str, object]) -> str:
        return hashlib.sha256(
            json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _create_review_in_transaction(
        self, conn: sqlite3.Connection, *, partition: str, operation: str,
        proposal: Mapping[str, object], evidence: Mapping[str, object],
        expected_revisions: Mapping[str, str], reason_codes: Sequence[str],
        action_id: str | None = None, idempotency_key: str | None = None,
    ) -> KnowledgeReview:
        if partition not in _PARTITIONS or not operation or not reason_codes:
            raise KnowledgeStoreError("review_invalid")
        self._validate_review_content(operation, proposal, evidence)
        identifier, now = uuid4(), utc_now_iso()
        payloads = (
            json.dumps(dict(proposal), sort_keys=True, separators=(",", ":")),
            json.dumps(dict(evidence), sort_keys=True, separators=(",", ":")),
            json.dumps(dict(expected_revisions), sort_keys=True, separators=(",", ":")),
            json.dumps(list(dict.fromkeys(reason_codes)), separators=(",", ":")),
        )
        conn.execute(
            "INSERT INTO knowledge_reviews(id,partition,operation,proposal_json,evidence_json,expected_revisions_json,reason_codes_json,decision,action_id,decision_at,created_at,idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, ?, ?)",
            (str(identifier), partition, operation, *payloads, action_id, now, idempotency_key),
        )
        if action_id is not None:
            conn.execute(
                "INSERT INTO knowledge_review_actions(review_id,action_id,created_at) VALUES (?, ?, ?)",
                (str(identifier), action_id, now),
            )
        return KnowledgeReview(
            identifier, partition, operation, dict(proposal), dict(evidence),
            dict(expected_revisions), tuple(dict.fromkeys(reason_codes)), "pending", action_id, None, now,
        )

    def _correction_decision_in_transaction(
        self, conn: sqlite3.Connection, *, partition: str, record_id: str,
        expected_updated_at: str | None, values: Mapping[str, object], sensitive: bool,
    ) -> dict[str, object]:
        """Freeze both sides of a correction before deciding whether it is direct."""
        target = conn.execute(
            f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?",
            (record_id, partition),
        ).fetchone()
        if target is None or str(target[4]) != "active" or str(target[12]) != expected_updated_at:
            raise KnowledgeConflictError("record_changed")
        capture = self.capture_decision(partition=partition, sensitive=sensitive, connection=conn, **dict(values))
        snapshot = dict(capture["expected_revisions"])
        snapshot[str(target[0])] = str(target[12])
        entity_ids = [str(item) for item in (target[5], target[7]) if item]
        old_peers: dict[str, str] = {}
        if target[5] and target[6]:
            old_peers = {
                str(row[0]): str(row[1])
                for row in conn.execute(
                    "SELECT id,updated_at FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? "
                    "AND status IN ('active','conflicting')",
                    (partition, str(target[5]), str(target[6])),
                ).fetchall()
            }
            snapshot.update(old_peers)
        snapshot.update(self._entity_snapshot_in_transaction(
            conn, partition=partition, entity_ids=entity_ids,
        ))
        peers = set(old_peers) | {
            key for key in snapshot if not key.startswith(("entity:", "alias:"))
        }
        peers.discard(str(target[0]))
        reasons = list(capture["reason_codes"])
        correction = dict(values)
        desired_subject = correction.get("subject")
        desired_predicate = correction.get("predicate")
        desired_structured = any(
            value is not None
            for value in (
                desired_subject, desired_predicate,
                correction.get("object_entity"), correction.get("object_value"),
            )
        )
        desired_subject_row = (
            conn.execute(
                "SELECT entity_id FROM entity_aliases WHERE normalized_alias=?",
                (normalize_alias(str(desired_subject)),),
            ).fetchone()
            if desired_structured and desired_subject else None
        )
        desired_predicate_value = (
            _required_text(str(desired_predicate), "predicate", limit=240)
            if desired_structured and desired_predicate else None
        )
        same_group = (
            not target[5] and not target[6] and not desired_structured
        ) or bool(
            target[5] and target[6] and desired_subject_row is not None
            and str(target[5]) == str(desired_subject_row[0])
            and str(target[6]) == desired_predicate_value
        )
        group_changed = not same_group
        if not peers and same_group:
            reasons = [reason for reason in reasons if reason != "known_conflict"]
        if peers and "known_conflict" not in reasons:
            reasons.append("known_conflict")
        if group_changed:
            reasons.append("correction_group_changed")
        return {
            "requires_review": bool(
                sensitive or peers or group_changed
                or any(reason not in {"known_conflict", "sensitive"} for reason in capture["reason_codes"])
            ),
            "expected_revisions": snapshot,
            "reason_codes": tuple(reasons),
        }

    def submit_operator(
        self, *, partition: str, values: Mapping[str, object], sensitive: bool,
        idempotency_key: str | None, correction_record_id: str | None = None,
        expected_updated_at: str | None = None,
    ) -> tuple[KnowledgeRecord | None, KnowledgeReview | None]:
        """Classify and apply one operator save under a single writer lock.

        The retry key is bound to the complete policy input before the current
        state is inspected.  A failed transaction therefore leaves no reserved
        key, while an exact retry returns the original durable outcome.
        """
        reject_payload = {
            "operation": "correct" if correction_record_id else "capture",
            "values": dict(values), "sensitive": bool(sensitive),
            "correction_record_id": correction_record_id,
            "expected_updated_at": expected_updated_at,
        }
        digest = self._submission_hash(reject_payload)
        action_id = f"operator-save-{uuid4()}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if idempotency_key is not None:
                    prior = conn.execute(
                        "SELECT payload_hash,result_json FROM knowledge_submission_keys WHERE partition=? AND idempotency_key=?",
                        (partition, idempotency_key),
                    ).fetchone()
                    if prior is not None:
                        if str(prior[0]) != digest:
                            raise KnowledgeConflictError("idempotency_key_reused")
                        if not prior[1]:
                            raise KnowledgeConflictError("idempotency_recovery_required")
                        result = json.loads(str(prior[1]))
                        conn.commit()
                        if result["kind"] == "record":
                            return self.get_record(UUID(result["id"]), partition=partition).record, None
                        return None, self.get_review(UUID(result["id"]), partition=partition)

                operation = "capture"
                proposal: dict[str, object] = dict(values)
                if correction_record_id is not None:
                    operation = "correct"
                    decision = self._correction_decision_in_transaction(
                        conn, partition=partition, record_id=correction_record_id,
                        expected_updated_at=expected_updated_at, values=values, sensitive=sensitive,
                    )
                    expected = dict(decision["expected_revisions"])
                    proposal = {
                        "record_id": correction_record_id,
                        "expected_updated_at": expected_updated_at or "",
                        "capture": dict(values),
                    }
                else:
                    decision = self.capture_decision(
                        partition=partition, sensitive=sensitive, connection=conn, **dict(values),
                    )
                    expected = dict(decision["expected_revisions"])

                evidence = {
                    "source_kind": "manual", "locator": f"manual/{action_id}",
                    "original_text": str(values["text"]), "source_origin": "operator_input",
                    "derivation": "direct", "occurred_at": None,
                }
                if decision["requires_review"]:
                    review = self._create_review_in_transaction(
                        conn, partition=partition, operation=operation, proposal=proposal,
                        evidence=evidence, expected_revisions=expected,
                        reason_codes=tuple(decision["reason_codes"]), idempotency_key=idempotency_key,
                    )
                    result = {"kind": "review", "id": str(review.id)}
                    if idempotency_key is not None:
                        conn.execute(
                            "INSERT INTO knowledge_submission_keys(partition,idempotency_key,payload_hash,action_id,result_json) VALUES (?, ?, ?, ?, ?)",
                            (partition, idempotency_key, digest, action_id, json.dumps(result, separators=(",", ":"))),
                        )
                    conn.commit()
                    return None, review

                if operation == "capture":
                    record, _source, _outcome = self.apply_capture(
                        action_id=action_id, partition=partition, source_kind="manual", locator=evidence["locator"],
                        original_text=evidence["original_text"], source_origin="operator_input", derivation="direct",
                        connection=conn, **dict(values),
                    )
                else:
                    outcome = self.reconcile(
                        action_id=action_id, operation="correct", partition=partition,
                        arguments=proposal, connection=conn,
                    )
                    row = conn.execute(
                        f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=? AND partition=?",
                        (outcome["target_id"], partition),
                    ).fetchone()
                    assert row is not None
                    record = self._record(row)
                if idempotency_key is not None:
                    result = {"kind": "record", "id": str(record.id)}
                    conn.execute(
                        "INSERT INTO knowledge_submission_keys(partition,idempotency_key,payload_hash,action_id,result_json) VALUES (?, ?, ?, ?, ?)",
                        (partition, idempotency_key, digest, action_id, json.dumps(result, separators=(",", ":"))),
                    )
                conn.commit()
                return record, None
            except Exception:
                conn.rollback()
                raise

    def apply_capture(
        self, *, action_id: str, partition: str, source_kind: str, locator: str,
        original_text: str, kind: str, text: str, subject: str | None = None,
        predicate: str | None = None, object_entity: str | None = None,
        object_value: str | None = None, effective_at: str | None = None,
        source_origin: str | None = None, source_occurred_at: str | None = None,
        derivation: str = "unknown", connection: sqlite3.Connection | None = None,
    ) -> tuple[KnowledgeRecord, KnowledgeSource, str]:
        """Apply one approved capture once and record an auditable outcome."""
        if partition not in _PARTITIONS or source_kind not in _SOURCE_KINDS or kind not in _KINDS or derivation not in _DERIVATIONS:
            raise KnowledgeStoreError("capture_invalid")
        from core.knowledge.capture import reject_secret_text, validate_effective_at

        reject_secret_text(text)
        reject_secret_text(original_text)
        validate_effective_at(effective_at)
        source_origin = source_origin or _source_origin_for_kind(source_kind)
        if source_origin not in _SOURCE_ORIGINS:
            raise KnowledgeStoreError("capture_invalid")
        source_occurred_at = _optional_timestamp(source_occurred_at, "occurred_at")
        text = _required_text(text, "text")
        original_text = _required_text(original_text, "original_text")
        locator = _required_text(locator, "locator")
        structured = any(value is not None for value in (subject, predicate, object_entity, object_value))
        if structured and (not subject or not predicate or bool(object_entity) == bool(object_value)):
            raise KnowledgeStoreError("record_structure_invalid")
        now = utc_now_iso()
        digest = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
        with self._write_connection(connection) as conn:
            existing_effect = conn.execute(
                f"SELECT {_RECORD_SELECT_R}, {_SOURCE_SELECT_S} "
                "FROM knowledge_action_effects e JOIN knowledge_records r ON r.id=e.record_id "
                "JOIN knowledge_sources s ON s.id=e.source_id WHERE e.action_id=?", (action_id,)
            ).fetchone()
            if existing_effect is not None:
                return self._record(existing_effect[:13]), self._source(existing_effect[13:22]), "confirmed"
            source_row = conn.execute(
                f"SELECT {_SOURCE_SELECT} FROM knowledge_sources "
                "WHERE kind=? AND partition=? AND locator=? AND content_hash=?",
                (source_kind, partition, locator, digest),
            ).fetchone()
            if source_row is None:
                source_id = uuid4()
                conn.execute(
                    "INSERT INTO knowledge_sources(id,kind,partition,locator,original_text,content_hash,created_at,origin,occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(source_id), source_kind, partition, locator, original_text, digest, now, source_origin, source_occurred_at),
                )
                source = KnowledgeSource(source_id, source_kind, partition, locator, original_text, digest, now, source_origin, source_occurred_at)
            else:
                source = self._source(source_row)
            subject_id = None
            object_id = None
            if structured:
                subject_id = self._resolve_or_create_entity_in_transaction(conn, subject or "", now)
                if object_entity:
                    object_id = self._resolve_or_create_entity_in_transaction(conn, object_entity, now)
                predicate = _required_text(predicate or "", "predicate", limit=240)
                if object_value:
                    object_value = _required_text(object_value, "object_value", limit=1_000)
                rows = conn.execute(
                    "SELECT * FROM knowledge_records WHERE partition=? AND subject_entity_id=? AND predicate=? "
                    "AND status IN ('active','conflicting') ORDER BY created_at,id",
                    (partition, str(subject_id), predicate),
                ).fetchall()
                same = next((row for row in rows if str(row[2]) == kind and str(row[7] or '') == str(object_id or '') and str(row[8] or '') == str(object_value or '') and (str(row[9]) if row[9] else None) == effective_at), None)
                if same is not None:
                    record = self._record(same)
                    outcome = "confirmed"
                    transitioned = []
                else:
                    transitioned = [row for row in rows if str(row[4]) != "conflicting"]
                    if transitioned:
                        conn.execute(
                            "UPDATE knowledge_records SET status='conflicting', updated_at=? WHERE id IN (%s)" % ",".join("?" for _ in transitioned),
                            (now, *(str(row[0]) for row in transitioned)),
                        )
                        status, outcome = "conflicting", "conflicting"
                    elif rows:
                        status, outcome = "conflicting", "conflicting"
                    else:
                        status, outcome = "active", "created"
                    record = self._insert_record_in_transaction(conn, partition=partition, kind=kind, text=text, status=status,
                        subject_entity_id=subject_id, predicate=predicate, object_entity_id=object_id, object_value=object_value,
                        effective_at=effective_at, now=now)
            else:
                normalized = normalize_alias(text)
                candidates = conn.execute(
                    "SELECT * FROM knowledge_records WHERE partition=? AND status IN ('active','conflicting') "
                    "AND subject_entity_id IS NULL AND predicate IS NULL "
                    "AND object_entity_id IS NULL AND object_value IS NULL ORDER BY created_at,id",
                    (partition,),
                ).fetchall()
                rows = [row for row in candidates if str(row[2]) == kind and normalize_alias(str(row[3])) == normalized and (str(row[9]) if row[9] else None) == effective_at]
                if rows:
                    record, outcome = self._record(rows[0]), "confirmed"
                    transitioned = []
                else:
                    record, outcome = self._insert_record_in_transaction(
                        conn, partition=partition, kind=kind, text=text, status="active",
                        effective_at=effective_at, now=now,
                    ), "created"
                    transitioned = []
            if outcome in {"created", "conflicting"}:
                for peer in transitioned:
                    self._record_history(
                        conn, record_id=str(peer[0]), operation="status_changed", reason_code="status_conflicting",
                        related_record_id=record.id, action_id=action_id, created_at=now,
                    )
                self._record_history(
                    conn, record_id=record.id, operation="created",
                    reason_code="initial_conflicting" if outcome == "conflicting" else "initial_active",
                    action_id=action_id, created_at=now,
                )
            linked = conn.execute(
                "INSERT OR IGNORE INTO knowledge_record_sources(record_id,source_id,action_id,linked_at,derivation) VALUES (?, ?, ?, ?, ?)",
                (str(record.id), str(source.id), action_id, now, derivation),
            )
            if linked.rowcount:
                conn.execute("UPDATE knowledge_records SET updated_at=? WHERE id=?", (now, str(record.id)))
                self._record_history(conn, record_id=record.id, operation="source_linked", reason_code=derivation, source_id=source.id, action_id=action_id, created_at=now)
            conn.execute("INSERT INTO knowledge_action_effects VALUES (?, ?, ?, ?, ?)", (action_id, str(record.id), str(source.id), outcome, now))
            self._sync_retrieval(conn)
        return record, source, outcome

    @staticmethod
    def _resolve_or_create_entity_in_transaction(conn: sqlite3.Connection, name: str, now: str) -> UUID:
        name = _required_text(name, "name", limit=240)
        normalized = normalize_alias(name)
        row = conn.execute("SELECT entity_id FROM entity_aliases WHERE normalized_alias=?", (normalized,)).fetchone()
        if row is not None:
            return UUID(str(row[0]))
        identifier = uuid4()
        conn.execute(
            "INSERT INTO entities(id,name,normalized_name,created_at) VALUES (?, ?, ?, ?)",
            (str(identifier), name, normalized, now),
        )
        conn.execute("INSERT INTO entity_aliases VALUES (?, ?, ?, ?)", (normalized, str(identifier), name, now))
        return identifier

    @staticmethod
    def _insert_record_in_transaction(conn: sqlite3.Connection, *, partition: str, kind: str, text: str, status: str,
        now: str, subject_entity_id: UUID | None = None, predicate: str | None = None,
        object_entity_id: UUID | None = None, object_value: str | None = None, effective_at: str | None = None) -> KnowledgeRecord:
        identifier = uuid4()
        conn.execute("INSERT INTO knowledge_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (str(identifier), partition, kind, text, status, str(subject_entity_id) if subject_entity_id else None,
             predicate, str(object_entity_id) if object_entity_id else None, object_value, effective_at, now, now))
        row = conn.execute(f"SELECT {_RECORD_SELECT} FROM knowledge_records WHERE id=?", (str(identifier),)).fetchone()
        assert row is not None
        return KnowledgeStore._record(row)

    def capture_effect(self, action_id: str) -> tuple[KnowledgeRecord, KnowledgeSource, str] | None:
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {_RECORD_SELECT_R},{_SOURCE_SELECT_S},e.outcome "
                "FROM knowledge_action_effects e JOIN knowledge_records r ON r.id=e.record_id "
                "JOIN knowledge_sources s ON s.id=e.source_id WHERE e.action_id=?", (action_id,)
            ).fetchone()
        return (self._record(row[:13]), self._source(row[13:22]), str(row[22])) if row else None

    def _sync_retrieval(self, conn: sqlite3.Connection) -> None:
        if self._memory_connection is not None:
            # DEMO_MODE has no shared durable retrieval database. Keep knowledge
            # process-local as well; the next process starts with a clean slate.
            return
        rows = conn.execute(
            "SELECT id,partition,kind,text,subject_entity_id,predicate,object_entity_id,object_value,updated_at "
            "FROM knowledge_records WHERE status = 'active' ORDER BY id"
        ).fetchall()
        items = [
            RetrievalItem(
                namespace="personal_context", source_type="knowledge_record", source_id=str(row[0]),
                partition=str(row[1]), conversation_id=None, message_id=None, role=None,
                timestamp=str(row[8]), locator=f"context/{row[0]}",
                content_hash=hashlib.sha256(str(row[3]).encode("utf-8")).hexdigest(), text=str(row[3]),
                title=str(row[2]), metadata={
                    "subject_entity_id": str(row[4]) if row[4] else None,
                    "predicate": str(row[5]) if row[5] else None,
                    "object_entity_id": str(row[6]) if row[6] else None,
                    "object_value": str(row[7]) if row[7] else None,
                },
            )
            for row in rows
        ]
        sync_namespace_in_transaction(conn, "personal_context", items)
