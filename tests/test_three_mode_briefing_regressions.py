from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from core.synthesis.formatting import compact_payload, parse_model_output, render_structured_briefing
from core.synthesis.models import (
    BriefingFacts,
    CalendarFact,
    EmailFact,
    NewsFact,
    ReminderFact,
    SportEventFact,
    WeatherDayFact,
    WeatherHourFact,
)
from core.synthesis.router import SynthesisRouter
from core.synthesis.models import SynthesisResult
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage
from core.connectors.models import ConnectorResult
from clients.weather_client import _hourly_window
from core.connectors.collect import _calendar_data


def rich_facts() -> BriefingFacts:
    return BriefingFacts(
        generated_at="2026-08-19T12:00:00+00:00",
        weather_daily=[WeatherDayFact(date=f"2026-08-{day:02d}") for day in range(1, 12)],
        weather_hourly=[WeatherHourFact(time=f"2026-08-19T{hour:02d}:00:00-04:00") for hour in range(48)],
        emails=[EmailFact(subject=f"Email {index}") for index in range(9)],
        news_headlines=[NewsFact(topic="world", headline=f"Story {index}", source="Wire", published_at="2026-08-19T10:00:00Z", synopsis="Context") for index in range(6)],
        calendar_event_count=24,
        calendar_events=[CalendarFact(title=f"Event {index}", start=f"2026-08-{index + 1:02d}T09:00:00Z") for index in range(24)],
        pending_reminder_count=24,
        reminders=[ReminderFact(note=f"Reminder {index}") for index in range(24)],
        sports_events=[SportEventFact(kind="football", title=f"Match {index}", start=f"2026-08-{index + 1:02d}T12:00:00Z") for index in range(16)],
    )


