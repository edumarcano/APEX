"""Focused coverage for the source-tracked world-model foundation."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from core.knowledge.store import (
    KnowledgeConflictError,
    KnowledgeNotFoundError,
    KnowledgeStore,
    KnowledgeStoreError,
)
from core.retrieval.store import RetrievalStore


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "apex_memory.db"
        self.retrieval = RetrievalStore(self.path)
        self.retrieval.initialize()
        self.store = KnowledgeStore(self.path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self.retrieval.close()
        self.temp_dir.cleanup()

    def _source(self, text: str = "Jordan prefers early meetings", *, partition: str = "production"):
        return self.store.create_source(
            kind="conversation_message", partition=partition,
            locator=f"conversation/example/message/{text[:8]}", original_text=text,
        )

    def test_initializes_schema_and_rejects_future_version(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                version = conn.execute("SELECT version FROM schema_versions WHERE domain = 'knowledge'").fetchone()
                self.assertEqual(version[0], 3)
                conn.execute("UPDATE schema_versions SET version = 4 WHERE domain = 'knowledge'")
        finally:
            conn.close()
        with self.assertRaises(KnowledgeStoreError):
            self.store.initialize()

    def test_sources_are_immutable_and_linked_to_records(self) -> None:
        source = self._source()
        same = self.store.create_source(
            kind="conversation_message", partition="production", locator=source.locator,
            original_text=source.original_text,
        )
        self.assertEqual(same.id, source.id)
        record = self.store.create_record(
            partition="production", kind="preference", text="Jordan prefers early meetings.", source_ids=[source.id],
        )
        detail = self.store.get_record(record.id, partition="production")
        self.assertEqual(detail.sources, (source,))
        with self.assertRaises(KnowledgeNotFoundError):
            self.store.get_record(record.id, partition="sandbox")

    def test_exact_aliases_are_unique_and_relationships_are_records(self) -> None:
        jordan = self.store.create_entity("Jordan Lee")
        project = self.store.create_entity("APEX")
        self.store.add_alias(jordan.id, "  JORDAN   LEE ")
        self.assertEqual(self.store.resolve_entity("jordan lee").id, jordan.id)
        self.assertEqual(self.store.resolve_entity("unknown"), None)
        with self.assertRaises(KnowledgeConflictError):
            self.store.add_alias(project.id, "Jordan Lee")
        source = self._source("Jordan owns APEX")
        record = self.store.create_record(
            partition="production", kind="fact", text="Jordan owns APEX.", source_ids=[source.id],
            subject_entity_id=jordan.id, predicate="owns", object_entity_id=project.id,
        )
        self.assertEqual([item.id for item in self.store.one_hop_relationships(jordan.id, partition="production")], [record.id])
        self.assertEqual(self.store.one_hop_relationships(project.id, partition="sandbox"), [])

    def test_temporal_statuses_preserve_history_and_reconcile_retrieval(self) -> None:
        source = self._source("Jordan lives in Boston")
        first = self.store.create_record(
            partition="production", kind="fact", text="Jordan lives in Boston.", source_ids=[source.id],
        )
        self.assertEqual(
            [hit.source_id for hit in self.retrieval.search_fts("Boston", namespace="personal_context", source_type=None, partition="production", limit=10)],
            [str(first.id)],
        )
        replacement_source = self._source("Jordan lives in Philadelphia")
        replacement = self.store.create_record(
            partition="production", kind="fact", text="Jordan lives in Philadelphia.", source_ids=[replacement_source.id],
            supersedes_record_id=first.id,
        )
        self.assertEqual(self.store.get_record(first.id, partition="production").record.status, "superseded")
        self.assertEqual(self.store.get_record(first.id, partition="production").superseded_by, (replacement.id,))
        self.assertEqual(self.retrieval.search_fts("Boston", namespace="personal_context", source_type=None, partition="production", limit=10), [])
        self.store.set_status(replacement.id, partition="production", status="retracted")
        self.assertEqual(self.retrieval.search_fts("Philadelphia", namespace="personal_context", source_type=None, partition="production", limit=10), [])
        restored = self.store.set_status(replacement.id, partition="production", status="active")
        self.assertEqual(restored.status, "active")
        with self.assertRaises(KnowledgeConflictError):
            self.store.set_status(first.id, partition="production", status="active")

    def test_retrieval_failure_rolls_back_canonical_write(self) -> None:
        source = self._source()
        with patch("core.knowledge.store.sync_namespace_in_transaction", side_effect=RuntimeError("broken index")):
            with self.assertRaises(RuntimeError):
                self.store.create_record(
                    partition="production", kind="preference", text="Jordan prefers early meetings.", source_ids=[source.id],
                )
        self.assertEqual(self.store.list_records(partition="production"), [])
        self.assertEqual(self.retrieval.search_fts("Jordan", namespace="personal_context", source_type=None, partition="production", limit=10), [])

    def test_reconciliation_retract_restore_and_correction_are_transactional(self) -> None:
        source = self._source("Jordan prefers focused work")
        record = self.store.create_record(
            partition="production", kind="preference", text="Jordan prefers focused work.", source_ids=[source.id],
        )
        retracted = self.store.reconcile(
            action_id="retract-1", operation="retract", partition="production",
            arguments={"record_id": str(record.id), "expected_updated_at": record.updated_at},
        )
        self.assertEqual(retracted["outcome"], "retracted")
        current = self.store.get_record(record.id, partition="production").record
        restored = self.store.reconcile(
            action_id="restore-1", operation="restore", partition="production",
            arguments={"record_id": str(record.id), "expected_updated_at": current.updated_at},
        )
        self.assertEqual(restored["outcome"], "active")
        current = self.store.get_record(record.id, partition="production").record
        corrected = self.store.reconcile(
            action_id="correct-1", operation="correct", partition="production",
            arguments={"record_id": str(record.id), "expected_updated_at": current.updated_at, "capture": {"kind": "preference", "text": "Jordan prefers deep work."}},
        )
        self.assertEqual(corrected["outcome"], "corrected")
        self.assertEqual(self.store.get_record(record.id, partition="production").record.status, "superseded")
        replacement = self.store.get_record(UUID(corrected["target_id"]), partition="production").record
        self.assertEqual(replacement.supersedes_record_id, record.id)
        self.assertEqual(self.store.reconciliation_effect("correct-1")["target_id"], str(replacement.id))

    def test_entity_merge_preserves_alias_resolution_and_reassigns_records(self) -> None:
        source_entity = self.store.create_entity("Jordan")
        target_entity = self.store.create_entity("Jordan Lee")
        source = self._source("Jordan owns APEX")
        record = self.store.create_record(
            partition="production", kind="fact", text="Jordan owns APEX.", source_ids=[source.id],
            subject_entity_id=source_entity.id, predicate="owns", object_value="APEX",
        )
        result = self.store.reconcile(
            action_id="merge-1", operation="merge_entities", partition="production",
            arguments={"source_entity_id": str(source_entity.id), "target_entity_id": str(target_entity.id)},
        )
        self.assertEqual(result["outcome"], "merged")
        self.assertEqual(self.store.resolve_entity("Jordan").id, target_entity.id)
        self.assertEqual(self.store.get_entity(source_entity.id, include_merged=True).merged_into_entity_id, target_entity.id)
        self.assertEqual(self.store.get_record(record.id, partition="production").record.subject_entity_id, target_entity.id)

    def test_partition_entity_listing_and_mutation_reject_cross_partition_records(self) -> None:
        entity = self.store.create_entity("Private Sandbox Entity")
        source = self._source("sandbox entity", partition="sandbox")
        self.store.create_record(partition="sandbox", kind="fact", text="sandbox entity", source_ids=[source.id], subject_entity_id=entity.id, predicate="is", object_value="private")
        self.assertEqual(self.store.list_entities_in_partition(partition="production"), [])
        self.assertEqual([item.id for item in self.store.list_entities_in_partition(partition="sandbox")], [entity.id])
        production_source = self._source("production entity")
        self.store.create_record(partition="production", kind="fact", text="production entity", source_ids=[production_source.id], subject_entity_id=entity.id, predicate="is", object_value="shared")
        with self.assertRaises(KnowledgeNotFoundError):
            self.store.reconcile(action_id="alias-cross-partition", operation="add_alias", partition="sandbox", arguments={"entity_id": str(entity.id), "alias": "private"})

    def test_memory_store_is_process_local(self) -> None:
        store = KnowledgeStore(None)
        try:
            store.initialize()
            source = store.create_source(kind="manual", partition="production", locator="manual/example", original_text="A private note")
            record = store.create_record(partition="production", kind="note", text="A private note", source_ids=[source.id])
            self.assertEqual(store.get_record(record.id, partition="production").record.text, "A private note")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
