"""Daily source-selection, masking, and production synthesis coverage."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from core.activity.models import ActivityReport, ActivityReportContent
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage
from core.briefings.daily import (
    _build_prompt,
    _fit_evidence_to_context,
    generate_daily_briefing,
)
from core.briefings.daily_inputs import (
    _external_inputs,
    _evidence,
    _personal_inputs,
    _telemetry_inputs,
)
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
    ExistingRecordReference,
    build_canonical_artifact,
    render_artifact_text,
)
from core.telemetry.models import TelemetryModuleEntry, TelemetrySnapshot


class _Control:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, str]]] = []
        self.handle = SimpleNamespace(
            get_record=lambda: SimpleNamespace(partition="production")
        )

    def check_cancelled(self) -> None:
        return None

    def publish_activity(self, event: str, payload: dict[str, str]) -> None:
        self.events.append((event, payload))


def _model_configuration() -> BriefingGenerationConfiguration:
    return BriefingGenerationConfiguration(
        profile=BUILTIN_BRIEFING_PROFILES["daily"],
        model=BriefingModelConfiguration(
            model_id="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
            reasoning="high",
            context_window=16_384,
            max_elapsed_seconds=30,
            max_retries=1,
            max_model_turns=1,
            max_tool_calls=1,
            output_token_limit=512,
        ),
        origin="hud",
    )


class DailyInputTests(unittest.TestCase):
    def test_malformed_cached_source_count_does_not_abort_daily_inputs(self) -> None:
        snapshot = TelemetrySnapshot(modules={
            "email": TelemetryModuleEntry(
                name="email", status="healthy", freshness="live",
                data={"count": "not-a-number", "emails": [{"id": "mail-1", "subject": "Update"}]},
            ),
        })

        coverage, evidence = _telemetry_inputs(snapshot, None, False)

        self.assertEqual(next(item for item in coverage if item.source == "email").status, "complete")
        self.assertEqual(len([item for item in evidence if item.source == "email"]), 1)

    def test_recurring_calendar_instances_without_original_start_keep_distinct_ids(self) -> None:
        snapshot = TelemetrySnapshot(modules={
            "calendar": TelemetryModuleEntry(
                name="calendar", status="healthy", freshness="live",
                data={"events": [
                    {"calendar_id": "primary", "recurring_event_id": "series-1", "event_id": "instance-1", "summary": "First", "start": "2026-09-25T09:00:00Z"},
                    {"calendar_id": "primary", "recurring_event_id": "series-1", "event_id": "instance-2", "summary": "Second", "start": "2026-09-26T09:00:00Z"},
                ]},
            ),
        })

        _, evidence = _telemetry_inputs(snapshot, None, False)
        calendar_ids = [item.source_id for item in evidence if item.source == "calendar"]
        self.assertEqual(len(calendar_ids), 2)
        self.assertEqual(len(set(calendar_ids)), 2)

    def test_long_composite_source_ids_remain_unique_after_bounding(self) -> None:
        first = "calendar:" + "x" * 510 + "A"
        second = "calendar:" + "x" * 510 + "B"

        first_evidence = _evidence(
            source="calendar",
            source_id=first,
            identity_kind="provider",
            content="Meeting",
        )
        second_evidence = _evidence(
            source="calendar",
            source_id=second,
            identity_kind="provider",
            content="Meeting",
        )

        self.assertEqual(len(first_evidence.source_id), 512)
        self.assertEqual(len(second_evidence.source_id), 512)
        self.assertNotEqual(first_evidence.source_id, second_evidence.source_id)
        self.assertEqual(first_evidence.identity_kind, "provider")
        self.assertEqual(second_evidence.identity_kind, "provider")

    def test_telemetry_normalization_marks_capped_reminders_and_calendar_partial(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        snapshot = TelemetrySnapshot(
            modules={
                "reminders": TelemetryModuleEntry(
                    name="reminders",
                    status="healthy",
                    freshness="live",
                    observed_at=now,
                    data={
                        "count": 9,
                        "records": [
                            {"id": f"reminder-{index}", "note": f"Task {index}"}
                            for index in range(9)
                        ],
                    },
                ),
                "calendar": TelemetryModuleEntry(
                    name="calendar",
                    status="healthy",
                    freshness="live",
                    observed_at=now,
                    data={
                        "total_count": 13,
                        "events": [
                            {"event_id": f"event-{index}", "summary": f"Event {index}", "start": now}
                            for index in range(13)
                        ],
                    },
                ),
            }
        )

        coverage, evidence = _telemetry_inputs(snapshot, None, dev_mode=False)
        coverage_by_source = {item.source: item for item in coverage}

        self.assertEqual(sum(item.source == "reminders" for item in evidence), 8)
        self.assertEqual(sum(item.source == "calendar" for item in evidence), 12)
        for source in ("reminders", "calendar"):
            self.assertEqual(coverage_by_source[source].status, "partial")
            self.assertTrue(coverage_by_source[source].truncated)
            self.assertEqual(coverage_by_source[source].reason, "source_limit_reached")

    def test_pending_review_and_action_caps_mark_coverage_partial(self) -> None:
        now = datetime.now(timezone.utc)
        reviews = [
            SimpleNamespace(
                id=uuid4(),
                created_at=now.isoformat(),
                operation="create",
                evidence={"original_text": f"Review source {index}"},
                proposal={"text": f"Review proposal {index}"},
            )
            for index in range(6)
        ]
        actions = [
            SimpleNamespace(
                action_id=f"action-{index}",
                updated_at=now,
                proposal=SimpleNamespace(summary=f"Verified outcome {index}"),
            )
            for index in range(20)
        ]
        knowledge = SimpleNamespace(
            list_reviews=lambda **_kwargs: reviews,
        )
        assembler = SimpleNamespace(personal_candidates=lambda **_kwargs: [])
        action_service = SimpleNamespace(list=lambda **_kwargs: actions)
        activity_service = SimpleNamespace(list=lambda **_kwargs: [])

        with (
            patch("core.briefings.daily_inputs.get_knowledge_service", return_value=knowledge),
            patch("core.briefings.daily_inputs.get_retrieval_service", return_value=object()),
            patch("core.briefings.daily_inputs.ContextAssembler", return_value=assembler),
            patch("core.briefings.daily_inputs.get_action_service", return_value=action_service),
            patch("core.briefings.daily_inputs.get_activity_service", return_value=activity_service),
        ):
            evidence, coverage = _personal_inputs(
                prompt="Today plans",
                policy=SimpleNamespace(),  # type: ignore[arg-type]
                partition="production",
                allow=True,
            )

        coverage_by_source = {item.source: item for item in coverage}
        self.assertEqual(sum(item.source == "pending_review" for item in evidence), 5)
        self.assertEqual(sum(item.source == "action" for item in evidence), 20)
        for source in ("pending_review", "action"):
            self.assertEqual(coverage_by_source[source].status, "partial")
            self.assertTrue(coverage_by_source[source].truncated)
            self.assertEqual(coverage_by_source[source].reason, "source_limit_reached")

    def test_context_budget_marks_evidence_dropped_from_model_prompt(self) -> None:
        configuration = _model_configuration()
        configuration = configuration.model_copy(
            update={
                "model": configuration.model.model_copy(
                    update={"context_window": 10_000, "output_token_limit": 512}
                )
            }
        )
        evidence = [
            BriefingEvidence(source="calendar", source_id="event-1", content="A" * 500),
            BriefingEvidence(source="weather", source_id="current", content="B" * 500),
        ]
        coverage = [
            BriefingCoverage(source="calendar", scope="selected events", status="complete"),
            BriefingCoverage(source="weather", scope="current weather", status="complete"),
        ]
        one_record_size = len(_build_prompt([evidence[0]], coverage).encode("utf-8"))
        schema_size = len(
            json.dumps(BriefingDraft.model_json_schema(), separators=(",", ":")).encode("utf-8")
        )
        available = one_record_size + 8
        system_bytes = (
            configuration.model.context_window
            - schema_size
            - configuration.model.output_token_limit
            - 512
            - available
        )

        with (
            patch("core.briefings.daily.get_visible_model_profile", return_value=SimpleNamespace(maximum_context_window=10_000)),
            patch(
                "core.agent.catalog.build_concrete_agent",
                return_value=SimpleNamespace(system_instruction="x" * system_bytes),
            ),
        ):
            _fit_evidence_to_context(
                evidence, coverage, configuration, BriefingDraft.model_json_schema()
            )

        self.assertEqual(len(evidence), 1)
        weather_coverage = next(item for item in coverage if item.source == "weather")
        self.assertEqual(weather_coverage.status, "partial")
        self.assertTrue(weather_coverage.truncated)
        self.assertEqual(weather_coverage.reason, "model_context_window_limit")

    def test_context_budget_fails_when_one_useful_record_cannot_fit(self) -> None:
        configuration = _model_configuration()
        configuration = configuration.model_copy(
            update={
                "model": configuration.model.model_copy(
                    update={"context_window": 10_000, "output_token_limit": 512}
                )
            }
        )
        evidence = [
            BriefingEvidence(source="calendar", source_id="event-1", content="A" * 10_000)
        ]
        coverage = [
            BriefingCoverage(source="calendar", scope="selected events", status="complete")
        ]
        empty_prompt_size = len(_build_prompt([], coverage).encode("utf-8"))
        schema_size = len(
            json.dumps(BriefingDraft.model_json_schema(), separators=(",", ":")).encode("utf-8")
        )
        available = empty_prompt_size + 32
        system_bytes = (
            configuration.model.context_window
            - schema_size
            - configuration.model.output_token_limit
            - 512
            - available
        )

        with (
            patch("core.briefings.daily.get_visible_model_profile", return_value=SimpleNamespace(maximum_context_window=10_000)),
            patch(
                "core.agent.catalog.build_concrete_agent",
                return_value=SimpleNamespace(system_instruction="x" * system_bytes),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "too little room for useful briefing evidence"):
                _fit_evidence_to_context(
                    evidence, coverage, configuration, BriefingDraft.model_json_schema()
                )

    def test_context_budget_rechecks_prompt_after_coverage_expands(self) -> None:
        configuration = _model_configuration()
        configuration = configuration.model_copy(
            update={
                "model": configuration.model.model_copy(
                    update={"context_window": 10_000, "output_token_limit": 512}
                )
            }
        )
        original = BriefingEvidence(source="calendar", source_id="event-1", content="A" * 300)
        clipped = original.model_copy(update={"content": "A" * 150})
        coverage = [
            BriefingCoverage(source="calendar", scope="selected events", status="complete")
        ]
        expanded_coverage = [
            coverage[0].model_copy(
                update={
                    "status": "partial",
                    "truncated": True,
                    "reason": "model_context_window_limit",
                }
            )
        ]
        base_prompt_size = len(_build_prompt([clipped], coverage).encode("utf-8"))
        expanded_prompt_size = len(
            _build_prompt([clipped], expanded_coverage).encode("utf-8")
        )
        self.assertGreater(expanded_prompt_size, base_prompt_size)
        minimum = original.model_copy(update={"content": "A" * 128})
        available = len(_build_prompt([minimum], expanded_coverage).encode("utf-8")) - 1
        schema_size = len(
            json.dumps(BriefingDraft.model_json_schema(), separators=(",", ":")).encode("utf-8")
        )
        system_bytes = (
            configuration.model.context_window
            - schema_size
            - configuration.model.output_token_limit
            - 512
            - available
        )

        with (
            patch("core.briefings.daily.get_visible_model_profile", return_value=SimpleNamespace(maximum_context_window=10_000)),
            patch(
                "core.agent.catalog.build_concrete_agent",
                return_value=SimpleNamespace(system_instruction="x" * system_bytes),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "too little room for useful briefing evidence"):
                _fit_evidence_to_context(
                    [original], coverage, configuration, BriefingDraft.model_json_schema()
                )

    def test_context_budget_rechecks_final_prompt_after_omission_changes_coverage(self) -> None:
        configuration = _model_configuration()
        configuration = configuration.model_copy(
            update={
                "model": configuration.model.model_copy(
                    update={"context_window": 10_000, "output_token_limit": 512}
                )
            }
        )
        retained = BriefingEvidence(source="calendar", source_id="event-1", content="A" * 300)
        omitted = BriefingEvidence(source="weather", source_id="wx-1", content="B" * 300)
        evidence = [retained, omitted]
        coverage = [
            BriefingCoverage(source="calendar", scope="selected events", status="complete"),
            BriefingCoverage(source="weather", scope="current conditions", status="complete"),
        ]
        fully_limited_coverage = [
            item.model_copy(
                update={
                    "status": "partial",
                    "truncated": True,
                    "reason": "model_context_window_limit",
                }
            )
            for item in coverage
        ]
        minimum_record = retained.model_copy(update={"content": "A" * 128})
        available = len(
            _build_prompt([minimum_record], fully_limited_coverage).encode("utf-8")
        )
        self.assertGreaterEqual(available, 256)
        self.assertGreater(
            len(_build_prompt(evidence, coverage).encode("utf-8")), available
        )
        schema_size = len(
            json.dumps(BriefingDraft.model_json_schema(), separators=(",", ":")).encode("utf-8")
        )
        system_bytes = (
            configuration.model.context_window
            - schema_size
            - configuration.model.output_token_limit
            - 512
            - available
        )

        with (
            patch("core.briefings.daily.get_visible_model_profile", return_value=SimpleNamespace(maximum_context_window=10_000)),
            patch(
                "core.agent.catalog.build_concrete_agent",
                return_value=SimpleNamespace(system_instruction="x" * system_bytes),
            ),
        ):
            _fit_evidence_to_context(
                evidence, coverage, configuration, BriefingDraft.model_json_schema()
            )

        self.assertEqual(len(evidence), 1)
        self.assertLessEqual(
            len(_build_prompt(evidence, coverage).encode("utf-8")), available
        )
        self.assertLess(len(evidence[0].content or ""), len(retained.content or ""))
        self.assertTrue(all(item.truncated for item in coverage))

    def test_missing_provider_id_uses_content_identity_and_dev_masking(self) -> None:
        snapshot = TelemetrySnapshot(
            modules={
                "reminders": TelemetryModuleEntry(
                    name="reminders",
                    status="healthy",
                    freshness="live",
                    observed_at="2026-09-25T13:00:00Z",
                    data={"records": [{"note": "Private reminder", "due": "2026-09-25T15:00:00Z"}]},
                )
            }
        )

        with patch("core.briefings.daily_inputs.is_dev_mode", return_value=True):
            _coverage, evidence = _telemetry_inputs(snapshot, None, dev_mode=True)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].identity_kind, "masked")
        self.assertEqual(evidence[0].revision_kind, "content")
        self.assertNotIn("Private reminder", evidence[0].content or "")
        self.assertTrue(evidence[0].source_id.startswith("dev:"))

    def test_dev_masks_personal_sources_but_retains_weather_telemetry(self) -> None:
        snapshot = TelemetrySnapshot(
            modules={
                "reminders": TelemetryModuleEntry(
                    name="reminders",
                    status="healthy",
                    freshness="live",
                    observed_at="2026-09-25T13:00:00Z",
                    data={"records": [{"id": "task-1", "note": "Private note"}]},
                ),
                "weather": TelemetryModuleEntry(
                    name="weather",
                    status="healthy",
                    freshness="live",
                    observed_at="2026-09-25T13:00:00Z",
                    data={"current": {"condition": "Clear", "temp_f": 72}},
                ),
            }
        )

        with patch("core.briefings.daily_inputs.is_dev_mode", return_value=True):
            _coverage, evidence = _telemetry_inputs(snapshot, None, dev_mode=True)

        by_source = {item.source: item for item in evidence}
        self.assertEqual(by_source["reminders"].identity_kind, "masked")
        self.assertNotIn("Private note", by_source["reminders"].content or "")
        self.assertEqual(by_source["weather"].source_id, "weather:current")
        self.assertEqual(by_source["weather"].identity_kind, "provider")
        self.assertIn("Clear", by_source["weather"].content or "")

    def test_external_report_selection_is_bounded_and_untrusted(self) -> None:
        reports = []
        for index in range(5):
            content = ActivityReportContent(
                submission_key=f"roadmap-{index}",
                title=f"Roadmap implementation report {index}",
                task_status="completed",
                outcome="Roadmap planning updated the follow-up timeline.",
                subjects=["roadmap planning"],
            )
            reports.append(
                ActivityReport(
                    id=uuid4(),
                    partition="production",
                    client_id="codex",
                    client_display_name="Codex",
                    principal="local",
                    received_at=f"2026-09-25T13:0{index}:00Z",
                    disposition="dismissed" if index == 0 else "new",
                    content=content,
                )
            )
        service = SimpleNamespace(list=lambda **_kwargs: reports)

        with patch("core.briefings.daily_inputs.get_activity_service", return_value=service):
            coverage, evidence = _external_inputs(
                prompt="roadmap planning follow-up", observed=[], partition="production"
            )

        self.assertEqual(len(evidence), 3)
        self.assertTrue(all(item.trust == "untrusted" for item in evidence))
        self.assertTrue(all(item.record_reference is not None for item in evidence))
        self.assertTrue(all("Untrusted external report" in (item.content or "") for item in evidence))
        self.assertEqual(coverage[0].status, "complete")

    def test_saved_conversation_text_retains_pending_and_untrusted_labels(self) -> None:
        report_ref = ExistingRecordReference(kind="external_activity", id="report-1")
        review_ref = ExistingRecordReference(kind="context_review", id="review-1")
        report = BriefingEvidence(
            source="external_report", source_id="report-1", trust="untrusted",
            content="An external report claims a delay.", record_reference=report_ref,
        )
        review = BriefingEvidence(
            source="pending_review", source_id="review-1", trust="pending",
            content="A proposed personal-context update.", record_reference=review_ref,
        )
        artifact = build_canonical_artifact(
            session_id=uuid4(),
            draft=BriefingDraft(sections=[BriefingSectionDraft(title="Today", items=[
                BriefingItemDraft(
                    category="analysis", title="Reported delay", body="Check the claim.",
                    evidence_ids=[report.id], record_references=[report_ref],
                ),
                BriefingItemDraft(
                    category="suggestion", title="Review context", body="Decide whether to accept it.",
                    evidence_ids=[review.id], record_references=[review_ref],
                ),
            ])]),
            evidence=[report, review], coverage=[],
        )

        rendered = render_artifact_text(artifact)
        self.assertIn("analysis; untrusted external report", rendered)
        self.assertIn("suggestion; pending review", rendered)

    def test_demo_generation_returns_an_isolated_daily_fixture(self) -> None:
        configuration = _model_configuration().model_copy(update={"execution_kind": "demo"})
        request = BriefingGenerationRequest(
            idempotency_key=uuid4(), profile_id="daily", model_id="demo/daily-fixture"
        )
        output = generate_daily_briefing(
            uuid4(), request, configuration, _Control()  # type: ignore[arg-type]
        )

        self.assertEqual(len(output.evidence), 1)
        self.assertEqual(output.evidence[0].source, "demo")
        self.assertEqual(output.draft.sections[0].items[0].evidence_ids, [output.evidence[0].id])

    def test_generation_runs_bounded_model_call_and_returns_canonical_evidence(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        snapshot = TelemetrySnapshot(
            modules={
                "reminders": TelemetryModuleEntry(
                    name="reminders",
                    status="healthy",
                    freshness="live",
                    observed_at=now,
                    data={"records": [{"id": "task-17", "note": "Prepare roadmap review", "due": now}]},
                ),
                **{
                    source: TelemetryModuleEntry(
                        name=source,
                        status="disabled",
                        freshness="none",
                        reason_code="disabled_by_settings",
                    )
                    for source in ("calendar", "email", "weather", "news", "f1", "football", "market")
                },
            }
        )

        class _Telemetry:
            def refresh(self, *, connectors, force, before_collect):
                for name in connectors:
                    before_collect(name)
                return snapshot

            def latest(self):
                return snapshot

        captured: dict[str, object] = {"prompts": []}

        def model_call(**kwargs):
            prompt = kwargs["prompt"]
            captured["prompts"].append(prompt)  # type: ignore[union-attr]
            evidence_json = prompt.split("\nEvidence:\n", 1)[1].split(
                "\n\nRepair your previous JSON draft.", 1
            )[0]
            rows = json.loads(evidence_json)
            captured["rows"] = rows
            reminder = next(row for row in rows if row["source"] == "reminders")
            output = {
                "sections": [{
                    "title": "Today",
                    "items": [{
                        "category": "observation",
                        "title": "Roadmap review",
                        "body": "Prepare the roadmap review.",
                        "evidence_ids": [reminder["id"]],
                    }],
                }]
            }
            if len(captured["prompts"]) == 1:  # type: ignore[arg-type]
                output = {"sections": [], "limitations": []}
            return ProviderTurnResult(
                message=AgentMessage(role="agent", content=json.dumps(output))
            )

        control = _Control()
        request = BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="deepseek/deepseek-v4-flash-0731",
            reasoning="high",
        )
        with (
            patch("core.briefings.daily.get_telemetry_service", return_value=_Telemetry()),
            patch("core.briefings.daily.get_settings_store", return_value=SimpleNamespace(get_snapshot=lambda: object())),
            patch("core.briefings.daily.ContextPolicy.from_settings", return_value=SimpleNamespace(permits_retrieval=False)),
            patch("core.briefings.daily.execute_single_call", side_effect=model_call),
        ):
            output = generate_daily_briefing(
                uuid4(), request, _model_configuration(), control  # type: ignore[arg-type]
            )

        row = next(item for item in output.evidence if item.source == "reminders")
        self.assertEqual(row.identity_kind, "provider")
        self.assertEqual(row.revision_kind, "content")
        self.assertTrue(row.included_in_synthesis)
        self.assertEqual(output.draft.sections[0].items[0].category, "observation")
        self.assertEqual(output.draft.sections[0].items[0].evidence_ids, [row.id])
        self.assertIn(("briefing.stage", {"stage": "synthesizing", "state": "completed"}), control.events)
        self.assertTrue(captured["rows"])
        self.assertEqual(len(captured["prompts"]), 2)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
