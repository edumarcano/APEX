"""Open-Meteo connector with typed briefing results."""

from __future__ import annotations

import math
import os
from typing import Any

import requests
from dotenv import load_dotenv

from clients.http_sessions import get_connector_http_session
from core.connectors.models import ConnectorResult, utc_now_iso

load_dotenv()

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_REQUEST_TIMEOUT_SECONDS = 10.0

_WMO_CONDITIONS: dict[int, tuple[str, str]] = {
    0: ("clear sky", "clear_day"),
    1: ("mainly clear", "clear_day"),
    2: ("partly cloudy", "clouds"),
    3: ("overcast", "clouds"),
    45: ("fog", "clouds"),
    48: ("rime fog", "clouds"),
    51: ("light drizzle", "rain"),
    53: ("moderate drizzle", "rain"),
    55: ("dense drizzle", "rain"),
    56: ("light freezing drizzle", "rain"),
    57: ("dense freezing drizzle", "rain"),
    61: ("slight rain", "rain"),
    63: ("moderate rain", "rain"),
    65: ("heavy rain", "rain"),
    66: ("light freezing rain", "rain"),
    67: ("heavy freezing rain", "rain"),
    71: ("slight snow fall", "clouds"),
    73: ("moderate snow fall", "clouds"),
    75: ("heavy snow fall", "clouds"),
    77: ("snow grains", "clouds"),
    80: ("slight rain showers", "rain"),
    81: ("moderate rain showers", "rain"),
    82: ("violent rain showers", "rain"),
    85: ("slight snow showers", "clouds"),
    86: ("heavy snow showers", "clouds"),
    95: ("thunderstorm", "thunderstorm"),
    96: ("thunderstorm with slight hail", "thunderstorm"),
    99: ("thunderstorm with heavy hail", "thunderstorm"),
}


def _weather_result(
    *,
    status: str,
    reason_code: str,
    display_text: str,
    data: dict[str, Any] | None = None,
    freshness: str = "none",
) -> ConnectorResult:
    return ConnectorResult(
        name="weather",
        status=status,  # type: ignore[arg-type]
        freshness=freshness,  # type: ignore[arg-type]
        reason_code=reason_code,
        observed_at=utc_now_iso(),
        display_text=display_text,
        data=data or {},
    )


