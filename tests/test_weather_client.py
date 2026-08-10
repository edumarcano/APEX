"""Focused contract coverage for the Open-Meteo weather connector."""

from __future__ import annotations

import unittest
from unittest import mock

import requests

from clients import weather_client


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


class _Session:
    def __init__(self, *responses: _Response | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _geocoding_payload() -> dict[str, object]:
    return {"results": [{"latitude": 42.3601, "longitude": -71.0589}]}


class OpenMeteoWeatherClientTests(unittest.TestCase):
    def test_collect_weather_resolves_location_and_requests_fahrenheit_current_conditions(
        self,
    ) -> None:
        session = _Session(
            _Response(_geocoding_payload()),
            _Response({"current": {"temperature_2m": 70.6, "weather_code": 2, "is_day": 1}}),
        )

        with mock.patch.dict("os.environ", {"TARGET_LOCATION": "Boston"}, clear=False), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=session
        ):
            result = weather_client.collect_weather()

        self.assertEqual(result.status, "healthy")
        self.assertIn("71 degrees", result.display_text)
        self.assertIn("partly cloudy", result.display_text)
        self.assertEqual(
            result.data,
            {
                "temp_f": 71,
                "condition": "partly cloudy",
                "location": "Boston",
                "archetype": "clouds",
            },
        )
        self.assertEqual(session.calls[0][0], weather_client._GEOCODING_URL)
        self.assertEqual(
            session.calls[0][1]["params"],
            {"name": "Boston", "count": 1, "language": "en", "format": "json"},
        )
        self.assertEqual(session.calls[1][0], weather_client._FORECAST_URL)
        self.assertEqual(
            session.calls[1][1]["params"],
            {
                "latitude": 42.3601,
                "longitude": -71.0589,
                "temperature_unit": "fahrenheit",
                "timezone": "auto",
                "current": "temperature_2m,weather_code,is_day",
                "forecast_days": 1,
            },
        )
        self.assertEqual(session.calls[0][1]["timeout"], 10.0)
        self.assertEqual(session.calls[1][1]["timeout"], 10.0)

    def test_collect_weather_uses_provider_day_night_signal_for_clear_conditions(self) -> None:
        session = _Session(
            _Response(_geocoding_payload()),
            _Response({"current": {"temperature_2m": 58, "weather_code": 1, "is_day": 0}}),
        )

        with mock.patch.dict("os.environ", {"TARGET_LOCATION": "Boston"}, clear=False), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=session
        ):
            result = weather_client.collect_weather()

        self.assertEqual(result.data["archetype"], "clear_night")

    def test_forecast_preserves_daily_contract_and_clamps_requested_days(self) -> None:
        session = _Session(
            _Response(_geocoding_payload()),
            _Response(
                {
                    "daily": {
                        "time": ["2026-08-10", "2026-08-11", "2026-08-12"],
                        "temperature_2m_max": [81.25, 76, 71.5],
                        "temperature_2m_min": [65.75, 61, 57.5],
                        "weather_code": [0, 45, 95],
                    }
                }
            ),
        )

        with mock.patch.dict("os.environ", {"TARGET_LOCATION": "Boston"}, clear=False), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=session
        ):
            result = weather_client.fetch_weather_forecast(days=99)

        self.assertEqual(
            result,
            {
                "location": "Boston",
                "forecast": [
                    {
                        "date": "2026-08-10",
                        "temp_max": 81.2,
                        "temp_min": 65.8,
                        "condition": "clear sky",
                    },
                    {
                        "date": "2026-08-11",
                        "temp_max": 76.0,
                        "temp_min": 61.0,
                        "condition": "fog",
                    },
                    {
                        "date": "2026-08-12",
                        "temp_max": 71.5,
                        "temp_min": 57.5,
                        "condition": "thunderstorm",
                    },
                ],
            },
        )
        self.assertEqual(session.calls[1][1]["params"]["forecast_days"], 5)
        self.assertEqual(
            session.calls[1][1]["params"]["daily"],
            "temperature_2m_max,temperature_2m_min,weather_code",
        )

    def test_weather_code_mapping_covers_clear_cloud_fog_rain_snow_and_thunderstorm(self) -> None:
        self.assertEqual(weather_client._weather_condition(0), ("clear sky", "clear_day"))
        self.assertEqual(
            weather_client._weather_condition(0, is_day=0),
            ("clear sky", "clear_night"),
        )
        self.assertEqual(
            weather_client._weather_condition(1, is_day=0),
            ("mainly clear", "clear_night"),
        )
        self.assertEqual(weather_client._weather_condition(3), ("overcast", "clouds"))
        self.assertEqual(weather_client._weather_condition(45), ("fog", "clouds"))
        self.assertEqual(weather_client._weather_condition(63), ("moderate rain", "rain"))
        self.assertEqual(weather_client._weather_condition(73), ("moderate snow fall", "clouds"))
        self.assertEqual(weather_client._weather_condition(96), ("thunderstorm with slight hail", "thunderstorm"))

    def test_missing_location_and_unresolvable_location_are_stable_failures(self) -> None:
        with mock.patch.dict("os.environ", {"TARGET_LOCATION": ""}, clear=False):
            current = weather_client.collect_weather()
            forecast = weather_client.fetch_weather_forecast()

        self.assertEqual(current.reason_code, "missing_credentials")
        self.assertEqual(current.display_text, "Weather API offline: Missing target location.")
        self.assertEqual(forecast, {"error": "Weather forecast offline: Missing target location."})

        session = _Session(_Response({"results": []}))
        with mock.patch.dict("os.environ", {"TARGET_LOCATION": "Missing Place"}, clear=False), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=session
        ):
            current = weather_client.collect_weather()

        forecast_session = _Session(_Response({"results": []}))
        with mock.patch.dict("os.environ", {"TARGET_LOCATION": "Missing Place"}, clear=False), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=forecast_session
        ):
            forecast = weather_client.fetch_weather_forecast()

        self.assertEqual(current.reason_code, "provider_error")
        self.assertEqual(current.display_text, "Weather API error: Location could not be resolved.")
        self.assertEqual(forecast, {"error": "Weather forecast unavailable."})

    def test_malformed_provider_payload_and_network_error_are_stable_failures(self) -> None:
        malformed_session = _Session(
            _Response(_geocoding_payload()),
            _Response({"current": {"temperature_2m": "not-a-number"}}),
        )
        with mock.patch.dict("os.environ", {"TARGET_LOCATION": "Boston"}, clear=False), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=malformed_session
        ):
            malformed = weather_client.collect_weather()

        self.assertEqual(malformed.reason_code, "provider_error")
        self.assertEqual(malformed.display_text, "Weather API error: Invalid provider response.")

        network_session = _Session(requests.ConnectionError("offline"))
        with mock.patch.dict("os.environ", {"TARGET_LOCATION": "Boston"}, clear=False), mock.patch.object(
            weather_client, "get_connector_http_session", return_value=network_session
        ):
            network = weather_client.collect_weather()

        self.assertEqual(network.reason_code, "network_error")
        self.assertEqual(network.display_text, "Failed to connect to Weather API.")

if __name__ == "__main__":
    unittest.main()
