"""Agent briefing history reads completed canonical sessions in one partition."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest import mock

from core.agent.tools import get_briefing_history
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
    BriefingService,
    BriefingSessionQueries,
)
from core.briefings.store import BriefingSessionStore
from core.conversations.store import ConversationStore
from core.runs.coordinator import CortexRunCoordinator
from core.runs.service import RunService
from core.runs.store import RunStore


class AgentBriefingHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="apex_agent_briefing_history_")
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "apex_memory.db"
        self.conversations = ConversationStore(self.db_path)
        self.conversations.initialize()
        self.runs = RunStore(self.db_path)
        self.runs.initialize()
        self.sessions = BriefingSessionStore(self.db_path)
        self.sessions.initialize()
        self.run_service = RunService(self.runs)
        self.coordinator = CortexRunCoordinator(self.run_service, max_workers=2)
        self.addCleanup(self.coordinator.close, timeout_seconds=2)
        self.addCleanup(self.sessions.close)
        self.addCleanup(self.runs.close)
        self.addCleanup(self.conversations.close)
        self.partition = "production"
        self.queries = BriefingSessionQueries(self.sessions, lambda: self.partition)

    def _start(self, title: str, *, fail: bool = False):
        request = BriefingGenerationRequest(
            idempotency_key=uuid4(), profile_id="daily", model_id="test/model"
        )
        configuration = BriefingGenerationConfiguration(
            profile=BUILTIN_BRIEFING_PROFILES[request.profile_id],
            model=BriefingModelConfiguration(
                model_id=request.model_id,
                provider="openrouter",
                runtime="cloud",
                max_elapsed_seconds=30,
                max_retries=0,
                max_model_turns=1,
                max_tool_calls=1,
                output_token_limit=512,
            ),
            origin=request.origin,
        )

        def execute(*_args):
            if fail:
                raise RuntimeError("expected generation failure")
            evidence = BriefingEvidence(
                source="calendar",
                source_id=f"event-{title}",
                trust="observed",
                content=title,
            )
            return BriefingGenerationOutput(
                draft=BriefingDraft(
                    sections=[BriefingSectionDraft(
                        title="Today",
                        items=[
                            BriefingItemDraft(
                                category="observation",
                                title=f"{title} item {index}",
                                body=f"{title} canonical content {index}",
                                evidence_ids=[evidence.id],
                            )
                            for index in range(4)
                        ],
                    )],
                    limitations=[f"Recorded limitation {index} " + "x" * 150 for index in range(8)],
                ),
                evidence=[evidence],
                coverage=[BriefingCoverage(source="calendar", scope="today", status="complete")],
            )

        service = BriefingService(
            store=self.sessions,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: self.partition,
            resolve_configuration=lambda _request: configuration,
            execute_generation=execute,
        )
        started = service.start(request)
        assert started.future is not None
        started.future.result(timeout=5)
        return self.sessions.get(started.session.id, self.partition)

    def test_history_skips_new_failed_runs_filters_partition_and_bounds_content(self) -> None:
        production = [self._start(f"Production {index}") for index in range(6)]
        self.sessions.mark_presented(production[-1].id, "production")
        self._start("Newest failed", fail=True)

        self.partition = "sandbox"
        sandbox = self._start("Sandbox private")

        with mock.patch(
            "core.briefings.service.get_briefing_session_queries",
            return_value=self.queries,
        ):
            self.partition = "production"
            newest = get_briefing_history(limit=1)
            bounded = get_briefing_history(limit=99)
            self.partition = "sandbox"
            sandbox_history = get_briefing_history(limit=5)

        self.assertEqual(len(newest["briefings"]), 1)
        latest = newest["briefings"][0]
        self.assertEqual(latest["id"], str(production[-1].id))
        self.assertEqual(latest["profile"], {"id": "daily", "label": "Daily"})
        self.assertEqual(latest["model_id"], "test/model")
        self.assertEqual(latest["presentation_status"], "presented")
        self.assertIsNotNone(latest["presented_at"])
        self.assertEqual(len(latest["sections"][0]["items"]), 2)
        self.assertEqual(len(latest["limitations"]), 4)
        self.assertNotIn("Newest failed", str(newest))
        self.assertNotIn("Sandbox private", str(newest))

        self.assertEqual(bounded["limit_requested"], 5)
        self.assertEqual(len(bounded["briefings"]), 5)
        self.assertEqual(
            [item["id"] for item in bounded["briefings"]],
            [str(record.id) for record in reversed(production[-5:])],
        )
        self.assertEqual(len(sandbox_history["briefings"]), 1)
        self.assertEqual(sandbox_history["briefings"][0]["id"], str(sandbox.id))
        self.assertIn("Sandbox private", str(sandbox_history))
        self.assertNotIn("Production", str(sandbox_history))


if __name__ == "__main__":
    unittest.main()
