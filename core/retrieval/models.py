"""Internal retrieval contracts and safe status snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RetrievalMode = Literal["disabled", "fts_only", "semantic"]
RetrievalState = Literal["disabled", "unprepared", "preparing", "ready", "degraded"]


@dataclass(frozen=True)
class RetrievalItem:
    namespace: str
    source_type: str
    source_id: str
    partition: str
    conversation_id: str | None
    message_id: str | None
    role: str | None
    timestamp: str
    locator: str
    content_hash: str
    text: str
    title: str | None = None
    heading: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalHit:
    item_id: str
    namespace: str
    source_type: str
    source_id: str
    partition: str
    locator: str
    text: str
    role: str | None
    conversation_id: str | None
    message_id: str | None
    timestamp: str
    score: float
    lexical_score: float | None = None
    semantic_score: float | None = None


@dataclass(frozen=True)
class RetrievalStatus:
    enabled: bool
    mode: RetrievalMode
    state: RetrievalState
    indexed_items: int = 0
    embedding_items: int = 0
    pending_items: int = 0
    last_prepared_at: str | None = None
    error_category: str | None = None
    model_fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "state": self.state,
            "indexed_items": self.indexed_items,
            "embedding_items": self.embedding_items,
            "pending_items": self.pending_items,
            "last_prepared_at": self.last_prepared_at,
            "error_category": self.error_category,
            "model_fingerprint": self.model_fingerprint,
        }
