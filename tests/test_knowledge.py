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
from core.knowledge import KnowledgeService
from core.knowledge.capture import ContextCaptureError
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
                self.assertEqual(version[0], 12)
                conn.execute("UPDATE schema_versions SET version = 13 WHERE domain = 'knowledge'")
        finally:
            conn.close()
        with self.assertRaises(KnowledgeStoreError):
            self.store.initialize()

    def test_rejects_older_schema_without_rewriting_it(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("UPDATE schema_versions SET version = 11 WHERE domain = 'knowledge'")
        finally:
            conn.close()
        with self.assertRaisesRegex(KnowledgeStoreError, "Unsupported knowledge persistence schema"):
            self.store.initialize()
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("SELECT version FROM schema_versions WHERE domain='knowledge'").fetchone()[0], 11)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0], 0)
        finally:
            conn.close()

    def test_rejects_incomplete_canonical_schema_without_rewriting_it(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DROP TABLE knowledge_history")
        finally:
            conn.close()
        with self.assertRaisesRegex(KnowledgeStoreError, "missing required tables"):
            self.store.initialize()
        conn = sqlite3.connect(self.path)
        try:
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_history'").fetchone())
            self.assertEqual(conn.execute("SELECT version FROM schema_versions WHERE domain='knowledge'").fetchone()[0], 12)
        finally:
            conn.close()

    def test_rejects_missing_version_marker_without_rewriting_data(self) -> None:
        source = self._source("Keep this record while rejecting the schema.")
        record = self.store.create_record(
            partition="production", kind="note", text="Keep this record while rejecting the schema.",
            source_ids=[source.id],
        )
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DELETE FROM schema_versions WHERE domain='knowledge'")
        finally:
            conn.close()
        with self.assertRaisesRegex(KnowledgeStoreError, "no version marker"):
            self.store.initialize()
        self.assertEqual(self.store.get_record(record.id, partition="production").record.text,
                         "Keep this record while rejecting the schema.")
        conn = sqlite3.connect(self.path)
        try:
            self.assertIsNone(conn.execute("SELECT 1 FROM schema_versions WHERE domain='knowledge'").fetchone())
        finally:
            conn.close()

    def test_unsupported_retrieval_schema_disables_knowledge_sync_for_instance(self) -> None:
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("DELETE FROM schema_versions WHERE domain='retrieval'")
        finally:
            conn.close()
        self.store.initialize()
        source = self.store.create_source(
            kind="manual", partition="production", locator="manual/retrieval-disabled",
            original_text="Knowledge writes remain available.",
        )
        with patch(
            "core.knowledge.store.sync_namespace_in_transaction",
            side_effect=AssertionError("retrieval synchronization must be disabled"),
        ):
            record = self.store.create_record(
                partition="production", kind="note", text="Knowledge remains available.",
                source_ids=[source.id],
            )
        self.assertEqual(record.text, "Knowledge remains available.")

    def test_review_acceptance_is_durable_and_stale_snapshot_writes_nothing(self) -> None:
        review = self.store.create_review(
            partition="production", operation="capture",
            proposal={"kind": "note", "text": "Freeze this evidence.", "effective_at": None},
            evidence={"source_kind": "manual", "locator": "manual/review-one", "original_text": "Freeze this evidence.", "source_origin": "operator_input", "derivation": "direct"},
            expected_revisions={}, reason_codes=("sensitive",),
        )
        accepted = self.store.accept_review(review.id, partition="production")
        self.assertEqual(accepted.decision, "accepted")
        self.assertEqual(len(self.store.list_records(partition="production")), 1)

        original = self.store.list_records(partition="production")[0]
        stale = self.store.create_review(
            partition="production", operation="capture",
            proposal={"kind": "note", "text": "A challenged replacement.", "effective_at": None},
            evidence={"source_kind": "manual", "locator": "manual/review-two", "original_text": "A challenged replacement.", "source_origin": "operator_input", "derivation": "direct"},
            expected_revisions={str(original.id): original.updated_at}, reason_codes=("known_conflict",),
        )
        self.store.set_status(original.id, partition="production", status="conflicting")
        with self.assertRaises(KnowledgeConflictError):
            self.store.accept_review(stale.id, partition="production")
        self.assertEqual(self.store.get_review(stale.id, partition="production").decision, "pending")
        self.assertEqual(len(self.store.list_records(partition="production", statuses=("active", "conflicting"))), 1)
        self.store.initialize()
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("SELECT version FROM schema_versions WHERE domain = 'knowledge'").fetchone()[0], 12)
        finally:
            conn.close()

    def test_operator_save_preserves_dates_and_replays_one_bound_submission(self) -> None:
        service = KnowledgeService(self.store)
        values = {"kind": "note", "text": "Ship the release notes.", "effective_at": "2026-09-09"}
        record, review = service.save_operator_context(
            partition="production", values=values, idempotency_key="save-one",
        )
        self.assertIsNone(review)
        assert record is not None
        self.assertEqual(record.effective_at, "2026-09-09")
        replay, replay_review = service.save_operator_context(
            partition="production", values=values, idempotency_key="save-one",
        )
        self.assertIsNone(replay_review)
        self.assertEqual(replay.id, record.id)
        with self.assertRaises(KnowledgeConflictError):
            service.save_operator_context(
                partition="production", values={**values, "text": "Different text."}, idempotency_key="save-one",
            )
        other_date, _ = service.save_operator_context(
            partition="production", values={**values, "effective_at": "2026-09-10"}, idempotency_key="save-two",
        )
        self.assertNotEqual(other_date.id, record.id)

    def test_unstructured_capture_does_not_duplicate_a_structured_claim_with_same_text(self) -> None:
        service = KnowledgeService(self.store)
        structured, structured_review = service.save_operator_context(
            partition="production",
            values={
                "kind": "fact", "text": "Project is blue.", "subject": "Project",
                "predicate": "color", "object_entity": None, "object_value": "blue", "effective_at": None,
            },
        )
        unstructured, unstructured_review = service.save_operator_context(
            partition="production", values={"kind": "fact", "text": "Project is blue.", "effective_at": None},
        )
        assert structured is not None and unstructured is not None
        self.assertIsNone(structured_review)
        self.assertIsNone(unstructured_review)
        self.assertNotEqual(structured.id, unstructured.id)
        self.assertEqual(
            {record.id for record in self.store.list_records(partition="production", statuses=("active",))},
            {structured.id, unstructured.id},
        )
        self.assertEqual(
            {hit.source_id for hit in self.retrieval.search_fts("Project", namespace="personal_context", source_type=None, partition="production", limit=10)},
            {str(structured.id), str(unstructured.id)},
        )

    def test_same_group_structured_correction_applies_without_review(self) -> None:
        service = KnowledgeService(self.store)
        original, review = service.save_operator_context(
            partition="production",
            values={
                "kind": "fact", "text": "A is blue.", "subject": "A", "predicate": "color",
                "object_entity": None, "object_value": "blue", "effective_at": None,
            },
        )
        self.assertIsNone(review)
        assert original is not None
        original = self.store.get_record(original.id, partition="production").record
        replacement, correction_review = service.correct_operator_context(
            partition="production", record_id=str(original.id), expected_updated_at=original.updated_at,
            values={
                "kind": "fact", "text": "A is red.", "subject": "A", "predicate": "color",
                "object_entity": None, "object_value": "red", "effective_at": None,
            },
            sensitive=False, idempotency_key="same-group-correction",
        )
        self.assertIsNone(correction_review)
        assert replacement is not None
        self.assertEqual(self.store.get_record(original.id, partition="production").record.status, "superseded")
        self.assertEqual(self.store.get_record(replacement.id, partition="production").record.status, "active")
        self.assertEqual(
            self.retrieval.search_fts("blue", namespace="personal_context", source_type=None, partition="production", limit=10),
            [],
        )
        self.assertEqual(
            [hit.source_id for hit in self.retrieval.search_fts("red", namespace="personal_context", source_type=None, partition="production", limit=10)],
            [str(replacement.id)],
        )

    def test_review_keys_are_partition_scoped_and_review_snapshots_include_aliases(self) -> None:
        proposal = {"kind": "note", "text": "Retry independently.", "effective_at": None}
        evidence = {
            "source_kind": "manual", "locator": "manual/retry", "original_text": "Retry independently.",
            "source_origin": "operator_input", "derivation": "direct",
        }
        production = self.store.create_review(
            partition="production", operation="capture", proposal=proposal, evidence=evidence,
            expected_revisions={}, reason_codes=("sensitive",), idempotency_key="same-key",
        )
        sandbox = self.store.create_review(
            partition="sandbox", operation="capture", proposal=proposal, evidence=evidence,
            expected_revisions={}, reason_codes=("sensitive",), idempotency_key="same-key",
        )
        self.assertNotEqual(production.id, sandbox.id)

        entity = self.store.create_entity("Jordan")
        source = self._source("Jordan owns APEX")
        self.store.create_record(
            partition="production", kind="fact", text="Jordan owns APEX.", source_ids=[source.id],
            subject_entity_id=entity.id, predicate="owns", object_value="APEX",
        )
        alias_proposal = {"entity_id": str(entity.id), "alias": "J"}
        review = self.store.create_review(
            partition="production", operation="add_alias", proposal=alias_proposal, evidence={},
            expected_revisions=self.store.review_snapshot(
                partition="production", operation="add_alias", proposal=alias_proposal,
            ), reason_codes=("ambiguous_entity",),
        )
        self.store.reconcile(
            action_id="alias-snapshot-change", operation="add_alias", partition="production",
            arguments={"entity_id": str(entity.id), "alias": "Jay"},
        )
        with self.assertRaisesRegex(KnowledgeConflictError, "review_refresh_required"):
            self.store.accept_review(review.id, partition="production")
        refreshed = self.store.refresh_review(review.id, partition="production")
        self.assertIn("refresh_revalidated", refreshed.reason_codes)

    def test_correction_snapshot_rejects_a_new_peer_and_store_rejects_secrets(self) -> None:
        entity = self.store.create_entity("Project")
        source = self._source("Project status is active")
        original = self.store.create_record(
            partition="production", kind="fact", text="Project status is active.", source_ids=[source.id],
            subject_entity_id=entity.id, predicate="status", object_value="active",
        )
        service = KnowledgeService(self.store)
        record, review = service.correct_operator_context(
            partition="production", record_id=str(original.id), expected_updated_at=original.updated_at,
            values={"kind": "fact", "text": "The project is active.", "subject": "Project", "predicate": "status", "object_entity": None, "object_value": "active", "effective_at": None},
            sensitive=True, idempotency_key="correction-peer",
        )
        self.assertIsNone(record)
        assert review is not None
        peer_source = self._source("Project status is paused")
        self.store.create_record(
            partition="production", kind="fact", text="Project status is paused.", source_ids=[peer_source.id],
            status="conflicting", subject_entity_id=entity.id, predicate="status", object_value="paused",
        )
        with self.assertRaisesRegex(KnowledgeConflictError, "review_refresh_required"):
            self.store.accept_review(review.id, partition="production")
        with self.assertRaises(ContextCaptureError):
            self.store.apply_capture(
                action_id="secret-write", partition="production", source_kind="manual", locator="manual/secret",
                original_text="api_key=private", kind="note", text="api_key=private",
            )
        with self.assertRaises(ContextCaptureError):
            self.store.create_review(
                partition="production", operation="capture", proposal={"kind": "note", "text": "api_key=private", "effective_at": None},
                evidence={"source_kind": "manual", "original_text": "api_key=private"},
                expected_revisions={}, reason_codes=("sensitive",),
            )

    def test_correction_into_an_occupied_destination_requires_review(self) -> None:
        service = KnowledgeService(self.store)
        first, _ = service.save_operator_context(
            partition="production", values={"kind": "fact", "text": "A is blue.", "subject": "A", "predicate": "color", "object_entity": None, "object_value": "blue", "effective_at": None},
        )
        service.save_operator_context(
            partition="production", values={"kind": "fact", "text": "B is green.", "subject": "B", "predicate": "color", "object_entity": None, "object_value": "green", "effective_at": None},
        )
        assert first is not None
        record, review = service.correct_operator_context(
            partition="production", record_id=str(first.id), expected_updated_at=first.updated_at,
            values={"kind": "fact", "text": "B is red.", "subject": "B", "predicate": "color", "object_entity": None, "object_value": "red", "effective_at": None},
            sensitive=False, idempotency_key="move-into-occupied",
        )
        self.assertIsNone(record)
        self.assertIsNotNone(review)
        assert review is not None
        self.store.accept_review(review.id, partition="production")
        active = self.store.list_records(partition="production", statuses=("active",))
        self.assertEqual([item.text for item in active], ["B is red."])
        self.assertEqual(
            self.retrieval.search_fts("green", namespace="personal_context", source_type=None, partition="production", limit=10),
            [],
        )
        replacement = active[0]
        self.assertIn(
            "review_accepted",
            [event.operation for event in self.store.get_record(replacement.id, partition="production").history],
        )

    def test_new_peer_after_review_snapshot_requires_refresh_without_writing(self) -> None:
        review = self.store.create_review(
            partition="production", operation="capture",
            proposal={"kind": "fact", "text": "Project is paused.", "subject": "Project", "predicate": "status", "object_entity": None, "object_value": "paused", "effective_at": None},
            evidence={"source_kind": "manual", "locator": "manual/pending", "original_text": "Project is paused.", "source_origin": "operator_input", "derivation": "direct", "occurred_at": None},
            expected_revisions={}, reason_codes=("sensitive",),
        )
        KnowledgeService(self.store).save_operator_context(
            partition="production",
            values={"kind": "fact", "text": "Project is active.", "subject": "Project", "predicate": "status", "object_entity": None, "object_value": "active", "effective_at": None},
        )
        with self.assertRaisesRegex(KnowledgeConflictError, "review_refresh_required"):
            self.store.accept_review(review.id, partition="production")
        self.assertEqual(self.store.get_review(review.id, partition="production").decision, "pending")
        self.assertEqual(
            [record.text for record in self.store.list_records(partition="production", statuses=("active", "conflicting"))],
            ["Project is active."],
        )

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
        self.assertEqual(detail.history[1].source_id, source.id)

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

    def test_old_version_rejection_preserves_existing_history_and_effects(self) -> None:
        source = self._source("Keep linked evidence.")
        record, _, _ = self.store.apply_capture(
            action_id="stable-capture", partition="production", source_kind="manual",
            locator="manual/stable-capture", original_text=source.original_text,
            kind="note", text=source.original_text, derivation="direct",
        )
        before = self.store.get_record(record.id, partition="production")
        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("UPDATE schema_versions SET version=3 WHERE domain='knowledge'")
        finally:
            conn.close()
        with self.assertRaisesRegex(KnowledgeStoreError, "expected version 12"):
            self.store.initialize()
        after = self.store.get_record(record.id, partition="production")
        self.assertEqual(after.record, before.record)
        self.assertEqual(after.sources, before.sources)
        self.assertEqual(after.history, before.history)
        self.assertEqual(self.store.capture_effect("stable-capture")[2], "created")

    def test_failed_fresh_bootstrap_rolls_back_schema_and_version(self) -> None:
        class _FailingBootstrapConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if "CREATE TRIGGER IF NOT EXISTS context_vault_revision_records_insert" in sql:
                    raise sqlite3.OperationalError("injected bootstrap failure")
                return super().execute(sql, parameters)

        failing = sqlite3.connect(":memory:", factory=_FailingBootstrapConnection)
        store = KnowledgeStore(None, connection=failing)
        with self.assertRaisesRegex(sqlite3.OperationalError, "injected bootstrap failure"):
            store.initialize()
        self.assertEqual(
            failing.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [],
        )
        self.assertFalse(failing.in_transaction)
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
        history = self.store.get_record(record.id, partition="production").history
        self.assertIn(
            "entity_alias_added",
            [event.operation for event in history],
        )
        self.store.reconcile(
            action_id="alias-duplicate", operation="add_alias", partition="production",
            arguments={"entity_id": str(source_entity.id), "alias": "j"},
        )
        self.assertEqual(self.store.get_record(record.id, partition="production").history, history)
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
