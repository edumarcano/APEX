"""Regression coverage for market cache, parsing, and telemetry boundaries."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from clients import market_client
from core.api.models import MarketResponse
from core.api.briefing import _build_synthesis_input
from core.connectors.models import ConnectorResult
from core.settings.models import ModulesSettings
from core.telemetry.collector import collect_connector_results
from core.telemetry.store import build_snapshot_from_results
from core.settings.models import FeaturesSettings, MarketSettings, RuntimeSettingsSnapshot


def _store(symbols: list[str], *, enabled: bool = True) -> mock.Mock:
    store = mock.Mock()
    store.get_snapshot.return_value = RuntimeSettingsSnapshot(
        features=FeaturesSettings(market=enabled), market=MarketSettings(symbols=tuple(symbols))
    )
    return store


def _daily_payload() -> dict[str, object]:
    return {"Time Series (Daily)": {
        "2026-09-08": {"1. open": "101", "2. high": "104", "3. low": "100", "4. close": "103", "5. volume": "150"},
        "2026-09-05": {"1. open": "99", "2. high": "102", "3. low": "98", "4. close": "101", "5. volume": "100"},
        "2026-09-04": {"1. open": "98", "2. high": "100", "3. low": "96", "4. close": "99", "5. volume": "90"},
    }}


_NOW = datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)


def _history_entry(*, fetched_at: datetime = _NOW) -> dict[str, object]:
    history = market_client._parse_daily_history(_daily_payload())
    assert history is not None
    return {
        "history": history,
        "market_fetched_at": market_client._iso_utc(fetched_at),
        "last_successful_fetch_date": fetched_at.date().isoformat(),
        "last_attempt_date": fetched_at.date().isoformat(),
        "consecutive_failures": 0,
    }


class MarketClientTests(unittest.TestCase):
    def test_unconfigured_market_is_unavailable_without_provider_call(self) -> None:
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPY"])), mock.patch.dict(market_client.os.environ, {}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get") as provider:
            response = market_client.refresh_market_data()
        self.assertEqual(response["status"], "unavailable")
        self.assertEqual(response["reason_code"], "not_configured")
        provider.assert_not_called()
        MarketResponse.model_validate(response)

    def test_daily_history_is_chronological_and_derives_metrics(self) -> None:
        history = market_client._parse_daily_history(_daily_payload())
        self.assertIsNotNone(history)
        assert history is not None
        self.assertEqual([bar["date"] for bar in history], ["2026-09-04", "2026-09-05", "2026-09-08"])
        entry = {"history": history, "market_fetched_at": market_client._iso_utc()}
        ticker = market_client._ticker_from_entry("SPY", entry, fetched_live=True)
        self.assertEqual(ticker["price"], 103.0)
        self.assertEqual(ticker["change"], 2.0)
        self.assertAlmostEqual(ticker["period_return_percent"], 4.0404, places=3)
        self.assertEqual(ticker["period_low"], 96.0)
        self.assertEqual(ticker["period_high"], 104.0)
        self.assertEqual(ticker["history"][0]["date"], "2026-09-04")

    def test_invalid_ohlcv_bars_are_rejected(self) -> None:
        payload = _daily_payload()
        series = payload["Time Series (Daily)"]
        assert isinstance(series, dict)
        series["2026-09-08"] = {"1. open": "101", "2. high": "100", "3. low": "102", "4. close": "103", "5. volume": "-1"}
        parsed = market_client._parse_daily_history(payload)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(len(parsed), 2)

    def test_cache_only_read_never_calls_provider(self) -> None:
        cache = market_client._empty_cache()
        cache["collection_revision"] = 4
        cache["symbols"]["SPY"] = _history_entry()
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_now_utc", return_value=_NOW), mock.patch.object(market_client, "_read_cache", return_value=cache), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPY"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get") as provider:
            response = market_client.read_market_data()
        provider.assert_not_called()
        self.assertEqual(response["collection_revision"], 4)
        self.assertEqual(response["status"], "healthy")
        MarketResponse.model_validate(response)

    def test_invalid_symbol_does_not_prevent_later_symbol_refresh(self) -> None:
        provider = mock.Mock(side_effect=[({}, None), (_daily_payload(), None)])
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_read_cache", return_value=market_client._empty_cache()), mock.patch.object(market_client, "_write_cache"), mock.patch.object(market_client, "get_settings_store", return_value=_store(["BAD", "SPY"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get", provider):
            response = market_client.refresh_market_data()
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(response["status"], "degraded")
        self.assertEqual(response["tickers"][1]["status"], "healthy")
        self.assertEqual(response["reason_code"], "invalid_series")

    def test_successful_symbol_is_requested_only_once_per_utc_day(self) -> None:
        cache = market_client._empty_cache()
        provider = mock.Mock(return_value=(_daily_payload(), None))
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_now_utc", return_value=_NOW), mock.patch.object(market_client, "_read_cache", return_value=cache), mock.patch.object(market_client, "_write_cache"), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPY"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get", provider):
            first = market_client.refresh_market_data()
            second = market_client.refresh_market_data()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(first["freshness"], "live")
        self.assertEqual(second["freshness"], "fresh_cache")
        self.assertEqual(cache["symbols"]["SPY"]["last_successful_fetch_date"], "2026-09-09")
        self.assertEqual(cache["symbols"]["SPY"]["last_attempt_date"], "2026-09-09")

    def test_failed_symbol_uses_daily_exponential_backoff(self) -> None:
        cache = market_client._empty_cache()
        provider = mock.Mock(return_value=({}, None))
        current = [_NOW]
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_now_utc", side_effect=lambda: current[0]), mock.patch.object(market_client, "_read_cache", return_value=cache), mock.patch.object(market_client, "_write_cache"), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPCX"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get", provider):
            first = market_client.refresh_market_data()
            market_client.refresh_market_data()
            current[0] = datetime(2026, 9, 10, 14, 0, tzinfo=timezone.utc)
            second = market_client.refresh_market_data()
            current[0] = datetime(2026, 9, 11, 14, 0, tzinfo=timezone.utc)
            market_client.refresh_market_data()
        entry = cache["symbols"]["SPCX"]
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(first["reason_code"], "invalid_series")
        self.assertEqual(second["reason_code"], "invalid_series")
        self.assertEqual(entry["consecutive_failures"], 2)
        self.assertEqual(entry["last_attempt_date"], "2026-09-10")
        self.assertEqual(entry["next_attempt_date"], "2026-09-12")

    def test_provider_failure_defers_unattempted_symbols_until_next_day(self) -> None:
        cache = market_client._empty_cache()
        provider = mock.Mock(return_value=(None, "timeout"))
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_now_utc", return_value=_NOW), mock.patch.object(market_client, "_read_cache", return_value=cache), mock.patch.object(market_client, "_write_cache"), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPY", "NVDA"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get", provider):
            response = market_client.refresh_market_data()
            market_client.refresh_market_data()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(response["reason_code"], "timeout")
        self.assertEqual(cache["provider_next_attempt_date"], "2026-09-10")
        self.assertEqual(cache["symbols"]["SPY"]["last_attempt_date"], "2026-09-09")
        self.assertNotIn("last_attempt_date", cache["symbols"]["NVDA"])

    def test_provider_request_requires_persisted_attempt_date(self) -> None:
        cache = market_client._empty_cache()
        provider = mock.Mock()
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_now_utc", return_value=_NOW), mock.patch.object(market_client, "_read_cache", return_value=cache), mock.patch.object(market_client, "_write_cache", return_value=False), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPY"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get", provider):
            response = market_client.refresh_market_data()
        provider.assert_not_called()
        self.assertEqual(response["reason_code"], "cache_write_error")
        self.assertNotIn("last_attempt_date", cache["symbols"]["SPY"])

    def test_weekend_fetch_keeps_older_trading_close_fresh_for_that_day(self) -> None:
        weekend = datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)
        cache = market_client._empty_cache()
        provider = mock.Mock(return_value=(_daily_payload(), None))
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_now_utc", return_value=weekend), mock.patch.object(market_client, "_read_cache", return_value=cache), mock.patch.object(market_client, "_write_cache"), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPY"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get", provider):
            market_client.refresh_market_data()
            cached = market_client.read_market_data()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(cached["status"], "healthy")
        self.assertEqual(cached["freshness"], "fresh_cache")
        self.assertEqual(cached["tickers"][0]["close_date"], "2026-09-08")
        self.assertEqual(cached["tickers"][0]["last_successful_fetch_date"], "2026-09-12")

    def test_provider_messages_are_reduced_to_sanitized_reason_codes(self) -> None:
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.side_effect = [
            {"Information": "Our standard API rate limit is 25 requests per day."},
            {"Error Message": "Invalid API call."},
        ]
        with mock.patch.object(market_client, "get_connector_http_session", return_value=None), mock.patch.object(market_client.requests, "get", return_value=response):
            _, quota_error = market_client._alpha_vantage_get({"symbol": "SPY"})
            _, symbol_error = market_client._alpha_vantage_get({"symbol": "BAD"})
        self.assertEqual(quota_error, "daily_rate_limit")
        self.assertEqual(symbol_error, "invalid_symbol")

    def test_partial_fresh_cache_preserves_symbol_failure_reason(self) -> None:
        cache = market_client._empty_cache()
        cache["symbols"]["SPY"] = _history_entry()
        cache["symbols"]["SPCX"] = {
            "last_attempt_date": "2026-09-09",
            "next_attempt_date": "2026-09-10",
            "consecutive_failures": 1,
            "last_error_code": "invalid_symbol",
        }
        with mock.patch.object(market_client, "_now_utc", return_value=_NOW):
            response = market_client._build_snapshot(cache, ["SPY", "SPCX"])
        self.assertEqual(response["status"], "degraded")
        self.assertEqual(response["freshness"], "fresh_cache")
        self.assertEqual(response["reason_code"], "invalid_symbol")
        self.assertEqual(response["tickers"][1]["next_attempt_date"], "2026-09-10")

    def test_cache_v2_migration_preserves_history_and_derives_daily_gate(self) -> None:
        cache_file = mock.mock_open(
            read_data='{"version":2,"collection_revision":7,"symbols":{"SPY":{"price":103,"market_fetched_at":"2026-09-09T13:00:00+00:00","history":[]}}}'
        )
        with mock.patch("pathlib.Path.open", cache_file):
            cache = market_client._read_cache()
        self.assertEqual(cache["version"], 3)
        self.assertEqual(cache["collection_revision"], 7)
        self.assertEqual(cache["symbols"]["SPY"]["price"], 103)
        self.assertEqual(cache["symbols"]["SPY"]["history"], [])
        self.assertEqual(cache["symbols"]["SPY"]["last_successful_fetch_date"], "2026-09-09")
        self.assertEqual(cache["symbols"]["SPY"]["last_attempt_date"], "2026-09-09")

    def test_demo_returns_valid_history_without_credentials(self) -> None:
        with mock.patch.object(market_client, "DEMO_MODE", True), mock.patch.object(market_client, "get_settings_store", return_value=_store([])), mock.patch.object(market_client, "_alpha_vantage_get") as provider:
            response = market_client.read_market_data()
        provider.assert_not_called()
        self.assertEqual(response["status"], "healthy")
        self.assertEqual(len(response["tickers"][0]["history"]), 20)
        MarketResponse.model_validate(response)

    def test_market_contributes_to_snapshot_health_but_not_briefing_facts(self) -> None:
        market = ConnectorResult(
            name="market", status="unavailable", freshness="none", reason_code="not_configured",
            observed_at=market_client._iso_utc(), data={"collection_revision": 0},
        )
        snapshot = build_snapshot_from_results({"market": market})
        self.assertIn("market", snapshot.failed_connectors)
        self.assertIn("market", [entry.name for entry in snapshot.connector_health])
        facts = _build_synthesis_input(results=snapshot.results_map(), failed_connectors=snapshot.failed_connectors)
        self.assertNotIn("market", facts.failed_connectors)
        self.assertNotIn("market", [entry.name for entry in facts.connector_health])

    def test_targeted_collection_and_failed_refresh_do_not_restore_removed_symbols(self) -> None:
        healthy = ConnectorResult(name="market", status="healthy", freshness="live", observed_at=market_client._iso_utc(), data={"tickers": [{"symbol": "OLD"}]})
        unavailable = ConnectorResult(name="market", status="unavailable", freshness="none", reason_code="not_configured", observed_at=market_client._iso_utc(), data={"tickers": []})
        with mock.patch("core.telemetry.collector.market_client.collect_market", return_value=healthy) as collect:
            results = collect_connector_results(features=FeaturesSettings(market=True), modules=ModulesSettings(), connectors=["market"])
        collect.assert_called_once_with()
        prior = build_snapshot_from_results(results)
        current = build_snapshot_from_results({"market": unavailable}, prior=prior)
        self.assertEqual(current.modules["market"].status, "unavailable")
        self.assertEqual(current.modules["market"].data["tickers"], [])


if __name__ == "__main__":
    unittest.main()
