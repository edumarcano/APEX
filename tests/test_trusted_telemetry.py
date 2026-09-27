"""Typed connector health, bounded untrusted text, and connector validation."""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import Mock, patch

from clients import news_client, sports_client
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
                "news": _result("news", "degraded", reason_code="partial_failure"),
                "email": _result("email", "unavailable", reason_code="connection_error"),
                "calendar": None,
                "f1": None,
                "football": None,
                "reminders": _result("reminders", "healthy"),
            }
        )
        self.assertEqual(report.sync_health_score, 62.5)
        self.assertEqual(report.confidence_score, 62.5)
        self.assertEqual(report.failed_connectors, ["email"])
        self.assertEqual(
            [entry.name for entry in report.connector_health],
            ["weather", "news", "email", "reminders"],
        )

    def test_sports_failures_map_to_the_connector_group(self) -> None:
        report = compute_sync_health(
            {
                "f1": _result("f1", "unavailable", reason_code="provider_error"),
                "football": _result("football", "unavailable", reason_code="throttled"),
                "reminders": _result("reminders", "healthy"),
            }
        )
        self.assertEqual(report.failed_connectors, ["sports"])
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
            "weather": None, "news": None, "email": None, "calendar": None,
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

    def test_unbroken_text_respects_character_limit(self) -> None:
        self.assertEqual(sanitize_fact("A" * 100, 32), "A" * 32)


class CompatibilityFacadeTests(unittest.TestCase):
    def test_weather_facade_returns_display_text(self) -> None:
        from clients import weather_client

        fake = ConnectorResult(
            name="weather", status="healthy", freshness="live", reason_code="ok",
            display_text="Current temperature is 70 degrees with clear sky.",
            data={"temp_f": 70, "condition": "clear sky"},
        )
        with patch.object(weather_client, "collect_weather", return_value=fake):
            self.assertEqual(
                weather_client.fetch_weather_data(),
                "Current temperature is 70 degrees with clear sky.",
            )


class ConnectorValidationTests(unittest.TestCase):
    def test_news_malformed_articles_return_typed_unavailable_result(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"articles": ["malformed"]}
        with patch.object(news_client, "api_key", "test-key"), patch.object(
            news_client.time, "sleep",
        ), patch.object(news_client.requests, "get", return_value=response):
            result = news_client.collect_news()
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.freshness, "none")
        self.assertEqual(result.reason_code, "invalid_payload")

    def test_news_partial_transport_failure_is_degraded(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        article_url = "https://news.example/articles/roadmap"
        response.json.return_value = {"articles": [{
            "title": "Verified headline", "url": article_url,
            "publishedAt": "2026-09-25T12:00:00Z",
        }]}
        with patch.object(news_client, "api_key", "test-key"), patch.object(
            news_client.time, "sleep",
        ), patch.object(
            news_client.requests,
            "get",
            side_effect=[response, news_client.requests.exceptions.RequestException("offline")],
        ):
            result = news_client.collect_news()
        self.assertEqual(result.status, "degraded")
        self.assertEqual(result.reason_code, "partial_failure")
        self.assertEqual(len(result.data["headlines"]), 1)
        self.assertEqual(
            result.data["headlines"][0]["article_id"],
            hashlib.sha256(article_url.encode("utf-8")).hexdigest(),
        )

    def test_news_malformed_article_url_keeps_headline_without_stable_id(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"articles": [{
            "title": "Useful headline", "url": "https://[invalid",
        }]}
        with patch.object(news_client, "api_key", "test-key"), patch.object(
            news_client.time, "sleep",
        ), patch.object(news_client.requests, "get", return_value=response):
            result = news_client.collect_news()
        self.assertEqual(result.status, "healthy")
        self.assertEqual(len(result.data["headlines"]), 1)
        self.assertEqual(result.data["headlines"][0]["headline"], "Useful headline")
        self.assertNotIn("article_id", result.data["headlines"][0])

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
