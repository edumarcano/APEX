from __future__ import annotations

import math
import sqlite3
import struct
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import numpy as np

from core.conversations.models import ConversationCreateRequest
from core.conversations.store import ConversationStore
from core.retrieval.embedding import EmbeddingError, FastEmbedAdapter
from core.retrieval.models import RetrievalItem
from core.retrieval.service import RetrievalBusyError, RetrievalService
from core.retrieval.store import RetrievalSchemaCompatibilityError, RetrievalStore


class FakeEmbeddingAdapter:
    model_id = "fake"
    dimension = 2
    version = "test"
    fingerprint = "fake:2:test"

    def __init__(self, *, invalid: bool = False, numpy_values: bool = False, cached: bool = True) -> None:
        self.invalid = invalid
        self.numpy_values = numpy_values
        self.cached = cached
        if invalid:
            self.fingerprint = "invalid:2:test"
        self.prepare_calls = 0
        self.download_flags: list[bool] = []
        self.release_calls = 0
        self.loaded = False

    def prepare(self, *, allow_download: bool = True) -> str:
        self.prepare_calls += 1
        self.download_flags.append(allow_download)
        if not self.cached and not allow_download:
            raise EmbeddingError("embedding_initialization_failed")
        self.loaded = True
        return self.fingerprint

    def release(self) -> None:
        self.release_calls += 1
        self.loaded = False

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

    def test_fts_sanitizes_punctuation_and_conversational_stopwords(self) -> None:
        self.store.upsert_item(self._item("m1", "The operator's favorite driver is Charles Leclerc."))
        self.store.upsert_item(self._item("m2", "The operator's favorite F1 team is Ferrari."))

        # Punctuation and conversational stop words stripped; m1 ranks top for driver query
        hits = self.store.search_fts("Do you remember my favorite driver?", namespace="conversation", source_type="message", partition="production", limit=10)
        self.assertTrue(hits)
        self.assertEqual(hits[0].source_id, "m1")

        # Punctuation and conversational question words stripped; m2 ranks top for team query
        hits_team = self.store.search_fts("What is my favorite F1 team?!", namespace="conversation", source_type="message", partition="production", limit=10)
        self.assertTrue(hits_team)
        self.assertEqual(hits_team[0].source_id, "m2")

        # All-stopwords query fallback does not error
        empty = self.store.search_fts("???", namespace="conversation", source_type="message", partition="production", limit=10)
        self.assertEqual(empty, [])

    def test_startup_backfill_and_archived_delete_trigger(self) -> None:
        conversation_id = uuid4()
        self.conversations.create(conversation_id=conversation_id, title="Test", partition="production", origin="cli", agent="apex", selected_tool_names=None, tool_profile_id=None)
        user_id, agent_id = uuid4(), uuid4()
        user, agent, _, _ = self.conversations.begin_turn(conversation_id=conversation_id, partition="production", user_id=user_id, agent_id=agent_id, parent_id=None, prompt="alpha question", agent="apex", request_metadata={}, selected_tool_names=None, tool_profile_id=None, history_limit=6)
        agent = self.conversations.finalize(conversation_id=conversation_id, agent_id=agent_id, answer="alpha answer", status="completed", response_metadata={})
        service = RetrievalService(self.store, self.conversations, adapter=FakeEmbeddingAdapter())
        service.initialize()
        self.assertEqual(service.adapter.prepare_calls, 0)
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
        self.assertIsNotNone(hits[0].lexical_score)
        self.assertIsNone(hits[0].semantic_score)
        semantic_only = service.search("unknown", namespace="conversation", partition="production", source_type="message", limit=2)
        self.assertTrue(semantic_only)
        self.assertEqual(semantic_only[0].source_id, "m2")
        self.assertIsNone(semantic_only[0].lexical_score)
        self.assertIsNotNone(semantic_only[0].semantic_score)
        invalid = RetrievalService(self.store, adapter=FakeEmbeddingAdapter(invalid=True))
        degraded = invalid.prepare()
        self.assertEqual(degraded.mode, "fts_only")
        self.assertEqual(degraded.error_category, "invalid_vector")
        self.assertTrue(math.isfinite(hits[0].score))

    def test_first_search_prepares_cached_model_without_download(self) -> None:
        self.store.upsert_item(self._item("m1", "alpha text"))
        adapter = FakeEmbeddingAdapter()
        service = RetrievalService(self.store, adapter=adapter)
        service.initialize()

        hits = service.search("alpha", namespace="conversation", partition="production")

        self.assertEqual([hit.source_id for hit in hits], ["m1"])
        self.assertEqual(adapter.download_flags, [False])
        self.assertEqual(self.store.counts(), (1, 1))
        self.assertEqual(service.status().state, "ready")

    def test_first_search_without_cached_model_keeps_lexical_results(self) -> None:
        self.store.upsert_item(self._item("m1", "alpha text"))
        adapter = FakeEmbeddingAdapter(cached=False)
        service = RetrievalService(self.store, adapter=adapter)
        service.initialize()

        hits = service.search("alpha", namespace="conversation", partition="production")

        self.assertEqual([hit.source_id for hit in hits], ["m1"])
        self.assertEqual(adapter.download_flags, [False])
        self.assertEqual(service.status().mode, "fts_only")
        self.assertEqual(service.status().error_category, "embedding_initialization_failed")

        repeated = service.search("alpha", namespace="conversation", partition="production")
        self.assertEqual([hit.source_id for hit in repeated], ["m1"])
        self.assertEqual(adapter.download_flags, [False])

        service.prepare(allow_download=True)
        self.assertEqual(adapter.download_flags, [False, True])

    def test_explicit_prepare_retains_download_permission(self) -> None:
        adapter = FakeEmbeddingAdapter(cached=False)
        service = RetrievalService(self.store, adapter=adapter)

        self.assertEqual(service.prepare(allow_download=True).state, "ready")
        self.assertEqual(adapter.download_flags, [True])

    def test_idle_release_preserves_persisted_state_and_reloads_on_demand(self) -> None:
        self.store.upsert_item(self._item("m1", "alpha text"))
        adapter = FakeEmbeddingAdapter()
        service = RetrievalService(self.store, adapter=adapter)
        now = [100.0]
        with mock.patch("core.retrieval.service._monotonic", side_effect=lambda: now[0]):
            now[0] += 301.0
            self.assertFalse(service.release_if_idle())
            self.assertEqual(adapter.release_calls, 0)
            service.search("alpha", namespace="conversation", partition="production")
            conn = sqlite3.connect(self.path)
            try:
                before = conn.execute(
                    "SELECT state, model_fingerprint, last_prepared_at FROM retrieval_model_state WHERE id=1"
                ).fetchone()
            finally:
                conn.close()

            self.assertFalse(service.release_if_idle())
            now[0] += 300.0
            self.assertTrue(service.release_if_idle())
            self.assertFalse(adapter.loaded)
            self.assertFalse(service.release_if_idle())
            conn = sqlite3.connect(self.path)
            try:
                after = conn.execute(
                    "SELECT state, model_fingerprint, last_prepared_at FROM retrieval_model_state WHERE id=1"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(after, before)

            service.search("alpha", namespace="conversation", partition="production")
            self.assertTrue(adapter.loaded)
            self.assertEqual(adapter.download_flags, [False, False])

    def test_concurrent_first_search_pins_real_fastembed_generator_during_close(self) -> None:
        query_started = threading.Event()
        two_queries_started = threading.Event()
        resume_queries = threading.Event()
        close_waiting = threading.Event()
        finish_close = threading.Event()
        constructors = []
        query_calls = [0]
        query_lock = threading.Lock()
        normalized: list[list[list[float]]] = []
        exhausted_batches: list[tuple[str, ...]] = []
        close_clock_calls = [0]
        now = [1_000.0]

        class FakeModel:
            def __init__(self, **_kwargs) -> None:
                constructors.append(self)

            @staticmethod
            def embed(texts):
                values = list(texts)

                def vectors():
                    try:
                        if values == ["alpha"]:
                            with query_lock:
                                query_calls[0] += 1
                                if query_calls[0] == 2:
                                    two_queries_started.set()
                            query_started.set()
                            if not resume_queries.wait(timeout=5):
                                raise AssertionError("test did not resume query generators")
                        for _text in values:
                            yield np.asarray([1.0, 0.0], dtype=np.float32)
                    finally:
                        exhausted_batches.append(tuple(values))

                return vectors()

        class ObservedFastEmbedAdapter(FastEmbedAdapter):
            dimension = 2

            def embed(self, texts, *, allow_download: bool = False):
                vectors = super().embed(texts, allow_download=allow_download)
                normalized.append(vectors)
                return vectors

        def monotonic() -> float:
            if threading.current_thread().name == "bounded-close":
                close_clock_calls[0] += 1
                if close_clock_calls[0] == 1:
                    return 1_000.0
                close_waiting.set()
                if not finish_close.wait(timeout=5):
                    raise AssertionError("test did not finish bounded close")
                return 1_001.0
            return now[0]

        self.store.upsert_item(self._item("m1", "alpha text"))
        adapter = ObservedFastEmbedAdapter(self.path.parent / "fastembed-test-cache")
        service = RetrievalService(self.store, adapter=adapter)
        results: list[list] = [[], []]
        errors: list[BaseException] = []

        with mock.patch.dict(sys.modules, {"fastembed": SimpleNamespace(TextEmbedding=FakeModel)}):
            with mock.patch("core.retrieval.service._monotonic", side_effect=monotonic):
                def search_into(index: int) -> None:
                    try:
                        results[index].extend(
                            service.search("alpha", namespace="conversation", partition="production")
                        )
                    except BaseException as exc:
                        errors.append(exc)

                workers = [
                    threading.Thread(target=search_into, args=(index,))
                    for index in range(2)
                ]
                for worker in workers:
                    worker.start()
                self.assertTrue(query_started.wait(timeout=5), repr(errors))
                self.assertTrue(two_queries_started.wait(timeout=5))
                self.assertEqual(len(constructors), 1)
                self.assertEqual(query_calls[0], 2)
                now[0] += 301.0
                self.assertEqual(service._active_embedding_uses, 2)
                self.assertFalse(service.release_if_idle())

                close_result = []
                closer = threading.Thread(
                    target=lambda: close_result.append(service.close(timeout_seconds=1.0)),
                    name="bounded-close",
                )
                closer.start()
                self.assertTrue(close_waiting.wait(timeout=5))

                # Closing rejects new model admissions while existing queries remain pinned.
                with self.assertRaises(RuntimeError):
                    with service._embedding_use():
                        self.fail("closing service admitted new embedding work")
                self.assertEqual(service._active_embedding_uses, 2)
                self.assertEqual(query_calls[0], 2)
                now_before = service._last_embedding_use_completed
                self.assertFalse(service.release_if_idle())
                self.assertEqual(service._last_embedding_use_completed, now_before)

                finish_close.set()
                closer.join(timeout=5)
                self.assertFalse(closer.is_alive())
                self.assertEqual(close_result, [False])
                self.assertTrue(adapter.is_loaded)

                resume_queries.set()
                for worker in workers:
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())

        self.assertEqual(errors, [])
        self.assertTrue(all(results))
        self.assertEqual(query_calls[0], 2)
        self.assertEqual(exhausted_batches.count(("alpha",)), 2)
        self.assertTrue(any(vectors == [[1.0, 0.0]] for vectors in normalized))

    def test_fastembed_model_construction_is_singleton_under_concurrency(self) -> None:
        entered = threading.Event()
        proceed = threading.Event()
        constructions = []

        class FakeModel:
            def __init__(self, **_kwargs) -> None:
                constructions.append(self)
                entered.set()
                if not proceed.wait(timeout=5):
                    raise AssertionError("test did not release model construction")

        adapter = FastEmbedAdapter(self.path.parent / "fastembed-cache")
        with mock.patch.dict(sys.modules, {"fastembed": SimpleNamespace(TextEmbedding=FakeModel)}):
            workers = [
                threading.Thread(target=lambda: adapter.prepare(allow_download=False))
                for _ in range(4)
            ]
            for worker in workers:
                worker.start()
            self.assertTrue(entered.wait(timeout=5))
            proceed.set()
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

        self.assertEqual(len(constructions), 1)
        adapter.release()

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

    def test_default_embedding_cache_uses_managed_data_path_without_creating_it(self) -> None:
        from types import SimpleNamespace

        cache_dir = self.path.parent / "managed-data" / "weights" / "fastembed"
        with mock.patch(
            "core.retrieval.service.get_runtime_paths",
            return_value=SimpleNamespace(fastembed_cache_dir=cache_dir),
        ):
            service = RetrievalService(self.store)

        self.assertEqual(service.adapter.cache_dir, cache_dir)
        self.assertFalse(cache_dir.exists())

    def test_initialize_and_status_do_not_construct_fastembed_model(self) -> None:
        constructions = []

        class FakeModel:
            def __init__(self, **_kwargs) -> None:
                constructions.append(self)

        with mock.patch.dict(sys.modules, {"fastembed": SimpleNamespace(TextEmbedding=FakeModel)}):
            service = RetrievalService(self.store, self.conversations)
            service.initialize()
            status = service.status()

        self.assertEqual(status.state, "unprepared")
        self.assertEqual(constructions, [])

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
        self.conversations.create(conversation_id=conversation_id, title="Test", partition="sandbox", origin="cli", agent="apex", selected_tool_names=None, tool_profile_id=None)
        user_id, agent_id = uuid4(), uuid4()
        user, agent, _, _ = self.conversations.begin_turn(conversation_id=conversation_id, partition="sandbox", user_id=user_id, agent_id=agent_id, parent_id=None, prompt="sandbox secret", agent="apex", request_metadata={}, selected_tool_names=None, tool_profile_id=None, history_limit=6)
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

    def test_unsupported_schema_disables_all_later_store_access(self) -> None:
        store = mock.Mock(spec=RetrievalStore)
        store.initialize.side_effect = RetrievalSchemaCompatibilityError(
            "Unsupported retrieval persistence schema."
        )
        service = RetrievalService(store, adapter=FakeEmbeddingAdapter())

        service.initialize()

        status = service.status()
        self.assertFalse(status.enabled)
        self.assertEqual(status.error_category, "retrieval_initialization_failed")
        self.assertEqual(service.search("alpha", namespace="conversation", partition="production"), [])
        self.assertEqual(service.sync_namespace("docs", []), 0)
        self.assertEqual(service.index_messages(()), 0)
        self.assertEqual(service.reconcile(), 0)
        self.assertEqual(service.prepare().mode, "disabled")
        service._backfill_embeddings("fake:2:test")

        store.initialize.assert_called_once_with()
        store.counts.assert_not_called()
        store.model_state.assert_not_called()
        store.search_fts.assert_not_called()
        store.sync_namespace.assert_not_called()
        store.items_missing_embeddings.assert_not_called()

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
