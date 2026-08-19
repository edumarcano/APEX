"""SQLite storage for durable Cortex conversation trees."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from core.agent.types import AgentMessage
from core.connectors.models import utc_now_iso
from core.conversations.models import (
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
)


class ConversationStoreError(RuntimeError):
    pass


class ConversationNotFoundError(ConversationStoreError):
    pass


class ConversationConflictError(ConversationStoreError):
    pass


class ConversationBusyError(ConversationConflictError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def _parse_json(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


class ConversationStore:
    """Owns only short SQLite transactions; model execution happens above it."""

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

    def initialize(self) -> None:
        with self._connection() as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions ("
                "domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL CHECK(version >= 1))"
            )
            row = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = 'conversations'"
            ).fetchone()
            if row is not None and int(row[0]) > 1:
                raise ConversationStoreError("Conversation schema is newer than this APEX build.")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY NOT NULL,
                    title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                    partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                    origin TEXT NOT NULL CHECK(origin IN ('hud', 'cli')),
                    agent TEXT NOT NULL CHECK(agent IN ('panthera', 'felis')),
                    selected_tool_names_json TEXT CHECK(selected_tool_names_json IS NULL OR json_valid(selected_tool_names_json)),
                    tool_profile_id TEXT,
                    active_leaf_message_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id TEXT PRIMARY KEY NOT NULL,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    parent_message_id TEXT,
                    role TEXT NOT NULL CHECK(role IN ('user', 'agent')),
                    content TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'completed', 'failed', 'interrupted')),
                    agent TEXT CHECK(agent IN ('panthera', 'felis')),
                    request_metadata_json TEXT CHECK(request_metadata_json IS NULL OR json_valid(request_metadata_json)),
                    response_metadata_json TEXT CHECK(response_metadata_json IS NULL OR json_valid(response_metadata_json)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(conversation_id, id),
                    FOREIGN KEY(conversation_id, parent_message_id)
                        REFERENCES conversation_messages(conversation_id, id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_partition_updated ON conversations(partition, archived_at, updated_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_messages_tree ON conversation_messages(conversation_id, parent_message_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_conversation_messages_status ON conversation_messages(conversation_id, status)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_agent_turn ON conversation_messages(conversation_id) WHERE role = 'agent' AND status = 'pending'")
            conn.execute(
                "INSERT INTO schema_versions(domain, version) VALUES ('conversations', 1) "
                "ON CONFLICT(domain) DO UPDATE SET version = excluded.version"
            )

    @staticmethod
    def _summary(row: sqlite3.Row | tuple[Any, ...]) -> ConversationSummary:
        return ConversationSummary(
            id=UUID(str(row[0])), title=str(row[1]), partition=str(row[2]), origin=str(row[3]),
            agent=str(row[4]), selected_tool_names=_parse_json(row[5]), tool_profile_id=row[6],
            active_leaf_message_id=UUID(str(row[7])) if row[7] else None,
            created_at=row[8], updated_at=row[9], archived_at=row[10],
        )

    @staticmethod
    def _message(row: sqlite3.Row | tuple[Any, ...]) -> ConversationMessage:
        return ConversationMessage(
            id=UUID(str(row[0])), conversation_id=UUID(str(row[1])),
            parent_message_id=UUID(str(row[2])) if row[2] else None,
            role=str(row[3]), content=str(row[4]), status=str(row[5]), agent=row[6],
            request_metadata=_parse_json(row[7]), response_metadata=_parse_json(row[8]),
            created_at=row[9], updated_at=row[10],
        )

    def create(self, *, conversation_id: UUID, title: str, partition: str, origin: str, agent: str, selected_tool_names: list[str] | None, tool_profile_id: str | None) -> ConversationSummary:
        now = utc_now_iso()
        with self._connection() as conn, conn:
            conn.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)",
                (str(conversation_id), title, partition, origin, agent, _json(selected_tool_names) if selected_tool_names is not None else None, tool_profile_id, now, now),
            )
        return self.get_summary(conversation_id, partition)

    def list(self, partition: str, archived: bool) -> list[ConversationSummary]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id,title,partition,origin,agent,selected_tool_names_json,tool_profile_id,active_leaf_message_id,created_at,updated_at,archived_at FROM conversations WHERE partition = ? AND archived_at IS %s ORDER BY updated_at DESC" % ("NOT NULL" if archived else "NULL"),
                (partition,),
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get_summary(self, conversation_id: UUID, partition: str) -> ConversationSummary:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id,title,partition,origin,agent,selected_tool_names_json,tool_profile_id,active_leaf_message_id,created_at,updated_at,archived_at FROM conversations WHERE id = ? AND partition = ?",
                (str(conversation_id), partition),
            ).fetchone()
        if row is None:
            raise ConversationNotFoundError("Conversation was not found.")
        return self._summary(row)

    def detail(self, conversation_id: UUID, partition: str) -> ConversationDetail:
        summary = self.get_summary(conversation_id, partition)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id,conversation_id,parent_message_id,role,content,status,agent,request_metadata_json,response_metadata_json,created_at,updated_at FROM conversation_messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC",
                (str(conversation_id),),
            ).fetchall()
        return ConversationDetail(**summary.model_dump(), messages=[self._message(row) for row in rows])

    def completed_messages(self, partition: str | None = None) -> list[ConversationMessage]:
        """Return completed user/Agent messages for local secondary indexes."""
        with self._connection() as conn:
            if partition is None:
                rows = conn.execute(
                    """
                    SELECT m.id,m.conversation_id,m.parent_message_id,m.role,m.content,
                           m.status,m.agent,m.request_metadata_json,m.response_metadata_json,
                           m.created_at,m.updated_at
                    FROM conversation_messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.status = 'completed'
                    ORDER BY m.created_at ASC, m.rowid ASC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT m.id,m.conversation_id,m.parent_message_id,m.role,m.content,
                           m.status,m.agent,m.request_metadata_json,m.response_metadata_json,
                           m.created_at,m.updated_at
                    FROM conversation_messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.status = 'completed' AND c.partition = ?
                    ORDER BY m.created_at ASC, m.rowid ASC
                    """,
                    (partition,),
                ).fetchall()
        return [self._message(row) for row in rows]

    def completed_messages_with_partitions(self) -> list[tuple[ConversationMessage, str]]:
        """Return completed messages together with their authoritative partition."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT m.id,m.conversation_id,m.parent_message_id,m.role,m.content,
                       m.status,m.agent,m.request_metadata_json,m.response_metadata_json,
                       m.created_at,m.updated_at,c.partition
                FROM conversation_messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.status = 'completed'
                ORDER BY m.created_at ASC, m.rowid ASC
                """
            ).fetchall()
        return [(self._message(row), str(row[11])) for row in rows]

    def conversation_partition(self, conversation_id: UUID) -> str | None:
        """Return a conversation's partition, or None when it cannot be resolved."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT partition FROM conversations WHERE id = ?",
                (str(conversation_id),),
            ).fetchone()
        return str(row[0]) if row else None

    def active_history(self, conversation_id: UUID, partition: str, limit: int) -> list[AgentMessage]:
        summary = self.get_summary(conversation_id, partition)
        with self._connection() as conn:
            return self._history(conn, conversation_id, summary.active_leaf_message_id, limit)

    def patch(self, conversation_id: UUID, partition: str, updates: dict[str, Any]) -> ConversationSummary:
        current = self.get_summary(conversation_id, partition)
        if "active_leaf_message_id" in updates and updates["active_leaf_message_id"] is not None:
            leaf = str(updates["active_leaf_message_id"])
            with self._connection() as conn:
                exists = conn.execute("SELECT 1 FROM conversation_messages WHERE id = ? AND conversation_id = ?", (leaf, str(conversation_id))).fetchone()
                child = conn.execute("SELECT 1 FROM conversation_messages WHERE conversation_id = ? AND parent_message_id = ?", (str(conversation_id), leaf)).fetchone()
            if not exists or child:
                raise ConversationConflictError("Active branch selection must reference a terminal message in this conversation.")
        values: dict[str, Any] = {}
        for key in ("title", "agent", "tool_profile_id"):
            if key in updates:
                values[key] = updates[key]
        if "selected_tool_names" in updates:
            values["selected_tool_names_json"] = _json(updates["selected_tool_names"]) if updates["selected_tool_names"] is not None else None
        if "active_leaf_message_id" in updates:
            values["active_leaf_message_id"] = str(updates["active_leaf_message_id"]) if updates["active_leaf_message_id"] else None
        if "archived" in updates:
            values["archived_at"] = utc_now_iso() if updates["archived"] else None
        if not values:
            return current
        values["updated_at"] = utc_now_iso()
        columns = ", ".join(f"{key} = ?" for key in values)
        with self._connection() as conn, conn:
            conn.execute(f"UPDATE conversations SET {columns} WHERE id = ? AND partition = ?", (*values.values(), str(conversation_id), partition))
        return self.get_summary(conversation_id, partition)

    def delete(self, conversation_id: UUID, partition: str) -> None:
        """Permanently remove one archived conversation and its message tree."""
        with self._connection() as conn, conn:
            row = conn.execute(
                "SELECT archived_at FROM conversations WHERE id = ? AND partition = ?",
                (str(conversation_id), partition),
            ).fetchone()
            if row is None:
                raise ConversationNotFoundError("Conversation was not found.")
            if row[0] is None:
                raise ConversationConflictError("Only archived conversations can be permanently deleted.")
            pending = conn.execute(
                "SELECT 1 FROM conversation_messages WHERE conversation_id = ? AND role = 'agent' AND status = 'pending' LIMIT 1",
                (str(conversation_id),),
            ).fetchone()
            if pending is not None:
                raise ConversationConflictError("A conversation with a pending turn cannot be deleted.")
            conn.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = ?",
                (str(conversation_id),),
            )
            # Retrieval owns a trigger in normal initialization. This guarded
            # cleanup keeps the same transaction safe when an older database
            # was initialized before the retrieval domain was introduced.
            retrieval_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'retrieval_items'"
            ).fetchone()
            if retrieval_table is not None:
                conn.execute(
                    "DELETE FROM retrieval_items WHERE conversation_id = ?",
                    (str(conversation_id),),
                )
            conn.execute(
                "DELETE FROM conversations WHERE id = ? AND partition = ?",
                (str(conversation_id), partition),
            )

    def begin_turn(self, *, conversation_id: UUID, partition: str, user_id: UUID, agent_id: UUID, parent_id: UUID | None, prompt: str, agent: str, request_metadata: dict[str, Any], selected_tool_names: list[str] | None, tool_profile_id: str | None, history_limit: int) -> tuple[ConversationMessage, ConversationMessage, list[AgentMessage], bool]:
        now = utc_now_iso()
        canonical = _json(request_metadata)
        with self._connection() as conn, conn:
            conversation = conn.execute("SELECT archived_at FROM conversations WHERE id = ? AND partition = ?", (str(conversation_id), partition)).fetchone()
            if conversation is None:
                raise ConversationNotFoundError("Conversation was not found.")
            if conversation[0] is not None:
                raise ConversationConflictError("Archived conversations must be unarchived before starting a turn.")
            existing_agent = conn.execute("SELECT id,conversation_id,parent_message_id,role,content,status,agent,request_metadata_json,response_metadata_json,created_at,updated_at FROM conversation_messages WHERE id = ?", (str(agent_id),)).fetchone()
            if existing_agent is not None:
                message = self._message(existing_agent)
                if message.conversation_id != conversation_id or message.parent_message_id != user_id or message.role != "agent" or message.agent != agent or _json(message.request_metadata) != canonical:
                    raise ConversationConflictError("Message IDs cannot be reused with different turn content.")
                existing_user = conn.execute("SELECT id,conversation_id,parent_message_id,role,content,status,agent,request_metadata_json,response_metadata_json,created_at,updated_at FROM conversation_messages WHERE id = ?", (str(user_id),)).fetchone()
                if (
                    existing_user is None
                    or self._message(existing_user).conversation_id != conversation_id
                    or self._message(existing_user).role != "user"
                    or self._message(existing_user).parent_message_id != parent_id
                    or self._message(existing_user).content != prompt
                ):
                    raise ConversationConflictError("Message IDs cannot be reused with different turn content.")
                if message.status == "pending":
                    raise ConversationBusyError("turn_in_progress")
                return self._message(existing_user), message, [], True
            pending = conn.execute("SELECT 1 FROM conversation_messages WHERE conversation_id = ? AND role = 'agent' AND status = 'pending'", (str(conversation_id),)).fetchone()
            if pending:
                raise ConversationBusyError("turn_in_progress")
            existing_user = conn.execute("SELECT id,conversation_id,parent_message_id,role,content,status,agent,request_metadata_json,response_metadata_json,created_at,updated_at FROM conversation_messages WHERE id = ?", (str(user_id),)).fetchone()
            if existing_user is None:
                if parent_id is not None:
                    parent = conn.execute("SELECT id FROM conversation_messages WHERE id = ? AND conversation_id = ? AND status = 'completed'", (str(parent_id), str(conversation_id))).fetchone()
                    if parent is None:
                        raise ConversationConflictError("Turn parent must be a completed message in this conversation.")
                conn.execute("INSERT INTO conversation_messages VALUES (?, ?, ?, 'user', ?, 'completed', NULL, NULL, NULL, ?, ?)", (str(user_id), str(conversation_id), str(parent_id) if parent_id else None, prompt, now, now))
            else:
                user = self._message(existing_user)
                if user.conversation_id != conversation_id or user.role != "user" or user.parent_message_id != parent_id or user.content != prompt:
                    raise ConversationConflictError("Message IDs cannot be reused with different turn content.")
            history = self._history(conn, conversation_id, parent_id, history_limit)
            conn.execute("INSERT INTO conversation_messages VALUES (?, ?, ?, 'agent', '', 'pending', ?, ?, NULL, ?, ?)", (str(agent_id), str(conversation_id), str(user_id), agent, canonical, now, now))
            conn.execute("UPDATE conversations SET agent=?, selected_tool_names_json=?, tool_profile_id=?, active_leaf_message_id=?, updated_at=? WHERE id=?", (agent, _json(selected_tool_names) if selected_tool_names is not None else None, tool_profile_id, str(agent_id), now, str(conversation_id)))
            user_row = conn.execute("SELECT id,conversation_id,parent_message_id,role,content,status,agent,request_metadata_json,response_metadata_json,created_at,updated_at FROM conversation_messages WHERE id=?", (str(user_id),)).fetchone()
            agent_row = conn.execute("SELECT id,conversation_id,parent_message_id,role,content,status,agent,request_metadata_json,response_metadata_json,created_at,updated_at FROM conversation_messages WHERE id=?", (str(agent_id),)).fetchone()
        return self._message(user_row), self._message(agent_row), history, False

    def _history(self, conn: sqlite3.Connection, conversation_id: UUID, leaf_id: UUID | None, limit: int) -> list[AgentMessage]:
        if leaf_id is None:
            return []
        rows = conn.execute("SELECT id,parent_message_id,role,content,status FROM conversation_messages WHERE conversation_id = ?", (str(conversation_id),)).fetchall()
        by_id = {str(row[0]): row for row in rows}
        current = str(leaf_id)
        seen: set[str] = set()
        path: list[sqlite3.Row | tuple[Any, ...]] = []
        while current:
            if current in seen:
                raise ConversationConflictError("Conversation history contains a cycle.")
            seen.add(current)
            row = by_id.get(current)
            if row is None:
                raise ConversationConflictError("Turn parent was not found in this conversation.")
            path.append(row)
            current = str(row[1]) if row[1] else ""
        result = [AgentMessage(role=str(row[2]), content=str(row[3])) for row in reversed(path) if row[4] == "completed"]
        return result[-limit:]

    def finalize(self, *, conversation_id: UUID, agent_id: UUID, answer: str, status: str, response_metadata: dict[str, Any]) -> ConversationMessage:
        now = utc_now_iso()
        with self._connection() as conn, conn:
            result = conn.execute("UPDATE conversation_messages SET content=?, status=?, response_metadata_json=?, updated_at=? WHERE id=? AND conversation_id=? AND status='pending'", (answer, status, _json(response_metadata), now, str(agent_id), str(conversation_id)))
            if result.rowcount != 1:
                raise ConversationConflictError("Pending conversation turn was no longer available.")
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, str(conversation_id)))
            row = conn.execute("SELECT id,conversation_id,parent_message_id,role,content,status,agent,request_metadata_json,response_metadata_json,created_at,updated_at FROM conversation_messages WHERE id=?", (str(agent_id),)).fetchone()
        return self._message(row)

    def recover_interrupted(self) -> int:
        now = utc_now_iso()
        metadata = _json({"error": "Agent turn was interrupted by an APEX restart."})
        with self._connection() as conn, conn:
            rows = conn.execute("SELECT DISTINCT conversation_id FROM conversation_messages WHERE status='pending'").fetchall()
            result = conn.execute("UPDATE conversation_messages SET status='interrupted', response_metadata_json=?, updated_at=? WHERE status='pending'", (metadata, now))
            for row in rows:
                conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, row[0]))
            return result.rowcount
