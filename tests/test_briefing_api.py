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
from unittest.mock import patch

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
    BriefingSessionGenerateRequest,
    BriefingItemDraft,
    BriefingModelConfiguration,
    BriefingSectionDraft,
    build_canonical_artifact,
)
from core.briefings.speech import (
    BriefingSpeechHighlight,
    BriefingSpeechScript,
    BriefingSpeechService,
    BriefingSpeechUnavailableError,
    BriefingSpeechValidationError,
    _generate_speech_script,
    canonical_artifact_sha256,
    validate_speech_script,
)
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
        self.speech_service = BriefingSpeechService(
            self.session_store,
            partition_getter=lambda: self.partition,
            voice_settings_reader=lambda: self.voice_settings,
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

    def _completed_demo_session(self):
        request = BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="demo/daily-fixture",
        )
        configuration = BriefingGenerationConfiguration(
            profile=BUILTIN_BRIEFING_PROFILES["daily"],
            model=BriefingModelConfiguration(
                model_id="demo/daily-fixture",
                provider="demo",
                runtime="demo",
                reasoning=None,
                context_window=16_384,
                local_reasoning_mode=None,
                max_elapsed_seconds=30,
                max_retries=0,
                max_model_turns=1,
                max_tool_calls=1,
                output_token_limit=512,
            ),
            origin=request.origin,
            execution_kind="demo",
        )
        started = self._service(
            lambda *_args: self._output(),
            resolver=lambda _request: configuration,
        ).start(request)
        assert started.future is not None
        started.future.result(timeout=3)
        return self.session_store.get(started.session.id, "production")

    @staticmethod
    def _artifact_with_item(category: str, body: str):
        evidence = BriefingEvidence(
            source="calendar",
            source_id="speech-validation-fixture",
            trust={"external_report": "untrusted", "pending_review": "pending"}.get(
                category, "observed"
            ),
            content=body,
        )
        return build_canonical_artifact(
            session_id=uuid4(),
            draft=BriefingDraft(sections=[BriefingSectionDraft(
                title="Today",
                items=[BriefingItemDraft(
                    category=category,
                    title="Calendar detail",
                    body=body,
                    evidence_ids=[evidence.id],
                )],
            )]),
            evidence=[evidence],
            coverage=[BriefingCoverage(source="calendar", scope="today", status="complete")],
            created_at=datetime.now(timezone.utc),
        )

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
                patch("core.agent.catalog.build_concrete_agent", return_value=SimpleNamespace(system_instruction="Daily fixture system instruction."))
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
                "core.agent.catalog.build_concrete_agent",
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
                        "model_id": "deepseek/deepseek-v4-flash-0731",
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
                        "model_id": "deepseek/deepseek-v4-flash-0731",
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
                model_id="deepseek/deepseek-v4-flash-0731",
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

    def test_speech_validator_rejects_changed_dates_and_critical_qualifiers(self) -> None:
        cases = [
            (
                "observation",
                "The review is scheduled for 2026-10-01 at 10:00.",
                "The review is scheduled for 2026-10-02 at 10:00.",
                "script_numeric_fact_mismatch",
            ),
            (
                "observation",
                "The meeting is on Monday, June 8.",
                "The meeting is on Tuesday, June 8.",
                "script_date_word_mismatch",
            ),
            (
                "observation",
                "The meeting starts at 10:00.",
                "The meeting starts at 00:10.",
                "script_numeric_fact_mismatch",
            ),
            (
                "observation",
                "The meeting might move to Tuesday.",
                "The meeting will move to Tuesday.",
                "script_uncertainty_omitted",
            ),
            (
                "external_report",
                "According to an external report, the service reached 5%.",
                "The service reached 5%.",
                "script_report_attribution_omitted",
            ),
            (
                "pending_review",
                "An unreviewed proposal would change the limit to 5%.",
                "A proposal would change the limit to 5%.",
                "script_review_status_omitted",
            ),
            (
                "suggestion",
                "Consider sending the agenda to Alex.",
                "You could consider sending the agenda to Alex. I sent the agenda successfully.",
                "script_suggestion_narrated_as_complete",
            ),
        ]
        for category, source, spoken, expected_error in cases:
            with self.subTest(category=category, expected_error=expected_error):
                artifact = self._artifact_with_item(category, source)
                item = artifact.sections[0].items[0]
                script = BriefingSpeechScript(highlights=[
                    BriefingSpeechHighlight(item_id=item.id, text=spoken)
                ])
                with self.assertRaisesRegex(
                    BriefingSpeechValidationError, expected_error
                ):
                    validate_speech_script(script, artifact)

    def test_speech_generation_uses_selected_provider_with_no_tools(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        item = record.artifact.sections[0].items[0]
        output = json.dumps({
            "highlights": [{
                "item_id": str(item.id),
                "text": "The meeting begins at 10:00.",
            }]
        })

        class FakeProvider:
            captured: dict[str, Any] | None = None

            def generate_turn(self, messages, tools, profile, **kwargs):
                self.captured = {
                    "messages": messages,
                    "tools": tools,
                    "profile": profile,
                    **kwargs,
                }
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content=output)
                )

        provider = FakeProvider()
        catalog_profile = SimpleNamespace(
            provider="openrouter",
            runtime="cloud",
            credential_env=None,
        )
        concrete_profile = SimpleNamespace(
            provider="openrouter",
            system_instruction="Selected catalog profile.",
        )
        with (
            patch(
                "core.briefings.execution.get_visible_model_profile",
                return_value=catalog_profile,
            ),
            patch("core.briefings.execution.model_has_credentials", return_value=True),
            patch(
                "core.briefings.execution.build_concrete_agent",
                return_value=concrete_profile,
            ) as build_agent,
        ):
            parsed = _generate_speech_script(
                record.artifact,
                record.configuration,
                threading.Event(),
                provider_factory=lambda _profile, _key: provider,
            )

        self.assertEqual(parsed.highlights[0].item_id, item.id)
        self.assertIsNotNone(provider.captured)
        call = provider.captured
        assert call is not None
        self.assertEqual(len(call["messages"]), 1)
        self.assertEqual(call["messages"][0].role, "user")
        prompt_data = json.loads(
            call["messages"][0].content.rsplit("Speech input JSON:\n", 1)[1]
        )
        self.assertEqual(
            prompt_data["canonical_artifact_json"],
            record.artifact.model_dump_json(),
        )
        self.assertEqual(call["tools"], [])
        self.assertEqual(call["output_token_limit"], 512)
        self.assertFalse(call["output_schema"].get("$defs"))
        self.assertEqual(set(call["output_schema"]), {"type", "properties", "required"})
        self.assertEqual(call["profile"], concrete_profile)
        self.assertEqual(build_agent.call_args.kwargs["google_search_enabled"], False)
        self.assertEqual(build_agent.call_args.kwargs["google_maps_enabled"], False)

    def test_speech_generation_repairs_invalid_script_once_with_safe_feedback(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        item = record.artifact.sections[0].items[0]
        invalid_output = json.dumps({"highlights": [{
            "item_id": str(uuid4()),
            "text": "The meeting begins at 10:00.",
        }]})
        valid_output = json.dumps({"highlights": [{
            "item_id": str(item.id),
            "text": "The meeting begins at 10:00.",
        }]})

        class SequenceProvider:
            def __init__(self, outputs: list[str]) -> None:
                self.outputs = outputs
                self.calls: list[dict[str, Any]] = []

            def generate_turn(self, messages, tools, profile, **kwargs):
                self.calls.append({
                    "messages": messages,
                    "tools": tools,
                    "profile": profile,
                    **kwargs,
                })
                output = self.outputs[len(self.calls) - 1]
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content=output)
                )

        def generate(provider: SequenceProvider):
            catalog_profile = SimpleNamespace(
                provider="openrouter", runtime="cloud", credential_env=None
            )
            concrete_profile = SimpleNamespace(
                provider="openrouter", system_instruction="Selected catalog profile."
            )
            with (
                patch(
                    "core.briefings.execution.get_visible_model_profile",
                    return_value=catalog_profile,
                ),
                patch("core.briefings.execution.model_has_credentials", return_value=True),
                patch(
                    "core.briefings.execution.build_concrete_agent",
                    return_value=concrete_profile,
                ),
            ):
                result = _generate_speech_script(
                    record.artifact,
                    record.configuration,
                    threading.Event(),
                    provider_factory=lambda _profile, _key: provider,
                )
            return result

        provider = SequenceProvider([invalid_output, valid_output])
        script = generate(provider)
        self.assertEqual(script.highlights[0].item_id, item.id)
        self.assertEqual(len(provider.calls), 2)
        repair_prompt = provider.calls[1]["messages"][0].content
        repair_input = json.loads(repair_prompt.rsplit("Speech input JSON:\n", 1)[1])
        self.assertEqual(repair_input["previous_output"], invalid_output)
        self.assertEqual(
            repair_input["validation_feedback"], "script_item_reference_invalid"
        )

        invalid_provider = SequenceProvider(["not json", "still not json"])
        with self.assertRaises(BriefingSpeechUnavailableError) as failure:
            generate(invalid_provider)
        self.assertEqual(str(failure.exception), "script_invalid")
        self.assertEqual(len(invalid_provider.calls), 2)

    def test_speech_storage_binds_ordered_chunks_to_exact_artifact_and_request(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        digest = canonical_artifact_sha256(record.artifact)
        request_id = uuid4()
        self.session_store.begin_speech_preparation(
            session_id=record.id,
            partition="production",
            artifact_sha256=digest,
            request_id=request_id,
            requested_engine="google",
            voice_gender="female",
        )
        script = BriefingSpeechScript(highlights=[BriefingSpeechHighlight(
            item_id=record.artifact.sections[0].items[0].id,
            text="The meeting begins at 10:00.",
        )])
        chunks = [
            {
                "audio": b"RIFF-first-wav-chunk",
                "content_type": "audio/wav",
                "engine": "kokoro",
                "duration_seconds": 1.25,
            },
            {
                "audio": b"RIFF-second-wav-chunk",
                "content_type": "audio/wav",
                "engine": "kokoro",
                "duration_seconds": 2.0,
            },
        ]
        self.assertTrue(self.session_store.complete_speech_preparation(
            session_id=record.id,
            partition="production",
            request_id=request_id,
            artifact_sha256=digest,
            script_json=script.model_dump_json(),
            engine="kokoro",
            duration_seconds=3.25,
            chunks=chunks,
        ))

        saved = self.session_store.get_speech_audio(record.id, "production")
        assert saved is not None
        self.assertEqual(saved["status"], "ready")
        self.assertEqual(saved["requested_engine"], "google")
        self.assertEqual(saved["engine"], "kokoro")
        self.assertEqual(saved["voice_gender"], "female")
        self.assertEqual(
            [chunk["audio"] for chunk in saved["chunks"]],
            [b"RIFF-first-wav-chunk", b"RIFF-second-wav-chunk"],
        )

        cancelled_request = uuid4()
        self.session_store.begin_speech_preparation(
            session_id=record.id,
            partition="production",
            artifact_sha256=digest,
            request_id=cancelled_request,
            requested_engine="google",
            voice_gender="male",
        )
        self.assertTrue(self.session_store.cancel_speech_preparation(
            session_id=record.id,
            partition="production",
            request_id=cancelled_request,
            artifact_sha256=digest,
        ))
        self.assertFalse(self.session_store.complete_speech_preparation(
            session_id=record.id,
            partition="production",
            request_id=cancelled_request,
            artifact_sha256=digest,
            script_json=script.model_dump_json(),
            engine="kokoro",
            duration_seconds=3.25,
            chunks=chunks,
        ))
        cancelled = self.session_store.get_speech_audio(record.id, "production")
        assert cancelled is not None
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["chunks"], [])

        with self.assertRaises(BriefingSessionNotFoundError):
            self.session_store.begin_speech_preparation(
                session_id=record.id,
                partition="sandbox",
                artifact_sha256=digest,
                request_id=uuid4(),
                requested_engine="google",
                voice_gender="female",
            )

    def test_speech_store_restart_marks_interrupted_without_losing_session(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        digest = canonical_artifact_sha256(record.artifact)
        request_id = uuid4()
        self.session_store.begin_speech_preparation(
            session_id=record.id,
            partition="production",
            artifact_sha256=digest,
            request_id=request_id,
            requested_engine="google",
            voice_gender="female",
        )

        self.session_store.close()
        reopened_store = BriefingSessionStore(
            None,
            connection=self.connection,
            lock=self.db_lock,
        )
        reopened_store.initialize()
        self.session_store = reopened_store
        self.queries = BriefingSessionQueries(
            reopened_store, lambda: self.partition
        )

        restored = reopened_store.get(record.id, "production")
        status = reopened_store.get_speech_status(record.id, "production")
        self.assertEqual(restored.run_status, "completed")
        self.assertEqual(restored.artifact, record.artifact)
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["error_code"], "speech_interrupted")
        with reopened_store._connection() as connection:
            row = connection.execute(
                "SELECT request_id FROM briefing_speech WHERE session_id = ?",
                (str(record.id),),
            ).fetchone()
        self.assertIsNone(row["request_id"])

    def test_deleted_briefing_cascades_cached_audio_and_playback_result_is_safe(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        digest = canonical_artifact_sha256(record.artifact)
        item = record.artifact.sections[0].items[0]
        request_id = uuid4()
        script = BriefingSpeechScript(highlights=[BriefingSpeechHighlight(
            item_id=item.id,
            text="The meeting begins at 10:00.",
        )])
        self.session_store.begin_speech_preparation(
            session_id=record.id,
            partition="production",
            artifact_sha256=digest,
            request_id=request_id,
            requested_engine="pyttsx3",
            voice_gender="female",
        )
        self.assertTrue(self.session_store.complete_speech_preparation(
            session_id=record.id,
            partition="production",
            request_id=request_id,
            artifact_sha256=digest,
            script_json=script.model_dump_json(),
            engine="pyttsx3",
            duration_seconds=1.0,
            chunks=[{
                "audio": b"cached-audio",
                "content_type": "audio/wav",
                "engine": "pyttsx3",
                "duration_seconds": 1.0,
            }],
        ))

        playback_started = threading.Event()
        release_playback = threading.Event()

        def blocked_playback(_chunks, *, playback_id, cancellation_event):
            playback_started.set()
            if not release_playback.wait(timeout=3):
                raise TimeoutError("deleted-session playback release was not signaled")
            return True

        try:
            with patch(
                "core.speaker.try_play_cached_audio",
                side_effect=blocked_playback,
            ):
                response = self.client.post(
                    f"/api/v1/briefing-sessions/{record.id}/speech/play"
                )
                self.assertEqual(response.status_code, 202)
                self.assertTrue(playback_started.wait(timeout=3))
                with self.speech_service._lock:
                    play_job = self.speech_service._active
                assert play_job is not None and play_job.future is not None

                self.conversations.patch(
                    record.conversation_id,
                    "production",
                    {"archived": True},
                )
                self.conversations.delete(record.conversation_id, "production")
                with self.session_store._connection() as connection:
                    speech_rows = connection.execute(
                        "SELECT COUNT(*) FROM briefing_speech WHERE session_id = ?",
                        (str(record.id),),
                    ).fetchone()[0]
                    audio_rows = connection.execute(
                        "SELECT COUNT(*) FROM briefing_speech_audio_chunks WHERE session_id = ?",
                        (str(record.id),),
                    ).fetchone()[0]
                self.assertEqual((speech_rows, audio_rows), (0, 0))

                release_playback.set()
                play_job.future.result(timeout=3)
        finally:
            release_playback.set()

    def test_deleted_briefing_during_preparation_does_not_fail_worker(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        item = record.artifact.sections[0].items[0]
        script = BriefingSpeechScript(highlights=[BriefingSpeechHighlight(
            item_id=item.id,
            text="The meeting begins at 10:00.",
        )])
        generation_started = threading.Event()
        release_generation = threading.Event()

        def blocked_generation(*_args):
            generation_started.set()
            if not release_generation.wait(timeout=3):
                raise TimeoutError("deleted-session preparation release was not signaled")
            return script

        try:
            with (
                patch(
                    "core.briefings.speech._generate_speech_script",
                    side_effect=blocked_generation,
                ),
                patch("core.speaker.synthesize_audio", return_value=([{
                    "audio": b"prepared-audio",
                    "content_type": "audio/wav",
                    "engine": "pyttsx3",
                    "duration_seconds": 1.0,
                }], "pyttsx3")),
            ):
                response = self.client.post(
                    f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
                )
                self.assertEqual(response.status_code, 202)
                self.assertTrue(generation_started.wait(timeout=3))
                with self.speech_service._lock:
                    job = self.speech_service._active
                assert job is not None and job.future is not None

                self.conversations.patch(
                    record.conversation_id,
                    "production",
                    {"archived": True},
                )
                self.conversations.delete(record.conversation_id, "production")
                release_generation.set()
                job.future.result(timeout=3)
        finally:
            release_generation.set()

    def test_speech_http_flow_uses_202_for_work_200_for_ready_and_cached_replay(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        item = record.artifact.sections[0].items[0]
        script = BriefingSpeechScript(highlights=[BriefingSpeechHighlight(
            item_id=item.id,
            text="The meeting begins at 10:00.",
        )])
        synthesis_started = threading.Event()
        release_synthesis = threading.Event()
        synthesis_calls: list[tuple[str, str]] = []
        played: list[list[bytes]] = []

        def synthesize(_text, *, tts_override, voice_gender, cancellation_event):
            synthesis_calls.append((tts_override, voice_gender))
            if len(synthesis_calls) == 1:
                synthesis_started.set()
                if not release_synthesis.wait(timeout=3):
                    raise TimeoutError("speech synthesis release was not signaled")
            content_type = "audio/wav" if tts_override == "pyttsx3" else "audio/mpeg"
            return ([
                {
                    "audio": b"first-cached-chunk",
                    "content_type": content_type,
                    "engine": tts_override,
                    "duration_seconds": 1.0,
                },
                {
                    "audio": b"second-cached-chunk",
                    "content_type": content_type,
                    "engine": tts_override,
                    "duration_seconds": 2.0,
                },
            ], tts_override)

        with (
            patch(
                "core.briefings.speech._generate_speech_script",
                return_value=script,
            ),
            patch("core.speaker.synthesize_audio", side_effect=synthesize) as synth_mock,
        ):
            prepare = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
            )
            self.assertEqual(prepare.status_code, 202)
            self.assertTrue(synthesis_started.wait(timeout=3))
            self.assertEqual(prepare.json()["status"], "preparing")
            self.assertEqual(
                self.client.get(f"/api/v1/briefing-sessions/{record.id}").json()["speech_status"],
                "preparing",
            )
            release_synthesis.set()
            with self.speech_service._lock:
                job = self.speech_service._active
            assert job is not None and job.future is not None
            job.future.result(timeout=3)

            ready = self.client.get(f"/api/v1/briefing-sessions/{record.id}/speech")
            self.assertEqual(ready.status_code, 200)
            ready_json = ready.json()
            self.assertEqual(ready_json["status"], "ready")
            self.assertEqual(ready_json["voice_gender"], "female")
            self.assertEqual(
                ready_json["artifact_sha256"],
                canonical_artifact_sha256(record.artifact),
            )
            self.assertNotIn("chunks", ready_json)
            self.assertNotIn("audio", ready_json)

            already_ready = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
            )
            self.assertEqual(already_ready.status_code, 200)

            self.voice_settings = ("manual", "google", "male")
            with patch(
                "core.speaker.try_play_cached_audio",
                side_effect=lambda chunks, **_kwargs: played.append(
                    [chunk["audio"] for chunk in chunks]
                ) or True,
            ) as play_mock:
                play = self.client.post(
                    f"/api/v1/briefing-sessions/{record.id}/speech/play"
                )
                self.assertEqual(play.status_code, 202)
                with self.speech_service._lock:
                    play_job = self.speech_service._active
                if play_job is not None and play_job.future is not None:
                    play_job.future.result(timeout=3)

            self.assertEqual(
                played,
                [[b"first-cached-chunk", b"second-cached-chunk"]],
            )
            play_mock.assert_called_once()
            synth_mock.assert_called_once()

            changed_voice = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
            )
            self.assertIn(changed_voice.status_code, {200, 202})
            with self.speech_service._lock:
                changed_job = self.speech_service._active
            if changed_job is not None and changed_job.future is not None:
                changed_job.future.result(timeout=3)

        self.assertEqual(synthesis_calls, [("pyttsx3", "female"), ("google", "male")])
        self.assertEqual(synth_mock.call_count, 2)
        new_saved = self.session_store.get_speech_audio(record.id, "production")
        assert new_saved is not None
        self.assertEqual(new_saved["requested_engine"], "google")
        self.assertEqual(new_saved["voice_gender"], "male")

    def test_speech_prepare_persists_unavailable_after_two_invalid_model_outputs(self) -> None:
        record = self._completed_session()
        first_call_started = threading.Event()
        release_first_call = threading.Event()
        provider_calls = 0

        class InvalidProvider:
            def generate_turn(self, _messages, _tools, _profile, **_kwargs):
                nonlocal provider_calls
                provider_calls += 1
                if provider_calls == 1:
                    first_call_started.set()
                    if not release_first_call.wait(timeout=3):
                        raise TimeoutError("invalid-output test release was not signaled")
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="not valid JSON")
                )

        provider = InvalidProvider()
        catalog_profile = SimpleNamespace(
            provider="openrouter", runtime="cloud", credential_env=None
        )
        concrete_profile = SimpleNamespace(
            provider="openrouter", system_instruction="Selected catalog profile."
        )

        def generate_with_fake_provider(artifact, configuration, cancellation_event):
            return _generate_speech_script(
                artifact,
                configuration,
                cancellation_event,
                provider_factory=lambda _profile, _key: provider,
            )

        with (
            patch(
                "core.briefings.execution.get_visible_model_profile",
                return_value=catalog_profile,
            ),
            patch("core.briefings.execution.model_has_credentials", return_value=True),
            patch(
                "core.briefings.execution.build_concrete_agent",
                return_value=concrete_profile,
            ),
            patch(
                "core.briefings.speech._generate_speech_script",
                side_effect=generate_with_fake_provider,
            ),
            patch("core.speaker.synthesize_audio") as synthesize,
        ):
            response = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
            )
            self.assertEqual(response.status_code, 202)
            self.assertTrue(first_call_started.wait(timeout=3))
            with self.speech_service._lock:
                job = self.speech_service._active
            assert job is not None and job.future is not None
            release_first_call.set()
            job.future.result(timeout=3)

        status = self.client.get(
            f"/api/v1/briefing-sessions/{record.id}/speech"
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "unavailable")
        self.assertEqual(status.json()["error_code"], "script_invalid")
        self.assertEqual(provider_calls, 2)
        synthesize.assert_not_called()

    def test_forced_speech_prepare_rebuilds_only_the_cached_derivative(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        item = record.artifact.sections[0].items[0]
        script = BriefingSpeechScript(highlights=[BriefingSpeechHighlight(
            item_id=item.id,
            text="The meeting begins at 10:00.",
        )])
        synthesis_started = threading.Event()
        release_synthesis = threading.Event()
        synthesized: list[bytes] = []

        def synthesize(_text, *, tts_override, voice_gender, cancellation_event):
            audio = f"prepared-{len(synthesized) + 1}".encode()
            synthesized.append(audio)
            synthesis_started.set()
            if not release_synthesis.wait(timeout=3):
                raise TimeoutError("forced preparation release was not signaled")
            return ([{
                "audio": audio,
                "content_type": "audio/wav",
                "engine": tts_override,
                "duration_seconds": 1.0,
            }], tts_override)

        with (
            patch("core.briefings.speech._generate_speech_script", return_value=script),
            patch("core.speaker.synthesize_audio", side_effect=synthesize),
        ):
            initial = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
            )
            self.assertEqual(initial.status_code, 202)
            self.assertTrue(synthesis_started.wait(timeout=3))
            with self.speech_service._lock:
                first_job = self.speech_service._active
            assert first_job is not None and first_job.future is not None
            release_synthesis.set()
            first_job.future.result(timeout=3)

            cached = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
            )
            self.assertEqual(cached.status_code, 200)
            self.assertEqual(len(synthesized), 1)

            synthesis_started.clear()
            release_synthesis.clear()
            forced = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/prepare?force=true"
            )
            self.assertEqual(forced.status_code, 202)
            self.assertTrue(synthesis_started.wait(timeout=3))
            with self.speech_service._lock:
                forced_job = self.speech_service._active
            assert forced_job is not None and forced_job.future is not None
            release_synthesis.set()
            forced_job.future.result(timeout=3)

        self.assertEqual(len(synthesized), 2)
        saved = self.session_store.get_speech_audio(record.id, "production")
        assert saved is not None
        self.assertEqual(saved["chunks"][0]["audio"], b"prepared-2")
        restored = self.session_store.get(record.id, "production")
        self.assertEqual(restored.artifact, record.artifact)
        self.assertEqual(
            self.client.get(f"/api/v1/briefing-sessions/{record.id}/speech").json()["status"],
            "ready",
        )

    def test_demo_speech_uses_deterministic_fixture_and_demo_tts_for_cached_replay(self) -> None:
        record = self._completed_demo_session()
        assert record.artifact is not None
        fixture_item = record.artifact.sections[0].items[0]
        demo_voice_settings = SimpleNamespace(
            voice=SimpleNamespace(mode="manual", engine="google", gender="female")
        )
        service = BriefingSpeechService(
            self.session_store,
            partition_getter=lambda: self.partition,
        )
        synthesized: list[tuple[str, str, str]] = []
        played: list[list[bytes]] = []
        synthesis_started = threading.Event()
        release_synthesis = threading.Event()
        playback_started = threading.Event()
        release_playback = threading.Event()

        def synthesize(text, *, tts_override, voice_gender, cancellation_event):
            synthesized.append((text, tts_override, voice_gender))
            synthesis_started.set()
            if not release_synthesis.wait(timeout=3):
                raise TimeoutError("demo synthesis release was not signaled")
            return ([{
                "audio": b"demo-cached-wav",
                "content_type": "audio/wav",
                "engine": tts_override,
                "duration_seconds": 1.5,
            }], tts_override)

        try:
            with (
                patch("core.briefings.speech.DEMO_MODE", True),
                patch("core.briefings.speech.DEMO_TTS", "kokoro"),
                patch(
                    "core.briefings.speech.get_settings_store",
                    return_value=SimpleNamespace(
                        get_snapshot=lambda: demo_voice_settings
                    ),
                ),
                patch(
                    "core.api.routers.briefings.get_briefing_speech_service",
                    return_value=service,
                ),
                patch(
                    "core.briefings.speech._generate_speech_script",
                    side_effect=AssertionError("demo speech must not call a model"),
                ) as model_call,
                patch("core.speaker.synthesize_audio", side_effect=synthesize),
            ):
                prepare = self.client.post(
                    f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
                )
                self.assertEqual(prepare.status_code, 202)
                self.assertTrue(synthesis_started.wait(timeout=3))
                with service._lock:
                    prepare_job = service._active
                assert prepare_job is not None and prepare_job.future is not None
                release_synthesis.set()
                prepare_job.future.result(timeout=3)

                ready = self.client.get(
                    f"/api/v1/briefing-sessions/{record.id}/speech"
                )
                self.assertEqual(ready.status_code, 200)
                self.assertEqual(ready.json()["status"], "ready")
                self.assertEqual(ready.json()["engine"], "kokoro")
                self.assertEqual(ready.json()["voice_gender"], "female")
                saved = self.session_store.get_speech_audio(record.id, "production")
                assert saved is not None
                script = BriefingSpeechScript.model_validate_json(saved["script_json"])
                self.assertEqual([highlight.item_id for highlight in script.highlights], [fixture_item.id])
                self.assertIn(fixture_item.title, script.render())
                self.assertIn(fixture_item.body, script.render())

                replay = self.client.post(
                    f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
                )
                self.assertEqual(replay.status_code, 200)

                def play_cached(chunks, **_kwargs):
                    playback_started.set()
                    if not release_playback.wait(timeout=3):
                        raise TimeoutError("demo playback release was not signaled")
                    played.append([chunk["audio"] for chunk in chunks])
                    return True

                with patch(
                    "core.speaker.try_play_cached_audio",
                    side_effect=play_cached,
                ):
                    play = self.client.post(
                        f"/api/v1/briefing-sessions/{record.id}/speech/play"
                    )
                    self.assertEqual(play.status_code, 202)
                    self.assertTrue(playback_started.wait(timeout=3))
                    with service._lock:
                        play_job = service._active
                    assert play_job is not None and play_job.future is not None
                    release_playback.set()
                    play_job.future.result(timeout=3)

            model_call.assert_not_called()
            self.assertEqual(synthesized, [(script.render(), "kokoro", "female")])
            self.assertEqual(played, [[b"demo-cached-wav"]])
            persisted = self.session_store.get_speech_audio(record.id, "production")
            assert persisted is not None
            self.assertEqual(persisted["status"], "ready")
            self.assertEqual(persisted["engine"], "kokoro")
        finally:
            release_synthesis.set()
            release_playback.set()
            service.close(timeout_seconds=2)

    def test_speech_stop_cancels_only_its_playback_and_shutdown_drains_worker(self) -> None:
        record = self._completed_session()
        assert record.artifact is not None
        item = record.artifact.sections[0].items[0]
        script = BriefingSpeechScript(highlights=[BriefingSpeechHighlight(
            item_id=item.id,
            text="The meeting begins at 10:00.",
        )])
        with (
            patch("core.briefings.speech._generate_speech_script", return_value=script),
            patch("core.speaker.synthesize_audio", return_value=([{
                "audio": b"cached-wav",
                "content_type": "audio/wav",
                "engine": "pyttsx3",
                "duration_seconds": 1.0,
            }], "pyttsx3")),
        ):
            self.client.post(f"/api/v1/briefing-sessions/{record.id}/speech/prepare")
            with self.speech_service._lock:
                prepare_job = self.speech_service._active
            if prepare_job is not None and prepare_job.future is not None:
                prepare_job.future.result(timeout=3)

        playing = threading.Event()
        stop_id: list[str] = []

        def wait_for_cancel(_chunks, *, playback_id, cancellation_event):
            playing.set()
            cancellation_event.wait(timeout=3)
            return not cancellation_event.is_set()

        with (
            patch("core.speaker.try_play_cached_audio", side_effect=wait_for_cancel),
            patch(
                "core.speaker.cancel_cached_audio",
                side_effect=lambda playback_id: stop_id.append(playback_id) or True,
            ),
            patch("core.speaker.cancel") as global_cancel,
        ):
            response = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/play"
            )
            self.assertEqual(response.status_code, 202)
            self.assertTrue(playing.wait(timeout=3))
            with self.speech_service._lock:
                play_job = self.speech_service._active
            assert play_job is not None and play_job.future is not None
            stopped = self.client.post(
                f"/api/v1/briefing-sessions/{record.id}/speech/stop"
            )
            self.assertEqual(stopped.status_code, 200)
            play_job.future.result(timeout=3)
            self.assertEqual(stop_id, [str(play_job.id)])
            global_cancel.assert_not_called()

        block_generation = threading.Event()
        release_generation = threading.Event()

        def ignore_cancel_until_released(*_args, **_kwargs):
            block_generation.set()
            if not release_generation.wait(timeout=3):
                raise TimeoutError("speech shutdown release was not signaled")
            return script

        with patch(
            "core.briefings.speech._generate_speech_script",
            side_effect=ignore_cancel_until_released,
        ), patch("core.speaker.synthesize_audio") as synth_mock:
            self.voice_settings = ("manual", "google", "male")
            self.client.post(f"/api/v1/briefing-sessions/{record.id}/speech/prepare")
            self.assertTrue(block_generation.wait(timeout=3))
            with self.speech_service._lock:
                shutdown_job = self.speech_service._active
            assert shutdown_job is not None and shutdown_job.future is not None
            self.assertFalse(self.speech_service.close(timeout_seconds=0))
            release_generation.set()
            shutdown_job.future.result(timeout=3)
            self.assertTrue(self.speech_service.close(timeout_seconds=1))
            synth_mock.assert_not_called()

    def test_speech_prepare_and_play_respect_voice_off_and_partition(self) -> None:
        record = self._completed_session()
        self.voice_settings = ("off", "pyttsx3", "female")
        prepare = self.client.post(
            f"/api/v1/briefing-sessions/{record.id}/speech/prepare"
        )
        play = self.client.post(f"/api/v1/briefing-sessions/{record.id}/speech/play")
        self.assertEqual(prepare.status_code, 403)
        self.assertEqual(play.status_code, 403)

        self.voice_settings = ("manual", "pyttsx3", "female")
        self.partition = "sandbox"
        missing = self.client.get(f"/api/v1/briefing-sessions/{record.id}/speech")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
