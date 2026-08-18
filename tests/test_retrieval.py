from __future__ import annotations

import math
import sqlite3
import struct
import unittest
from pathlib import Path
from uuid import uuid4

import numpy as np

from core.conversations.models import ConversationCreateRequest
from core.conversations.store import ConversationStore
from core.retrieval.embedding import EmbeddingError, FastEmbedAdapter
from core.retrieval.models import RetrievalItem
from core.retrieval.service import RetrievalBusyError, RetrievalService
from core.retrieval.store import RetrievalStore


class FakeEmbeddingAdapter:
    model_id = "fake"
    dimension = 2
    version = "test"
    fingerprint = "fake:2:test"

    def __init__(self, *, invalid: bool = False, numpy_values: bool = False) -> None:
        self.invalid = invalid
        self.numpy_values = numpy_values
        if invalid:
            self.fingerprint = "invalid:2:test"
        self.prepare_calls = 0

    def prepare(self) -> str:
        self.prepare_calls += 1
        return self.fingerprint

    def embed(self, texts, *, allow_download: bool = False):
        values = list(texts)
        if self.invalid:
            return [[0.0, 0.0] for _ in values]
        vectors = [[1.0, 0.0] if "alpha" in text else [0.0, 1.0] for text in values]
        return [np.asarray(vector, dtype=np.float32) for vector in vectors] if self.numpy_values else vectors


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(".apex-test-retrieval.db")
        if self.path.exists():
            self.path.unlink()
        self.conversations = ConversationStore(self.path)
        self.conversations.initialize()
        self.store = RetrievalStore(self.path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self.conversations.close()
        if self.path.exists():
            self.path.unlink()

    def _item(self, source_id: str, text: str, partition: str = "production") -> RetrievalItem:
        return RetrievalItem(
            namespace="conversation", source_type="message", source_id=source_id,
            partition=partition, conversation_id="conversation-1", message_id=source_id,
            role="user", timestamp="2026-01-01T00:00:00+00:00",
            locator=f"conversation/conversation-1/message/{source_id}",
            content_hash=source_id, text=text,
        )

    def test_fts_is_transactional_and_partition_filtered(self) -> None:
        self.store.upsert_item(self._item("m1", "alpha local text"))
        self.store.upsert_item(self._item("m2", "alpha sandbox text", "sandbox"))
        self.assertEqual([hit.source_id for hit in self.store.search_fts("alpha", namespace="conversation", source_type="message", partition="production", limit=10)], ["m1"])
        self.store.upsert_item(self._item("m1", "changed text"))
        self.assertEqual(self.store.search_fts("alpha", namespace="conversation", source_type="message", partition="production", limit=10), [])
        self.assertEqual([hit.source_id for hit in self.store.search_fts("changed", namespace="conversation", source_type="message", partition="production", limit=10)], ["m1"])

    def test_startup_backfill_and_archived_delete_trigger(self) -> None:
        conversation_id = uuid4()
        self.conversations.create(conversation_id=conversation_id, title="Test", partition="production", origin="cli", agent="panthera", selected_tool_names=None, tool_profile_id=None)
        user_id, agent_id = uuid4(), uuid4()
        user, agent, _, _ = self.conversations.begin_turn(conversation_id=conversation_id, partition="production", user_id=user_id, agent_id=agent_id, parent_id=None, prompt="alpha question", agent="panthera", request_metadata={}, selected_tool_names=None, tool_profile_id=None, history_limit=6)
        agent = self.conversations.finalize(conversation_id=conversation_id, agent_id=agent_id, answer="alpha answer", status="completed", response_metadata={})
        service = RetrievalService(self.store, self.conversations, adapter=FakeEmbeddingAdapter())
        service.initialize()
        self.assertEqual(self.store.counts(), (2, 0))
        self.assertEqual(self.store.search_fts("alpha", namespace="conversation", source_type="message", partition="sandbox", limit=10), [])
        self.conversations.patch(conversation_id, "production", {"archived": True})
        self.conversations.delete(conversation_id, "production")
        self.assertEqual(self.store.counts(), (0, 0))

    def test_prepare_and_semantic_fallback(self) -> None:
        self.store.upsert_item(self._item("m1", "alpha text"))
        self.store.upsert_item(self._item("m2", "beta text"))
        adapter = FakeEmbeddingAdapter()
        service = RetrievalService(self.store, adapter=adapter)
        result = service.prepare()
        self.assertEqual(result.mode, "semantic")
        self.assertEqual(result.embedding_items, 2)
        self.store.upsert_item(self._item("m1", "alpha changed"))
        self.assertEqual(self.store.counts(), (2, 1))
        hits = service.search("alpha", namespace="conversation", partition="production", source_type="message", limit=2)
        self.assertEqual(hits[0].source_id, "m1")
        semantic_only = service.search("unknown", namespace="conversation", partition="production", source_type="message", limit=2)
        self.assertTrue(semantic_only)
        self.assertEqual(semantic_only[0].source_id, "m2")
        invalid = RetrievalService(self.store, adapter=FakeEmbeddingAdapter(invalid=True))
        degraded = invalid.prepare()
        self.assertEqual(degraded.mode, "fts_only")
        self.assertEqual(degraded.error_category, "invalid_vector")
        self.assertTrue(math.isfinite(hits[0].score))

    def test_numpy_vectors_are_accepted(self) -> None:
        self.store.upsert_item(self._item("m1", "alpha text"))
        service = RetrievalService(self.store, adapter=FakeEmbeddingAdapter(numpy_values=True))
        result = service.prepare()
        self.assertEqual(result.mode, "semantic")
        self.assertEqual(result.embedding_items, 1)

    def test_fastembed_adapter_normalizes_numpy_scalars(self) -> None:
        class FakeModel:
            @staticmethod
            def embed(texts):
                return [np.asarray([1.0, 0.0], dtype=np.float32) for _ in texts]

        adapter = FastEmbedAdapter(self.path.parent / "weights")
        adapter._model = FakeModel()
        vector = adapter.embed(["alpha"])[0]
        self.assertEqual(vector, [1.0, 0.0])
        self.assertTrue(all(type(value) is float for value in vector))

    def test_corrupt_persisted_vector_degrades_to_fts(self) -> None:
        item_id = self.store.upsert_item(self._item("m1", "alpha text"))
        service = RetrievalService(self.store, adapter=FakeEmbeddingAdapter())
        self.assertEqual(service.prepare().mode, "semantic")
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute(
                    "UPDATE retrieval_embeddings SET vector = ? WHERE item_id = ?",
                    (struct.pack("<2f", float("nan"), 0.0), item_id),
                )
        finally:
            conn.close()
        hits = service.search("alpha", namespace="conversation", partition="production", source_type="message", limit=2)
        self.assertEqual([hit.source_id for hit in hits], ["m1"])
        self.assertEqual(service.status().mode, "fts_only")
        self.assertEqual(service.status().error_category, "invalid_vector")

    def test_unresolved_partition_is_not_written_as_production(self) -> None:
        conversation_id = uuid4()
        self.conversations.create(conversation_id=conversation_id, title="Test", partition="sandbox", origin="cli", agent="panthera", selected_tool_names=None, tool_profile_id=None)
        user_id, agent_id = uuid4(), uuid4()
        user, agent, _, _ = self.conversations.begin_turn(conversation_id=conversation_id, partition="sandbox", user_id=user_id, agent_id=agent_id, parent_id=None, prompt="sandbox secret", agent="panthera", request_metadata={}, selected_tool_names=None, tool_profile_id=None, history_limit=6)
        agent = self.conversations.finalize(conversation_id=conversation_id, agent_id=agent_id, answer="sandbox answer", status="completed", response_metadata={})
        service = RetrievalService(self.store, self.conversations, adapter=FakeEmbeddingAdapter())
        self.assertEqual(service.index_messages((user, agent), partitions={}), 0)
        self.assertEqual(self.store.counts(), (0, 0))

    def test_initialization_error_is_visible_in_status(self) -> None:
        class FailingConversationStore:
            def completed_messages_with_partitions(self):
                raise RuntimeError("reconcile failed")

        service = RetrievalService(self.store, FailingConversationStore(), adapter=FakeEmbeddingAdapter())
        with self.assertRaises(RuntimeError):
            service.initialize()
        status = service.status()
        self.assertEqual(status.state, "degraded")
        self.assertEqual(status.error_category, "retrieval_initialization_failed")

    def test_prepare_is_non_blocking_and_disabled_mode_writes_nothing(self) -> None:
        service = RetrievalService(self.store, adapter=FakeEmbeddingAdapter())
        service._prepare_lock.acquire()
        try:
            with self.assertRaises(RetrievalBusyError):
                service.prepare()
        finally:
            service._prepare_lock.release()
        disabled = RetrievalService(self.store, enabled=False, adapter=FakeEmbeddingAdapter())
        self.assertEqual(disabled.status().mode, "disabled")
        self.assertEqual(disabled.index_messages(()), 0)
        self.assertEqual(self.store.counts(), (0, 0))


if __name__ == "__main__":
    unittest.main()