class BriefingProjectionRegressionTests(unittest.TestCase):
    def test_router_passes_flash_and_focused_views_to_their_routes(self) -> None:
        router = SynthesisRouter()
        source = rich_facts()
        with patch.object(router, "_synthesize_explicit_local") as local:
            router.synthesize_mode(source, "flash")
        flash_source = local.call_args.args[0]
        self.assertEqual(len(flash_source.weather_daily), 1)
        self.assertEqual(len(flash_source.emails), 3)
        self.assertEqual(len(flash_source.calendar_events), 2)
        self.assertEqual(len(flash_source.reminders), 3)

        with patch.object(router, "_synthesize_focused") as focused:
            router.synthesize_mode(source, "focused")
        focused_source, focused_fallback = focused.call_args.args
        self.assertEqual(len(focused_source.weather_daily), 10)
        self.assertEqual(len(focused_source.emails), 8)
        self.assertEqual(len(focused_source.calendar_events), 24)
        self.assertEqual(len(focused_fallback.calendar_events), 2)

    def test_focused_parser_preserves_its_word_budget(self) -> None:
        speech = " ".join(f"word{index}" for index in range(300))
        parsed, _insights = parse_model_output(
            f"===SPEECH===\n{speech}\n===INSIGHTS===\n- Clear",
            max_words=450,
            max_insights=5,
        )
        self.assertEqual(len(parsed.split()), 300)

    def test_news_payload_keeps_focused_analysis_fields(self) -> None:
        payload = json.loads(compact_payload(rich_facts().focused_view(), max_chars=28_000))
        story = payload["news_headlines"][0]
        self.assertEqual(story["source"], "Wire")
        self.assertEqual(story["published_at"], "2026-08-19T10:00:00Z")
        self.assertEqual(story["synopsis"], "Context")

    def test_structured_view_marks_presentation_truncation(self) -> None:
        briefing, _insights = render_structured_briefing(rich_facts().structured_view())
        self.assertIn("CALENDAR [TRUNCATED]", briefing)
        self.assertIn("REMINDERS: 24 pending [TRUNCATED]", briefing)
        self.assertIn("SPORTS [TRUNCATED]", briefing)
        self.assertNotIn("Event 23", briefing)

    def test_global_config_derives_strategy_and_agent_from_one_mode(self) -> None:
        from core.api.routers.system import get_global_config

        snapshot = SimpleNamespace(
            briefing=SimpleNamespace(default_mode="flash"),
            ask_apex=SimpleNamespace(enabled=True),
            features=SimpleNamespace(market=False),
            voice=SimpleNamespace(mode="off"),
        )
        with patch("core.api.routers.system.get_settings_store", return_value=SimpleNamespace(get_snapshot=lambda: snapshot)), patch(
            "core.api.routers.system.resolve_agent_selection", return_value=("local", "felis", "none")
        ), patch("core.api.routers.system.is_dev_mode", return_value=False), patch(
            "core.api.routers.system.DEMO_MODE", False
        ):
            config = get_global_config()
        self.assertEqual(config["synthesis_strategy"], "local")
        self.assertEqual(config["synthesis_agent"], "felis")

    def test_reminders_are_ordered_for_flash_by_urgency_then_importance(self) -> None:
        from core.api.briefing import _build_synthesis_input

        reminders = ConnectorResult(
            name="reminders", status="healthy", freshness="live", reason_code="ok",
            display_text="", data={"records": [
                {"note": "Low priority", "importance": "low"},
                {"note": "High priority", "importance": "high"},
                {"note": "Overdue", "importance": "low", "due": {"date_time": "2000-01-01T09:00:00Z"}},
            ]},
        )
        source = _build_synthesis_input(results={"reminders": reminders}, failed_connectors=[])
        self.assertEqual([item.note for item in source.flash_view().reminders], ["Overdue", "High priority", "Low priority"])

    def test_hourly_weather_window_starts_at_current_hour(self) -> None:
        raw = {
            "time": [f"2026-08-19T{hour:02d}:00" for hour in range(24)] + [f"2026-08-20T{hour:02d}:00" for hour in range(24)],
            "temperature_2m": list(range(48)),
        }
        forecasts = _hourly_window(
            raw, timezone_name="America/New_York",
            now=datetime(2026, 8, 19, 22, 30, tzinfo=ZoneInfo("America/New_York")),
        )
        self.assertEqual(forecasts[0]["time"], "2026-08-19T22:00")
        self.assertEqual(len(forecasts), 26)

    def test_all_day_event_remains_active_until_exclusive_end(self) -> None:
        data = _calendar_data(
            [{"summary": "Offsite", "start": "2026-08-19", "end": "2026-08-20", "all_day": True, "time_zone": "America/New_York"}],
            now=datetime(2026, 8, 19, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(data["total_count"], 1)

    def test_reminder_due_time_is_normalized_with_its_provider_timezone(self) -> None:
        from core.api.briefing import _build_synthesis_input

        reminders = ConnectorResult(
            name="reminders", status="healthy", freshness="live", reason_code="ok", display_text="",
            data={"records": [{"note": "Eastern task", "due": {"date_time": "2026-08-20T09:00:00", "time_zone": "Eastern Standard Time"}}]},
        )
        source = _build_synthesis_input(results={"reminders": reminders}, failed_connectors=[])
        self.assertEqual(source.reminders[0].due, "2026-08-20T09:00:00-04:00")
        self.assertEqual(source.reminders[0].due_time_zone, "Eastern Standard Time")

    def test_sports_projections_use_time_horizons(self) -> None:
        source = BriefingFacts(
            generated_at="2026-08-19T12:00:00Z",
            sports_events=[
                SportEventFact(kind="football", title="Near", start="2026-08-20T12:00:00Z"),
                SportEventFact(kind="f1", title="Next week", start="2026-08-27T12:00:00Z"),
            ],
        )
        self.assertEqual([item.title for item in source.flash_view().sports_events], ["Near"])
        self.assertEqual([item.title for item in source.focused_view().sports_events], ["Near", "Next week"])

    def test_focused_compaction_preserves_cross_source_floors(self) -> None:
        source = rich_facts().model_copy(update={
            "calendar_events": [CalendarFact(title="C" * 160, start=f"2026-09-{index % 28 + 1:02d}T09:00:00Z") for index in range(100)],
            "reminders": [ReminderFact(note="R" * 160) for _ in range(50)],
            "emails": [EmailFact(subject="E" * 160, snippet="S" * 200) for _ in range(8)],
            "sports_events": [SportEventFact(kind="football", title="M" * 160, start=f"2026-09-{index % 28 + 1:02d}T12:00:00Z") for index in range(15)],
        })
        payload = json.loads(compact_payload(source, max_chars=28_000))
        self.assertGreaterEqual(len(payload["calendar_events"]), 3)
        self.assertGreaterEqual(len(payload["reminders"]), 2)
        self.assertGreaterEqual(len(payload["emails"]), 2)
        self.assertGreaterEqual(len(payload["sports_events"]), 1)
        self.assertIn("payload", payload["truncated"])


class BriefingRouterContractTests(unittest.TestCase):
    def test_focused_falls_back_through_flash_then_structured(self) -> None:
        router = SynthesisRouter()
        local = SynthesisResult(briefing="Local orientation.", provider="llama_cpp", agent="felis")
        with patch.object(router, "_panthera", side_effect=RuntimeError("openrouter_unavailable")), patch.object(
            router, "_try_panthera_local_fallback", return_value=(local, "")
        ) as fallback:
            result = router.synthesize_mode(rich_facts(), "focused")
        self.assertEqual(result.agent, "felis")
        self.assertEqual(result.fallback_reason, "openrouter_unavailable")
        self.assertEqual(len(fallback.call_args.args[0].calendar_events), 2)

    def test_focused_provider_uses_fixed_model_high_effort_and_no_tools(self) -> None:
        router = SynthesisRouter()
        turn = ProviderTurnResult(
            message=AgentMessage(role="agent", content="===SPEECH===\nReady.\n===INSIGHTS===\n- Clear"),
            resolved_model="deepseek/deepseek-v4-flash-0731",
        )
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test"}, clear=False), patch(
            "core.synthesis.router.OpenRouterProvider.generate_turn", return_value=turn
        ) as generate:
            result = router._panthera(rich_facts().focused_view())
        _messages, tools, profile = generate.call_args.args
        self.assertEqual(tools, [])
        self.assertEqual(profile.reasoning_effort, "high")
        self.assertEqual(profile.api_model, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(result.resolved_model, "deepseek/deepseek-v4-flash-0731")

    def test_structured_bypasses_model_and_warmup(self) -> None:
        router = SynthesisRouter()
        with patch.object(router, "_panthera") as panthera, patch.object(router, "_local") as local:
            result = router.synthesize_mode(rich_facts(), "structured")
        self.assertEqual(result.provider, "raw")
        panthera.assert_not_called()
        local.assert_not_called()

    def test_f1_upcoming_uses_an_iso_timestamp_inside_focused_horizon(self) -> None:
        from core.api.briefing import _build_synthesis_input

        f1 = ConnectorResult(
            name="f1", status="healthy", freshness="live", reason_code="ok", display_text="",
            data={"f1_map": {"raceName": "Grand Prix", "raceStart": (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=7)).isoformat(), "sprintScheduled": True}},
        )
        source = _build_synthesis_input(results={"f1": f1}, failed_connectors=[])
        self.assertIsNotNone(source.f1_upcoming)
        self.assertEqual(source.f1_upcoming.race_name, "Grand Prix")
        self.assertEqual(source.focused_view().sports_events[0].kind, "f1")

    def test_build_briefing_target_statuses_orders_focused_first_and_names_gemma(self) -> None:
        from core.api.briefing import build_briefing_target_statuses

        targets = build_briefing_target_statuses()
        self.assertEqual([t.mode for t in targets], ["focused", "flash", "structured"])
        flash_target = next(t for t in targets if t.mode == "flash")
        self.assertTrue(flash_target.description.startswith("Felis · Gemma"))

    def test_structured_mode_delivery_policy_is_visual_first(self) -> None:
        from core.api.briefing import _synthesize_from_snapshot
        from core.telemetry.models import TelemetrySnapshot

        snapshot = TelemetrySnapshot(
            snapshot_id="snap-123",
            collected_at="2026-08-20T00:00:00Z",
            modules={},
            sync_health_score=100.0,
            connector_health=[],
            failed_connectors=[],
        )
        settings_mock = SimpleNamespace(
            voice=SimpleNamespace(mode="automatic", engine="google", gender="female"),
        )
        with patch("core.api.briefing.get_settings_store", return_value=SimpleNamespace(get_snapshot=lambda: settings_mock)), patch(
            "core.api.briefing.is_dev_mode", return_value=False
        ), patch("core.api.briefing.database"):
            response = _synthesize_from_snapshot(
                snapshot=snapshot,
                mode="structured",
                run_id="run-test",
                speak_fillers=False,
            )
        self.assertFalse(response.metadata.spoken)
