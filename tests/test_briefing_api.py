"""Partition, read, and presentation boundaries for saved briefing sessions."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api.routers import briefings as briefing_routes
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
)
from core.briefings.service import (
    BriefingGenerationOutput,
    BriefingSessionQueries,
    BriefingService,
)
from core.briefings.store import BriefingSessionStore
from core.conversations.store import ConversationStore
from core.runs.coordinator import CortexRunCoordinator
from core.runs.service import RunService
from core.runs.store import RunStore


class BriefingSessionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "apex_memory.db"
        self.conversations = ConversationStore(db_path)
        self.conversations.initialize()
        self.run_store = RunStore(db_path)
        self.run_store.initialize()
        self.session_store = BriefingSessionStore(db_path)
        self.session_store.initialize()
        self.run_service = RunService(self.run_store)
        self.coordinator = CortexRunCoordinator(self.run_service, max_workers=2)
        self.partition = "production"
        self.queries = BriefingSessionQueries(
            self.session_store, lambda: self.partition
        )
        self.query_patch = patch(
            "core.api.routers.briefings.get_briefing_session_queries",
            return_value=self.queries,
        )
        self.query_patch.start()
        app = FastAPI()
        app.include_router(briefing_routes.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.query_patch.stop()
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
                max_model_turns=1,
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
            coverage=[BriefingCoverage(source="calendar", scope="today", status="complete")],
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

    def test_get_and_evidence_reads_do_not_mark_session_presented(self) -> None:
        started = self._service(lambda *_args: self._output()).start(self._request())
        started.future.result(timeout=3)

        listed_response = self.client.get("/api/v1/briefing-sessions")
        before_response = self.client.get(
            f"/api/v1/briefing-sessions/{started.session.id}"
        )
        listed = listed_response.json()
        before = before_response.json()
        evidence_id = before["artifact"]["sections"][0]["items"][0]["evidence_ids"][0]
        evidence_response = self.client.get(
            f"/api/v1/briefing-sessions/{started.session.id}/evidence/{evidence_id}"
        )

        self.assertEqual(listed_response.status_code, 200)
        self.assertEqual(before_response.status_code, 200)
        self.assertEqual(evidence_response.status_code, 200)
        self.assertEqual(len(listed), 1)
        self.assertEqual(evidence_response.json()["id"], evidence_id)
        self.assertIsNone(before["presented_at"])
        self.assertIsNone(
            self.session_store.get(started.session.id, "production").presented_at
        )

        first_ack = self.client.post(
            f"/api/v1/briefing-sessions/{started.session.id}/presented"
        )
        second_ack = self.client.post(
            f"/api/v1/briefing-sessions/{started.session.id}/presented"
        )
        self.assertEqual(first_ack.status_code, 200)
        self.assertEqual(second_ack.status_code, 200)
        self.assertIsNotNone(first_ack.json()["presented_at"])
        self.assertEqual(
            second_ack.json()["presented_at"], first_ack.json()["presented_at"]
        )

    def test_session_and_evidence_reads_are_partition_scoped(self) -> None:
        started = self._service(lambda *_args: self._output()).start(self._request())
        started.future.result(timeout=3)
        detail = self.client.get(f"/api/v1/briefing-sessions/{started.session.id}").json()
        evidence_id = detail["artifact"]["sections"][0]["items"][0]["evidence_ids"][0]
        self.partition = "sandbox"

        self.assertEqual(self.client.get("/api/v1/briefing-sessions").json(), [])
        session_response = self.client.get(
            f"/api/v1/briefing-sessions/{started.session.id}"
        )
        evidence_response = self.client.get(
            f"/api/v1/briefing-sessions/{started.session.id}/evidence/{evidence_id}"
        )
        self.assertEqual(session_response.status_code, 404)
        self.assertEqual(evidence_response.status_code, 404)

    def test_pending_and_failed_sessions_cannot_be_presented_or_read_as_complete(self) -> None:
        executing = threading.Event()
        release = threading.Event()

        def fail_after_release(*_args):
            executing.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test release was not signaled")
            raise RuntimeError("provider failure")

        started = self._service(fail_after_release).start(self._request())
        self.assertTrue(executing.wait(timeout=3))

        pending_response = self.client.post(
            f"/api/v1/briefing-sessions/{started.session.id}/presented"
        )
        evidence_response = self.client.get(
            f"/api/v1/briefing-sessions/{started.session.id}/evidence/{uuid4()}"
        )
        self.assertEqual(pending_response.status_code, 409)
        self.assertEqual(evidence_response.status_code, 409)

        release.set()
        started.future.result(timeout=3)
        failed_response = self.client.post(
            f"/api/v1/briefing-sessions/{started.session.id}/presented"
        )
        self.assertEqual(failed_response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
