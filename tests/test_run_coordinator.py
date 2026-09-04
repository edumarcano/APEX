"""Focused lifecycle coverage for bounded Cortex run coordination."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage
from core.api.routers.cortex import _validate_replayed_turn
from core.connectors.models import utc_now_iso
from core.conversations.models import ConversationTurnRequest
from core.runs.coordinator import (
    ActiveConversationRunError,
    CortexRunCoordinator,
    RunCapacityError,
    RunExecutionControl,
    RunHttpError,
)
from core.runs.models import RunCompletionEvidence, RunLimitSnapshot
from core.runs.service import RunService
from core.runs.store import RunStore
from core.conversations.store import ConversationStore


class _ProductionRunService(RunService):
    @staticmethod
    def partition() -> str:
        return "production"


class RunCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "apex_memory.db"
        self.conversations = ConversationStore(self.db_path)
        self.conversations.initialize()
        self.store = RunStore(self.db_path)
        self.store.initialize()
        self.service = _ProductionRunService(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.conversations.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _limits() -> RunLimitSnapshot:
        return RunLimitSnapshot(
            max_elapsed_seconds=600,
            max_total_tokens=128000,
            max_retries=4,
            max_model_turns=6,
            max_tool_calls=10,
        )

    def _create_run(
        self, *, coordinator: CortexRunCoordinator | None = None
    ) -> tuple[UUID, UUID, UUID, object, object]:
        conversation_id = uuid4()
        user_id = uuid4()
        agent_id = uuid4()
        self.conversations.create(
            conversation_id=conversation_id,
            title="Coordinator test",
            partition="production",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )
        now = utc_now_iso()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO conversation_messages (id, conversation_id, role, content, status, created_at, updated_at) "
                "VALUES (?, ?, 'user', 'Hello', 'completed', ?, ?)",
                (str(user_id), str(conversation_id), now, now),
            )
            conn.execute(
                "INSERT INTO conversation_messages (id, conversation_id, parent_message_id, role, content, status, agent, request_metadata_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 'agent', '', 'pending', 'apex', '{}', ?, ?)",
                (str(agent_id), str(conversation_id), str(user_id), now, now),
            )
        if coordinator is not None:
            coordinator.admit(
                conversation_id=conversation_id,
                agent_message_id=agent_id,
            )
        record, handle, _ = self.service.create_run(
            run_id=uuid4(),
            conversation_id=conversation_id,
            user_message_id=user_id,
            agent_message_id=agent_id,
            requested_model="test-model",
            limit_snapshot=self._limits(),
        )
        return conversation_id, user_id, agent_id, record, handle

    @staticmethod
    def _finalize(_response, message_status: str, _error_code: str | None):
        return SimpleNamespace(status=message_status)

    def test_admission_rejects_capacity_and_same_conversation_before_submission(self) -> None:
        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        conversation_one = uuid4()
        conversation_two = uuid4()
        first_message = uuid4()

        coordinator.admit(conversation_id=conversation_one, agent_message_id=first_message)
        with self.assertRaises(ActiveConversationRunError):
            coordinator.admit(conversation_id=conversation_one, agent_message_id=uuid4())
        with self.assertRaises(RunCapacityError):
            coordinator.admit(conversation_id=conversation_two, agent_message_id=uuid4())

        coordinator.abandon_admission(first_message)
        self.assertIsNone(
            coordinator.admit(conversation_id=conversation_two, agent_message_id=uuid4())
        )

    def test_cancellation_after_start_ends_cancelled_at_next_checkpoint(self) -> None:
        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        conversation_id, _user_id, agent_id, record, handle = self._create_run(
            coordinator=coordinator
        )
        entered_execute = threading.Event()
        continue_execute = threading.Event()

        def execute(control):
            entered_execute.set()
            self.assertTrue(continue_execute.wait(timeout=2))
            control.before_model_turn()
            raise AssertionError("cancelled work reached model execution")

        future = coordinator.submit(
            handle=handle,
            resolved_model="test-model",
            provider="openai",
            runtime="cloud",
            execute=execute,
            finalize_conversation=self._finalize,
        )
        self.assertTrue(entered_execute.wait(timeout=2))
        coordinator.cancel(record.id)
        continue_execute.set()
        completed = future.result(timeout=2)

        self.assertEqual(completed.status, "cancelled")
        self.assertEqual(completed.stop_reason, "operator_cancelled")
        self.assertEqual(self.service.get_run(record.id).status, "cancelled")

    def test_cancellation_before_worker_start_ends_cancelled(self) -> None:
        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        conversation_id, _user_id, agent_id, record, handle = self._create_run(
            coordinator=coordinator
        )
        coordinator.cancel(record.id)

        future = coordinator.submit(
            handle=handle,
            resolved_model="test-model",
            provider="openai",
            runtime="cloud",
            execute=lambda _control: self.fail("cancelled work executed"),
            finalize_conversation=self._finalize,
        )
        completed = future.result(timeout=2)

        self.assertEqual(completed.status, "cancelled")
        self.assertEqual(self.service.get_run(record.id).status, "cancelled")

    def test_http_failure_is_persisted_safely_and_rethrown_to_sync_caller(self) -> None:
        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        conversation_id, _user_id, agent_id, record, handle = self._create_run(
            coordinator=coordinator
        )

        def execute(_control):
            raise RunHttpError(status_code=503, detail="provider unavailable")

        future = coordinator.submit(
            handle=handle,
            resolved_model="test-model",
            provider="openai",
            runtime="cloud",
            execute=execute,
            finalize_conversation=self._finalize,
        )
        with self.assertRaises(RunHttpError) as raised:
            future.result(timeout=2)

        self.assertEqual(raised.exception.status_code, 503)
        failed = self.service.get_run(record.id)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.stop_reason, "provider_error")
        self.assertEqual(failed.error.code, "provider_unavailable")

    def test_progress_preserves_provider_measurements_across_tool_updates(self) -> None:
        _conversation_id, _user_id, _agent_id, _record, handle = self._create_run()
        handle.start(resolved_model="test-model", provider="openai", runtime="cloud")
        control = RunExecutionControl(handle, threading.Event())
        control.after_model_turn(
            ProviderTurnResult(
                message=AgentMessage(role="agent", content="tool call"),
                provider_ms=12.5,
            )
        )
        control.after_tool()

        progress = handle.get_record()
        self.assertEqual(progress.runtime_measurements.eval_duration_ms, 12.5)
        self.assertGreaterEqual(progress.runtime_measurements.total_duration_ms or 0, 0)

    def test_replay_validation_rejects_mismatched_turn_content(self) -> None:
        conversation_id, user_id, agent_id, record, _handle = self._create_run()
        detail = self.conversations.detail(conversation_id, "production")
        payload = ConversationTurnRequest(
            user_message_id=user_id,
            agent_message_id=agent_id,
            prompt="Hello",
            agent="apex",
        )

        _validate_replayed_turn(
            detail,
            payload=payload,
            agent_key="apex",
            request_metadata={},
            run=record,
        )
        changed_payload = payload.model_copy(update={"prompt": "Different request"})
        with self.assertRaisesRegex(RuntimeError, "Message IDs cannot be reused"):
            _validate_replayed_turn(
                detail,
                payload=changed_payload,
                agent_key="apex",
                request_metadata={},
                run=record,
            )
