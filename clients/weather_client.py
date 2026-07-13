"""OpenWeatherMap connector with typed briefing results."""

from __future__ import annotations

import os
from collections import Counter
from typing import Any

import requests
from dotenv import load_dotenv

from core.connectors.models import ConnectorResult, utc_now_iso

load_dotenv()


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


def collect_weather() -> ConnectorResult:
    """Collect current weather as a typed connector result."""
    api_key = os.getenv("OPENWEATHER_API_KEY")
    location = os.getenv("TARGET_LOCATION")

    if not api_key or not location:
        return _weather_result(
            status="unavailable",
            reason_code="missing_credentials",
            display_text="Weather API offline: Missing API key or location.",
        )

    url = (
        f"http://api.openweathermap.org/data/2.5/weather"
        f"?q={location}&appid={api_key}&units=imperial"
    )

    try:
        response = requests.get(url, timeout=10.0)
        payload = response.json()

        if response.status_code == 200:
            temp = round(payload["main"]["temp"])
            condition = payload["weather"][0]["description"]
            display = f"Current temperature is {temp} degrees with {condition}."
            return _weather_result(
                status="healthy",
                reason_code="ok",
                freshness="live",
                display_text=display,
                data={
                    "temp_f": temp,
                    "condition": condition,
                    "location": location,
                    "archetype": _condition_archetype(condition),
                },
            )

        return _weather_result(
            status="unavailable",
            reason_code="provider_error",
            display_text=(
                f"Weather API error: {payload.get('message', 'Unknown error')}."
            ),
        )
    except Exception:
        return _weather_result(
            status="unavailable",
            reason_code="network_error",
            display_text="Failed to connect to Weather API.",
        )


def _condition_archetype(condition: str) -> str:
    lowered = condition.lower()
    if "thunder" in lowered:
        return "thunderstorm"
    if any(token in lowered for token in ("rain", "drizzle", "shower")):
        return "rain"
    if any(token in lowered for token in ("cloud", "overcast", "mist", "fog")):
        return "clouds"
    if any(token in lowered for token in ("clear", "sun")):
        return "clear_day"
    return "clouds"


def fetch_weather_data() -> str:
    """Compatibility façade returning display text for non-briefing callers."""
    return collect_weather().display_text


def fetch_weather_forecast(days: int = 5) -> dict[str, Any]:
    """Fetch a multi-day weather forecast from OpenWeatherMap.

    Args:
        days: Maximum number of daily forecast records to return (capped at 5).

    Returns:
        dict: Location and grouped daily forecast records, or an error payload.
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    location = os.getenv("TARGET_LOCATION")

    if not api_key or not location:
        return {"error": "Weather forecast offline: Missing API key or location."}

    url = (
        f"http://api.openweathermap.org/data/2.5/forecast"
        f"?q={location}&appid={api_key}&units=imperial"
    )

    try:
        response = requests.get(url, timeout=10.0)
        data = response.json()

        if response.status_code != 200:
            message = data.get("message", "Unknown error")
            return {"error": f"Weather API error: {message}."}

        daily_records: dict[str, dict[str, Any]] = {}

        for entry in data.get("list", []):
            dt_txt = entry.get("dt_txt", "")
            date = dt_txt.split(" ")[0] if dt_txt else ""
            if not date:
                continue

            main = entry.get("main", {})
            temp = main.get("temp")
            if temp is None:
                continue

            weather_items = entry.get("weather", [])
            condition = (
                weather_items[0].get("description", "unknown")
                if weather_items
                else "unknown"
            )
            temp_value = float(temp)

            if date not in daily_records:
                daily_records[date] = {
                    "date": date,
                    "temp_max": temp_value,
                    "temp_min": temp_value,
                    "conditions": [condition],
                }
                continue

            record = daily_records[date]
            record["temp_max"] = max(record["temp_max"], temp_value)
            record["temp_min"] = min(record["temp_min"], temp_value)
            record["conditions"].append(condition)

        max_days = max(1, min(5, days))
        forecast: list[dict[str, Any]] = []

        for date in sorted(daily_records.keys())[:max_days]:
            record = daily_records[date]
            conditions: list[str] = record.pop("conditions")
            condition = Counter(conditions).most_common(1)[0][0]
            forecast.append(
                {
                    "date": date,
                    "temp_max": round(record["temp_max"], 1),
                    "temp_min": round(record["temp_min"], 1),
                    "condition": condition,
                }
            )

        return {"location": location, "forecast": forecast}

    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    print("[WEATHER]: Weather client diagnostics")
    print(f"[WEATHER]: {fetch_weather_data()}")
