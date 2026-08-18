"""Local retrieval substrate for durable APEX context sources."""

from core.retrieval.models import RetrievalHit, RetrievalStatus
from core.retrieval.service import (
    RetrievalBusyError,
    RetrievalService,
    get_retrieval_service,
    set_retrieval_service,
)
from core.retrieval.store import RetrievalStore

__all__ = [
    "RetrievalBusyError",
    "RetrievalHit",
    "RetrievalService",
    "RetrievalStatus",
    "RetrievalStore",
    "get_retrieval_service",
    "set_retrieval_service",
]
