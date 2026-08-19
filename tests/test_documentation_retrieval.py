from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.retrieval.docs import (
    DOCS_NAMESPACE,
    build_documentation_items,
    search_documentation,
)
from core.retrieval.models import RetrievalItem
from core.retrieval.service import RetrievalService
from core.retrieval.store import RetrievalStore, item_id_for


class FakeEmbeddingAdapter:
    model_id = "fake"
    dimension = 2
    version = "test"
    fingerprint = "fake:2:test"

    def __init__(self) -> None:
        self.embed_calls = 0

    def prepare(self, *, allow_download: bool = True) -> str:
        return self.fingerprint

    def embed(self, texts, *, allow_download: bool = False):
        self.embed_calls += 1
        self.assert_no_download(allow_download)
        return [[1.0, 0.0] if "alpha" in text else [0.0, 1.0] for text in texts]

    @staticmethod
    def assert_no_download(allow_download: bool) -> None:
        if allow_download:
            raise AssertionError("normal embedding calls must not download")


class DocumentationRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "docs").mkdir()
        (self.root / "README.md").write_text("# APEX\n\nAlpha reference.\n", encoding="utf-8")
        (self.root / "docs" / "architecture.md").write_text(
            "# Architecture\n\nAlpha design.\n\n```md\n# Not a heading\n```\n\n## Retrieval\n\nBeta reference.\n",
            encoding="utf-8",
        )
        self.store = RetrievalStore(self.root / "retrieval.db")
        self.adapter = FakeEmbeddingAdapter()
        self.service = RetrievalService(self.store, adapter=self.adapter)
        self.service.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_heading_aware_chunks_keep_exact_locations_and_exclude_other_files(self) -> None:
        (self.root / ".local-plans").mkdir()
        (self.root / ".local-plans" / "secret.md").write_text("# Secret\n", encoding="utf-8")
        (self.root / "docs" / "generated.txt").write_text("alpha", encoding="utf-8")

        items = build_documentation_items(self.root)

        self.assertTrue(items)
        self.assertTrue(all(item.namespace == DOCS_NAMESPACE for item in items))
        self.assertTrue(all(item.partition == "shared" for item in items))
        self.assertTrue(all(not item.title.startswith(".local-plans") for item in items if item.title))
        headings = {item.heading for item in items}
        self.assertIn("Architecture", headings)
        self.assertIn("Architecture > Retrieval", headings)
        self.assertNotIn("Architecture > Not a heading", headings)
        architecture = next(item for item in items if item.title == "docs/architecture.md")
        self.assertEqual(architecture.metadata["line_start"], 1)
        self.assertIn(":L", architecture.locator)

    def test_search_refreshes_incrementally_and_uses_cached_embeddings(self) -> None:
        first = search_documentation("alpha", self.service, root=self.root)
        self.assertEqual(first["retrieval_mode"], "fts_only")
        self.assertEqual(first["trust"], "untrusted_reference")
        self.assertTrue(any(result["path"] == "README.md" for result in first["results"]))

        self.assertEqual(self.service.prepare().mode, "semantic")
        embedded_before = self.store.counts()[1]
        calls_before = self.adapter.embed_calls
        search_documentation("alpha", self.service, root=self.root)
        self.assertEqual(self.store.counts()[1], embedded_before)
        self.assertEqual(self.adapter.embed_calls, calls_before + 1)

        (self.root / "docs" / "architecture.md").write_text(
            "# Architecture\n\nGamma design.\n", encoding="utf-8"
        )
        updated = search_documentation("gamma", self.service, root=self.root)
        self.assertEqual(updated["retrieval_mode"], "semantic")
        self.assertTrue(updated["results"])
        self.assertGreater(self.adapter.embed_calls, calls_before + 1)

        (self.root / "docs" / "architecture.md").unlink()
        search_documentation("architecture", self.service, root=self.root)
        self.assertFalse(any("architecture.md" in hit.locator for hit in self.service.search("architecture", namespace=DOCS_NAMESPACE, source_type="markdown_chunk", partition="shared")))

    def test_v1_migration_preserves_source_items_and_resets_derived_embeddings(self) -> None:
        item = RetrievalItem(
            namespace="conversation", source_type="message", source_id="message-1",
            partition="production", conversation_id="conversation-1", message_id="message-1",
            role="user", timestamp="2026-01-01T00:00:00+00:00", locator="conversation/1/message/1",
            content_hash="hash", text="alpha", metadata={},
        )
        self.store.upsert_item(item)
        self.store.upsert_embedding(item_id_for(item), "fake:2:test", [1.0, 0.0])
        conn = sqlite3.connect(self.root / "retrieval.db")
        try:
            with conn:
                conn.execute("UPDATE schema_versions SET version = 1 WHERE domain = 'retrieval'")
        finally:
            conn.close()

        self.store.initialize()

        self.assertEqual(self.store.counts(), (1, 0))
        self.assertEqual(self.store.model_state()[0], "unprepared")


if __name__ == "__main__":
    unittest.main()
