"""SQLite persistence for immutable knowledge evidence and temporal records."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence
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

    def __init__(self, db_path: Path | str | None) -> None:
        self._db_path = str(db_path) if db_path is not None else None
        self._lock = threading.RLock()
        self._memory_connection = (
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
                self._memory_connection.close()
                self._memory_connection = None

    def initialize(self) -> None:
        with self._connection() as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions ("
                "domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version >= 1))"
            )
            row = conn.execute("SELECT version FROM schema_versions WHERE domain = 'knowledge'").fetchone()
            if row is not None and int(row[0]) > 2:
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
                """
            )
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('knowledge', 2) "
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
        return Entity(id=UUID(str(row[0])), name=str(row[1]), normalized_name=str(row[2]), created_at=str(row[3]))

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
            row = conn.execute("SELECT id,name,normalized_name,created_at FROM entities WHERE normalized_name = ?", (normalized,)).fetchone()
            if row is not None:
                return self._entity(row)
            try:
                conn.execute("INSERT INTO entities VALUES (?, ?, ?, ?)", (str(identifier), name, normalized, now))
                conn.execute("INSERT INTO entity_aliases VALUES (?, ?, ?, ?)", (normalized, str(identifier), name, now))
            except sqlite3.IntegrityError as exc:
                raise KnowledgeConflictError("entity_conflict") from exc
        return Entity(identifier, name, normalized, now)

    def add_alias(self, entity_id: UUID, alias: str) -> Entity:
        alias = _required_text(alias, "name", limit=240)
        normalized = normalize_alias(alias)
        now = utc_now_iso()
        with self._connection() as conn, conn:
            entity = conn.execute("SELECT id,name,normalized_name,created_at FROM entities WHERE id = ?", (str(entity_id),)).fetchone()
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
                "SELECT e.id,e.name,e.normalized_name,e.created_at FROM entity_aliases a "
                "JOIN entities e ON e.id = a.entity_id WHERE a.normalized_alias = ?",
                (normalized,),
            ).fetchone()
        return self._entity(row) if row is not None else None

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

    def list_records(self, *, partition: str, statuses: Sequence[str] = ("active",), kind: str | None = None, entity_id: UUID | None = None) -> list[KnowledgeRecord]:
        if partition not in _PARTITIONS or not statuses or any(status not in _STATUSES for status in statuses):
            raise KnowledgeStoreError("record_filter_invalid")
        clauses, params = ["partition = ?", "status IN (%s)" % ",".join("?" for _ in statuses)], [partition, *statuses]
        if kind is not None:
            if kind not in _KINDS:
                raise KnowledgeStoreError("record_filter_invalid")
            clauses.append("kind = ?")
            params.append(kind)
        if entity_id is not None:
            clauses.append("(subject_entity_id = ? OR object_entity_id = ?)")
            params.extend((str(entity_id), str(entity_id)))
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM knowledge_records WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC, id", params).fetchall()
        return [self._record(row) for row in rows]

    def one_hop_relationships(self, entity_id: UUID, *, partition: str) -> list[KnowledgeRecord]:
        return self.list_records(partition=partition, entity_id=entity_id)

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
        conn.execute("INSERT INTO entities VALUES (?, ?, ?, ?)", (str(identifier), name, normalized, now))
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
