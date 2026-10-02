"""Partition, read, and presentation boundaries for saved briefing sessions."""

from __future__ import annotations

import json
import sqlite3
import threading
import unittest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from core.api.routers import briefings as briefing_routes
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage
from core.briefings.daily import generate_briefing_generation
from core.briefings.execution import InvalidBriefingModelOutputError
from core.briefings.models import (
    AVAILABLE_BRIEFING_PROFILES,
    BUILTIN_BRIEFING_PROFILES,
    BriefingCoverage,
    BriefingDraft,
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingItemDraft,
    BriefingModelConfiguration,
    BriefingSectionDraft,
    BriefingSessionGenerateRequest,
    build_canonical_artifact,
)
from core.briefings.speech import BriefingSpeechService
from core.briefings.service import (
    BriefingGenerationOutput,
    BriefingSessionQueries,
    BriefingService,
)
from core.briefings.store import BriefingSessionNotFoundError, BriefingSessionStore
from core.conversations.store import ConversationStore
from core.runs.coordinator import CortexRunCoordinator
from core.runs.service import RunService
from core.runs.store import RunStore


class BriefingSessionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.db_lock = threading.RLock()
        self.conversations = ConversationStore(
            None, connection=self.connection, lock=self.db_lock
        )
        self.conversations.initialize()
        self.run_store = RunStore(None, connection=self.connection, lock=self.db_lock)
        self.run_store.initialize()
        self.session_store = BriefingSessionStore(
            None, connection=self.connection, lock=self.db_lock
        )
        self.session_store.initialize()
        self.run_service = RunService(self.run_store)
        self.coordinator = CortexRunCoordinator(self.run_service, max_workers=2)
        self.partition = "production"
        self.queries = BriefingSessionQueries(
            self.session_store, lambda: self.partition
        )
        self.voice_settings = ("manual", "pyttsx3", "female")
        self.user_designation = ""
        self.speech_service = BriefingSpeechService(
            self.session_store,
            partition_getter=lambda: self.partition,
            voice_settings_reader=lambda: self.voice_settings,
            user_designation_reader=lambda: self.user_designation,
        )
        self.speech_patch = patch(
            "core.api.routers.briefings.get_briefing_speech_service",
            return_value=self.speech_service,
        )
        self.speech_patch.start()
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
        self.speech_patch.stop()
        self.speech_service.close(timeout_seconds=2)
        self.coordinator.close(timeout_seconds=2)
        self.session_store.close()
        self.run_store.close()
        self.conversations.close()
        self.connection.close()

    @staticmethod
    def _request() -> BriefingGenerationRequest:
        return BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="z-ai/glm-5.3-flash",
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

    def _service(self, executor, resolver=None):
        return BriefingService(
            store=self.session_store,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=resolver or self._configuration,
            execute_generation=executor,
        )

    def _completed_session(self):
        started = self._service(lambda *_args: self._output()).start(self._request())
        assert started.future is not None
        started.future.result(timeout=3)
        return self.session_store.get(started.session.id, "production")

    @contextmanager
    def _patched_daily_generation(
        self, model_call, *, evidence_content="Private evidence fixture."
    ):
        evidence = BriefingEvidence(
            source="reminders",
            source_id="fixture-private-reminder",
            trust="observed",
            content=evidence_content,
        )
        coverage = [
            BriefingCoverage(source="reminders", scope="current reminders", status="complete")
        ]
        profile = SimpleNamespace(maximum_context_window=16_384)
        with ExitStack() as stack:
            stack.enter_context(
                patch("core.briefings.daily._collect_snapshot", return_value=(None, None))
            )
            stack.enter_context(
                patch("core.briefings.daily._telemetry_inputs", return_value=(coverage, [evidence]))
            )
            stack.enter_context(
                patch("core.briefings.daily._personal_inputs", return_value=([], []))
            )
            stack.enter_context(
                patch("core.briefings.daily.get_settings_store", return_value=SimpleNamespace(get_snapshot=lambda: object()))
            )
            stack.enter_context(
                patch("core.briefings.daily.ContextPolicy.from_settings", return_value=SimpleNamespace(permits_retrieval=False))
            )
            stack.enter_context(patch("core.briefings.daily.is_dev_mode", return_value=False))
            stack.enter_context(
                patch("core.briefings.daily.get_visible_model_profile", return_value=profile)
            )
            stack.enter_context(
                patch("core.agent.catalog.build_provider_profile", return_value=SimpleNamespace(system_instruction="Daily fixture system instruction."))
            )
            stack.enter_context(
                patch("core.briefings.daily.execute_single_call", side_effect=model_call)
            )
            yield evidence

    def test_incompatible_context_is_rejected_before_session_admission(self) -> None:
        from types import SimpleNamespace

        from core.briefings.runtime import resolve_briefing_configuration

        profile = SimpleNamespace(
            model_id="test/daily-small-context",
            provider="openrouter",
            runtime="cloud",
            credential_env="OPENROUTER_API_KEY",
            reasoning_options=("high",),
            default_reasoning="high",
            maximum_context_window=4096,
        )
        settings = SimpleNamespace(
            ask_apex=SimpleNamespace(enabled=True),
        )
        service = self._service(
            lambda *_args: self._output(), resolver=resolve_briefing_configuration
        )

        with (
            patch("core.briefings.runtime.DEMO_MODE", False),
            patch("core.briefings.runtime.is_dev_mode", return_value=False),
            patch("core.briefings.runtime.visible_cloud_models", return_value=[profile]),
            patch("core.briefings.runtime.visible_local_models", return_value=[]),
            patch("core.briefings.runtime.model_has_credentials", return_value=True),
            patch(
                "core.briefings.runtime.get_settings_store",
                return_value=SimpleNamespace(get_snapshot=lambda: settings),
            ),
            patch("core.briefings.daily.get_visible_model_profile", return_value=profile),
            patch(
                "core.agent.catalog.build_provider_profile",
                return_value=SimpleNamespace(system_instruction="x" * 1408),
            ),
            patch(
                "core.api.routers.briefings.get_briefing_service",
                return_value=service,
            ),
        ):
            response = self.client.post(
                "/api/v1/briefing-sessions",
                json={
                    "idempotency_key": str(uuid4()),
                    "profile_id": "daily",
                    "model_id": profile.model_id,
                    "reasoning": "high",
                    "context_window": 4096,
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("context window is too small", response.json()["detail"])
        self.assertEqual(self.session_store.list("production", limit=10, offset=0), [])
        self.assertEqual(self.run_store.list_runs("production", limit=10), [])

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

    def test_saved_session_list_excludes_archived_conversations_before_pagination(self) -> None:
        oldest = self._completed_session()
        middle = self._completed_session()
        newest = self._completed_session()
        self.conversations.patch(
            newest.conversation_id, "production", {"archived": True}
        )

        first_page = self.client.get("/api/v1/briefing-sessions?limit=1")
        second_page = self.client.get("/api/v1/briefing-sessions?limit=1&offset=1")
        archived_detail = self.client.get(
            f"/api/v1/briefing-sessions/{newest.id}"
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual([row["id"] for row in first_page.json()], [str(middle.id)])
        self.assertEqual([row["id"] for row in second_page.json()], [str(oldest.id)])
        self.assertEqual(archived_detail.status_code, 200)
        self.assertIn(
            newest.id,
            [record.id for record in self.queries.completed_history(limit=5)],
        )

        self.conversations.patch(
            newest.conversation_id, "production", {"archived": False}
        )
        restored_page = self.client.get("/api/v1/briefing-sessions?limit=1")
        self.assertEqual([row["id"] for row in restored_page.json()], [str(newest.id)])

    def test_profile_catalog_lists_builtins_with_availability(self) -> None:
        response = self.client.get("/api/v1/briefing-profiles")

        self.assertEqual(response.status_code, 200)
        catalog = response.json()
        self.assertEqual([entry["id"] for entry in catalog], list(BUILTIN_BRIEFING_PROFILES))
        for entry in catalog:
            profile = BUILTIN_BRIEFING_PROFILES[entry["id"]]
            self.assertEqual(entry["label"], profile.label)
            self.assertEqual(entry["investigation_required"], profile.investigation_required)
            available = entry["id"] in AVAILABLE_BRIEFING_PROFILES
            self.assertEqual(entry["available"], available)
            if available:
                self.assertIsNone(entry["unavailable_reason"])
            else:
                self.assertTrue(entry["unavailable_reason"])
        self.assertTrue(next(e for e in catalog if e["id"] == "daily")["available"])

    def test_profile_catalog_marks_deep_unavailable_in_demo_mode(self) -> None:
        with patch("core.api.routers.briefings.DEMO_MODE", True):
            response = self.client.get("/api/v1/briefing-profiles")

        self.assertEqual(response.status_code, 200)
        deep = next(entry for entry in response.json() if entry["id"] == "deep")
        self.assertFalse(deep["available"])
        self.assertIn("unavailable in demo mode", deep["unavailable_reason"])

    def test_generation_and_catalog_share_profile_availability(self) -> None:
        unavailable = sorted(set(BUILTIN_BRIEFING_PROFILES) - AVAILABLE_BRIEFING_PROFILES)
        service = self._service(lambda *_args: self._output())
        with patch("core.api.routers.briefings.get_briefing_service", return_value=service):
            for profile_id in unavailable:
                response = self.client.post(
                    "/api/v1/briefing-sessions",
                    json={
                        "idempotency_key": str(uuid4()),
                        "profile_id": profile_id,
                        "model_id": "z-ai/glm-5.3-flash",
                    },
                )
                self.assertEqual(response.status_code, 422, profile_id)

            with patch("core.briefings.models.AVAILABLE_BRIEFING_PROFILES", frozenset()):
                catalog = self.client.get("/api/v1/briefing-profiles").json()
                response = self.client.post(
                    "/api/v1/briefing-sessions",
                    json={
                        "idempotency_key": str(uuid4()),
                        "profile_id": "daily",
                        "model_id": "z-ai/glm-5.3-flash",
                    },
                )

        self.assertFalse(any(entry["available"] for entry in catalog))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/v1/briefing-sessions").json(), [])

    def test_daily_generation_route_returns_saved_session_and_replays_idempotently(self) -> None:
        executing = threading.Event()
        release = threading.Event()

        def wait_for_release(*_args):
            executing.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test release was not signaled")
            return self._output()

        service = self._service(wait_for_release)
        with patch(
            "core.api.routers.briefings.get_briefing_service",
            return_value=service,
        ):
            body = BriefingSessionGenerateRequest(
                idempotency_key=uuid4(),
                profile_id="daily",
                model_id="z-ai/glm-5.3-flash",
                reasoning="high",
            )
            first = self.client.post(
                "/api/v1/briefing-sessions", json=body.model_dump(mode="json")
            )
            self.assertEqual(first.status_code, 202)
            self.assertTrue(executing.wait(timeout=3))
            summary = first.json()
            self.assertEqual(summary["profile_id"], "daily")
            self.assertIn(summary["run_status"], {"queued", "running"})
            self.assertTrue(summary["conversation_id"])
            self.assertTrue(summary["run_id"])

            future = self.coordinator.future_for(UUID(summary["run_id"]))
            self.assertIsNotNone(future)
            release.set()
            assert future is not None
            future.result(timeout=3)

            replay = self.client.post(
                "/api/v1/briefing-sessions", json=body.model_dump(mode="json")
            )

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["id"], summary["id"])
        self.assertEqual(replay.json()["conversation_id"], summary["conversation_id"])

    def test_invalid_daily_draft_can_be_repaired_and_saved(self) -> None:
        calls: list[str] = []
        output_schemas: list[dict[str, Any]] = []

        def model_call(**kwargs):
            prompt = kwargs["prompt"]
            calls.append(prompt)
            output_schemas.append(kwargs["output_schema"])
            if len(calls) == 1:
                return ProviderTurnResult(
                    message=AgentMessage(
                        role="agent", content='{"sections":[],"limitations":[]}'
                    )
                )
            evidence_block = prompt.split("\nEvidence:\n", 1)[1].split(
                "\n\nRepair the previous model response.", 1
            )[0]
            evidence_id = json.loads(evidence_block)[0]["id"]
            output = {
                "sections": [{
                    "title": "Today",
                    "items": [{
                        "category": "observation",
                        "title": "Reminder",
                        "body": "Review the current reminder.",
                        "evidence_ids": [evidence_id],
                    }],
                }],
                "limitations": [],
            }
            return ProviderTurnResult(
                message=AgentMessage(role="agent", content=json.dumps(output))
            )

        service = self._service(generate_briefing_generation)
        with self._patched_daily_generation(model_call) as evidence:
            started = service.start(self._request())
            assert started.future is not None
            run = started.future.result(timeout=3)
            detail_response = self.client.get(
                f"/api/v1/briefing-sessions/{started.session.id}"
            )

        self.assertEqual(run.status, "completed")
        self.assertIsNone(run.error)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(output_schemas), 2)
        for output_schema in output_schemas:
            item_properties = output_schema["$defs"]["BriefingItemDraft"]["properties"]
            self.assertNotIn("record_references", item_properties)
            self.assertNotIn("ExistingRecordReference", output_schema["$defs"])
        self.assertIn("Safe validation feedback", calls[1])
        self.assertIn("empty result with usable evidence", calls[1])
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()
        self.assertEqual(detail["run_status"], "completed")
        self.assertIsNone(detail["run_error_code"])
        self.assertEqual(
            detail["artifact"]["sections"][0]["items"][0]["evidence_ids"],
            [str(evidence.id)],
        )

    def test_persistent_invalid_daily_output_has_safe_error_and_is_not_logged(self) -> None:
        model_response = "PRIVATE_MODEL_RESPONSE_SENTINEL"
        evidence_content = "PRIVATE_EVIDENCE_SENTINEL"

        def model_call(**_kwargs):
            return ProviderTurnResult(
                message=AgentMessage(
                    role="agent",
                    content=json.dumps({"unexpected": model_response}),
                )
            )

        service = self._service(generate_briefing_generation)
        with self.assertLogs("core.briefings.daily", level="WARNING") as captured:
            with self._patched_daily_generation(
                model_call, evidence_content=evidence_content
            ) as evidence:
                started = service.start(self._request())
                assert started.future is not None
                run = started.future.result(timeout=3)
                detail_response = self.client.get(
                    f"/api/v1/briefing-sessions/{started.session.id}"
                )

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.stop_reason, "provider_error")
        self.assertEqual(run.error.code if run.error else None, "invalid_model_output")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["run_error_code"], "invalid_model_output")
        log_text = "\n".join(captured.output)
        self.assertIn("Briefing synthesis output remained invalid after one repair attempt", log_text)
        self.assertIn(f"run_id={run.id}", log_text)
        self.assertIn("stage=draft_validation", log_text)
        self.assertIn("first_failure=draft_schema_invalid", log_text)
        self.assertIn("repair_failure=draft_schema_invalid", log_text)
        self.assertNotIn(model_response, log_text)
        self.assertNotIn(evidence_content, log_text)
        self.assertNotIn(model_response, "\n".join(self.connection.iterdump()))
        self.assertNotIn(evidence_content, "\n".join(self.connection.iterdump()))

    def test_unknown_evidence_reference_is_reported_without_logging_model_content(self) -> None:
        unknown_evidence_id = uuid4()
        model_content = "PRIVATE_UNKNOWN_REFERENCE_MODEL_CONTENT"
        evidence_content = "PRIVATE_UNKNOWN_REFERENCE_EVIDENCE_CONTENT"

        def model_call(**_kwargs):
            return ProviderTurnResult(
                message=AgentMessage(
                    role="agent",
                    content=json.dumps({
                        "sections": [{
                            "title": "Today",
                            "items": [{
                                "category": "observation",
                                "title": "Private item",
                                "body": model_content,
                                "evidence_ids": [str(unknown_evidence_id)],
                            }],
                        }],
                        "limitations": [],
                    }),
                )
            )

        service = self._service(generate_briefing_generation)
        with self.assertLogs("core.briefings.daily", level="WARNING") as captured:
            with self._patched_daily_generation(
                model_call, evidence_content=evidence_content
            ):
                started = service.start(self._request())
                assert started.future is not None
                run = started.future.result(timeout=3)

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error.code if run.error else None, "invalid_model_output")
        log_text = "\n".join(captured.output)
        self.assertIn("first_failure=unknown_evidence_ids", log_text)
        self.assertIn("repair_failure=unknown_evidence_ids", log_text)
        self.assertNotIn(model_content, log_text)
        self.assertNotIn(str(unknown_evidence_id), log_text)
        self.assertNotIn(evidence_content, log_text)

    def test_persistent_provider_output_error_is_classified_at_safe_stage(self) -> None:
        def reject_provider_output(**_kwargs):
            raise InvalidBriefingModelOutputError("empty")

        service = self._service(generate_briefing_generation)
        with self.assertLogs("core.briefings.daily", level="WARNING") as captured:
            with self._patched_daily_generation(reject_provider_output):
                started = service.start(self._request())
                assert started.future is not None
                run = started.future.result(timeout=3)

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error.code if run.error else None, "invalid_model_output")
        log_text = "\n".join(captured.output)
        self.assertIn(f"run_id={run.id}", log_text)
        self.assertIn("stage=provider_output", log_text)
        self.assertNotIn("No response content", log_text)

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
