from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clients.google_auth import get_service
from core.config import is_dev_mode

_DEV_MASKED_SUMMARY = (
    "[HIDDEN] Calendar Fetch Successful (Payload masked due to DEV_MODE)"
)
_DEV_OFFLINE_SUMMARY = (
    "[HIDDEN] Local Sandbox Synchronization Block (Offline / Token Missing)"
)


def _normalize_datetime(value: str, *, time_zone: str | None) -> str:
    """Return a validated ISO value, attaching an event timezone when needed."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        try:
            tzinfo = ZoneInfo(time_zone) if time_zone else timezone.utc
        except ZoneInfoNotFoundError:
            tzinfo = timezone.utc
        parsed = parsed.replace(tzinfo=tzinfo)
    return parsed.isoformat()


def _normalize_event(
    item: dict[str, Any],
    *,
    calendar_time_zone: str | None,
) -> dict[str, Any] | None:
    start = item.get("start")
    if not isinstance(start, dict):
        return None

    start_datetime = start.get("dateTime")
    start_date = start.get("date")
    all_day = not isinstance(start_datetime, str) and isinstance(start_date, str)
    start_value = start_date if all_day else start_datetime
    if not isinstance(start_value, str) or not start_value:
        return None

    time_zone_value = start.get("timeZone") or calendar_time_zone
    time_zone_name = (
        str(time_zone_value) if isinstance(time_zone_value, str) else None
    )
    try:
        normalized_start = (
            date.fromisoformat(start_value).isoformat()
            if all_day
            else _normalize_datetime(start_value, time_zone=time_zone_name)
        )
    except ValueError:
        return None

    normalized_end: str | None = None
    end = item.get("end")
    if isinstance(end, dict):
        end_value = end.get("date") if all_day else end.get("dateTime")
        if isinstance(end_value, str) and end_value:
            try:
                normalized_end = (
                    date.fromisoformat(end_value).isoformat()
                    if all_day
                    else _normalize_datetime(
                        end_value,
                        time_zone=(
                            str(end.get("timeZone"))
                            if isinstance(end.get("timeZone"), str)
                            else time_zone_name
                        ),
                    )
                )
            except ValueError:
                normalized_end = None

    return {
        "summary": str(item.get("summary") or "(No title)"),
        "start": normalized_start,
        "end": normalized_end,
        "all_day": all_day,
        "time_zone": time_zone_name,
    }


def get_upcoming_calendar_events(
    service: Any, days: int = 7
) -> list[dict[str, Any]]:
    """
    Fetches upcoming calendar events from the user's primary calendar.

    Args:
        service: A service object for the Calendar API.
        days: Number of days into the future to query. Clamped to the range
            1–14. Defaults to 7.

    Returns:
        Normalized events with summary, ISO start and end values, all-day
        status, and the source timezone when available.
    """
    now_dt = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        clamped_days = max(1, min(14, days))
        end_of_day_dt = now_dt + timedelta(days=clamped_days)
        now = now_dt.isoformat()
        end_of_day = end_of_day_dt.isoformat()

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                timeMax=end_of_day,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        if is_dev_mode():
            return [
                {
                    "summary": _DEV_MASKED_SUMMARY,
                    "start": now,
                    "end": None,
                    "all_day": False,
                    "time_zone": "UTC",
                }
            ]

        items = events_result.get("items", [])
        if not isinstance(items, list):
            return []
        calendar_time_zone = events_result.get("timeZone")
        if not isinstance(calendar_time_zone, str):
            calendar_time_zone = None
        events: list[dict[str, Any]] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            event = _normalize_event(
                item,
                calendar_time_zone=calendar_time_zone,
            )
            if event is not None:
                events.append(event)

        return events
    except Exception:
        if is_dev_mode():
            return [
                {
                    "summary": _DEV_OFFLINE_SUMMARY,
                    "start": now_dt.isoformat(),
                    "end": None,
                    "all_day": False,
                    "time_zone": "UTC",
                }
            ]
        raise


if __name__ == "__main__":
    print("[CALENDAR] Initializing calendar service.")
    service = get_service('calendar', 'v3')
    if service:
        print("[CALENDAR] Fetching upcoming events.")
        events = get_upcoming_calendar_events(service)

        if not events:
            print("[CALENDAR] No upcoming events found for the next 7 days.")
        else:
            print(f"[CALENDAR] Successfully fetched {len(events)} upcoming events.")
    else:
        print("[CALENDAR] Error: Failed to initialize calendar service.")
