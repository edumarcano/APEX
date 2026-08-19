"""Application service for conversation indexing and local retrieval."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import numbers
import threading
from pathlib import Path
from typing import Iterable, Mapping

from core.config import DEMO_MODE, PROJECT_ROOT
from core.connectors.models import utc_now_iso
from core.conversations.models import ConversationMessage
from core.conversations.store import ConversationStore
from core.retrieval.embedding import EmbeddingAdapter, EmbeddingError, FastEmbedAdapter
from core.retrieval.models import RetrievalHit, RetrievalItem, RetrievalStatus
from core.retrieval.store import RetrievalStore, RetrievalStoreError, blob_to_vector

_LOGGER = logging.getLogger(__name__)
_service: "RetrievalService | None" = None


class RetrievalBusyError(RuntimeError):
    pass


def set_retrieval_service(service: "RetrievalService | None") -> None:
    global _service
    _service = service


def get_retrieval_service() -> "RetrievalService":
    if _service is None:
        raise RuntimeError("Retrieval service is unavailable.")
    return _service


class RetrievalService:
    """Coordinates repairable indexing, FTS search, and optional embeddings."""

    def __init__(
        self,
        store: RetrievalStore,
        conversation_store: ConversationStore | None = None,
        *,
        adapter: EmbeddingAdapter | None = None,
        enabled: bool = True,
        initialization_error: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.store = store
        self.conversation_store = conversation_store
        self.adapter = adapter or FastEmbedAdapter(PROJECT_ROOT / "weights" / "fastembed")
        self.enabled = enabled and not DEMO_MODE
        self.initialization_error = initialization_error
        self.batch_size = max(1, batch_size)
        self._prepare_lock = threading.Lock()
        self._sync_lock = threading.RLock()

    def initialize(self) -> None:
        if not self.enabled:
            return
        try:
            self.store.initialize()
            self.reconcile()
            self.initialization_error = None
        except Exception as exc:
            self.initialization_error = "retrieval_initialization_failed"
            _LOGGER.error(
                "Retrieval initialization failed: category=retrieval_initialization_failed error_type=%s",
                type(exc).__name__,
            )
            raise exc

    def _item_for_message(self, message: ConversationMessage, partition: str) -> RetrievalItem:
        content = message.content
        return RetrievalItem(
            namespace="conversation",
            source_type="message",
            source_id=str(message.id),
            partition=partition,
            conversation_id=str(message.conversation_id),
            message_id=str(message.id),
            role=message.role,
            timestamp=message.created_at.isoformat(),
            locator=f"conversation/{message.conversation_id}/message/{message.id}",
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            text=content,
        )

    def reconcile(self) -> int:
        if not self.enabled or self.conversation_store is None:
            return 0
        records = self.conversation_store.completed_messages_with_partitions()
        return self.index_messages(
            (message for message, _ in records),
            partitions={str(message.conversation_id): partition for message, partition in records},
        )

    def index_messages(
        self,
        messages: Iterable[ConversationMessage],
        *,
        partition: str | None = None,
        partitions: Mapping[str, str] | None = None,
    ) -> int:
        if not self.enabled:
            return 0
        count = 0
        for message in messages:
            if message.status != "completed" or message.role not in {"user", "agent"}:
                continue
            resolved_partition = partition or (partitions or {}).get(str(message.conversation_id))
            if resolved_partition not in {"production", "sandbox"}:
                _LOGGER.warning("Conversation retrieval update skipped: category=partition_unresolved")
                continue
            self.store.upsert_item(self._item_for_message(message, resolved_partition))
            count += 1
        return count

    def index_turn(
        self,
        user: ConversationMessage,
        agent: ConversationMessage,
        *,
        partition: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            resolved_partition = partition
            if resolved_partition is None and self.conversation_store is not None:
                resolved_partition = self.conversation_store.conversation_partition(user.conversation_id)
            self.index_messages((user, agent), partition=resolved_partition)
        except Exception:
            _LOGGER.error("Conversation retrieval update failed: category=indexing_failed")

    def _fingerprint(self) -> str:
        return str(getattr(self.adapter, "fingerprint", f"{self.adapter.model_id}:{self.adapter.dimension}:{self.adapter.version}"))

    def _backfill_embeddings(self, fingerprint: str, *, namespace: str | None = None) -> None:
        pending = self.store.items_missing_embeddings(fingerprint, namespace=namespace)
        for offset in range(0, len(pending), self.batch_size):
            batch = pending[offset : offset + self.batch_size]
            vectors = self.adapter.embed((text for _, text in batch), allow_download=False)
            if len(vectors) != len(batch):
                raise EmbeddingError("invalid_vector")
            for (item_id, _), vector in zip(batch, vectors):
                self._validate_vector(vector, int(self.adapter.dimension))
                self.store.upsert_embedding(item_id, fingerprint, vector)

    def sync_namespace(self, namespace: str, items: list[RetrievalItem]) -> int:
        """Synchronize a derived corpus and backfill it only from cached weights."""
        if not self.enabled:
            return 0
        with self._sync_lock:
            changed = self.store.sync_namespace(namespace, items)
            state, fingerprint, _prepared, _error = self.store.model_state()
            if state == "ready" and fingerprint is not None:
                try:
                    self._backfill_embeddings(fingerprint, namespace=namespace)
                except EmbeddingError as exc:
                    category = str(exc) if str(exc) in {"embedding_initialization_failed", "embedding_inference_failed", "invalid_vector"} else "semantic_search_failed"
                    self.store.set_model_state(state="degraded", fingerprint=None, error_category=category)
            return len(changed)

    @staticmethod
    def _validate_vector(vector: list[float], dimension: int) -> None:
        if len(vector) != dimension:
            raise EmbeddingError("invalid_vector")
        norm = 0.0
        for value in vector:
            if not isinstance(value, numbers.Real) or not math.isfinite(float(value)):
                raise EmbeddingError("invalid_vector")
            norm += float(value) * float(value)
        if norm <= 0:
            raise EmbeddingError("invalid_vector")

    def prepare(self, *, allow_download: bool = True) -> RetrievalStatus:
        if not self.enabled:
            return self.status()
        if not self._prepare_lock.acquire(blocking=False):
            raise RetrievalBusyError("retrieval_prepare_in_progress")
        try:
            with self._sync_lock:
                self.store.set_model_state(state="preparing", error_category=None)
                self.reconcile()
                fingerprint = self.adapter.prepare(allow_download=allow_download)
                self._backfill_embeddings(fingerprint)
                self.store.set_model_state(state="ready", fingerprint=fingerprint, prepared_at=utc_now_iso(), error_category=None)
                return self.status()
        except EmbeddingError as exc:
            category = str(exc) or "embedding_initialization_failed"
            if category not in {"model_download_failed", "embedding_initialization_failed", "embedding_inference_failed", "invalid_vector"}:
                category = "embedding_initialization_failed"
            self.store.set_model_state(state="degraded", fingerprint=None, error_category=category)
            _LOGGER.warning("Retrieval preparation degraded: category=%s", category)
            return self.status()
        except Exception:
            self.store.set_model_state(state="degraded", fingerprint=None, error_category="preparation_failed")
            _LOGGER.error("Retrieval preparation failed: category=preparation_failed")
            return self.status()
        finally:
            self._prepare_lock.release()

    def status(self) -> RetrievalStatus:
        if not self.enabled:
            return RetrievalStatus(enabled=False, mode="disabled", state="disabled", error_category=self.initialization_error)
        try:
            indexed, embeddings = self.store.counts()
            state, fingerprint, prepared, error = self.store.model_state()
            pending = self.store.pending_count(fingerprint if state == "ready" else None)
        except Exception:
            return RetrievalStatus(enabled=True, mode="fts_only", state="degraded", error_category="retrieval_unavailable")
        effective_error = error or self.initialization_error
        effective_state = "degraded" if self.initialization_error else state
        mode = "semantic" if effective_state == "ready" and embeddings > 0 else "fts_only"
        return RetrievalStatus(enabled=True, mode=mode, state=effective_state, indexed_items=indexed, embedding_items=embeddings, pending_items=pending, last_prepared_at=prepared, error_category=effective_error, model_fingerprint=fingerprint)

    def search(self, query: str, *, namespace: str, partition: str, source_type: str | None = None, limit: int = 10) -> list[RetrievalHit]:
        if not self.enabled:
            return []
        lexical = self.store.search_fts(query, namespace=namespace, source_type=source_type, partition=partition, limit=limit)
        status = self.status()
        if status.mode != "semantic" or not query.strip():
            return lexical
        try:
            query_vector = self.adapter.embed([query], allow_download=False)[0]
            self._validate_vector(query_vector, int(self.adapter.dimension))
            vector_by_id = {
                item_id: blob_to_vector(blob, int(self.adapter.dimension))
                for item_id, blob, fingerprint in self.store.embedding_rows(fingerprint=status.model_fingerprint)
                if fingerprint == status.model_fingerprint
            }
            semantic: list[tuple[str, float]] = []
            qnorm = math.sqrt(sum(float(value) ** 2 for value in query_vector))
            for item in self.store.scoped_items(namespace=namespace, source_type=source_type, partition=partition):
                vector = vector_by_id.get(str(item[0]))
                if vector is None:
                    continue
                denom = qnorm * math.sqrt(sum(float(value) ** 2 for value in vector))
                semantic.append((str(item[0]), sum(float(a) * float(b) for a, b in zip(query_vector, vector)) / denom if denom else 0.0))
            semantic.sort(key=lambda pair: (-pair[1], pair[0]))
            all_rows = self.store.scoped_items(namespace=namespace, source_type=source_type, partition=partition)
            all_hits = {
                str(row[0]): RetrievalHit(
                    item_id=str(row[0]), namespace=str(row[1]), source_type=str(row[2]),
                    source_id=str(row[3]), partition=str(row[4]), locator=str(row[5]),
                    text=str(row[6]), role=row[7], conversation_id=row[8],
                    message_id=row[9], timestamp=str(row[10]), title=row[11],
                    heading=row[12], metadata=json.loads(row[13]), score=0.0,
                )
                for row in all_rows
            }
            lexical_rank = {hit.item_id: index + 1 for index, hit in enumerate(lexical)}
            semantic_rank = {item_id: index + 1 for index, (item_id, _) in enumerate(semantic)}
            lexical_score = {hit.item_id: hit.lexical_score or 0.0 for hit in lexical}
            semantic_score = dict(semantic)
            candidates = set(lexical_rank) | set(semantic_rank)
            fused = sorted(candidates, key=lambda item_id: (-(1 / (60 + lexical_rank[item_id]) if item_id in lexical_rank else 0.0) - (1 / (60 + semantic_rank[item_id]) if item_id in semantic_rank else 0.0), item_id))
            by_id = all_hits
            return [
                RetrievalHit(
                    **{
                        **by_id[item_id].__dict__,
                        "score": (1 / (60 + lexical_rank[item_id]) if item_id in lexical_rank else 0.0) + (1 / (60 + semantic_rank[item_id]) if item_id in semantic_rank else 0.0),
                        "lexical_score": lexical_score.get(item_id),
                        "semantic_score": semantic_score.get(item_id),
                    }
                )
                for item_id in fused[: max(1, min(limit, 100))]
                if item_id in by_id
            ]
        except EmbeddingError as exc:
            category = str(exc) if str(exc) in {"invalid_vector", "embedding_initialization_failed", "embedding_inference_failed"} else "semantic_search_failed"
            self.store.set_model_state(state="degraded", fingerprint=None, error_category=category)
            _LOGGER.warning("Semantic retrieval degraded: category=%s", category)
            return lexical
        except RetrievalStoreError as exc:
            category = str(exc) if str(exc) in {"embedding_dimension_mismatch", "invalid_vector"} else "semantic_search_failed"
            self.store.set_model_state(state="degraded", fingerprint=None, error_category=category)
            _LOGGER.warning("Semantic retrieval degraded: category=%s", category)
            return lexical
        except Exception:
            self.store.set_model_state(
                state="degraded",
                fingerprint=None,
                error_category="semantic_search_failed",
            )
            _LOGGER.warning("Semantic retrieval degraded: category=semantic_search_failed")
            return lexical
