from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.actions import ActionService, ActionStore
from core.knowledge.reconciliation import CAPABILITY_NAME, ContextReconciliationExecutor, ContextReconciliationVerifier
from core.knowledge.store import KnowledgeStore
from core.knowledge import KnowledgeService
from core.retrieval.store import RetrievalStore


class _ConversationService:
    def partition(self) -> str:
        return "production"


class ContextReconciliationActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "apex.db"
        RetrievalStore(self.path).initialize()
        self.knowledge = KnowledgeStore(self.path)
        self.knowledge.initialize()
        self.actions = ActionService(ActionStore(self.path))
        self.actions.register_handler(
            CAPABILITY_NAME,
            executor=ContextReconciliationExecutor(self.knowledge),
            verifier=ContextReconciliationVerifier(self.knowledge),
        )
        source = self.knowledge.create_source(
            kind="manual", partition="production", locator="manual/seed", original_text="Keep meetings in the morning.",
            origin="external_tool", occurred_at="2026-09-09T09:00:00+00:00",
        )
        self.record = self.knowledge.create_record(
            partition="production", kind="preference", text="Keep meetings in the morning.", source_ids=[source.id],
            source_derivations={source.id: "model_interpretation"},
        )

    def tearDown(self) -> None:
        self.knowledge.close()
        self.tempdir.cleanup()

    def test_retract_is_proposed_before_it_changes_the_record(self) -> None:
        action = self.actions.propose(
            agent_key="operator", capability_name=CAPABILITY_NAME,
            arguments={"operation": "retract", "partition": "production", "record_id": str(self.record.id), "expected_updated_at": self.record.updated_at},
            target="Personal Context", risk="destructive", summary="Approve personal context retract", actor="operator",
        )
        self.assertEqual(self.knowledge.get_record(self.record.id, partition="production").record.status, "active")
        verified = self.actions.approve_and_execute(action.action_id, actor="operator", expected_version=0)
        self.assertEqual(verified.status, "verified")
        self.assertEqual(self.knowledge.get_record(self.record.id, partition="production").record.status, "retracted")

    def test_stale_reconciliation_action_fails_without_writing(self) -> None:
        action = self.actions.propose(
            agent_key="operator", capability_name=CAPABILITY_NAME,
            arguments={"operation": "retract", "partition": "production", "record_id": str(self.record.id), "expected_updated_at": self.record.updated_at},
            target="Personal Context", risk="destructive", summary="Approve personal context retract", actor="operator",
        )
        self.knowledge.set_status(self.record.id, partition="production", status="conflicting")
        result = self.actions.approve_and_execute(action.action_id, actor="operator", expected_version=0)
        self.assertEqual(result.status, "execution_failed")
        self.assertEqual(self.knowledge.get_record(self.record.id, partition="production").record.status, "conflicting")

    def test_sensitive_direct_correction_review_builds_server_owned_attempt_arguments(self) -> None:
        service = KnowledgeService(self.knowledge)
        record, review = service.correct_operator_context(
            partition="production", record_id=str(self.record.id), expected_updated_at=self.record.updated_at,
            values={"kind": "preference", "text": "Keep meetings after lunch.", "effective_at": None},
            sensitive=True, idempotency_key="sensitive-correction",
        )
        self.assertIsNone(record)
        assert review is not None
        accepted = service.decide_review_accept(
            self.actions, review.id, partition="production", expected_revisions=review.expected_revisions,
        )
        self.assertEqual(accepted.decision, "accepted")
        action = self.actions.get(accepted.action_id)
        self.assertEqual(action.proposal.arguments["operation"], "correct")
        self.assertEqual(action.proposal.arguments["partition"], "production")
        replacement = self.knowledge.list_records(partition="production", statuses=("active",))[0]
        source_link = self.knowledge.get_record(replacement.id, partition="production").source_links[0]
        self.assertEqual(source_link.source.original_text, "Keep meetings after lunch.")
        self.assertEqual(source_link.derivation, "direct")

    def test_stale_correction_refreshes_the_target_revision_without_writing(self) -> None:
        service = KnowledgeService(self.knowledge)
        current = self.knowledge.get_record(self.record.id, partition="production").record
        record, review = service.correct_operator_context(
            partition="production", record_id=str(current.id), expected_updated_at=current.updated_at,
            values={"kind": "preference", "text": "Keep meetings after lunch.", "effective_at": None},
            sensitive=True, idempotency_key="refresh-correction",
        )
        self.assertIsNone(record)
        assert review is not None
        self.knowledge.apply_capture(
            action_id="revision-change", partition="production", source_kind="manual", locator="manual/revision-change",
            original_text="Keep meetings in the morning.", kind="preference", text="Keep meetings in the morning.",
            derivation="direct",
        )
        with self.assertRaisesRegex(Exception, "review_refresh_required"):
            service.decide_review_accept(
                self.actions, review.id, partition="production", expected_revisions=review.expected_revisions,
            )
        refreshed = service.decide_review_refresh(
            review.id, partition="production", expected_revisions=review.expected_revisions,
        )
        updated = self.knowledge.get_record(self.record.id, partition="production").record
        self.assertEqual(refreshed.decision, "pending")
        self.assertEqual(refreshed.proposal["expected_updated_at"], updated.updated_at)
        self.assertEqual(self.knowledge.get_review(review.id, partition="production").decision, "stale")
        self.assertEqual(len(self.knowledge.list_records(partition="production")), 1)

    def test_context_read_and_action_routes_use_current_partition_and_action_boundary(self) -> None:
        from core.api.routers.cortex import get_context_record, list_context_records, propose_context_action
        from core.api.models import ContextRetractActionRequest
        from core.knowledge import KnowledgeService

        conversations = _ConversationService()
        with patch("core.api.routers.cortex.get_knowledge_service", return_value=KnowledgeService(self.knowledge)), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=conversations
        ), patch("core.api.routers.cortex.get_action_service", return_value=self.actions):
            records = list_context_records(status_filter=["active"], kind=None, q="morning", limit=100)
            self.assertEqual([record.id for record in records], [str(self.record.id)])
            detail = get_context_record(str(self.record.id))
            self.assertEqual(detail.sources[0].original_text, "Keep meetings in the morning.")
            self.assertEqual(detail.sources[0].origin, "external_tool")
            self.assertEqual(detail.sources[0].derivation, "model_interpretation")
            self.assertEqual(detail.sources[0].occurred_at, "2026-09-09T09:00:00+00:00")
            self.assertEqual(detail.sources[0].captured_at, detail.sources[0].created_at)
            self.assertEqual(detail.history[1].source_id, detail.sources[0].id)
            successor_source = self.knowledge.create_source(
                kind="manual", partition="production", locator="manual/successor", original_text="Meetings start after lunch.",
            )
            successor = self.knowledge.create_record(
                partition="production", kind="preference", text="Meetings start after lunch.", source_ids=[successor_source.id],
                supersedes_record_id=self.record.id,
            )
            successor_detail = get_context_record(str(successor.id))
            self.assertEqual(successor_detail.predecessors, [str(self.record.id)])
            proposed = propose_context_action(ContextRetractActionRequest(operation="retract", record_id=str(successor.id)))
        self.assertEqual(proposed.status, "proposed")
        self.assertEqual(self.knowledge.get_record(successor.id, partition="production").record.status, "active")


if __name__ == "__main__":
    unittest.main()
