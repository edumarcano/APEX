from datetime import datetime, timezone, timedelta
from typing import Any

from clients.google_auth import get_service
from core.config import is_dev_mode

_DEV_MASKED_SUMMARY = (
    "[HIDDEN] Calendar Fetch Successful (Payload masked due to DEV_MODE)"
)
_DEV_OFFLINE_SUMMARY = (
    "[HIDDEN] Local Sandbox Synchronization Block (Offline / Token Missing)"
)


def get_upcoming_calendar_events(
    service: Any, days: int = 2
) -> list[dict[str, str]]:
    """
    Fetches upcoming calendar events from the user's primary calendar.

    Args:
        service: A service object for the Calendar API.
        days: Number of days into the future to query. Clamped to the range
            1–14. Defaults to 2 (48-hour HUD viewport).

    Returns:
        A list of dictionaries with event summary and formatted start time.
    """
    try:
        clamped_days = max(1, min(14, days))
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
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
            return [{"summary": _DEV_MASKED_SUMMARY, "start": ""}]

        items = events_result.get("items", [])
        events: list[dict[str, str]] = []

        for item in items:
            summary = item.get("summary", "(No title)")
            start = item.get("start", {})
            start_value = start.get("dateTime") or start.get("date")

            if not start_value:
                continue

            # Timed events use dateTime, all-day events use date only.
            if "T" in start_value:
                parsed = datetime.fromisoformat(
                    start_value.replace("Z", "+00:00")
                )
                start_str = parsed.strftime("%I:%M %p")
            else:
                parsed = datetime.fromisoformat(start_value)
                start_str = parsed.strftime("%Y-%m-%d (All day)")

            events.append({"summary": summary, "start": start_str})

        return events
    except Exception:
        if is_dev_mode():
            return [{"summary": _DEV_OFFLINE_SUMMARY, "start": ""}]
        raise


if __name__ == "__main__":
    print("[CALENDAR] Initializing calendar service.")
    service = get_service('calendar', 'v3')
    if service:
        print("[CALENDAR] Fetching upcoming events.")
        events = get_upcoming_calendar_events(service)

        if not events:
            print("[CALENDAR] No upcoming events found for the next 48 hours.")
        else:
            print(f"[CALENDAR] Successfully fetched {len(events)} upcoming events.")
    else:
        print("[CALENDAR] Error: Failed to initialize calendar service.")
