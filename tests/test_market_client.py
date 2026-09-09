"""Regression coverage for market cache, parsing, and telemetry boundaries."""

from __future__ import annotations

import unittest
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
        cache["symbols"]["SPY"] = {"history": market_client._parse_daily_history(_daily_payload()), "market_fetched_at": market_client._iso_utc()}
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.object(market_client, "_read_cache", return_value=cache), mock.patch.object(market_client, "get_settings_store", return_value=_store(["SPY"])), mock.patch.dict(market_client.os.environ, {"ALPHA_VANTAGE_API_KEY": "configured"}, clear=True), mock.patch.object(market_client, "_alpha_vantage_get") as provider:
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
