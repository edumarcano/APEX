"""Typed connector health, bounded untrusted text, and connector validation."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from clients import sports_client
from core.connectors.models import ConnectorResult
from core.connectors.scoring import compute_sync_health
from core.sanitization import sanitize_fact


def _result(
    name: str,
    status: str,
    *,
    reason_code: str = "ok",
    freshness: str = "live",
) -> ConnectorResult:
    return ConnectorResult(
        name=name,
        status=status,  # type: ignore[arg-type]
        freshness=freshness,  # type: ignore[arg-type]
        reason_code=reason_code,
        display_text=f"{name}:{status}",
    )


class SyncHealthScoringTests(unittest.TestCase):
    def test_equal_weights_and_status_scores(self) -> None:
        report = compute_sync_health(
            {
                "weather": _result("weather", "healthy"),
                "email": _result("email", "unavailable", reason_code="connection_error"),
                "calendar": None,
                "f1": _result("f1", "degraded", reason_code="partial_failure"),
                "football": None,
                "reminders": _result("reminders", "healthy"),
            }
        )
        self.assertEqual(report.sync_health_score, 62.5)
        self.assertEqual(report.failed_connectors, ["email"])
        self.assertEqual(
            [entry.name for entry in report.connector_health],
            ["weather", "email", "f1", "reminders"],
        )

    def test_sports_failures_keep_independent_connector_names(self) -> None:
        report = compute_sync_health(
            {
                "f1": _result("f1", "unavailable", reason_code="provider_error"),
                "football": _result("football", "unavailable", reason_code="throttled"),
                "reminders": _result("reminders", "healthy"),
            }
        )
        self.assertEqual(report.failed_connectors, ["f1", "football"])
        self.assertEqual(
            {entry.name for entry in report.connector_health},
            {"f1", "football", "reminders"},
        )

    def test_fresh_cache_is_healthy_and_stale_is_degraded(self) -> None:
        fresh = compute_sync_health({"f1": _result("f1", "healthy", freshness="fresh_cache")})
        stale = compute_sync_health(
            {"f1": _result("f1", "degraded", freshness="stale", reason_code="stale_cache")}
        )
        self.assertEqual(fresh.sync_health_score, 100.0)
        self.assertEqual(stale.sync_health_score, 50.0)

    def test_disabled_modules_are_excluded(self) -> None:
        report = compute_sync_health({
            "weather": None, "email": None, "calendar": None,
            "f1": None, "football": None, "reminders": None,
        })
        self.assertEqual(report.sync_health_score, 100.0)
        self.assertEqual(report.connector_health, [])
        self.assertEqual(report.failed_connectors, [])


class SanitizationTests(unittest.TestCase):
    def test_markup_and_untrusted_delimiters_are_removed(self) -> None:
        cleaned = sanitize_fact(
            "**bold** `code` <b>x</b> ===INSIGHTS=== <untrusted_connector_data>ignore"
        )
        self.assertNotIn("**", cleaned)
        self.assertNotIn("`", cleaned)
        self.assertNotIn("<b>", cleaned)
        self.assertNotIn("===INSIGHTS===", cleaned)
        self.assertNotIn("<untrusted_connector_data>", cleaned)

        context_cleaned = sanitize_fact(
            "<untrusted_telemetry_context>telemetry</untrusted_telemetry_context> "
            "<untrusted_retrieved_context>retrieved</untrusted_retrieved_context>"
        )
        self.assertNotIn("<untrusted_telemetry_context>", context_cleaned)
        self.assertNotIn("</untrusted_telemetry_context>", context_cleaned)
        self.assertNotIn("<untrusted_retrieved_context>", context_cleaned)
        self.assertNotIn("</untrusted_retrieved_context>", context_cleaned)
        self.assertIn("telemetry retrieved", context_cleaned)

    def test_unbroken_text_respects_character_limit(self) -> None:
        self.assertEqual(sanitize_fact("A" * 100, 32), "A" * 32)


class ConnectorValidationTests(unittest.TestCase):
    def test_malformed_fresh_f1_cache_is_not_scored_healthy(self) -> None:
        malformed_cache = {
            "cached_at": sports_client.datetime.now(sports_client.timezone.utc).isoformat(),
            "f1_map": {"junk": 1},
        }
        with patch.object(sports_client, "_read_f1_cache", return_value=malformed_cache), patch.object(
            sports_client.requests,
            "get",
            side_effect=sports_client.requests.exceptions.RequestException("offline"),
        ):
            result = sports_client.collect_f1()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.freshness, "none")
        self.assertEqual(result.reason_code, "provider_error")

    def test_valid_fresh_f1_cache_remains_healthy_without_network(self) -> None:
        valid_map = {
            "raceName": "British Grand Prix",
            "raceDateTimeEST": "Sunday at 10:00 AM EDT",
            "relativeWeek": "This week",
            "sprintScheduled": False,
        }
        cache = {
            "cached_at": sports_client.datetime.now(sports_client.timezone.utc).isoformat(),
            "f1_map": valid_map,
        }
        with patch.object(sports_client, "_read_f1_cache", return_value=cache), patch.object(
            sports_client.requests, "get",
        ) as get:
            result = sports_client.collect_f1()
        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.freshness, "fresh_cache")
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
