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


def get_upcoming_calendar_events(days: int = 14) -> dict[str, Any]:
    """Retrieve upcoming Google Calendar events beyond the HUD viewport.

    Queries the operator's primary Google Calendar for scheduled events within
    a configurable forward-looking window. Extends the default 48-hour HUD cap
    up to 14 days, enabling multi-week scheduling awareness and semantic
    event search by the agent.

    Args:
        days: Number of days into the future to query. Must be between 1 and
            14 inclusive. Values outside this range are clamped. Defaults to
            14.

    Returns:
        dict: On success, a payload with ``days_queried`` (int) and ``events``
            (list of dicts, each containing ``summary`` and ``start``). On
            authentication failure, ``{"error": "Calendar authentication failed
            or Google Workspace service is offline."}``. On other failures,
            ``{"error": "<exception message>"}``.
    """
    days = max(1, min(14, days))
    try:
        from clients.google_auth import get_service

        service = get_service("calendar", "v3")
        if not service:
            return {
                "error": (
                    "Calendar authentication failed or Google Workspace "
                    "service is offline."
                )
            }
    except Exception:
        return {
            "error": (
                "Calendar authentication failed or Google Workspace "
                "service is offline."
            )
        }

    try:
        from clients.calendar_client import (
            get_upcoming_calendar_events as fetch_events,
        )

        events = fetch_events(service, days=days)
        return {"days_queried": days, "events": events}
    except Exception as exc:
        return {"error": str(exc)}


def get_active_reminders() -> list[dict[str, Any]]:
    """Retrieve all pending (unread) reminders from the APEX task ledger.

    Returns every active reminder stored in the local SQLite database where
    ``is_read = 0``. Enables the agent to perform semantic search,
    categorization, keyword clustering, and priority grouping over outstanding
    operator tasks without mirroring on-screen HUD state.

    Returns:
        list[dict]: A list of reminder records, each containing ``id`` (int)
            and ``note`` (str). Returns an empty list on failure or when no
            unread reminders exist.
    """
    try:
        from core import database

        records = database.fetch_unread_reminders()
        return [{"id": row_id, "note": note} for row_id, note in records]
    except Exception:
        return []


def get_briefing_history(limit: int = 5) -> dict[str, Any]:
    """Retrieve recent APEX briefing digests for episodic memory queries.

    Fetches structured historical briefing records from the SQLite ledger,
    allowing the agent to perform temporal comparative analysis across past
    runs. Only essential metadata fields are returned to preserve the model's
    token context window.

    Args:
        limit: Maximum number of historical briefing records to retrieve.
            Must be between 1 and 5 inclusive. Values outside this range are
            clamped. Defaults to 5.

    Returns:
        dict: On success with records, ``{"limit_requested": limit,
            "briefings": [<records>]}`` where each record contains ``id``,
            ``timestamp``, ``briefing``, and ``insights`` (list). When no
            records exist, ``{"message": "No briefings have been recorded in
            the system ledger yet."}``. On failure, ``{"error": "<exception
            message>"}``.
    """
    limit = max(1, min(5, limit))
    try:
        from core import database

        rows = database.fetch_briefing_history(limit=limit)
        if not rows:
            return {
                "message": (
                    "No briefings have been recorded in the system ledger yet."
                )
            }

        briefings: list[dict[str, Any]] = []
        for record in rows:
            digest = record.get("digest", {})
            briefings.append(
                {
                    "id": record["id"],
                    "timestamp": record["timestamp"],
                    "briefing": record["briefing"],
                    "insights": digest.get("insights", []),
                }
            )
        return {"limit_requested": limit, "briefings": briefings}
    except Exception as exc:
        return {"error": str(exc)}


AGENT_TOOLS_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_current_weather": get_current_weather,
    "get_weather_forecast": get_weather_forecast,
    "get_f1_driver_standings": get_f1_driver_standings,
    "get_f1_season_calendar": get_f1_season_calendar,
    "get_upcoming_calendar_events": get_upcoming_calendar_events,
    "get_active_reminders": get_active_reminders,
    "get_briefing_history": get_briefing_history,
}
