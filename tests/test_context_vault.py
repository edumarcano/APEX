from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from core.context_vault.selection import ContextVaultSelectionService
from core.knowledge.service import KnowledgeService
from core.knowledge.store import KnowledgeConflictError, KnowledgeStore
from core.retrieval.store import RetrievalStore
from core.settings.models import ContextVaultScopeSettings, ContextVaultSettings


class ContextVaultSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "knowledge.db"
        self.retrieval = RetrievalStore(self.path)
        self.retrieval.initialize()
        self.store = KnowledgeStore(self.path)
        self.store.initialize()
        self.knowledge = KnowledgeService(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.retrieval.close()
        self.temp_dir.cleanup()

    def _record(
        self, *, entity_id: UUID, index: int, partition: str = "production", status: str = "active",
        predicate: str | None = None,
    ):
        source = self.store.create_source(
            kind="manual", partition=partition, locator=f"manual/{partition}/{index}/{uuid4()}",
            original_text=f"Private source {index}",
        )
        return self.store.create_record(
            partition=partition, kind="note", text=f"Canonical claim {index}",
            source_ids=(source.id,), status=status, subject_entity_id=entity_id,
            predicate=predicate or f"claim_{index}", object_value=f"value_{index}",
        )

    @staticmethod
    def _selection_service(knowledge, *, enabled: bool, scopes, destination_configured: bool = True):
        return ContextVaultSelectionService(
            knowledge, ContextVaultSettings(enabled=enabled, scopes=tuple(scopes)),
            destination_configured=destination_configured,
        )

    def test_preview_reads_all_production_candidates_and_reports_policy_exclusions(self) -> None:
        entity = self.store.create_entity("Project Northstar")
        records = [self._record(entity_id=entity.id, index=index) for index in range(110)]
        for index, state in ((0, "conflicting"), (1, "superseded"), (2, "retracted")):
            self.store.set_status(records[index].id, partition="production", status=state)
        sensitive = self.store.set_sensitive(
            records[3].id, partition="production", sensitive=True,
            expected_updated_at=records[3].updated_at,
        )
        pending = self.store.create_review(
            partition="production", operation="retract",
            proposal={"record_id": str(records[4].id)}, evidence={},
            expected_revisions={str(records[4].id): records[4].updated_at},
            reason_codes=("operator_review",),
        )
        excluded_id = records[5].id
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Northstar", enabled=True,
            selected_entity_ids=(entity.id,), excluded_record_ids=(excluded_id,),
        )
        preview = self._selection_service(
            self.knowledge, enabled=True, scopes=(scope,),
        ).preview(scope.id)

        by_id = {record.record_id: record for record in preview.records}
        self.assertEqual(preview.eligible_count, 104)
        self.assertEqual(len(preview.records), 110)
        self.assertEqual(by_id[str(records[0].id)].exclusion_reasons, ("conflicting",))
        self.assertEqual(by_id[str(records[1].id)].exclusion_reasons, ("superseded",))
        self.assertEqual(by_id[str(records[2].id)].exclusion_reasons, ("retracted",))
        self.assertEqual(by_id[str(sensitive.id)].exclusion_reasons, ("sensitive",))
        self.assertEqual(by_id[str(records[4].id)].exclusion_reasons, ("pending_review",))
        self.assertEqual(by_id[str(excluded_id)].exclusion_reasons, ("operator_excluded",))
        self.assertEqual(by_id[str(records[6].id)].projected_path, f"records/{records[6].id}.md")
        self.assertFalse(hasattr(by_id[str(records[6].id)], "sources"))
        self.assertFalse(hasattr(by_id[str(records[6].id)], "review_proposal"))
        self.assertNotIn(str(pending.id), repr(preview))
        self.assertNotIn("Private source 6", repr(preview))
        self.assertFalse(hasattr(by_id[str(records[6].id)], "source_metadata"))

        snapshot = self.store.context_vault_selection_snapshot(
            selected_entity_ids=(), record_ids=(records[6].id,), excluded_record_ids=(),
        )
        self.assertEqual(snapshot.records[0].updated_at, records[6].updated_at)
        self.assertEqual(snapshot.records[0].source_metadata[0].source.original_text, "Private source 6")
        self.assertTrue(snapshot.records[0].source_metadata[0].source.locator.startswith("manual/production/6/"))

        sandbox_record = self._record(entity_id=entity.id, index=111, partition="sandbox")
        again = self._selection_service(self.knowledge, enabled=True, scopes=(scope,)).preview(scope.id)
        self.assertNotIn(str(sandbox_record.id), {record.record_id for record in again.records})

    def test_candidate_preview_hypothetically_activates_unsaved_scope_without_persisting(self) -> None:
        entity = self.store.create_entity("Project Preview")
        ordinary = self._record(entity_id=entity.id, index=120)
        sensitive_record = self._record(entity_id=entity.id, index=121)
        sensitive = self.store.set_sensitive(
            sensitive_record.id,
            partition="production",
            sensitive=True,
            expected_updated_at=sensitive_record.updated_at,
        )
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Draft Project", enabled=False,
            selected_entity_ids=(entity.id,), include_sensitive=False,
        )

        service = self._selection_service(self.knowledge, enabled=False, scopes=())
        preview = service.preview_candidate(scope)

        by_id = {record.record_id: record for record in preview.records}
        self.assertTrue(preview.hypothetical_enabled)
        self.assertFalse(preview.vault_enabled)
        self.assertFalse(preview.scope_enabled)
        self.assertTrue(by_id[str(ordinary.id)].eligible)
        self.assertEqual(by_id[str(ordinary.id)].exclusion_reasons, ())
        self.assertEqual(by_id[str(sensitive.id)].exclusion_reasons, ("sensitive",))
        self.assertEqual(preview.scope_name, "Draft Project")
        self.assertFalse(service.status().enabled)
        self.assertEqual(service.status().scopes, ())

    def test_production_revision_advances_at_committed_export_input_changes(self) -> None:
        initial_revision = self.store.context_vault_revision()
        sandbox = self._record(
            entity_id=self.store.create_entity("Sandbox only").id,
            index=900,
            partition="sandbox",
        )
        self.assertGreater(sandbox.id.int, 0)
        self.assertEqual(self.store.context_vault_revision(), initial_revision)

        events: list[tuple[int, int]] = []
        self.store.set_context_vault_change_callback(
            lambda revision: events.append((revision, self.store.context_vault_revision()))
        )
        record = self._record(
            entity_id=self.store.create_entity("Production revision").id,
            index=901,
        )
        created_revision = self.store.context_vault_revision()
        self.assertGreater(created_revision, initial_revision)
        self.assertTrue(events)
        self.assertTrue(all(observed == current for observed, current in events))

        proposal = {"record_id": str(record.id), "expected_updated_at": record.updated_at}
        review = self.store.create_review(
            partition="production",
            operation="retract",
            proposal=proposal,
            evidence={},
            expected_revisions=self.store.review_snapshot(
                partition="production", operation="retract", proposal=proposal,
            ),
            reason_codes=("operator_review",),
        )
        challenge_revision = self.store.context_vault_revision()
        self.assertGreater(challenge_revision, created_revision)
        self.store.reject_review(review.id, partition="production")
        self.assertGreater(self.store.context_vault_revision(), challenge_revision)

        current = self.store.get_record(record.id, partition="production").record
        before_sensitivity = self.store.context_vault_revision()
        self.store.set_sensitive(
            record.id, partition="production", sensitive=True,
            expected_updated_at=current.updated_at,
        )
        self.assertGreater(self.store.context_vault_revision(), before_sensitivity)

    def test_rolled_back_export_input_change_does_not_notify_runtime(self) -> None:
        record = self._record(entity_id=self.store.create_entity("Rollback").id, index=902)
        before_revision = self.store.context_vault_revision()
        events: list[int] = []
        self.store.set_context_vault_change_callback(events.append)

        with self.assertRaisesRegex(RuntimeError, "rollback test"):
            with self.store._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE knowledge_records SET sensitive=1 WHERE id=? AND partition='production'",
                    (str(record.id),),
                )
                raise RuntimeError("rollback test")

        self.assertEqual(self.store.context_vault_revision(), before_revision)
        self.assertEqual(events, [])

    def test_entity_selection_matches_object_entity(self) -> None:
        subject = self.store.create_entity("Project Orion")
        selected_object = self.store.create_entity("Budget Review")
        source = self.store.create_source(
            kind="manual", partition="production", locator=f"manual/object/{uuid4()}",
            original_text="Project Orion requires a budget review.",
        )
        record = self.store.create_record(
            partition="production", kind="decision", text="Project Orion requires a budget review.",
            source_ids=(source.id,), subject_entity_id=subject.id, predicate="requires",
            object_entity_id=selected_object.id,
        )
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Budget", enabled=True, selected_entity_ids=(selected_object.id,),
        )

        preview = self._selection_service(self.knowledge, enabled=True, scopes=(scope,)).preview(scope.id)

        self.assertEqual([item.record_id for item in preview.records], [str(record.id)])

    def test_exclusions_follow_known_replacement_lineage(self) -> None:
        old = self._record(entity_id=self.store.create_entity("Legacy note").id, index=151)
        correction = self.store.reconcile(
            action_id="replace-excluded-record", operation="correct", partition="production",
            arguments={
                "record_id": str(old.id), "expected_updated_at": old.updated_at,
                "capture": {"kind": "note", "text": "Replacement claim."},
            },
        )
        new_id = UUID(correction["target_id"])
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Explicit record", enabled=True,
            record_ids=(old.id,), excluded_record_ids=(old.id,),
        )

        preview = self._selection_service(self.knowledge, enabled=True, scopes=(scope,)).preview(scope.id)

        by_id = {record.record_id: record for record in preview.records}
        self.assertEqual(set(by_id), {str(old.id), str(new_id)})
        self.assertIn("operator_excluded", by_id[str(new_id)].exclusion_reasons)
        self.assertFalse(by_id[str(new_id)].eligible)

    def test_sensitive_state_is_revision_checked_and_corrections_inherit_it(self) -> None:
        direct, _, _ = self.store.apply_capture(
            action_id="direct-sensitive-capture", partition="production", source_kind="manual",
            locator="manual/direct-sensitive", original_text="Direct private claim.",
            kind="note", text="Direct private claim.", sensitive=True,
        )
        self.assertTrue(direct.sensitive)

        values = {"kind": "note", "text": "Launch date is private."}
        record, review = self.store.submit_operator(
            partition="production", values=values, sensitive=True,
            idempotency_key="sensitive-capture",
        )
        self.assertIsNone(record)
        assert review is not None
        self.assertTrue(review.proposal["sensitive"])
        self.assertTrue(review.evidence["sensitive"])
        self.store.accept_review(review.id, partition="production")
        created = next(
            item for item in self.store.list_records(partition="production", statuses=("active",))
            if item.text == values["text"]
        )
        self.assertTrue(created.sensitive)

        corrected, correction_review = self.store.submit_operator(
            partition="production", correction_record_id=str(created.id),
            expected_updated_at=created.updated_at,
            values={"kind": "note", "text": "Updated private launch date."},
            sensitive=False, idempotency_key="sensitive-correction",
        )
        self.assertIsNone(correction_review)
        assert corrected is not None
        self.assertTrue(corrected.sensitive)

        changed = self.store.set_sensitive(
            corrected.id, partition="production", sensitive=False,
            expected_updated_at=corrected.updated_at,
        )
        self.assertFalse(changed.sensitive)
        with self.assertRaises(KnowledgeConflictError):
            self.store.set_sensitive(
                corrected.id, partition="production", sensitive=True,
                expected_updated_at=corrected.updated_at,
            )
        detail = self.store.get_record(corrected.id, partition="production")
        self.assertEqual(detail.history[-1].operation, "sensitivity_changed")
        self.assertEqual(detail.history[-1].reason_code, "sensitive_disabled")

    def test_conflict_resolution_inherits_sensitivity_from_any_predecessor(self) -> None:
        entity = self.store.create_entity("Project Ember")
        selected = self._record(
            entity_id=entity.id, index=201, status="conflicting", predicate="launch_date",
        )
        sensitive_peer = self._record(
            entity_id=entity.id, index=202, status="conflicting", predicate="launch_date",
        )
        ordinary_peer = self._record(
            entity_id=entity.id, index=203, status="conflicting", predicate="launch_date",
        )
        self.store.set_sensitive(
            sensitive_peer.id, partition="production", sensitive=True,
            expected_updated_at=sensitive_peer.updated_at,
        )

        self.store.reconcile(
            action_id="select-sensitive-peer", operation="set_current", partition="production",
            arguments={"record_id": str(selected.id), "expected_updated_at": selected.updated_at},
        )

        detail = self.store.get_record(selected.id, partition="production")
        self.assertEqual(detail.record.status, "active")
        self.assertTrue(detail.record.sensitive)
        self.assertIn("sensitive_inherited", {event.reason_code for event in detail.history})
        self.assertEqual(self.store.get_record(ordinary_peer.id, partition="production").record.status, "superseded")

    def test_merged_entity_selection_requires_reselection_and_does_not_expand(self) -> None:
        source = self.store.create_entity("Former Project Name")
        target = self.store.create_entity("Current Project Name")
        record = self._record(entity_id=source.id, index=301)
        self.store.reconcile(
            action_id="merge-selected-entity", operation="merge_entities", partition="production",
            arguments={"source_entity_id": str(source.id), "target_entity_id": str(target.id)},
        )
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Former project", enabled=True, selected_entity_ids=(source.id,),
        )

        preview = self._selection_service(self.knowledge, enabled=True, scopes=(scope,)).preview(scope.id)

        self.assertEqual(preview.records, ())
        self.assertEqual(preview.selection_issues[0].reason_code, "entity_merged_requires_reselection")
        self.assertEqual(preview.selection_issues[0].replacement_entity_id, str(target.id))
        self.assertNotIn(str(record.id), {item.record_id for item in preview.records})

    def test_accepted_sensitive_reviews_backfill_only_linked_records(self) -> None:
        sensitive_record, review = self.store.submit_operator(
            partition="production", values={"kind": "note", "text": "Private accepted claim."},
            sensitive=True, idempotency_key="migration-sensitive",
        )
        self.assertIsNone(sensitive_record)
        assert review is not None
        self.store.accept_review(review.id, partition="production")
        ordinary, ordinary_review = self.store.submit_operator(
            partition="production", values={"kind": "note", "text": "Ordinary accepted claim."},
            sensitive=False, idempotency_key="migration-ordinary",
        )
        self.assertIsNone(ordinary_review)
        assert ordinary is not None

        conn = sqlite3.connect(self.path)
        try:
            with conn:
                conn.execute("UPDATE schema_versions SET version=10 WHERE domain='knowledge'")
                conn.execute("ALTER TABLE knowledge_records DROP COLUMN sensitive")
        finally:
            conn.close()

        migrated = KnowledgeStore(self.path)
        migrated.initialize()
        try:
            migrated_sensitive = next(
                item for item in migrated.list_records(partition="production", statuses=("active",))
                if item.text == "Private accepted claim."
            )
            migrated_ordinary = migrated.get_record(ordinary.id, partition="production").record
            self.assertTrue(migrated_sensitive.sensitive)
            self.assertFalse(migrated_ordinary.sensitive)
        finally:
            migrated.close()

    def test_preview_uses_one_snapshot_during_review_acceptance(self) -> None:
        record = self._record(entity_id=self.store.create_entity("Project Race").id, index=401)
        proposal = {"record_id": str(record.id), "expected_updated_at": record.updated_at}
        review = self.store.create_review(
            partition="production", operation="retract", proposal=proposal,
            evidence={}, expected_revisions=self.store.review_snapshot(
                partition="production", operation="retract", proposal=proposal,
            ),
            reason_codes=("operator_review",),
        )
        candidates_loaded = threading.Event()
        resume_snapshot = threading.Event()

        class PausingKnowledgeStore(KnowledgeStore):
            def _context_vault_candidates_in_transaction(self, conn, *, selected_entity_ids, record_ids):
                result = super()._context_vault_candidates_in_transaction(
                    conn, selected_entity_ids=selected_entity_ids, record_ids=record_ids,
                )
                candidates_loaded.set()
                if not resume_snapshot.wait(timeout=10):
                    raise TimeoutError("test did not release the paused snapshot")
                return result

        reader_store = PausingKnowledgeStore(self.path)
        reader_store.initialize()
        self.addCleanup(reader_store.close)
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Race scope", enabled=True, record_ids=(record.id,),
        )
        service = self._selection_service(
            KnowledgeService(reader_store), enabled=True, scopes=(scope,),
        )
        result: dict[str, object] = {}
        failures: list[BaseException] = []

        def preview() -> None:
            try:
                result["preview"] = service.preview(scope.id)
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=preview)
        worker.start()
        self.assertTrue(candidates_loaded.wait(timeout=10), "snapshot did not reach candidate read")
        try:
            accepted = self.store.accept_review(review.id, partition="production")
            self.assertEqual(accepted.decision, "accepted")
        finally:
            resume_snapshot.set()
        worker.join(timeout=10)
        self.assertFalse(worker.is_alive(), "preview thread did not finish")
        self.assertEqual(failures, [])

        preview_result = result["preview"]
        assert hasattr(preview_result, "records")
        selected = next(item for item in preview_result.records if item.record_id == str(record.id))
        self.assertEqual(selected.status, "active")
        self.assertEqual(selected.exclusion_reasons, ("pending_review",))
        self.assertFalse(selected.eligible)
        self.assertEqual(self.store.get_record(record.id, partition="production").record.status, "retracted")


if __name__ == "__main__":
    unittest.main()
