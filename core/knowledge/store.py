"""SQLite persistence for immutable knowledge evidence and temporal records."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence
from uuid import UUID, uuid4

from core.connectors.models import utc_now_iso
from core.knowledge.models import Entity, KnowledgeRecord, KnowledgeRecordDetail, KnowledgeSource
from core.retrieval.models import RetrievalItem
from core.retrieval.store import sync_namespace_in_transaction

_KINDS = {"idea", "preference", "decision", "goal", "fact", "constraint", "note", "observation"}
_STATUSES = {"active", "conflicting", "superseded", "retracted"}
_SOURCE_KINDS = {"conversation_message", "manual"}
_PARTITIONS = {"production", "sandbox"}
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
            row = conn.execute("SELECT version FROM schema_versions WHERE domain = 'knowledge'").fetchone()
            if row is not None and int(row[0]) > 3:
                raise KnowledgeStoreError("Knowledge schema is newer than this APEX build.")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_sources (
                    id TEXT PRIMARY KEY NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('conversation_message', 'manual')),
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                    locator TEXT NOT NULL,
                    original_text TEXT NOT NULL CHECK(length(trim(original_text)) > 0),
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(kind, partition, locator, content_hash)
                );
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY NOT NULL,
                    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
                    normalized_name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entity_aliases (
                    normalized_alias TEXT PRIMARY KEY NOT NULL,
                    entity_id TEXT NOT NULL REFERENCES entities(id),
                    alias TEXT NOT NULL CHECK(length(trim(alias)) > 0),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_records (
                    id TEXT PRIMARY KEY NOT NULL,
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                    kind TEXT NOT NULL CHECK(kind IN ('idea', 'preference', 'decision', 'goal', 'fact', 'constraint', 'note', 'observation')),
                    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
                    status TEXT NOT NULL CHECK(status IN ('active', 'conflicting', 'superseded', 'retracted')),
                    subject_entity_id TEXT REFERENCES entities(id),
                    predicate TEXT,
                    object_entity_id TEXT REFERENCES entities(id),
                    object_value TEXT,
                    effective_at TEXT,
                    supersedes_record_id TEXT REFERENCES knowledge_records(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    CHECK((subject_entity_id IS NULL AND predicate IS NULL AND object_entity_id IS NULL AND object_value IS NULL)
                       OR (subject_entity_id IS NOT NULL AND predicate IS NOT NULL
                           AND (object_entity_id IS NOT NULL OR object_value IS NOT NULL))),
                    CHECK(NOT (object_entity_id IS NOT NULL AND object_value IS NOT NULL))
                );
                CREATE TABLE IF NOT EXISTS knowledge_record_sources (
                    record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                    source_id TEXT NOT NULL REFERENCES knowledge_sources(id),
                    action_id TEXT,
                    linked_at TEXT NOT NULL,
                    PRIMARY KEY(record_id, source_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_action_effects (
                    action_id TEXT PRIMARY KEY NOT NULL,
                    record_id TEXT NOT NULL REFERENCES knowledge_records(id),
                    source_id TEXT NOT NULL REFERENCES knowledge_sources(id),
                    outcome TEXT NOT NULL CHECK(outcome IN ('created', 'confirmed', 'conflicting')),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_records_partition_status
                    ON knowledge_records(partition, status, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_knowledge_records_subject
                    ON knowledge_records(partition, subject_entity_id, status);
                CREATE INDEX IF NOT EXISTS idx_knowledge_records_object
                    ON knowledge_records(partition, object_entity_id, status);
                CREATE INDEX IF NOT EXISTS idx_knowledge_record_sources_source
                    ON knowledge_record_sources(source_id);
                CREATE TABLE IF NOT EXISTS knowledge_reconciliation_effects (
                    action_id TEXT PRIMARY KEY NOT NULL,
                    operation TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            if "merged_into_entity_id" not in {
                str(column[1]) for column in conn.execute("PRAGMA table_info(entities)")
            }:
                conn.execute(
                    "ALTER TABLE entities ADD COLUMN merged_into_entity_id TEXT REFERENCES entities(id)"
                )
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('knowledge', 3) "
                "ON CONFLICT(domain) DO UPDATE SET version = excluded.version"
            )

    @staticmethod
    def _source(row: Sequence[object]) -> KnowledgeSource:
        return KnowledgeSource(
            id=UUID(str(row[0])), kind=str(row[1]), partition=str(row[2]), locator=str(row[3]),
            original_text=str(row[4]), content_hash=str(row[5]), created_at=str(row[6]),
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

    def create_source(self, *, kind: str, partition: str, locator: str, original_text: str, source_id: UUID | None = None) -> KnowledgeSource:
        if kind not in _SOURCE_KINDS or partition not in _PARTITIONS:
            raise KnowledgeStoreError("source_invalid")
        locator = _required_text(locator, "locator")
        original_text = _required_text(original_text, "original_text")
        digest = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
        identifier = source_id or uuid4()
        now = utc_now_iso()
        with self._connection() as conn, conn:
            existing = conn.execute(
                "SELECT id,kind,partition,locator,original_text,content_hash,created_at FROM knowledge_sources "
                "WHERE kind = ? AND partition = ? AND locator = ? AND content_hash = ?",
                (kind, partition, locator, digest),
            ).fetchone()
            if existing is not None:
                return self._source(existing)
            try:
                conn.execute(
                    "INSERT INTO knowledge_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(identifier), kind, partition, locator, original_text, digest, now),
                )
            except sqlite3.IntegrityError as exc:
                raise KnowledgeConflictError("source_conflict") from exc
        return KnowledgeSource(identifier, kind, partition, locator, original_text, digest, now)

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
            conn.execute(
                "INSERT INTO entity_aliases VALUES (?, ?, ?, ?) ON CONFLICT(normalized_alias) DO NOTHING",
                (normalized, str(entity_id), alias, now),
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
        action_id: str | None = None,
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
            if supersedes_record_id is not None:
                prior = conn.execute("SELECT status,partition FROM knowledge_records WHERE id = ?", (str(supersedes_record_id),)).fetchone()
                if prior is None:
                    raise KnowledgeNotFoundError("superseded_record_not_found")
                if str(prior[1]) != partition or str(prior[0]) not in {"active", "conflicting"}:
                    raise KnowledgeConflictError("supersession_invalid")
                conn.execute("UPDATE knowledge_records SET status = 'superseded', updated_at = ? WHERE id = ?", (now, str(supersedes_record_id)))
            try:
                conn.execute(
                    "INSERT INTO knowledge_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(identifier), partition, kind, text, status, str(subject_entity_id) if subject_entity_id else None,
                     predicate, str(object_entity_id) if object_entity_id else None, object_value, effective_at,
                     str(supersedes_record_id) if supersedes_record_id else None, now, now),
                )
                conn.executemany(
                    "INSERT INTO knowledge_record_sources VALUES (?, ?, ?, ?)",
                    ((str(identifier), str(source_id), action_id, now) for source_id in dict.fromkeys(source_ids)),
                )
            except sqlite3.IntegrityError as exc:
                raise KnowledgeConflictError("record_conflict") from exc
            self._sync_retrieval(conn)
            row = conn.execute("SELECT * FROM knowledge_records WHERE id = ?", (str(identifier),)).fetchone()
        assert row is not None
        return self._record(row)

    def set_status(self, record_id: UUID, *, partition: str, status: str) -> KnowledgeRecord:
        if partition not in _PARTITIONS or status not in _STATUSES:
            raise KnowledgeStoreError("record_invalid")
        now = utc_now_iso()
        with self._connection() as conn, conn:
            row = conn.execute("SELECT * FROM knowledge_records WHERE id = ? AND partition = ?", (str(record_id), partition)).fetchone()
            if row is None:
                raise KnowledgeNotFoundError("record_not_found")
            current = str(row[4])
            if current == status:
                return self._record(row)
            if status not in _TRANSITIONS[current]:
                raise KnowledgeConflictError("status_transition_invalid")
            conn.execute("UPDATE knowledge_records SET status = ?, updated_at = ? WHERE id = ?", (status, now, str(record_id)))
            self._sync_retrieval(conn)
            updated = conn.execute("SELECT * FROM knowledge_records WHERE id = ?", (str(record_id),)).fetchone()
        assert updated is not None
        return self._record(updated)

    def get_record(self, record_id: UUID, *, partition: str) -> KnowledgeRecordDetail:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM knowledge_records WHERE id = ? AND partition = ?", (str(record_id), partition)).fetchone()
            if row is None:
                raise KnowledgeNotFoundError("record_not_found")
            sources = conn.execute(
                "SELECT s.id,s.kind,s.partition,s.locator,s.original_text,s.content_hash,s.created_at "
                "FROM knowledge_record_sources l JOIN knowledge_sources s ON s.id = l.source_id "
                "WHERE l.record_id = ? ORDER BY s.created_at, s.id",
                (str(record_id),),
            ).fetchall()
            children = conn.execute("SELECT id FROM knowledge_records WHERE supersedes_record_id = ? ORDER BY created_at, id", (str(record_id),)).fetchall()
        return KnowledgeRecordDetail(self._record(row), tuple(self._source(source) for source in sources), tuple(UUID(str(child[0])) for child in children))

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
                "SELECT r.* FROM knowledge_records r "
                "LEFT JOIN entities subject ON subject.id=r.subject_entity_id "
                "LEFT JOIN entities object_entity ON object_entity.id=r.object_entity_id WHERE "
                + " AND ".join(clauses) + " ORDER BY r.updated_at DESC,r.id LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [self._record(row) for row in rows]

    def one_hop_relationships(self, entity_id: UUID, *, partition: str) -> list[KnowledgeRecord]:
        return self.list_records(partition=partition, statuses=("active", "conflicting"), entity_id=entity_id)

    def reconcile(
        self,
        *, action_id: str, operation: str, partition: str, arguments: dict[str, Any],
    ) -> dict[str, str]:
        """Apply one approval-gated context mutation exactly once."""
        if partition not in _PARTITIONS:
            raise KnowledgeStoreError("reconciliation_invalid")
        now = utc_now_iso()
        with self._connection() as conn, conn:
            prior = conn.execute(
                "SELECT operation,target_id,outcome FROM knowledge_reconciliation_effects WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if prior is not None:
                return {"operation": str(prior[0]), "target_id": str(prior[1]), "outcome": str(prior[2])}

            def record(identifier: str) -> sqlite3.Row | tuple[object, ...]:
                row = conn.execute(
                    "SELECT * FROM knowledge_records WHERE id=? AND partition=?", (identifier, partition)
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
                conn.execute(
                    "INSERT INTO entity_aliases VALUES (?, ?, ?, ?) ON CONFLICT(normalized_alias) DO NOTHING",
                    (normalized, entity_id, alias, now),
                )
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
                conn.execute("UPDATE knowledge_records SET subject_entity_id=? WHERE subject_entity_id=?", (target_entity_id, source_id))
                conn.execute("UPDATE knowledge_records SET object_entity_id=? WHERE object_entity_id=?", (target_entity_id, source_id))
                conn.execute("UPDATE entity_aliases SET entity_id=? WHERE entity_id=?", (target_entity_id, source_id))
                conn.execute("UPDATE entities SET merged_into_entity_id=? WHERE id=?", (target_entity_id, source_id))
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
                locator = f"manual/action/{action_id}"
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                conn.execute("INSERT INTO knowledge_sources VALUES (?, 'manual', ?, ?, ?, ?, ?)", (str(source_id), partition, locator, text, digest, now))
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
                conn.execute("INSERT INTO knowledge_record_sources VALUES (?, ?, ?, ?)", (str(created.id), str(source_id), action_id, now))
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

    def apply_capture(
        self, *, action_id: str, partition: str, source_kind: str, locator: str,
        original_text: str, kind: str, text: str, subject: str | None = None,
        predicate: str | None = None, object_entity: str | None = None,
        object_value: str | None = None, effective_at: str | None = None,
    ) -> tuple[KnowledgeRecord, KnowledgeSource, str]:
        """Apply one approved capture once and record an auditable outcome."""
        if partition not in _PARTITIONS or source_kind not in _SOURCE_KINDS or kind not in _KINDS:
            raise KnowledgeStoreError("capture_invalid")
        text = _required_text(text, "text")
        original_text = _required_text(original_text, "original_text")
        locator = _required_text(locator, "locator")
        structured = any(value is not None for value in (subject, predicate, object_entity, object_value))
        if structured and (not subject or not predicate or bool(object_entity) == bool(object_value)):
            raise KnowledgeStoreError("record_structure_invalid")
        now = utc_now_iso()
        digest = hashlib.sha256(original_text.encode("utf-8")).hexdigest()
        with self._connection() as conn, conn:
            existing_effect = conn.execute(
                "SELECT r.* , s.id,s.kind,s.partition,s.locator,s.original_text,s.content_hash,s.created_at "
                "FROM knowledge_action_effects e JOIN knowledge_records r ON r.id=e.record_id "
                "JOIN knowledge_sources s ON s.id=e.source_id WHERE e.action_id=?", (action_id,)
            ).fetchone()
            if existing_effect is not None:
                return self._record(existing_effect[:13]), self._source(existing_effect[13:]), "confirmed"
            source_row = conn.execute(
                "SELECT id,kind,partition,locator,original_text,content_hash,created_at FROM knowledge_sources "
                "WHERE kind=? AND partition=? AND locator=? AND content_hash=?",
                (source_kind, partition, locator, digest),
            ).fetchone()
            if source_row is None:
                source_id = uuid4()
                conn.execute("INSERT INTO knowledge_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(source_id), source_kind, partition, locator, original_text, digest, now))
                source = KnowledgeSource(source_id, source_kind, partition, locator, original_text, digest, now)
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
                same = next((row for row in rows if str(row[7] or '') == str(object_id or '') and str(row[8] or '') == str(object_value or '')), None)
                if same is not None:
                    record = self._record(same)
                    outcome = "confirmed"
                else:
                    if rows:
                        conn.execute("UPDATE knowledge_records SET status='conflicting', updated_at=? WHERE id IN (%s)" % ",".join("?" for _ in rows), (now, *(str(row[0]) for row in rows)))
                        status, outcome = "conflicting", "conflicting"
                    else:
                        status, outcome = "active", "created"
                    record = self._insert_record_in_transaction(conn, partition=partition, kind=kind, text=text, status=status,
                        subject_entity_id=subject_id, predicate=predicate, object_entity_id=object_id, object_value=object_value,
                        effective_at=effective_at, now=now)
            else:
                normalized = normalize_alias(text)
                candidates = conn.execute("SELECT * FROM knowledge_records WHERE partition=? AND status IN ('active','conflicting') ORDER BY created_at,id", (partition,)).fetchall()
                rows = [row for row in candidates if normalize_alias(str(row[3])) == normalized]
                if rows:
                    record, outcome = self._record(rows[0]), "confirmed"
                else:
                    record, outcome = self._insert_record_in_transaction(conn, partition=partition, kind=kind, text=text, status="active", now=now), "created"
            conn.execute("INSERT OR IGNORE INTO knowledge_record_sources VALUES (?, ?, ?, ?)", (str(record.id), str(source.id), action_id, now))
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
        row = conn.execute("SELECT * FROM knowledge_records WHERE id=?", (str(identifier),)).fetchone()
        assert row is not None
        return KnowledgeStore._record(row)

    def capture_effect(self, action_id: str) -> tuple[KnowledgeRecord, KnowledgeSource, str] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT r.*,s.id,s.kind,s.partition,s.locator,s.original_text,s.content_hash,s.created_at,e.outcome "
                "FROM knowledge_action_effects e JOIN knowledge_records r ON r.id=e.record_id "
                "JOIN knowledge_sources s ON s.id=e.source_id WHERE e.action_id=?", (action_id,)
            ).fetchone()
        return (self._record(row[:13]), self._source(row[13:20]), str(row[20])) if row else None

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
