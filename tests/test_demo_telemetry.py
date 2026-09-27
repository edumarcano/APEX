"""Regression coverage for unified DEMO_MODE telemetry fixtures."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from clients import market_client
from core.mock.demo_fixture import load_demo_bundle, resolve_relative_time
from core.settings.models import FeaturesSettings, MarketSettings, RuntimeSettingsSnapshot
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

    def test_bundle_derives_structured_connector_data(self) -> None:
        bundle = load_demo_bundle(now=self.anchor)

        self.assertIn("72", bundle.modules["weather"].display_text)
        self.assertEqual(bundle.modules["email"].data["count"], 3)
        self.assertEqual(bundle.modules["calendar"].data["total_count"], 3)
        self.assertEqual(bundle.modules["reminders"].data["count"], 3)
        self.assertTrue(
            bundle.modules["f1"].data["f1_map"]["raceDateTimeEST"].startswith("Sunday,")
        )

        weather = bundle.modules["weather"].data
        self.assertEqual(weather["temp_f"], 72)
        self.assertEqual(weather["apparent_temp_f"], 74)
        self.assertEqual(weather["temp_max_f"], 78)
        self.assertEqual(weather["temp_min_f"], 62)
        self.assertEqual(weather["humidity_pct"], 52)
        self.assertEqual(weather["wind_speed_mph"], 8)
        self.assertEqual(weather["precip_probability_max"], 0)
        self.assertEqual(weather["condition"], "clear sky")
        self.assertEqual(weather["archetype"], "clear_day")
        self.assertEqual(weather["location"], "Simulation City")
        self.assertEqual(len(weather["timeline"]), 3)
        self.assertEqual(weather["timeline"][0]["label"], "NOW")
        self.assertEqual(weather["timeline"][0]["temp_f"], 72)
        self.assertIn("feels like 74", bundle.modules["weather"].display_text)
        self.assertIn("Today's high is 78, low 62", bundle.modules["weather"].display_text)

        calendar = bundle.modules["calendar"].data
        self.assertEqual(calendar["total_count"], 3)
        self.assertTrue(all("summary" in event for event in calendar["events"]))

        football = bundle.modules["football"].data
        self.assertEqual(len(football["fixtures"]), 1)
        self.assertEqual(football["fixtures"][0]["team"], "Barcelona")

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

    def test_demo_market_uses_configured_weekday_snapshot_for_route_and_telemetry(self) -> None:
        anchor = datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)
        settings = mock.Mock()
        settings.get_snapshot.return_value = RuntimeSettingsSnapshot(
            features=FeaturesSettings(market=True),
            market=MarketSettings(symbols=("TSLA",)),
        )
        with (
            mock.patch.object(market_client, "DEMO_MODE", True),
            mock.patch.object(market_client, "_now_utc", return_value=anchor),
            mock.patch.object(market_client, "get_settings_store", return_value=settings),
            mock.patch("core.telemetry.service.config.DEMO_MODE", True),
        ):
            route_payload = market_client.read_market_data()
            telemetry = get_telemetry_service().refresh(force=True)

        market_module = telemetry.modules["market"]
        self.assertEqual(route_payload["status"], market_module.status)
        self.assertEqual(route_payload["freshness"], market_module.freshness)
        self.assertEqual(route_payload["reason_code"], market_module.reason_code)
        self.assertEqual(
            route_payload["collection_revision"],
            market_module.data["collection_revision"],
        )
        self.assertEqual([ticker["symbol"] for ticker in route_payload["tickers"]], ["TSLA"])
        self.assertEqual(
            [ticker["symbol"] for ticker in market_module.data["tickers"]],
            ["TSLA"],
        )
        self.assertTrue(
            all(
                datetime.fromisoformat(bar["date"]).weekday() < 5
                for bar in route_payload["tickers"][0]["history"]
            )
        )


if __name__ == "__main__":
    unittest.main()
