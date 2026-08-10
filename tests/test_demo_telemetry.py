"""Regression coverage for unified DEMO_MODE telemetry fixtures."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from core.api.demo import build_demo_briefing, load_mock_telemetry
from core.mock.demo_fixture import load_demo_bundle, resolve_relative_time
from core.telemetry.service import get_telemetry_service, reset_telemetry_service_for_tests


class RelativeTimeResolutionTests(unittest.TestCase):
    def test_resolve_now_and_offsets(self) -> None:
        anchor = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(resolve_relative_time("now", now=anchor), anchor)
        self.assertEqual(
            resolve_relative_time("now-15m", now=anchor).isoformat(),
            "2026-08-08T11:45:00+00:00",
        )
        self.assertEqual(
            resolve_relative_time("now+4h", now=anchor).isoformat(),
            "2026-08-08T16:00:00+00:00",
        )
        self.assertEqual(
            resolve_relative_time("now+1d", now=anchor).isoformat(),
            "2026-08-09T12:00:00+00:00",
        )
        self.assertEqual(
            resolve_relative_time("now+1d2h", now=anchor).isoformat(),
            "2026-08-09T14:00:00+00:00",
        )
        self.assertEqual(
            resolve_relative_time("next_sunday+15h", now=anchor).isoformat(),
            "2026-08-09T15:00:00+00:00",
        )
        sunday = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(
            resolve_relative_time("next_sunday+15h", now=sunday).isoformat(),
            "2026-08-16T15:00:00+00:00",
        )


class DemoFixtureNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.anchor = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)

    def test_bundle_derives_coherent_legacy_and_structured_data(self) -> None:
        bundle = load_demo_bundle(now=self.anchor)

        self.assertEqual(bundle.telemetry.weather, bundle.modules["weather"].display_text)
        self.assertEqual(bundle.telemetry.sports, bundle.modules["f1"].display_text)
        self.assertEqual(bundle.digest.unread_emails_count, 3)
        self.assertEqual(bundle.digest.upcoming_events_count, 3)
        self.assertEqual(bundle.digest.reminders_pending_count, 3)
        self.assertEqual(bundle.digest.weather_archetype, "clear_day")
        self.assertEqual(bundle.digest.failed_connectors, [])
        self.assertGreater(bundle.digest.sync_health_score or 0.0, 90.0)
        self.assertLess(bundle.digest.sync_health_score or 100.0, 100.0)
        self.assertTrue(
            bundle.modules["f1"].data["f1_map"]["raceDateTimeEST"].startswith("Sunday,")
        )

        weather = bundle.modules["weather"].data
        self.assertEqual(weather["temp_f"], 72)
        self.assertEqual(weather["condition"], "clear sky")
        self.assertEqual(weather["archetype"], "clear_day")

        calendar = bundle.modules["calendar"].data
        self.assertEqual(calendar["total_count"], 3)
        self.assertTrue(all("summary" in event for event in calendar["events"]))

        football = bundle.modules["football"].data
        self.assertEqual(len(football["fixtures"]), 1)
        self.assertEqual(football["fixtures"][0]["team"], "Barcelona")

        for entry in bundle.digest.connector_health:
            self.assertIsNotNone(entry.observed_at)

    def test_calendar_events_resolve_into_the_future(self) -> None:
        bundle = load_demo_bundle(now=self.anchor)
        events = bundle.modules["calendar"].data["events"]
        for event in events:
            start = datetime.fromisoformat(
                event["start"] if "T" in event["start"] else f"{event['start']}T12:00:00+00:00"
            )
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            self.assertGreaterEqual(start, self.anchor)

    def test_briefing_reflects_fixture_facts(self) -> None:
        telemetry, _digest = load_mock_telemetry()
        with mock.patch(
            "core.api.demo.load_demo_bundle_or_raise",
            return_value=load_demo_bundle(now=self.anchor),
        ):
            briefing = build_demo_briefing(telemetry)
        self.assertIn("72 degrees", briefing)
        self.assertIn("3 unread primary messages", briefing)
        self.assertIn("Product review", briefing)
        self.assertIn("3 reminders remain pending", briefing)
        self.assertIn(
            "Next calendar item is Product review, scheduled for today at 4:00 PM UTC.",
            briefing,
        )
        self.assertNotIn("Greetings", briefing)
        self.assertNotIn("Chief", briefing)
        self.assertNotIn("Your ", briefing)


class DemoSnapshotIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_telemetry_service_for_tests()

    def tearDown(self) -> None:
        reset_telemetry_service_for_tests()

    def test_demo_refresh_builds_structured_snapshot(self) -> None:
        with mock.patch("core.telemetry.service.config.DEMO_MODE", True):
            snapshot = get_telemetry_service().refresh(force=True)

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertTrue(snapshot.connector_health)
        self.assertGreater(snapshot.sync_health_score, 90.0)


if __name__ == "__main__":
    unittest.main()
