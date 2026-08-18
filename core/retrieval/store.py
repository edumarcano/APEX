"""SQLite persistence for local retrieval items, FTS, and embeddings."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.connectors.models import utc_now_iso
from core.retrieval.models import RetrievalHit, RetrievalItem


class RetrievalStoreError(RuntimeError):
    pass


def item_id_for(item: RetrievalItem) -> str:
    key = f"{item.namespace}\x1f{item.source_type}\x1f{item.source_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def vector_to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def blob_to_vector(blob: bytes, dimension: int) -> list[float]:
    if len(blob) != dimension * 4:
        raise RetrievalStoreError("embedding_dimension_mismatch")
    return list(struct.unpack(f"<{dimension}f", blob))


class RetrievalStore:
    """Owns short SQLite transactions and never stores provider payloads."""

    def __init__(self, db_path: Path | str | None) -> None:
        self._db_path = str(db_path) if db_path is not None else None
        self._lock = threading.RLock()
        self._memory_connection = (
            sqlite3.connect(":memory:", check_same_thread=False)
            if db_path is None
            else None
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._memory_connection is not None:
                conn = self._memory_connection
                conn.execute("PRAGMA foreign_keys=ON")
                yield conn
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

    @property
    def db_path(self) -> str | None:
        return self._db_path

    def initialize(self) -> None:
        with self._connection() as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions ("
                "domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version >= 1))"
            )
            row = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = 'retrieval'"
            ).fetchone()
            if row is not None and int(row[0]) > 1:
                raise RetrievalStoreError("Retrieval schema is newer than this APEX build.")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_items (
                    id TEXT PRIMARY KEY NOT NULL,
                    namespace TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                    conversation_id TEXT,
                    message_id TEXT,
                    role TEXT,
                    timestamp TEXT NOT NULL,
                    locator TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    title TEXT,
                    heading TEXT,
                    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(namespace, source_type, source_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_embeddings (
                    item_id TEXT PRIMARY KEY NOT NULL REFERENCES retrieval_items(id) ON DELETE CASCADE,
                    model_fingerprint TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_model_state (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    state TEXT NOT NULL,
                    model_fingerprint TEXT,
                    last_prepared_at TEXT,
                    error_category TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS retrieval_items_fts USING fts5(
                    item_id UNINDEXED, text, title, heading
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_items_scope ON retrieval_items(namespace, source_type, partition, updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_items_source ON retrieval_items(conversation_id, message_id)")
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('retrieval', 1) "
                "ON CONFLICT(domain) DO UPDATE SET version = excluded.version"
            )
            conn.execute(
                "INSERT INTO retrieval_model_state(id, state, updated_at) VALUES (1, 'unprepared', ?) "
                "ON CONFLICT(id) DO NOTHING",
                (utc_now_iso(),),
            )
            self._create_triggers(conn)
            self._reconcile_fts(conn)

    @staticmethod
    def _create_triggers(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS retrieval_items_fts_insert
            AFTER INSERT ON retrieval_items BEGIN
                INSERT INTO retrieval_items_fts(item_id, text, title, heading)
                VALUES (new.id, new.text, COALESCE(new.title, ''), COALESCE(new.heading, ''));
            END;
            CREATE TRIGGER IF NOT EXISTS retrieval_items_fts_delete
            AFTER DELETE ON retrieval_items BEGIN
                DELETE FROM retrieval_items_fts WHERE item_id = old.id;
            END;
            CREATE TRIGGER IF NOT EXISTS retrieval_items_fts_update
            AFTER UPDATE OF text, title, heading ON retrieval_items BEGIN
                DELETE FROM retrieval_items_fts WHERE item_id = old.id;
                INSERT INTO retrieval_items_fts(item_id, text, title, heading)
                VALUES (new.id, new.text, COALESCE(new.title, ''), COALESCE(new.heading, ''));
            END;
            CREATE TRIGGER IF NOT EXISTS retrieval_items_embedding_update
            AFTER UPDATE OF text, content_hash ON retrieval_items BEGIN
                DELETE FROM retrieval_embeddings WHERE item_id = old.id;
            END;
            """
        )
        # Branch 2 permanently deletes messages in this transaction. This trigger
        # is installed when the conversation schema is already present and is
        # harmlessly retried on every initialization.
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "conversation_messages" in tables:
            conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS retrieval_cleanup_conversation_message
                AFTER DELETE ON conversation_messages BEGIN
                    DELETE FROM retrieval_items
                    WHERE namespace = 'conversation' AND source_type = 'message'
                      AND source_id = old.id;
                END;
                """
            )

    @staticmethod
    def _reconcile_fts(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM retrieval_items_fts")
        conn.execute(
            "INSERT INTO retrieval_items_fts(item_id, text, title, heading) "
            "SELECT id, text, COALESCE(title, ''), COALESCE(heading, '') FROM retrieval_items"
        )

    def reconcile_fts(self) -> None:
        with self._connection() as conn, conn:
            self._reconcile_fts(conn)

    def upsert_item(self, item: RetrievalItem) -> str:
        identifier = item_id_for(item)
        now = utc_now_iso()
        metadata = json.dumps(item.metadata, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        with self._connection() as conn, conn:
            old = conn.execute("SELECT content_hash FROM retrieval_items WHERE id = ?", (identifier,)).fetchone()
            conn.execute(
                """
                INSERT INTO retrieval_items(
                    id, namespace, source_type, source_id, partition, conversation_id,
                    message_id, role, timestamp, locator, content_hash, text, title,
                    heading, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(namespace, source_type, source_id) DO UPDATE SET
                    partition=excluded.partition, conversation_id=excluded.conversation_id,
                    message_id=excluded.message_id, role=excluded.role, timestamp=excluded.timestamp,
                    locator=excluded.locator, content_hash=excluded.content_hash, text=excluded.text,
                    title=excluded.title, heading=excluded.heading, metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (identifier, item.namespace, item.source_type, item.source_id, item.partition,
                 item.conversation_id, item.message_id, item.role, item.timestamp, item.locator,
                 item.content_hash, item.text, item.title, item.heading, metadata, now, now),
            )
            if old is not None and old[0] != item.content_hash:
                conn.execute("DELETE FROM retrieval_embeddings WHERE item_id = ?", (identifier,))
        return identifier

    def delete_source(self, namespace: str, source_type: str, source_id: str) -> None:
        with self._connection() as conn, conn:
            conn.execute(
                "DELETE FROM retrieval_items WHERE namespace = ? AND source_type = ? AND source_id = ?",
                (namespace, source_type, source_id),
            )

    def replace_namespace(self, namespace: str, items: list[RetrievalItem]) -> None:
        """Atomically replace one source namespace and its derived FTS rows."""
        now = utc_now_iso()
        with self._connection() as conn, conn:
            conn.execute("DELETE FROM retrieval_items WHERE namespace = ?", (namespace,))
            for item in items:
                if item.namespace != namespace:
                    raise RetrievalStoreError("namespace_mismatch")
                metadata = json.dumps(item.metadata, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO retrieval_items(
                        id, namespace, source_type, source_id, partition, conversation_id,
                        message_id, role, timestamp, locator, content_hash, text, title,
                        heading, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (item_id_for(item), item.namespace, item.source_type, item.source_id,
                     item.partition, item.conversation_id, item.message_id, item.role,
                     item.timestamp, item.locator, item.content_hash, item.text, item.title,
                     item.heading, metadata, now, now),
                )

    def upsert_embedding(self, item_id: str, fingerprint: str, vector: list[float]) -> None:
        now = utc_now_iso()
        with self._connection() as conn, conn:
            conn.execute(
                "INSERT INTO retrieval_embeddings(item_id, model_fingerprint, vector, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET model_fingerprint=excluded.model_fingerprint, vector=excluded.vector, updated_at=excluded.updated_at",
                (item_id, fingerprint, vector_to_blob(vector), now),
            )

    def clear_embeddings(self) -> None:
        with self._connection() as conn, conn:
            conn.execute("DELETE FROM retrieval_embeddings")

    def embedding_rows(self, *, fingerprint: str | None = None) -> list[tuple[str, bytes, str]]:
        with self._connection() as conn:
            if fingerprint is None:
                rows = conn.execute("SELECT item_id, vector, model_fingerprint FROM retrieval_embeddings").fetchall()
            else:
                rows = conn.execute("SELECT item_id, vector, model_fingerprint FROM retrieval_embeddings WHERE model_fingerprint = ?", (fingerprint,)).fetchall()
        return [(str(row[0]), bytes(row[1]), str(row[2])) for row in rows]

    def items_missing_embeddings(self, fingerprint: str) -> list[tuple[str, str]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT i.id, i.text FROM retrieval_items i LEFT JOIN retrieval_embeddings e ON e.item_id = i.id AND e.model_fingerprint = ? WHERE e.item_id IS NULL ORDER BY i.id",
                (fingerprint,),
            ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def set_model_state(self, *, state: str, fingerprint: str | None = None, prepared_at: str | None = None, error_category: str | None = None) -> None:
        with self._connection() as conn, conn:
            conn.execute(
                "UPDATE retrieval_model_state SET state = ?, model_fingerprint = ?, last_prepared_at = COALESCE(?, last_prepared_at), error_category = ?, updated_at = ? WHERE id = 1",
                (state, fingerprint, prepared_at, error_category, utc_now_iso()),
            )

    def model_state(self) -> tuple[str, str | None, str | None, str | None]:
        with self._connection() as conn:
            row = conn.execute("SELECT state, model_fingerprint, last_prepared_at, error_category FROM retrieval_model_state WHERE id = 1").fetchone()
        return (str(row[0]), row[1], row[2], row[3]) if row else ("unprepared", None, None, None)

    def counts(self) -> tuple[int, int]:
        with self._connection() as conn:
            indexed = conn.execute("SELECT COUNT(*) FROM retrieval_items").fetchone()
            embeddings = conn.execute("SELECT COUNT(*) FROM retrieval_embeddings").fetchone()
        return int(indexed[0]), int(embeddings[0])

    def pending_count(self) -> int:
        with self._connection() as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "conversation_messages" not in tables:
                return 0
            row = conn.execute(
                """
                SELECT COUNT(*) FROM conversation_messages m
                LEFT JOIN retrieval_items i ON i.namespace = 'conversation'
                  AND i.source_type = 'message' AND i.source_id = m.id
                WHERE m.status = 'completed' AND i.id IS NULL
                """
            ).fetchone()
        return int(row[0])

    def search_fts(self, query: str, *, namespace: str, source_type: str | None, partition: str, limit: int) -> list[RetrievalHit]:
        terms = [term for term in query.replace('"', ' ').split() if term.strip()]
        if not terms:
            return []
        match = " AND ".join(f'"{term.replace("\"", "")}"' for term in terms)
        params: list[Any] = [match, namespace, partition]
        source_clause = ""
        if source_type is not None:
            source_clause = " AND i.source_type = ?"
            params.append(source_type)
        params.append(max(1, min(limit, 100)))
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    """
                    SELECT i.id, i.namespace, i.source_type, i.source_id, i.partition,
                           i.locator, i.text, i.role, i.conversation_id, i.message_id,
                           i.timestamp, bm25(retrieval_items_fts) AS rank
                    FROM retrieval_items_fts f JOIN retrieval_items i ON i.id = f.item_id
                    WHERE retrieval_items_fts MATCH ? AND i.namespace = ? AND i.partition = ?
                    """ + source_clause + " ORDER BY rank ASC, i.id ASC LIMIT ?",
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            RetrievalHit(item_id=str(row[0]), namespace=str(row[1]), source_type=str(row[2]), source_id=str(row[3]), partition=str(row[4]), locator=str(row[5]), text=str(row[6]), role=row[7], conversation_id=row[8], message_id=row[9], timestamp=str(row[10]), score=float(-row[11]), lexical_score=float(-row[11]))
            for row in rows
        ]

    def scoped_items(self, *, namespace: str, source_type: str | None, partition: str) -> list[tuple[Any, ...]]:
        params: list[Any] = [namespace, partition]
        clause = ""
        if source_type is not None:
            clause = " AND source_type = ?"
            params.append(source_type)
        with self._connection() as conn:
            return conn.execute(
                "SELECT id, namespace, source_type, source_id, partition, locator, text, role, conversation_id, message_id, timestamp FROM retrieval_items WHERE namespace = ? AND partition = ?" + clause + " ORDER BY id",
                params,
            ).fetchall()
