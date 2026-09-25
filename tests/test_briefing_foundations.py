"""Production SQLite and coordinator coverage for briefing session foundations."""

from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    BriefingCoverage,
    BriefingDraft,
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingItemDraft,
    BriefingModelConfiguration,
    BriefingSectionDraft,
    render_artifact_text,
)
from core.briefings.service import BriefingGenerationOutput, BriefingService
from core.briefings.store import BriefingSessionStore
from core.conversations.store import ConversationStore
from core.runs.coordinator import CortexRunCoordinator
from core.runs.service import RunService
from core.runs.store import RunStore


class BriefingSessionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "apex_memory.db"
        self.conversations = ConversationStore(self.db_path)
        self.conversations.initialize()
        self.run_store = RunStore(self.db_path)
        self.run_store.initialize()
        self.session_store = BriefingSessionStore(self.db_path)
        self.session_store.initialize()
        self.run_service = RunService(self.run_store)
        self.coordinator = CortexRunCoordinator(self.run_service, max_workers=2)

    def tearDown(self) -> None:
        self.coordinator.close(timeout_seconds=2)
        self.session_store.close()
        self.run_store.close()
        self.conversations.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _request() -> BriefingGenerationRequest:
        return BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="deepseek/deepseek-v4-flash-0731",
            reasoning="high",
        )

    @staticmethod
    def _configuration(
        request: BriefingGenerationRequest,
    ) -> BriefingGenerationConfiguration:
        return BriefingGenerationConfiguration(
            profile=BUILTIN_BRIEFING_PROFILES[request.profile_id],
            model=BriefingModelConfiguration(
                model_id=request.model_id,
                provider="openrouter",
                runtime="cloud",
                reasoning="high",
                max_elapsed_seconds=30,
                max_retries=1,
                max_model_turns=2,
                max_tool_calls=1,
                output_token_limit=512,
            ),
            origin=request.origin,
        )

    @staticmethod
    def _output() -> BriefingGenerationOutput:
        evidence = BriefingEvidence(
            source="calendar",
            source_id="event-1",
            trust="observed",
            content="A planning meeting begins at 10:00.",
        )
        return BriefingGenerationOutput(
            draft=BriefingDraft(
                sections=[
                    BriefingSectionDraft(
                        title="Today",
                        items=[
                            BriefingItemDraft(
                                category="observation",
                                title="Planning meeting",
                                body="The meeting begins at 10:00.",
                                evidence_ids=[evidence.id],
                            )
                        ],
                    )
                ]
            ),
            evidence=[evidence],
            coverage=[
                BriefingCoverage(
                    source="calendar", scope="today", status="complete"
                )
            ],
        )

    def _service(self, executor):
        return BriefingService(
            store=self.session_store,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=self._configuration,
            execute_generation=executor,
        )

    def test_success_persists_artifact_opening_message_and_run_together(self) -> None:
        request = self._request()
        service = self._service(lambda *_args: self._output())

        started = service.start(request)
        self.assertIsNotNone(started.future)
        run = started.future.result(timeout=3)

        self.assertEqual(run.status, "completed")
        saved = self.session_store.get(started.session.id, "production")
        conversation = self.conversations.detail(
            saved.conversation_id, "production"
        )
        agent_message = next(message for message in conversation.messages if message.role == "agent")
        self.assertEqual(saved.run_status, "completed")
        self.assertIsNotNone(saved.artifact)
        self.assertEqual(len(saved.evidence), 1)
        self.assertEqual(agent_message.status, "completed")
        self.assertEqual(agent_message.content, render_artifact_text(saved.artifact))
        self.assertEqual(agent_message.response_metadata["briefing_session_id"], str(saved.id))
        self.assertTrue(run.evidence.answer_persisted)

    def test_generation_failure_keeps_session_without_artifact(self) -> None:
        def fail(*_args):
            raise RuntimeError("provider details must not be persisted")

        started = self._service(fail).start(self._request())
        run = started.future.result(timeout=3)

        saved = self.session_store.get(started.session.id, "production")
        conversation = self.conversations.detail(
            saved.conversation_id, "production"
        )
        agent_message = next(message for message in conversation.messages if message.role == "agent")
        self.assertEqual(run.status, "failed")
        self.assertEqual(saved.run_status, "failed")
        self.assertIsNone(saved.artifact)
        self.assertEqual(saved.evidence, [])
        self.assertEqual(agent_message.status, "failed")
        self.assertNotIn("provider details", str(agent_message.response_metadata))

    def test_cancelled_generation_cannot_publish_artifact(self) -> None:
        started_execution = threading.Event()
        release_execution = threading.Event()

        def wait_then_return(*_args):
            started_execution.set()
            if not release_execution.wait(timeout=3):
                raise TimeoutError("test executor release was not signaled")
            return self._output()

        started = self._service(wait_then_return).start(self._request())
        self.assertTrue(started_execution.wait(timeout=3))
        cancel = self.coordinator.cancel(started.session.run_id)
        self.assertEqual(cancel.status, "cancelling")
        release_execution.set()
        run = started.future.result(timeout=3)

        saved = self.session_store.get(started.session.id, "production")
        self.assertEqual(run.status, "cancelled")
        self.assertIsNone(saved.artifact)
        self.assertEqual(saved.evidence, [])

    def test_snapshot_write_failure_rolls_back_artifact_message_and_run_success(self) -> None:
        original_save = self.session_store.save_completed_snapshot

        def fail_after_snapshot_write(*args, **kwargs):
            original_save(*args, **kwargs)
            raise OSError("simulated disk failure")

        service = self._service(lambda *_args: self._output())
        with patch.object(
            self.session_store,
            "save_completed_snapshot",
            side_effect=fail_after_snapshot_write,
        ):
            started = service.start(self._request())
            run = started.future.result(timeout=3)

        saved = self.session_store.get(started.session.id, "production")
        conversation = self.conversations.detail(
            saved.conversation_id, "production"
        )
        agent_message = next(message for message in conversation.messages if message.role == "agent")
        self.assertEqual(run.status, "failed")
        self.assertEqual(saved.run_status, "failed")
        self.assertIsNone(saved.artifact)
        self.assertEqual(saved.evidence, [])
        self.assertEqual(agent_message.status, "failed")
        self.assertFalse(run.evidence.answer_persisted)

    def test_idempotent_retry_returns_the_same_session(self) -> None:
        request = self._request()
        service = self._service(lambda *_args: self._output())
        first = service.start(request)
        first.future.result(timeout=3)

        retry = service.start(request)

        self.assertTrue(retry.replayed)
        self.assertEqual(retry.session.id, first.session.id)
        self.assertEqual(retry.session.conversation_id, first.session.conversation_id)

    def test_concurrent_same_key_requests_create_one_session(self) -> None:
        request = self._request()
        both_resolving = threading.Barrier(2)

        def resolve(request_value):
            config = self._configuration(request_value)
            both_resolving.wait(timeout=3)
            return config

        service = BriefingService(
            store=self.session_store,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=resolve,
            execute_generation=lambda *_args: self._output(),
        )
        with ThreadPoolExecutor(max_workers=2) as callers:
            results = list(callers.map(lambda _index: service.start(request), range(2)))

        self.assertEqual(results[0].session.id, results[1].session.id)
        self.assertEqual(sum(not result.replayed for result in results), 1)
        futures = [result.future for result in results if result.future is not None]
        self.assertTrue(futures)
        futures[0].result(timeout=3)
        self.assertEqual(len(self.session_store.list("production", limit=100, offset=0)), 1)


if __name__ == "__main__":
    unittest.main()
