"""Source-tracked internal personal knowledge domain."""

from core.knowledge.service import KnowledgeService, get_knowledge_service, set_knowledge_service
from core.knowledge.store import (
    KnowledgeConflictError,
    KnowledgeNotFoundError,
    KnowledgeStore,
    KnowledgeStoreError,
    normalize_alias,
)

__all__ = [
    "KnowledgeConflictError", "KnowledgeNotFoundError", "KnowledgeService", "KnowledgeStore",
    "KnowledgeStoreError", "get_knowledge_service", "normalize_alias", "set_knowledge_service",
]