def _request_json(url: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Request one Open-Meteo JSON resource through the shared session."""
    session = get_connector_http_session("weather")
    response = (
        session.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
        if session is not None
        else requests.get(url, params=params, timeout=_REQUEST_TIMEOUT_SECONDS)
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Weather provider returned a non-object payload.")
    return response.status_code, payload


def _configured_location() -> str | None:
    location = os.getenv("TARGET_LOCATION", "").strip()
    return location or None


def _as_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _weather_condition(value: Any, *, is_day: Any = None) -> tuple[str, str] | None:
    numeric = _as_finite_float(value)
    if numeric is None or not numeric.is_integer():
        return None
    condition = _WMO_CONDITIONS.get(int(numeric), ("unknown conditions", "clouds"))
    if int(numeric) in {0, 1}:
        day_flag = _as_finite_float(is_day)
        if day_flag is not None and day_flag in {0.0, 1.0}:
            return condition[0], "clear_day" if day_flag == 1.0 else "clear_night"
    return condition


def _resolve_coordinates(location: str) -> tuple[float, float] | None:
    status_code, payload = _request_json(
        _GEOCODING_URL,
        {"name": location, "count": 1, "language": "en", "format": "json"},
    )
    if status_code != 200:
        return None

    results = payload.get("results")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return None

    latitude = _as_finite_float(results[0].get("latitude"))
    longitude = _as_finite_float(results[0].get("longitude"))
    if latitude is None or longitude is None:
        return None
    return latitude, longitude


def _forecast_payload(
    coordinates: tuple[float, float],
    *,
    current: str | None = None,
    daily: str | None = None,
    forecast_days: int | None = None,
) -> dict[str, Any] | None:
    latitude, longitude = coordinates
    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
    }
    if current is not None:
        params["current"] = current
    if daily is not None:
        params["daily"] = daily
    if forecast_days is not None:
        params["forecast_days"] = forecast_days

    status_code, payload = _request_json(_FORECAST_URL, params)
    return payload if status_code == 200 else None


def collect_weather() -> ConnectorResult:
    """Collect current weather as a typed connector result."""
    location = _configured_location()
    if location is None:
        return _weather_result(
            status="unavailable",
            reason_code="missing_credentials",
            display_text="Weather API offline: Missing target location.",
        )

    try:
        coordinates = _resolve_coordinates(location)
        if coordinates is None:
            return _weather_result(
                status="unavailable",
                reason_code="provider_error",
                display_text="Weather API error: Location could not be resolved.",
            )

        payload = _forecast_payload(
            coordinates,
            current="temperature_2m,weather_code,is_day",
            forecast_days=1,
        )
        current = payload.get("current") if payload is not None else None
        if not isinstance(current, dict):
            raise ValueError("Weather provider returned no current conditions.")

        temperature = _as_finite_float(current.get("temperature_2m"))
        condition = _weather_condition(
            current.get("weather_code"), is_day=current.get("is_day")
        )
        if temperature is None or condition is None:
            raise ValueError("Weather provider current conditions were incomplete.")

        description, archetype = condition
        temp_f = round(temperature)
        return _weather_result(
            status="healthy",
            reason_code="ok",
            freshness="live",
            display_text=f"Current temperature is {temp_f} degrees with {description}.",
            data={
                "temp_f": temp_f,
                "condition": description,
                "location": location,
                "archetype": archetype,
            },
        )
    except requests.RequestException:
        return _weather_result(
            status="unavailable",
            reason_code="network_error",
            display_text="Failed to connect to Weather API.",
        )
    except (TypeError, ValueError, KeyError):
        return _weather_result(
            status="unavailable",
            reason_code="provider_error",
            display_text="Weather API error: Invalid provider response.",
        )


def fetch_weather_data() -> str:
    """Compatibility facade returning display text for non-briefing callers."""
    return collect_weather().display_text


def fetch_weather_forecast(days: int = 5) -> dict[str, Any]:
    """Fetch a multi-day Open-Meteo forecast for the configured location."""
    location = _configured_location()
    if location is None:
        return {"error": "Weather forecast offline: Missing target location."}

    max_days = max(1, min(5, days))
    try:
        coordinates = _resolve_coordinates(location)
        if coordinates is None:
            return {"error": "Weather forecast unavailable."}

        payload = _forecast_payload(
            coordinates,
            daily="temperature_2m_max,temperature_2m_min,weather_code",
            forecast_days=max_days,
        )
        daily = payload.get("daily") if payload is not None else None
        if not isinstance(daily, dict):
            raise ValueError("Weather provider returned no daily forecast.")

        dates = daily.get("time")
        maximums = daily.get("temperature_2m_max")
        minimums = daily.get("temperature_2m_min")
        weather_codes = daily.get("weather_code")
        if not all(isinstance(values, list) for values in (dates, maximums, minimums, weather_codes)):
            raise ValueError("Weather provider daily forecast was incomplete.")

        forecast: list[dict[str, Any]] = []
        for date, maximum, minimum, weather_code in zip(
            dates, maximums, minimums, weather_codes, strict=True
        ):
            max_temp = _as_finite_float(maximum)
            min_temp = _as_finite_float(minimum)
            condition = _weather_condition(weather_code)
            if not isinstance(date, str) or max_temp is None or min_temp is None or condition is None:
                raise ValueError("Weather provider daily forecast entry was invalid.")
            forecast.append(
                {
                    "date": date,
                    "temp_max": round(max_temp, 1),
                    "temp_min": round(min_temp, 1),
                    "condition": condition[0],
                }
            )

        return {"location": location, "forecast": forecast}
    except (requests.RequestException, TypeError, ValueError, KeyError):
        return {"error": "Weather forecast unavailable."}


if __name__ == "__main__":
    print("[WEATHER]: Weather client diagnostics")
    print(f"[WEATHER]: {fetch_weather_data()}")
