from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
from core.connectors.models import ConnectorResult


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
