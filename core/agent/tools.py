from typing import Any, Callable

from clients.sports_client import fetch_f1_driver_standings, fetch_f1_season_calendar
from clients.weather_client import fetch_weather_data, fetch_weather_forecast


def get_current_weather() -> str:
    """Retrieve the current weather for the configured target location.

    Reads live conditions from OpenWeatherMap for the location set in the
    TARGET_LOCATION environment variable. No parameters are required.

    Returns:
        str: A human-readable summary of the current temperature and weather
            condition, or an error message if the API is unavailable.
    """
    return fetch_weather_data()


def get_weather_forecast(days: int = 5) -> dict[str, Any]:
    """Retrieve a multi-day weather forecast for the configured target location.

    Groups OpenWeatherMap 3-hour forecast entries into daily high/low
    temperature and condition summaries.

    Args:
        days: Number of forecast days to return. Values below 1 are raised to
            1; values above 5 are lowered to 5.

    Returns:
        dict: A payload with ``location`` and ``forecast`` (list of daily
            records containing ``date``, ``temp_max``, ``temp_min``, and
            ``condition``), or an ``error`` key on failure.
    """
    clamped_days = max(1, min(5, days))
    return fetch_weather_forecast(clamped_days)


def get_f1_driver_standings() -> dict[str, Any]:
    """Retrieve current Formula 1 driver championship standings.

    Fetches the latest driver points table from the Ergast F1 API for the
    active season. No parameters are required.

    Returns:
        dict: A payload with ``season``, ``round``, and ``standings`` (list of
            driver records with ``position``, ``points``, ``wins``,
            ``driver_name``, ``driver_code``, and ``team``), or an ``error``
            key on failure.
    """
    return fetch_f1_driver_standings()


def get_f1_season_calendar() -> dict[str, Any]:
    """Retrieve the full Formula 1 race calendar for the current season.

    Fetches all scheduled races from the Ergast F1 API for the active season.
    No parameters are required.

    Returns:
        dict: A payload with ``season`` and ``calendar`` (list of race records
            with ``round``, ``raceName``, ``circuitName``, ``country``,
            ``date``, and ``time``), or an ``error`` key on failure.
    """
    return fetch_f1_season_calendar()


AGENT_TOOLS_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_current_weather": get_current_weather,
    "get_weather_forecast": get_weather_forecast,
    "get_f1_driver_standings": get_f1_driver_standings,
    "get_f1_season_calendar": get_f1_season_calendar,
}
