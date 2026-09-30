from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from core.actions import ActionService, ActionStore, ExecutionOutcome
from core.api.models import ActionMutationRequest, ContextCaptureRequest, ContextReviewDecisionRequest
from core.api.routers.cortex import accept_context_review, propose_context_capture, refresh_context_review, reject_context_review
from core.knowledge.capture import CAPABILITY_NAME, ContextCaptureExecutor, ContextCaptureVerifier
from core.knowledge.store import KnowledgeConflictError, KnowledgeStore
from core.knowledge import KnowledgeService
from core.retrieval.store import RetrievalStore


class _ConversationStore:
    def __init__(self, message_id, text: str, created_at: str = "2026-09-09T12:00:00+00:00") -> None:
        self.message_id = message_id
        self.text = text
        self.created_at = created_at

    def detail(self, _conversation_id, _partition):
        return SimpleNamespace(messages=[SimpleNamespace(
            id=self.message_id, role="user", status="completed", content=self.text, created_at=self.created_at,
        )])


class _ConversationService:
    def __init__(self, message_id, text: str) -> None:
        self.store = _ConversationStore(message_id, text)

    def partition(self) -> str:
        return "production"


class _UnknownOnceCaptureExecutor:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def execute(self, action):
        self.calls += 1
        if self.calls == 1:
            return ExecutionOutcome(None, "capture_transport_unknown", {})
        return self.delegate.execute(action)


class ContextCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "apex.db"
        RetrievalStore(self.path).initialize()
        self.knowledge = KnowledgeStore(self.path)
        self.knowledge.initialize()
        self.message_id = uuid4()
        self.conversations = _ConversationService(self.message_id, "Keep the project plan concise.")
        self.actions = ActionService(ActionStore(self.path))
        self.actions.register_handler(
            CAPABILITY_NAME,
            executor=ContextCaptureExecutor(self.knowledge),
            verifier=ContextCaptureVerifier(self.knowledge),
        )

    def tearDown(self) -> None:
        self.knowledge.close()
        self.tempdir.cleanup()

    def _propose(
        self, *, link_review: bool = True, include_review_id: bool = True,
        requested_review_id: str | None = None, **overrides,
    ):
        arguments = {
            "kind": "preference", "text": "Keep the project plan concise.",
            "subject": None, "predicate": None, "object_entity": None, "object_value": None,
            "effective_at": None,
            "_apex_provenance": {
                "source_kind": "conversation_message", "conversation_id": str(uuid4()),
                "message_id": str(self.message_id), "partition": "production",
            },
        }
        arguments.update(overrides)
        action_id = str(uuid4())
        provenance = dict(arguments.pop("_apex_provenance"))
        payload = {key: value for key, value in arguments.items() if key != "review_id"}
        partition = str(provenance["partition"])
        locator = f"conversation/{provenance['conversation_id']}/message/{provenance['message_id']}"
        original_text = self.conversations.store.text
        occurred_at = self.conversations.store.created_at
        decision = self.knowledge.capture_decision(partition=partition, **payload)
        review = None
        if link_review:
            review = KnowledgeService(self.knowledge).create_action_review(
                partition=partition, operation="capture", proposal=payload,
                evidence={
                    "source_kind": "conversation_message", "locator": locator,
                    "original_text": original_text, "source_origin": "operator_input",
                    "derivation": "model_interpretation", "occurred_at": occurred_at,
                },
                expected_revisions=decision["expected_revisions"],
                reason_codes=("approval_requested", *decision["reason_codes"]), action_id=action_id,
            )
        action_arguments = {
            **payload, "_apex_provenance": {
                "source_kind": "conversation_message", "partition": partition,
                "original_text": original_text, "occurred_at": occurred_at,
            },
        }
        if include_review_id:
            action_arguments["review_id"] = requested_review_id or (str(review.id) if review else str(uuid4()))
        return self.actions.propose(
            agent_key="apex", capability_name=CAPABILITY_NAME,
            arguments=action_arguments, target="Personal Context", risk="write",
            summary="Approve personal context capture", action_id=action_id,
        )

    def test_approved_capture_writes_source_record_effect_and_verifies(self) -> None:
        action = self._propose()
        result = self.actions.approve_and_execute(action.action_id, actor="operator", expected_version=0)
        self.assertEqual(result.status, "verified")
        records = self.knowledge.list_records(partition="production")
        self.assertEqual(len(records), 1)
        detail = self.knowledge.get_record(records[0].id, partition="production")
        self.assertEqual(detail.sources[0].original_text, "Keep the project plan concise.")
        self.assertEqual(detail.source_links[0].source.occurred_at, "2026-09-09T12:00:00+00:00")
        self.assertEqual(detail.source_links[0].derivation, "model_interpretation")
        self.assertIsNotNone(self.knowledge.capture_effect(action.action_id))

    def test_linked_review_can_execute_without_embedded_review_id(self) -> None:
        action = self._propose(include_review_id=False)
        result = ContextCaptureExecutor(self.knowledge).execute(action)
        self.assertTrue(result.succeeded)
        self.assertEqual(len(self.knowledge.list_records(partition="production")), 1)

    def test_missing_mismatched_and_superseded_review_links_reject_without_writes(self) -> None:
        cases = (
            self._propose(link_review=False),
            self._propose(requested_review_id=str(uuid4())),
        )
        for action in cases:
            with self.subTest(action=action.action_id):
                outcome = ContextCaptureExecutor(self.knowledge).execute(action)
                self.assertFalse(outcome.succeeded)
                self.assertEqual(outcome.evidence["category"], "ContextCaptureError")
                self.assertEqual(self.knowledge.list_records(partition="production"), [])
                self.assertIsNone(self.knowledge.capture_effect(action.action_id))

        superseded = self._propose()
        review = self.knowledge.review_for_action(superseded.action_id, partition="production")
        assert review is not None
        self.knowledge.link_review_action(review.id, partition="production", action_id=str(uuid4()))
        outcome = ContextCaptureExecutor(self.knowledge).execute(superseded)
        self.assertFalse(outcome.succeeded)
        self.assertIsNone(self.knowledge.capture_effect(superseded.action_id))
        self.assertEqual(self.knowledge.list_records(partition="production"), [])

    def test_duplicate_confirms_existing_record_and_new_evidence(self) -> None:
        first = self._propose()
        self.actions.approve_and_execute(first.action_id, actor="operator", expected_version=0)
        self.conversations.store.text = "Please remember the same preference."
        second = self._propose()
        self.actions.approve_and_execute(second.action_id, actor="operator", expected_version=0)
        self.assertEqual(len(self.knowledge.list_records(partition="production")), 1)
        self.assertEqual(self.knowledge.capture_effect(second.action_id)[2], "confirmed")

    def test_structured_difference_creates_conflict(self) -> None:
        first = self._propose(kind="fact", text="Project status is active.", subject="Project", predicate="status", object_value="active")
        self.assertEqual(self.actions.approve_and_execute(first.action_id, actor="operator", expected_version=0).status, "verified")
        second = self._propose(kind="fact", text="Project status is paused.", subject="Project", predicate="status", object_value="paused")
        self.assertEqual(self.actions.approve_and_execute(second.action_id, actor="operator", expected_version=0).status, "verified")
        records = self.knowledge.list_records(
            partition="production", statuses=("active", "conflicting", "superseded"),
        )
        self.assertEqual(len(records), 2)
        first_record = next(record for record in records if record.text == "Project status is active.")
        second_record = next(record for record in records if record.text == "Project status is paused.")
        self.assertEqual(first_record.status, "superseded")
        self.assertEqual(second_record.status, "active")
        self.assertEqual(self.knowledge.capture_effect(second.action_id)[2], "conflicting")

    def test_historical_capture_verification_uses_effect_without_replaying_executor(self) -> None:
        action_id = str(uuid4())
        self.knowledge.apply_capture(
            action_id=action_id, partition="production", source_kind="manual",
            locator=f"manual/{action_id}", original_text="Historical context evidence.",
            kind="note", text="Historical context evidence.", derivation="direct",
        )

        class _UnknownAttempt:
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, _action):
                self.calls += 1
                return ExecutionOutcome(None, "legacy_capture_outcome_unknown", {})

        executor = _UnknownAttempt()
        self.actions.register_handler(
            CAPABILITY_NAME, executor=executor, verifier=ContextCaptureVerifier(self.knowledge),
        )
        action = self.actions.propose(
            agent_key="apex", capability_name=CAPABILITY_NAME, arguments={},
            target="Personal Context", risk="write", summary="Legacy capture attempt", action_id=action_id,
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

    def test_manual_endpoint_proposes_without_writing_and_rejects_secret(self) -> None:
        payload = ContextCaptureRequest(kind="note", text="Remember this for later.")
        with patch("core.api.routers.cortex.get_action_service", return_value=self.actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=KnowledgeService(self.knowledge)
        ):
            response = propose_context_capture(payload)
        self.assertEqual(response.status, "proposed")
        self.assertEqual(self.knowledge.list_records(partition="production"), [])
        self.assertEqual(
            self.actions.approve_and_execute(response.action_id, actor="operator", expected_version=0).status,
            "verified",
        )
        record = self.knowledge.list_records(partition="production")[0]
        source_link = self.knowledge.get_record(record.id, partition="production").source_links[0]
        self.assertEqual(source_link.source.kind, "manual")
        self.assertEqual(source_link.derivation, "direct")
        with self.assertRaises(HTTPException) as rejected:
            propose_context_capture(ContextCaptureRequest(kind="note", text="api_key=very-secret-value"))
        self.assertEqual(rejected.exception.status_code, 422)

    def test_review_routes_accept_once_and_replay_the_decision(self) -> None:
        knowledge_service = KnowledgeService(self.knowledge)
        with patch("core.api.routers.cortex.get_action_service", return_value=self.actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=knowledge_service):
            proposal = propose_context_capture(ContextCaptureRequest(kind="note", text="Route lifecycle evidence."))
            review = self.knowledge.review_for_action(proposal.action_id, partition="production")
            assert review is not None
            payload = ContextReviewDecisionRequest(expected_revisions=review.expected_revisions)
            accepted = accept_context_review(review.id, payload)
            replay = accept_context_review(review.id, payload)
        self.assertEqual((accepted.decision, replay.decision), ("accepted", "accepted"))
        self.assertEqual(len(self.knowledge.list_records(partition="production")), 1)

    def test_review_accept_after_linked_action_expiry_replaces_and_verifies(self) -> None:
        now = [datetime(2026, 9, 10, tzinfo=UTC)]
        actions = ActionService(ActionStore(self.path), clock=lambda: now[0])
        actions.register_handler(
            CAPABILITY_NAME,
            executor=ContextCaptureExecutor(self.knowledge),
            verifier=ContextCaptureVerifier(self.knowledge),
        )
        knowledge_service = KnowledgeService(self.knowledge)
        with patch("core.api.routers.cortex.get_action_service", return_value=actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=knowledge_service):
            proposal = propose_context_capture(ContextCaptureRequest(kind="note", text="Expired review evidence."))
            review = self.knowledge.review_for_action(proposal.action_id, partition="production")
            assert review is not None
            now[0] += timedelta(hours=25)
            accepted = accept_context_review(
                review.id, ContextReviewDecisionRequest(expected_revisions=review.expected_revisions),
            )
        self.assertEqual(accepted.decision, "accepted")
        self.assertEqual(actions.get(proposal.action_id).status, "expired")
        self.assertNotEqual(accepted.action_id, proposal.action_id)
        self.assertEqual(actions.get(accepted.action_id).status, "verified")

    def test_generic_approve_after_expiry_uses_review_replacement_lifecycle(self) -> None:
        now = [datetime(2026, 9, 10, tzinfo=UTC)]
        actions = ActionService(ActionStore(self.path), clock=lambda: now[0])
        actions.register_handler(
            CAPABILITY_NAME,
            executor=ContextCaptureExecutor(self.knowledge),
            verifier=ContextCaptureVerifier(self.knowledge),
        )
        knowledge_service = KnowledgeService(self.knowledge)
        with patch("core.api.routers.cortex.get_action_service", return_value=actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=knowledge_service):
            proposal = propose_context_capture(ContextCaptureRequest(kind="note", text="Generic expiry evidence."))
        now[0] += timedelta(hours=25)
        from core.api.routers.actions import approve_action

        with patch("core.api.routers.actions.get_action_service", return_value=actions), patch(
            "core.knowledge.get_knowledge_service", return_value=knowledge_service,
        ):
            response = approve_action(proposal.action_id, ActionMutationRequest(expected_version=0))
        self.assertEqual(actions.get(proposal.action_id).status, "expired")
        self.assertNotEqual(response.action_id, proposal.action_id)
        self.assertEqual(response.status, "verified")

    def test_unknown_attempt_is_verified_before_review_replacement_executes(self) -> None:
        actions = ActionService(ActionStore(self.path))
        executor = _UnknownOnceCaptureExecutor(ContextCaptureExecutor(self.knowledge))
        actions.register_handler(
            CAPABILITY_NAME, executor=executor, verifier=ContextCaptureVerifier(self.knowledge),
        )
        knowledge_service = KnowledgeService(self.knowledge)
        with patch("core.api.routers.cortex.get_action_service", return_value=actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=knowledge_service):
            proposal = propose_context_capture(ContextCaptureRequest(kind="note", text="Verify before retry."))
            review = self.knowledge.review_for_action(proposal.action_id, partition="production")
            assert review is not None
            with self.assertRaisesRegex(KnowledgeConflictError, "review_verification_required"):
                knowledge_service.decide_review_accept(
                    actions, review.id, partition="production", expected_revisions=review.expected_revisions,
                )
            accepted = knowledge_service.decide_review_accept(
                actions, review.id, partition="production", expected_revisions=review.expected_revisions,
            )
        self.assertEqual(accepted.decision, "accepted")
        self.assertEqual(executor.calls, 2)
        self.assertEqual(actions.get(proposal.action_id).status, "verification_failed")
        self.assertEqual(actions.events(proposal.action_id)[-1].result_code, "context_capture_missing")

    def test_stale_review_route_refreshes_the_current_snapshot(self) -> None:
        knowledge_service = KnowledgeService(self.knowledge)
        payload = ContextCaptureRequest(
            kind="fact", text="Project status is paused.", subject="Project", predicate="status", object_value="paused",
        )
        with patch("core.api.routers.cortex.get_action_service", return_value=self.actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=knowledge_service):
            proposal = propose_context_capture(payload)
            review = self.knowledge.review_for_action(proposal.action_id, partition="production")
            assert review is not None
            self.knowledge.apply_capture(
                action_id="refresh-peer", partition="production", source_kind="manual", locator="manual/refresh-peer",
                original_text="Project status is active.", kind="fact", text="Project status is active.",
                subject="Project", predicate="status", object_value="active", derivation="direct",
            )
            decision = ContextReviewDecisionRequest(expected_revisions=review.expected_revisions)
            with self.assertRaises(HTTPException) as stale:
                accept_context_review(review.id, decision)
            self.assertEqual(stale.exception.status_code, 409)
            refreshed = refresh_context_review(review.id, decision)
        self.assertEqual(refreshed.decision, "pending")
        self.assertNotEqual(refreshed.id, str(review.id))
        self.assertEqual(self.knowledge.get_review(review.id, partition="production").decision, "stale")

    def test_review_route_rejects_the_linked_action(self) -> None:
        knowledge_service = KnowledgeService(self.knowledge)
        with patch("core.api.routers.cortex.get_action_service", return_value=self.actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=knowledge_service):
            proposal = propose_context_capture(ContextCaptureRequest(kind="note", text="Reject route evidence."))
            review = self.knowledge.review_for_action(proposal.action_id, partition="production")
            assert review is not None
            rejected = reject_context_review(
                review.id, ContextReviewDecisionRequest(expected_revisions=review.expected_revisions),
            )
        self.assertEqual(rejected.decision, "rejected")
        self.assertEqual(self.actions.get(proposal.action_id).status, "rejected")

    def test_generic_reject_resolves_a_capture_review_with_frozen_mapping(self) -> None:
        knowledge_service = KnowledgeService(self.knowledge)
        with patch("core.api.routers.cortex.get_action_service", return_value=self.actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ), patch("core.api.routers.cortex.get_knowledge_service", return_value=knowledge_service):
            proposal = propose_context_capture(ContextCaptureRequest(kind="note", text="Generic reject evidence."))
        from core.api.routers.actions import reject_action

        with patch("core.api.routers.actions.get_action_service", return_value=self.actions), patch(
            "core.knowledge.get_knowledge_service", return_value=knowledge_service,
        ):
            rejected = reject_action(proposal.action_id, ActionMutationRequest(expected_version=0))
        self.assertEqual(rejected.status, "rejected")
        review = self.knowledge.review_for_action(proposal.action_id, partition="production")
        assert review is not None
        self.assertEqual(review.decision, "rejected")


if __name__ == "__main__":
    unittest.main()
