from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from core.actions import ActionService, ActionStore, ExecutionOutcome
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

    def _propose_reconciliation(
        self, *, link_review: bool = True, include_review_id: bool = True,
        requested_review_id: str | None = None,
    ):
        action_id = str(uuid4())
        proposal = {
            "record_id": str(self.record.id), "expected_updated_at": self.record.updated_at,
        }
        expected = self.knowledge.review_snapshot(
            partition="production", operation="retract", proposal=proposal,
        )
        review = None
        if link_review:
            review = KnowledgeService(self.knowledge).create_action_review(
                partition="production", operation="retract", proposal=proposal, evidence={},
                expected_revisions=expected, reason_codes=("status_change",), action_id=action_id,
            )
        arguments = {**proposal, "operation": "retract", "partition": "production"}
        if include_review_id:
            arguments["review_id"] = requested_review_id or (str(review.id) if review else str(uuid4()))
        return self.actions.propose(
            agent_key="operator", capability_name=CAPABILITY_NAME,
            arguments=arguments, target="Personal Context", risk="destructive",
            summary="Approve personal context retract", actor="operator", action_id=action_id,
        )

    def test_retract_is_proposed_before_it_changes_the_record(self) -> None:
        action = self._propose_reconciliation()
        self.assertEqual(self.knowledge.get_record(self.record.id, partition="production").record.status, "active")
        verified = self.actions.approve_and_execute(action.action_id, actor="operator", expected_version=0)
        self.assertEqual(verified.status, "verified")
        self.assertEqual(self.knowledge.get_record(self.record.id, partition="production").record.status, "retracted")

    def test_linked_review_can_execute_without_embedded_review_id(self) -> None:
        action = self._propose_reconciliation(include_review_id=False)
        outcome = ContextReconciliationExecutor(self.knowledge).execute(action)
        self.assertTrue(outcome.succeeded)
        self.assertEqual(self.knowledge.get_record(self.record.id, partition="production").record.status, "retracted")

    def test_stale_reconciliation_action_fails_without_writing(self) -> None:
        action = self._propose_reconciliation()
        self.knowledge.set_status(self.record.id, partition="production", status="conflicting")
        result = self.actions.approve_and_execute(action.action_id, actor="operator", expected_version=0)
        self.assertEqual(result.status, "execution_failed")
        self.assertEqual(self.knowledge.get_record(self.record.id, partition="production").record.status, "conflicting")

    def test_missing_mismatched_and_superseded_review_links_reject_without_writes(self) -> None:
        for action in (
            self._propose_reconciliation(link_review=False),
            self._propose_reconciliation(requested_review_id=str(uuid4())),
        ):
            with self.subTest(action=action.action_id):
                outcome = ContextReconciliationExecutor(self.knowledge).execute(action)
                self.assertFalse(outcome.succeeded)
                self.assertEqual(
                    self.knowledge.get_record(self.record.id, partition="production").record.status,
                    "active",
                )
                self.assertIsNone(self.knowledge.reconciliation_effect(action.action_id))

        superseded = self._propose_reconciliation()
        review = self.knowledge.review_for_action(superseded.action_id, partition="production")
        assert review is not None
        self.knowledge.link_review_action(review.id, partition="production", action_id=str(uuid4()))
        outcome = ContextReconciliationExecutor(self.knowledge).execute(superseded)
        self.assertFalse(outcome.succeeded)
        self.assertIsNone(self.knowledge.reconciliation_effect(superseded.action_id))
        self.assertEqual(
            self.knowledge.get_record(self.record.id, partition="production").record.status,
            "active",
        )

    def test_historical_reconciliation_verification_uses_effect_without_replay(self) -> None:
        action_id = str(uuid4())
        self.knowledge.reconcile(
            action_id=action_id, operation="retract", partition="production",
            arguments={"record_id": str(self.record.id), "expected_updated_at": self.record.updated_at},
        )

        class _UnknownAttempt:
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, _action):
                self.calls += 1
                return ExecutionOutcome(None, "legacy_reconciliation_outcome_unknown", {})

        executor = _UnknownAttempt()
        self.actions.register_handler(
            CAPABILITY_NAME, executor=executor,
            verifier=ContextReconciliationVerifier(self.knowledge),
        )
        action = self.actions.propose(
            agent_key="apex", capability_name=CAPABILITY_NAME, arguments={},
            target="Personal Context", risk="write", summary="Legacy reconciliation attempt",
            action_id=action_id,
        )
        pending = self.actions.approve_and_execute(
            action.action_id, actor="operator", expected_version=0,
        )
        self.assertEqual(pending.status, "outcome_unknown")
        verified = self.actions.retry_verification(
            action.action_id, actor="operator", expected_version=pending.version,
        )
        self.assertEqual(verified.status, "verified")
        self.assertEqual(executor.calls, 1)

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
