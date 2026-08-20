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
    hourly: str | None = None,
    forecast_days: int | None = None,
    wind_speed_unit: str = "mph",
    precipitation_unit: str = "inch",
) -> dict[str, Any] | None:
    latitude, longitude = coordinates
    params: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": wind_speed_unit,
        "precipitation_unit": precipitation_unit,
        "timezone": "auto",
    }
    if current is not None:
        params["current"] = current
    if daily is not None:
        params["daily"] = daily
    if hourly is not None:
        params["hourly"] = hourly
    if forecast_days is not None:
        params["forecast_days"] = forecast_days

    status_code, payload = _request_json(_FORECAST_URL, params)
    return payload if status_code == 200 else None


def _format_hour_label(iso_time: str) -> str:
    if "T" in iso_time:
        time_part = iso_time.split("T")[1]
        hour_str = time_part.split(":")[0]
        try:
            hour = int(hour_str)
            suffix = "AM" if hour < 12 else "PM"
            h12 = hour % 12
            if h12 == 0:
                h12 = 12
            return f"{h12} {suffix}"
        except ValueError:
            pass
    return iso_time


def _extract_timeline(
    payload: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        return []

    times = hourly.get("time")
    temps = hourly.get("temperature_2m")
    codes = hourly.get("weather_code")
    days = hourly.get("is_day")
    probs = hourly.get("precipitation_probability")

    if not isinstance(times, list) or not isinstance(temps, list):
        return []

    current_time = str(current.get("time", "")).strip() if isinstance(current, dict) else ""
    start_idx = 0
    if current_time and current_time in times:
        start_idx = times.index(current_time)
    elif current_time and "T" in current_time:
        prefix = current_time[:13]
        for idx, t in enumerate(times):
            if isinstance(t, str) and t.startswith(prefix):
                start_idx = idx
                break

    offsets = [(0, "NOW"), (4, "+4H"), (8, "+8H")]
    timeline: list[dict[str, Any]] = []

    for offset, label in offsets:
        target_idx = start_idx + offset
        if target_idx < len(times):
            t_str = str(times[target_idx])
            temp_val = _as_finite_float(temps[target_idx]) if target_idx < len(temps) else None
            code_val = codes[target_idx] if isinstance(codes, list) and target_idx < len(codes) else None
            day_val = days[target_idx] if isinstance(days, list) and target_idx < len(days) else None
            prob_val = _as_finite_float(probs[target_idx]) if isinstance(probs, list) and target_idx < len(probs) else None

            condition = _weather_condition(code_val, is_day=day_val)
            desc, archetype = condition if condition else ("unknown", "clouds")
            formatted_time = _format_hour_label(t_str)

            timeline.append(
                {
                    "label": label,
                    "time": formatted_time,
                    "temp_f": round(temp_val) if temp_val is not None else None,
                    "condition": desc,
                    "archetype": archetype,
                    "precip_prob": round(prob_val) if prob_val is not None else 0,
                }
            )

    return timeline


def _parse_current_conditions(current: dict[str, Any] | None) -> dict[str, Any] | None:
    """Parse real-time atmospheric conditions from an Open-Meteo current payload."""
    if not isinstance(current, dict):
        return None

    temperature = _as_finite_float(current.get("temperature_2m"))
    condition = _weather_condition(
        current.get("weather_code"), is_day=current.get("is_day")
    )
    if temperature is None or condition is None:
        return None

    description, archetype = condition
    result: dict[str, Any] = {
        "temp_f": round(temperature),
        "condition": description,
        "archetype": archetype,
    }
    apparent_raw = _as_finite_float(current.get("apparent_temperature"))
    if apparent_raw is not None:
        result["apparent_temp_f"] = round(apparent_raw)
    humidity_raw = _as_finite_float(current.get("relative_humidity_2m"))
    if humidity_raw is not None:
        result["humidity_pct"] = round(humidity_raw)
    wind_raw = _as_finite_float(current.get("wind_speed_10m"))
    if wind_raw is not None:
        result["wind_speed_mph"] = round(wind_raw)

    return result


def _get_daily_metric(
    values: list[Any] | None, index: int, decimals: int | None = None
) -> float | int | None:
    """Extract and round a numerical metric at an index from a daily payload list."""
    if not isinstance(values, list) or index >= len(values):
        return None
    val = _as_finite_float(values[index])
    if val is None:
        return None
    return round(val) if decimals is None else round(val, decimals)


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
            current="temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            daily="temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max,precipitation_sum,wind_speed_10m_max",
            hourly="temperature_2m,weather_code,is_day,precipitation_probability,wind_speed_10m",
            forecast_days=10,
        )
        current_data = _parse_current_conditions(payload.get("current") if payload is not None else None)
        if current_data is None:
            raise ValueError("Weather provider current conditions were incomplete.")

        daily = payload.get("daily") if payload is not None else None
        maxs = daily.get("temperature_2m_max") if isinstance(daily, dict) else None
        mins = daily.get("temperature_2m_min") if isinstance(daily, dict) else None
        probs = daily.get("precipitation_probability_max") if isinstance(daily, dict) else None
        sums = daily.get("precipitation_sum") if isinstance(daily, dict) else None

        temp_max_f = _get_daily_metric(maxs, 0)
        temp_min_f = _get_daily_metric(mins, 0)
        precip_probability_max = _get_daily_metric(probs, 0)
        precip_sum_in = _get_daily_metric(sums, 0, decimals=2)

        timeline = _extract_timeline(payload, payload.get("current") if payload is not None else None)

        temp_f = current_data["temp_f"]
        apparent_temp_f = current_data.get("apparent_temp_f")
        description = current_data["condition"]

        parts = [f"Current temperature is {temp_f} degrees"]
        if apparent_temp_f is not None:
            parts.append(f"(feels like {apparent_temp_f})")
        parts.append(f"with {description}.")
        if temp_max_f is not None and temp_min_f is not None:
            parts.append(f"Today's high is {temp_max_f}, low {temp_min_f}.")
        display_text = " ".join(parts)

        data: dict[str, Any] = {
            **current_data,
            "location": location,
            "timeline": timeline,
            "timezone": str(payload.get("timezone") or "America/New_York"),
        }
        daily_times = daily.get("time") if isinstance(daily, dict) else None
        daily_codes = daily.get("weather_code") if isinstance(daily, dict) else None
        daily_wind = daily.get("wind_speed_10m_max") if isinstance(daily, dict) else None
        if isinstance(daily_times, list):
            forecasts: list[dict[str, Any]] = []
            for index, day in enumerate(daily_times[:10]):
                condition = _weather_condition(
                    daily_codes[index] if isinstance(daily_codes, list) and index < len(daily_codes) else None,
                    is_day=True,
                )
                forecasts.append({
                    "date": str(day),
                    "temp_max_f": _get_daily_metric(maxs, index),
                    "temp_min_f": _get_daily_metric(mins, index),
                    "precip_probability": _get_daily_metric(probs, index),
                    "precipitation_in": _get_daily_metric(sums, index, decimals=2),
                    "wind_speed_mph": _get_daily_metric(daily_wind, index),
                    "condition": condition[0] if condition else None,
                })
            data["daily"] = forecasts

        raw_hourly = payload.get("hourly") if isinstance(payload, dict) else None
        if isinstance(raw_hourly, dict) and isinstance(raw_hourly.get("time"), list):
            forecasts = []
            for index, hour in enumerate(raw_hourly["time"][:48]):
                condition = _weather_condition(
                    raw_hourly.get("weather_code", [None])[index] if isinstance(raw_hourly.get("weather_code"), list) and index < len(raw_hourly.get("weather_code", [])) else None,
                    is_day=raw_hourly.get("is_day", [None])[index] if isinstance(raw_hourly.get("is_day"), list) and index < len(raw_hourly.get("is_day", [])) else None,
                )
                forecasts.append({
                    "time": str(hour),
                    "temp_f": _get_daily_metric(raw_hourly.get("temperature_2m"), index),
                    "precip_probability": _get_daily_metric(raw_hourly.get("precipitation_probability"), index),
                    "wind_speed_mph": _get_daily_metric(raw_hourly.get("wind_speed_10m"), index),
                    "condition": condition[0] if condition else None,
                })
            data["hourly"] = forecasts
        if temp_max_f is not None:
            data["temp_max_f"] = temp_max_f
        if temp_min_f is not None:
            data["temp_min_f"] = temp_min_f
        if precip_probability_max is not None:
            data["precip_probability_max"] = precip_probability_max
        if precip_sum_in is not None:
            data["precip_sum_in"] = precip_sum_in

        return _weather_result(
            status="healthy",
            reason_code="ok",
            freshness="live",
            display_text=display_text,
            data=data,
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


def fetch_weather_forecast(location: str | None = None, days: int = 5) -> dict[str, Any]:
    """Fetch an enriched multi-day Open-Meteo forecast and current conditions for any location or configured default."""
    resolved_location = location.strip() if isinstance(location, str) and location.strip() else _configured_location()
    if resolved_location is None:
        return {"error": "Weather forecast offline: Missing target location."}

    max_days = max(1, min(14, days))
    try:
        coordinates = _resolve_coordinates(resolved_location)
        if coordinates is None:
            return {"error": "Weather forecast unavailable."}

        payload = _forecast_payload(
            coordinates,
            current="temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            daily="temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,uv_index_max",
            forecast_days=max_days,
        )
        if payload is None:
            raise ValueError("Weather provider returned no response.")

        current_data = _parse_current_conditions(payload.get("current"))

        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise ValueError("Weather provider returned no daily forecast.")

        dates = daily.get("time")
        maximums = daily.get("temperature_2m_max")
        minimums = daily.get("temperature_2m_min")
        weather_codes = daily.get("weather_code")
        precip_probs = daily.get("precipitation_probability_max")
        precip_sums = daily.get("precipitation_sum")
        wind_speeds = daily.get("wind_speed_10m_max")
        uv_indices = daily.get("uv_index_max")

        if not all(isinstance(values, list) for values in (dates, maximums, minimums, weather_codes)):
            raise ValueError("Weather provider daily forecast was incomplete.")

        forecast: list[dict[str, Any]] = []
        for i, (date, maximum, minimum, weather_code) in enumerate(
            zip(dates, maximums, minimums, weather_codes, strict=True)
        ):
            max_temp = _as_finite_float(maximum)
            min_temp = _as_finite_float(minimum)
            condition = _weather_condition(weather_code)
            if not isinstance(date, str) or max_temp is None or min_temp is None or condition is None:
                raise ValueError("Weather provider daily forecast entry was invalid.")

            day_entry: dict[str, Any] = {
                "date": date,
                "temp_max": round(max_temp, 1),
                "temp_min": round(min_temp, 1),
                "condition": condition[0],
            }
            precip_prob = _get_daily_metric(precip_probs, i)
            if precip_prob is not None:
                day_entry["precip_probability_max"] = precip_prob
            precip_sum = _get_daily_metric(precip_sums, i, decimals=2)
            if precip_sum is not None:
                day_entry["precip_sum_in"] = precip_sum
            wind_speed = _get_daily_metric(wind_speeds, i)
            if wind_speed is not None:
                day_entry["wind_speed_max_mph"] = wind_speed
            uv_index = _get_daily_metric(uv_indices, i, decimals=1)
            if uv_index is not None:
                day_entry["uv_index_max"] = uv_index

            forecast.append(day_entry)

        result: dict[str, Any] = {
            "location": resolved_location,
            "forecast": forecast,
        }
        if current_data is not None:
            result["current"] = current_data

        return result
    except (requests.RequestException, TypeError, ValueError, KeyError):
        return {"error": "Weather forecast unavailable."}
    except (requests.RequestException, TypeError, ValueError, KeyError):
        return {"error": "Weather forecast unavailable."}


if __name__ == "__main__":
    print("[WEATHER]: Weather client diagnostics")
    print(f"[WEATHER]: {fetch_weather_data()}")
