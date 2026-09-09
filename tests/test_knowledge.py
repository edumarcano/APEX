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
                self.assertEqual(version[0], 4)
                conn.execute("UPDATE schema_versions SET version = 5 WHERE domain = 'knowledge'")
        finally:
            conn.close()
        with self.assertRaises(KnowledgeStoreError):
            self.store.initialize()

    def test_sources_keep_origin_occurrence_and_per_claim_derivation(self) -> None:
        with self.assertRaises(KnowledgeStoreError):
            self.store.create_source(
                kind="manual", partition="production", locator="external/tool/invalid",
                original_text="Invalid timestamp.", occurred_at="not-a-time",
            )
        source = self.store.create_source(
            kind="manual", partition="production", locator="external/tool/run/1",
            original_text="The deployment completed.", origin="external_tool",
            occurred_at="2026-09-09T12:00:00+00:00",
        )
        record = self.store.create_record(
            partition="production", kind="observation", text="The deployment completed.",
            source_ids=[source.id], source_derivations={source.id: "model_interpretation"},
        )
        detail = self.store.get_record(record.id, partition="production")
        self.assertEqual(detail.source_links[0].source.origin, "external_tool")
        self.assertEqual(detail.source_links[0].source.occurred_at, "2026-09-09T12:00:00+00:00")
        self.assertEqual(detail.source_links[0].derivation, "model_interpretation")
        self.assertEqual([event.operation for event in detail.history], ["created", "source_linked"])

    def test_duplicate_evidence_keeps_each_claim_source_derivation(self) -> None:
        first, _, _ = self.store.apply_capture(
            action_id="capture-one", partition="production", source_kind="manual", locator="manual/one",
            original_text="Keep plans concise.", kind="preference", text="Keep plans concise.", derivation="direct",
        )
        self.store.apply_capture(
            action_id="capture-two", partition="production", source_kind="manual", locator="manual/two",
            original_text="Keep plans concise.", kind="preference", text="Keep plans concise.", derivation="model_interpretation",
        )
        detail = self.store.get_record(first.id, partition="production")
        self.assertEqual([link.derivation for link in detail.source_links], ["direct", "model_interpretation"])
        history_count = len(detail.history)
        self.store.apply_capture(
            action_id="capture-two", partition="production", source_kind="manual", locator="manual/two",
            original_text="Keep plans concise.", kind="preference", text="Keep plans concise.", derivation="model_interpretation",
        )
        self.assertEqual(len(self.store.get_record(first.id, partition="production").history), history_count)

    def test_conflict_resolution_records_every_predecessor(self) -> None:
        entity = self.store.create_entity("Release")
        records = []
        for value in ("queued", "running", "complete"):
            source = self._source(f"Release status is {value}")
            records.append(self.store.create_record(
                partition="production", kind="fact", text=f"Release status is {value}.", source_ids=[source.id],
                subject_entity_id=entity.id, predicate="status", object_value=value,
            ))
        for record in records:
            self.store.set_status(record.id, partition="production", status="conflicting")
        selected = self.store.get_record(records[-1].id, partition="production").record
        self.store.reconcile(
            action_id="select-current", operation="set_current", partition="production",
            arguments={"record_id": str(selected.id), "expected_updated_at": selected.updated_at},
        )
        detail = self.store.get_record(selected.id, partition="production")
        self.assertEqual(set(detail.predecessors), {records[0].id, records[1].id})
        for predecessor in records[:2]:
            self.assertEqual(self.store.get_record(predecessor.id, partition="production").superseded_by, (selected.id,))

    def test_v3_migration_preserves_records_and_marks_legacy_provenance_unknown(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        original_id, replacement_id, source_id = UUID(int=101), UUID(int=102), UUID(int=103)
        conn = sqlite3.connect(legacy_path)
        try:
            with conn:
                conn.executescript("""
                    CREATE TABLE schema_versions (domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL);
                    CREATE TABLE knowledge_sources (id TEXT PRIMARY KEY, kind TEXT NOT NULL, partition TEXT NOT NULL, locator TEXT NOT NULL, original_text TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(kind,partition,locator,content_hash));
                    CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
                    CREATE TABLE entity_aliases (normalized_alias TEXT PRIMARY KEY, entity_id TEXT NOT NULL, alias TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE knowledge_records (id TEXT PRIMARY KEY, partition TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, subject_entity_id TEXT, predicate TEXT, object_entity_id TEXT, object_value TEXT, effective_at TEXT, supersedes_record_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE knowledge_record_sources (record_id TEXT NOT NULL, source_id TEXT NOT NULL, action_id TEXT, linked_at TEXT NOT NULL, PRIMARY KEY(record_id,source_id));
                    CREATE TABLE knowledge_action_effects (action_id TEXT PRIMARY KEY, record_id TEXT NOT NULL, source_id TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE knowledge_reconciliation_effects (action_id TEXT PRIMARY KEY, operation TEXT NOT NULL, target_id TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL);
                """)
                conn.execute("INSERT INTO schema_versions VALUES ('knowledge', 3)")
                conn.execute("INSERT INTO knowledge_sources VALUES (?, 'manual', 'production', 'manual/legacy', 'Original wording', 'digest', '2026-01-01T00:00:00+00:00')", (str(source_id),))
                conn.execute("INSERT INTO knowledge_records VALUES (?, 'production', 'note', 'Original wording', 'superseded', NULL, NULL, NULL, NULL, NULL, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')", (str(original_id),))
                conn.execute("INSERT INTO knowledge_records VALUES (?, 'production', 'note', 'Replacement wording', 'active', NULL, NULL, NULL, NULL, NULL, ?, '2026-01-02T00:00:00+00:00', '2026-01-02T00:00:00+00:00')", (str(replacement_id), str(original_id)))
                conn.execute("INSERT INTO knowledge_record_sources VALUES (?, ?, NULL, '2026-01-01T00:00:00+00:00')", (str(original_id), str(source_id)))
        finally:
            conn.close()
        RetrievalStore(legacy_path).initialize()
        legacy_store = KnowledgeStore(legacy_path)
        legacy_store.initialize()
        original = legacy_store.get_record(original_id, partition="production")
        replacement = legacy_store.get_record(replacement_id, partition="production")
        self.assertEqual(original.sources[0].id, source_id)
        self.assertEqual(original.source_links[0].source.origin, "unknown")
        self.assertEqual(original.source_links[0].derivation, "unknown")
        self.assertEqual(replacement.predecessors, (original_id,))
        self.assertEqual(original.superseded_by, (replacement_id,))
        self.assertEqual(original.history[0].reason_code, "migration_baseline")
        legacy_store.close()

    def test_failed_v3_migration_rolls_back_schema_and_version(self) -> None:
        class _FailingMigrationConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if "INSERT INTO knowledge_history" in sql:
                    raise sqlite3.OperationalError("injected migration failure")
                return super().execute(sql, parameters)

        legacy_path = Path(self.temp_dir.name) / "failed-migration.db"
        conn = sqlite3.connect(legacy_path)
        try:
            with conn:
                conn.executescript("""
                    CREATE TABLE schema_versions (domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL);
                    CREATE TABLE knowledge_sources (id TEXT PRIMARY KEY, kind TEXT NOT NULL, partition TEXT NOT NULL, locator TEXT NOT NULL, original_text TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(kind,partition,locator,content_hash));
                    CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
                    CREATE TABLE entity_aliases (normalized_alias TEXT PRIMARY KEY, entity_id TEXT NOT NULL, alias TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE knowledge_records (id TEXT PRIMARY KEY, partition TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, subject_entity_id TEXT, predicate TEXT, object_entity_id TEXT, object_value TEXT, effective_at TEXT, supersedes_record_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE knowledge_record_sources (record_id TEXT NOT NULL, source_id TEXT NOT NULL, action_id TEXT, linked_at TEXT NOT NULL, PRIMARY KEY(record_id,source_id));
                    CREATE TABLE knowledge_action_effects (action_id TEXT PRIMARY KEY, record_id TEXT NOT NULL, source_id TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE knowledge_reconciliation_effects (action_id TEXT PRIMARY KEY, operation TEXT NOT NULL, target_id TEXT NOT NULL, outcome TEXT NOT NULL, created_at TEXT NOT NULL);
                """)
                conn.execute("INSERT INTO schema_versions VALUES ('knowledge', 3)")
                conn.execute("INSERT INTO knowledge_sources VALUES ('source', 'manual', 'production', 'manual/legacy', 'Original evidence', 'digest', '2026-01-01T00:00:00+00:00')")
                conn.execute("INSERT INTO knowledge_records VALUES ('record', 'production', 'note', 'Original evidence', 'active', NULL, NULL, NULL, NULL, NULL, NULL, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')")
                conn.execute("INSERT INTO knowledge_record_sources VALUES ('record', 'source', NULL, '2026-01-01T00:00:00+00:00')")
        finally:
            conn.close()
        failing = sqlite3.connect(legacy_path, factory=_FailingMigrationConnection)
        store = KnowledgeStore(None, connection=failing)
        with self.assertRaises(sqlite3.OperationalError):
            store.initialize()
        self.assertNotIn("origin", {column[1] for column in failing.execute("PRAGMA table_info(knowledge_sources)")})
        self.assertEqual(failing.execute("SELECT version FROM schema_versions WHERE domain='knowledge'").fetchone()[0], 3)
        self.assertEqual(failing.execute("SELECT original_text FROM knowledge_sources").fetchone()[0], "Original evidence")
        failing.close()

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
        self.store.reconcile(
            action_id="alias-1", operation="add_alias", partition="production",
            arguments={"entity_id": str(source_entity.id), "alias": "J"},
        )
        self.assertIn(
            "entity_alias_added",
            [event.operation for event in self.store.get_record(record.id, partition="production").history],
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
