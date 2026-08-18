from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from core.actions import ActionService, ActionStore
from core.api.models import ContextCaptureRequest
from core.api.routers.cortex import propose_context_capture
from core.knowledge.capture import CAPABILITY_NAME, ContextCaptureExecutor, ContextCaptureVerifier
from core.knowledge.store import KnowledgeStore
from core.retrieval.store import RetrievalStore


class _ConversationStore:
    def __init__(self, message_id, text: str) -> None:
        self.message_id = message_id
        self.text = text

    def detail(self, _conversation_id, _partition):
        return SimpleNamespace(messages=[SimpleNamespace(
            id=self.message_id, role="user", status="completed", content=self.text,
        )])


class _ConversationService:
    def __init__(self, message_id, text: str) -> None:
        self.store = _ConversationStore(message_id, text)

    def partition(self) -> str:
        return "production"


class ContextCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        path = Path(self.tempdir.name) / "apex.db"
        RetrievalStore(path).initialize()
        self.knowledge = KnowledgeStore(path)
        self.knowledge.initialize()
        self.message_id = uuid4()
        self.conversations = _ConversationService(self.message_id, "Keep the project plan concise.")
        self.actions = ActionService(ActionStore(path))
        self.actions.register_handler(
            CAPABILITY_NAME,
            executor=ContextCaptureExecutor(self.knowledge, self.conversations),
            verifier=ContextCaptureVerifier(self.knowledge),
        )

    def tearDown(self) -> None:
        self.knowledge.close()
        self.tempdir.cleanup()

    def _propose(self, **overrides):
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
        return self.actions.propose(agent_key="panthera", capability_name=CAPABILITY_NAME,
            arguments=arguments, target="Personal Context", risk="write", summary="Approve personal context capture")

    def test_approved_capture_writes_source_record_effect_and_verifies(self) -> None:
        action = self._propose()
        result = self.actions.approve_and_execute(action.action_id, actor="operator", expected_version=0)
        self.assertEqual(result.status, "verified")
        records = self.knowledge.list_records(partition="production")
        self.assertEqual(len(records), 1)
        detail = self.knowledge.get_record(records[0].id, partition="production")
        self.assertEqual(detail.sources[0].original_text, "Keep the project plan concise.")
        self.assertIsNotNone(self.knowledge.capture_effect(action.action_id))

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
        records = self.knowledge.list_records(partition="production", statuses=("conflicting",))
        self.assertEqual(len(records), 2)

    def test_manual_endpoint_proposes_without_writing_and_rejects_secret(self) -> None:
        payload = ContextCaptureRequest(kind="note", text="Remember this for later.")
        with patch("core.api.routers.cortex.get_action_service", return_value=self.actions), patch(
            "core.api.routers.cortex.get_conversation_service", return_value=self.conversations
        ):
            response = propose_context_capture(payload)
        self.assertEqual(response.status, "proposed")
        self.assertEqual(self.knowledge.list_records(partition="production"), [])
        self.assertEqual(
            self.actions.approve_and_execute(response.action_id, actor="operator", expected_version=0).status,
            "verified",
        )
        record = self.knowledge.list_records(partition="production")[0]
        self.assertEqual(
            self.knowledge.get_record(record.id, partition="production").sources[0].kind,
            "manual",
        )
        with self.assertRaises(HTTPException) as rejected:
            propose_context_capture(ContextCaptureRequest(kind="note", text="api_key=very-secret-value"))
        self.assertEqual(rejected.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
