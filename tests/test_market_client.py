"""Regression coverage for market configuration and demo boundaries."""

from __future__ import annotations

import unittest
from unittest import mock

from clients import market_client
from core.api.models import MarketResponse


class MarketConfigurationTests(unittest.TestCase):
    def test_missing_api_key_returns_empty_not_configured_response(self) -> None:
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.dict(
            market_client.os.environ,
            {"MARKET_SYMBOLS": "SPY,AAPL"},
            clear=True,
        ), mock.patch.object(market_client, "_alpha_vantage_get") as provider:
            response = market_client.fetch_market_data()

        self.assertEqual(response["status"], "not_configured")
        self.assertEqual(response["tickers"], [])
        provider.assert_not_called()
        self.assertEqual(MarketResponse.model_validate(response).model_dump(), response)

    def test_missing_symbols_returns_empty_not_configured_response(self) -> None:
        with mock.patch.object(market_client, "DEMO_MODE", False), mock.patch.dict(
            market_client.os.environ,
            {"ALPHA_VANTAGE_API_KEY": "configured"},
            clear=True,
        ), mock.patch.object(market_client, "_alpha_vantage_get") as provider:
            response = market_client.fetch_market_data()

        self.assertEqual(response["status"], "not_configured")
        self.assertEqual(response["tickers"], [])
        provider.assert_not_called()

    def test_demo_mode_returns_simulated_live_tickers_without_credentials(self) -> None:
        with mock.patch.object(market_client, "DEMO_MODE", True), mock.patch.dict(
            market_client.os.environ,
            {},
            clear=True,
        ), mock.patch.object(market_client, "_alpha_vantage_get") as provider:
            response = market_client.fetch_market_data()

        self.assertEqual(response["status"], "live")
        self.assertEqual(
            [ticker["symbol"] for ticker in response["tickers"]],
            ["SPY", "AAPL", "MSFT"],
        )
        self.assertTrue(all(ticker["status"] == "live" for ticker in response["tickers"]))
        provider.assert_not_called()
        MarketResponse.model_validate(response)


if __name__ == "__main__":
    unittest.main()
