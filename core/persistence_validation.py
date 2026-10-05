"""Read-only validation shared by host startup and profile import."""

from __future__ import annotations

import sqlite3


class PersistenceValidationError(RuntimeError):
    """The canonical APEX database cannot safely be opened by this build."""

    def __init__(self, message: str, *, code: str = "database_schema_invalid") -> None:
        self.code = code
        super().__init__(message)


def validate_persistence(
    connection: sqlite3.Connection,
    *,
    include_actions: bool = True,
    check_integrity: bool = False,
) -> bool:
    """Validate SQLite integrity and core schemas; return retrieval compatibility.

    The connection must be read-only (or an in-memory validation database).
    An unsupported retrieval schema is retained as a warning while every
    canonical domain remains available.
    """
    from core import database
    from core.activity.store import ActivityStore
    from core.briefings.store import BriefingSessionStore
    from core.conversations import ConversationStore
    from core.knowledge.store import KnowledgeStore
    from core.retrieval.store import RetrievalSchemaCompatibilityError, RetrievalStore
    from core.runs import RunStore

    try:
        if check_integrity:
            rows = connection.execute("PRAGMA integrity_check").fetchall()
            if rows != [("ok",)]:
                raise PersistenceValidationError(
                    "SQLite integrity check failed.", code="database_integrity_failed"
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise PersistenceValidationError(
                    "SQLite foreign key check failed.", code="database_foreign_key_check_failed"
                )
        database.validate_schema(connection, include_actions=include_actions)
        ConversationStore.validate_schema(connection)
        RunStore.validate_schema(connection)
        BriefingSessionStore.validate_schema(connection)
        KnowledgeStore.validate_schema(connection)
        ActivityStore.validate_schema(connection)
        try:
            RetrievalStore.validate_schema(connection)
        except RetrievalSchemaCompatibilityError:
            return False
        return True
    except PersistenceValidationError:
        raise
    except Exception as exc:
        raise PersistenceValidationError(str(exc)) from exc


__all__ = ["PersistenceValidationError", "validate_persistence"]
