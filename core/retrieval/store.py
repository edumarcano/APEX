"""SQLite persistence for local retrieval items, FTS, and embeddings."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.connectors.models import utc_now_iso
from core.retrieval.models import RetrievalHit, RetrievalItem

_CONVERSATIONAL_STOPWORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "know",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over",
    "own", "remember", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't",
    "so", "some", "such", "tell", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's",
    "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why",
    "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
    "your", "yours", "yourself", "yourselves",
})


def sanitize_fts_query(query: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", query)
    raw_terms = [term for term in cleaned.split() if term.strip()]
    if not raw_terms:
        return ""
    meaningful = [term for term in raw_terms if term.lower() not in _CONVERSATIONAL_STOPWORDS]
    terms = meaningful if meaningful else raw_terms
    return " OR ".join(f'"{term}"' for term in terms)


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
    vector = list(struct.unpack(f"<{dimension}f", blob))
    norm = 0.0
    for value in vector:
        if not math.isfinite(value):
            raise RetrievalStoreError("invalid_vector")
        norm += value * value
    if norm <= 0.0:
        raise RetrievalStoreError("invalid_vector")
    return vector


class RetrievalStore:
    """Owns short SQLite transactions and never stores provider payloads."""

    def __init__(
        self,
        db_path: Path | str | None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self._db_path = str(db_path) if db_path is not None else None
        self._lock = threading.RLock()
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
                if self._owns_memory_connection:
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
            version = int(row[0]) if row is not None else 0
            if version > 2:
                raise RetrievalStoreError("Retrieval schema is newer than this APEX build.")
            if version == 1:
                self._migrate_v1_to_v2(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retrieval_items (
                    id TEXT PRIMARY KEY NOT NULL,
                    namespace TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox', 'shared')),
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
                "INSERT INTO schema_versions(domain, version) VALUES ('retrieval', 2) "
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
    def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
        """Preserve source rows while rebuilding derived retrieval state."""
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS retrieval_items_fts_insert;
            DROP TRIGGER IF EXISTS retrieval_items_fts_delete;
            DROP TRIGGER IF EXISTS retrieval_items_fts_update;
            DROP TRIGGER IF EXISTS retrieval_items_embedding_update;
            DROP TRIGGER IF EXISTS retrieval_cleanup_conversation_message;
            DROP TABLE IF EXISTS retrieval_items_fts;
            DROP TABLE IF EXISTS retrieval_embeddings;
            ALTER TABLE retrieval_items RENAME TO retrieval_items_v1;
            CREATE TABLE retrieval_items (
                id TEXT PRIMARY KEY NOT NULL,
                namespace TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox', 'shared')),
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
            );
            INSERT INTO retrieval_items(
                id, namespace, source_type, source_id, partition, conversation_id,
                message_id, role, timestamp, locator, content_hash, text, title,
                heading, metadata_json, created_at, updated_at
            ) SELECT
                id, namespace, source_type, source_id, partition, conversation_id,
                message_id, role, timestamp, locator, content_hash, text, title,
                heading, metadata_json, created_at, updated_at
            FROM retrieval_items_v1;
            DROP TABLE retrieval_items_v1;
            """
        )
        conn.execute(
            "UPDATE retrieval_model_state SET state = 'unprepared', model_fingerprint = NULL, "
            "last_prepared_at = NULL, error_category = NULL, updated_at = ? WHERE id = 1",
            (utc_now_iso(),),
        )

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

    def sync_namespace(self, namespace: str, items: list[RetrievalItem]) -> list[str]:
        """Incrementally reconcile one namespace without discarding unchanged vectors."""
        with self._connection() as conn, conn:
            return self._sync_namespace_in_transaction(conn, namespace, items)

    @staticmethod
    def _sync_namespace_in_transaction(
        conn: sqlite3.Connection,
        namespace: str,
        items: list[RetrievalItem],
    ) -> list[str]:
        """Synchronize a namespace using a caller-owned SQLite transaction.

        Domains that own canonical rows in the shared APEX database use this helper
        to update their derived retrieval rows atomically. It intentionally does
        not initialize schema or create embeddings; the normal retrieval service
        continues to own those repairable concerns.
        """
        expected = {item_id_for(item): item for item in items}
        if any(item.namespace != namespace for item in items):
            raise RetrievalStoreError("namespace_mismatch")
        now = utc_now_iso()
        changed: list[str] = []
        existing = {
            str(row[0]): tuple(row[1:])
            for row in conn.execute(
                "SELECT id, content_hash, partition, conversation_id, message_id, role, "
                "timestamp, locator, title, heading, metadata_json FROM retrieval_items "
                "WHERE namespace = ?",
                (namespace,),
            )
        }
        for identifier, item in expected.items():
            metadata = json.dumps(item.metadata, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
            current = existing.get(identifier)
            item_state = (
                item.content_hash, item.partition, item.conversation_id, item.message_id,
                item.role, item.timestamp, item.locator, item.title, item.heading, metadata,
            )
            if current == item_state:
                continue
            if current is not None and current[0] == item.content_hash:
                conn.execute(
                    """
                    UPDATE retrieval_items SET
                        partition = ?, conversation_id = ?, message_id = ?, role = ?,
                        timestamp = ?, locator = ?, title = ?, heading = ?, metadata_json = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        item.partition, item.conversation_id, item.message_id, item.role,
                        item.timestamp, item.locator, item.title, item.heading,
                        metadata, now, identifier,
                    ),
                )
                continue
            changed.append(identifier)
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
        stale = set(existing) - set(expected)
        if stale:
            conn.executemany("DELETE FROM retrieval_items WHERE id = ?", ((identifier,) for identifier in stale))
        return changed

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

    def items_missing_embeddings(self, fingerprint: str, *, namespace: str | None = None) -> list[tuple[str, str]]:
        clause = ""
        params: list[Any] = [fingerprint]
        if namespace is not None:
            clause = " AND i.namespace = ?"
            params.append(namespace)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT i.id, i.text FROM retrieval_items i LEFT JOIN retrieval_embeddings e ON e.item_id = i.id AND e.model_fingerprint = ? WHERE e.item_id IS NULL" + clause + " ORDER BY i.id",
                params,
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

    def pending_count(self, fingerprint: str | None = None) -> int:
        with self._connection() as conn:
            if fingerprint is None:
                row = conn.execute("SELECT COUNT(*) FROM retrieval_items").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM retrieval_items i LEFT JOIN retrieval_embeddings e "
                    "ON e.item_id = i.id AND e.model_fingerprint = ? WHERE e.item_id IS NULL",
                    (fingerprint,),
                ).fetchone()
        return int(row[0])

    def search_fts(self, query: str, *, namespace: str, source_type: str | None, partition: str, limit: int) -> list[RetrievalHit]:
        match = sanitize_fts_query(query)
        if not match:
            return []
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
                           i.timestamp, i.title, i.heading, i.metadata_json,
                           bm25(retrieval_items_fts) AS rank
                    FROM retrieval_items_fts f JOIN retrieval_items i ON i.id = f.item_id
                    WHERE retrieval_items_fts MATCH ? AND i.namespace = ? AND i.partition = ?
                    """ + source_clause + " ORDER BY rank ASC, i.id ASC LIMIT ?",
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            RetrievalHit(item_id=str(row[0]), namespace=str(row[1]), source_type=str(row[2]), source_id=str(row[3]), partition=str(row[4]), locator=str(row[5]), text=str(row[6]), role=row[7], conversation_id=row[8], message_id=row[9], timestamp=str(row[10]), title=row[11], heading=row[12], metadata=json.loads(row[13]), score=float(-row[14]), lexical_score=float(-row[14]))
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
                "SELECT id, namespace, source_type, source_id, partition, locator, text, role, conversation_id, message_id, timestamp, title, heading, metadata_json FROM retrieval_items WHERE namespace = ? AND partition = ?" + clause + " ORDER BY id",
                params,
            ).fetchall()


def sync_namespace_in_transaction(
    conn: sqlite3.Connection,
    namespace: str,
    items: list[RetrievalItem],
) -> list[str]:
    """Synchronize derived rows using the caller's existing transaction."""
    return RetrievalStore._sync_namespace_in_transaction(conn, namespace, items)
