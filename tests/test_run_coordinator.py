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

from unittest.mock import MagicMock, patch

from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage
from core.api.routers.cortex import (
    _resolved_turn_metadata,
    _submit_run,
    _validate_replayed_turn,
)
from core.connectors.models import utc_now_iso
from core.conversations.models import ConversationCreateRequest, ConversationTurnRequest
from core.conversations.service import ConversationService, set_conversation_service
from core.runs.coordinator import (
    ActiveConversationRunError,
    CortexRunCoordinator,
    RunCapacityError,
    RunExecutionControl,
    RunHttpError,
    set_run_coordinator,
)
from core.runs.models import RunCompletionEvidence, RunLimitSnapshot
from core.runs.service import RunService, set_run_service
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
        events, _gap, terminal = coordinator.events.get(record.id).replay(0)
        self.assertTrue(terminal)
        self.assertEqual(events[-2].type, "response.reset")
        self.assertEqual(events[-1].type, "run.completed")

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

    def test_terminal_run_retains_replayable_lifecycle_events(self) -> None:
        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        _conversation_id, _user_id, _agent_id, record, handle = self._create_run(
            coordinator=coordinator
        )
        response = SimpleNamespace(error=None, tool_trace=[], tool_outputs=[])

        completed = coordinator.submit(
            handle=handle,
            resolved_model="test-model",
            provider="openai",
            runtime="cloud",
            execute=lambda control: (control.finish(), response)[1],
            finalize_conversation=self._finalize,
        ).result(timeout=2)

        buffer = coordinator.events.get(record.id)
        self.assertIsNotNone(buffer)
        events, gap, terminal = buffer.replay(0)
        self.assertFalse(gap)
        self.assertTrue(terminal)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(events[-1].type, "run.completed")
        self.assertIn("run.snapshot", [event.type for event in events])

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

    def test_admitted_run_records_and_emits_queue_duration(self) -> None:
        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        _conv_id, _user_id, _agent_id, record, handle = self._create_run(
            coordinator=coordinator
        )
        response = SimpleNamespace(error=None, tool_trace=[], tool_outputs=[])
        completed = coordinator.submit(
            handle=handle,
            resolved_model="test-model",
            provider="openai",
            runtime="cloud",
            execute=lambda control: (control.finish(), response)[1],
            finalize_conversation=self._finalize,
        ).result(timeout=2)

        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(completed.runtime_measurements.queue_duration_ms)
        self.assertGreaterEqual(completed.runtime_measurements.queue_duration_ms, 0.0)

        events, _gap, _terminal = coordinator.events.get(record.id).replay(0)
        runtime_events = [e for e in events if e.type == "runtime.updated"]
        self.assertTrue(len(runtime_events) > 0)
        self.assertIn("queue_duration_ms", runtime_events[0].payload["runtime_measurements"])

    @patch("core.api.routers.cortex.is_dev_mode", return_value=True)
    def test_resolved_turn_metadata_sets_effective_context_window(self, _dev_mode) -> None:
        local_payload = ConversationTurnRequest(
            user_message_id=uuid4(),
            agent_message_id=uuid4(),
            prompt="Hello",
            model_id="qwen3:1.7b",
            context_window=16384,
        )
        metadata = _resolved_turn_metadata(local_payload)
        self.assertEqual(metadata["effective_context_window"], 16384)

        default_local = ConversationTurnRequest(
            user_message_id=uuid4(),
            agent_message_id=uuid4(),
            prompt="Hello",
            model_id="qwen3:1.7b",
        )
        metadata_default = _resolved_turn_metadata(default_local)
        self.assertIsInstance(metadata_default["effective_context_window"], int)
        self.assertGreater(metadata_default["effective_context_window"], 0)

        cloud_payload = ConversationTurnRequest(
            user_message_id=uuid4(),
            agent_message_id=uuid4(),
            prompt="Hello",
            model_id="deepseek/deepseek-v4-flash-0731",
        )
        metadata_cloud = _resolved_turn_metadata(cloud_payload)
        self.assertEqual(metadata_cloud["effective_context_window"], 1_310_720)

    @patch("core.api.routers.cortex.get_knowledge_service")
    @patch("core.api.routers.cortex.get_retrieval_service")
    @patch("core.api.routers.cortex.is_dev_mode", return_value=True)
    @patch("core.api.routers.cortex.query_agent")
    @patch("core.api.routers.cortex.ContextAssembler")
    def test_submit_run_uses_effective_context_window_for_limit_snapshot(
        self, mock_assembler, mock_query, _dev_mode, _mock_retrieval, _mock_knowledge
    ) -> None:
        mock_assembler.return_value.assemble.return_value = MagicMock()
        mock_query.return_value = SimpleNamespace(
            answer="Done",
            error=None,
            tool_trace=[],
            tool_outputs=[],
            measurements={},
        )
        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        set_run_coordinator(coordinator)
        self.addCleanup(set_run_coordinator, None)
        set_run_service(self.service)
        self.addCleanup(set_run_service, None)

        conv_service = ConversationService(self.conversations, history_limit=20)
        set_conversation_service(conv_service)
        self.addCleanup(set_conversation_service, None)

        conv = conv_service.create(
            ConversationCreateRequest(title="Context limit test", origin="hud", agent="apex")
        )
        payload = ConversationTurnRequest(
            user_message_id=uuid4(),
            agent_message_id=uuid4(),
            prompt="Hello",
            agent="apex",
            model_id="qwen3:1.7b",
            context_window=16384,
        )

        record, future = _submit_run(conv.id, payload)
        self.assertIsNotNone(record)
        self.assertEqual(record.limit_snapshot.max_total_tokens, 16384)
        if future is not None:
            future.result(timeout=2)

    def test_after_model_turn_derives_universal_throughput_and_eval_timings(self) -> None:
        from core.agent.types import TokenUsage

        coordinator = CortexRunCoordinator(self.service, max_workers=1)
        self.addCleanup(coordinator.close)
        _conv_id, _user_id, _agent_id, _record, handle = self._create_run(coordinator=coordinator)
        handle.start(resolved_model="deepseek/deepseek-v4-flash-0731", provider="openrouter", runtime="cloud")
        control = RunExecutionControl(handle, threading.Event())

        result = ProviderTurnResult(
            message=AgentMessage(role="agent", content="Hello world"),
            resolved_model="deepseek/deepseek-v4-flash-0731",
            usage=TokenUsage(input_tokens=50, output_tokens=100, total_tokens=150),
            provider_ms=1200.0,
            runtime_measurements={"ttft_ms": 200.0},
        )

        control.after_model_turn(result)

        self.assertAlmostEqual(control.runtime_measurements.ttft_ms, 200.0)
        self.assertEqual(control.runtime_measurements.eval_count, 100)
        self.assertEqual(control.runtime_measurements.prompt_eval_count, 50)
        self.assertAlmostEqual(control.runtime_measurements.eval_duration_ms, 1000.0)
        self.assertAlmostEqual(control.runtime_measurements.tokens_per_second, 100.0)
