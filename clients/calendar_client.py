"""Bounded Google Calendar discovery and selected-calendar event reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.config import DEMO_MODE, is_dev_mode

_CALENDAR_LIST_CAP = 250
_PER_CALENDAR_EVENT_CAP = 100
_CALENDAR_LIST_PAGE_CAP = 10
_PER_CALENDAR_EVENT_PAGE_CAP = 10
_NAME_MAX_LENGTH = 160
_DEV_MASKED_SUMMARY = "[HIDDEN] Calendar Fetch Successful (Payload masked due to DEV_MODE)"
_DEV_OFFLINE_SUMMARY = "[HIDDEN] Local Sandbox Synchronization Block (Offline / Token Missing)"


@dataclass(frozen=True)
class CalendarFetchResult:
    """Normalized selected-calendar events and bounded collection evidence."""

    events: list[dict[str, Any]]
    selected_calendar_count: int
    successful_calendar_count: int
    failed_calendar_count: int
    truncated: bool = False


def _bounded_text(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = " ".join(value.split())
    return cleaned[:_NAME_MAX_LENGTH] or fallback


def _normalize_datetime(value: str, *, time_zone: str | None) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        try:
            tzinfo = ZoneInfo(time_zone) if time_zone else timezone.utc
        except ZoneInfoNotFoundError:
            tzinfo = timezone.utc
        parsed = parsed.replace(tzinfo=tzinfo)
    return parsed.isoformat()


def _normalize_event(item: dict[str, Any], *, calendar_time_zone: str | None, calendar_name: str | None) -> dict[str, Any] | None:
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
    time_zone_name = str(time_zone_value) if isinstance(time_zone_value, str) else None
    try:
        normalized_start = date.fromisoformat(start_value).isoformat() if all_day else _normalize_datetime(start_value, time_zone=time_zone_name)
    except ValueError:
        return None
    normalized_end: str | None = None
    end = item.get("end")
    if isinstance(end, dict):
        end_value = end.get("date") if all_day else end.get("dateTime")
        if isinstance(end_value, str) and end_value:
            try:
                normalized_end = date.fromisoformat(end_value).isoformat() if all_day else _normalize_datetime(end_value, time_zone=str(end.get("timeZone")) if isinstance(end.get("timeZone"), str) else time_zone_name)
            except ValueError:
                pass
    event = {
        "summary": _bounded_text(item.get("summary"), "(No title)"),
        "start": normalized_start,
        "end": normalized_end,
        "all_day": all_day,
        "time_zone": time_zone_name,
        "location": _bounded_text(item.get("location"), "") or None,
    }
    if calendar_name is not None:
        event["calendar_name"] = calendar_name
    return event


def _event_sort_key(event: dict[str, Any]) -> tuple[datetime, str]:
    raw_start = event.get("start")
    try:
        if event.get("all_day"):
            return (datetime.combine(date.fromisoformat(str(raw_start)), datetime.min.time(), timezone.utc), str(event.get("summary", "")))
        parsed = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
        return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc), str(event.get("summary", "")))
    except ValueError:
        return (datetime.max.replace(tzinfo=timezone.utc), str(event.get("summary", "")))


def demo_calendars() -> dict[str, Any]:
    """Return stable Calendar-picker choices without Google access in DEMO_MODE."""
    return {"calendars": [
        {"id": "primary", "display_name": "Personal", "primary": True, "hidden": False},
        {"id": "demo-team", "display_name": "Demo team", "primary": False, "hidden": False},
    ], "truncated": False}


def list_readable_calendars(service: Any) -> dict[str, Any]:
    """List up to 250 readable, non-deleted calendars with sanitized labels."""
    if DEMO_MODE:
        return demo_calendars()
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    request_count = 0
    while len(rows) < _CALENDAR_LIST_CAP and request_count < _CALENDAR_LIST_PAGE_CAP:
        response = service.calendarList().list(
            maxResults=min(_CALENDAR_LIST_CAP - len(rows), _CALENDAR_LIST_CAP),
            pageToken=page_token,
            showDeleted=False,
            showHidden=True,
        ).execute()
        request_count += 1
        items = response.get("items") if isinstance(response, dict) else None
        if not isinstance(items, list):
            items = []
        for item in items:
            if not isinstance(item, dict) or item.get("deleted") is True or item.get("accessRole") == "freeBusyReader":
                continue
            provider_calendar_id = item.get("id")
            if not isinstance(provider_calendar_id, str):
                continue
            provider_calendar_id = provider_calendar_id.strip()
            if not provider_calendar_id or len(provider_calendar_id) > 512:
                continue
            is_primary = item.get("primary") is True
            # Google accepts the literal "primary" calendarId for Events.list,
            # while CalendarList returns a provider-specific ID for that entry.
            calendar_id = "primary" if is_primary else provider_calendar_id
            rows.append({"id": calendar_id, "display_name": _bounded_text(item.get("summaryOverride") or item.get("summary"), "Unnamed calendar"), "primary": is_primary, "hidden": item.get("hidden") is True})
            if len(rows) >= _CALENDAR_LIST_CAP:
                break
        token = response.get("nextPageToken") if isinstance(response, dict) else None
        page_token = token if isinstance(token, str) and token else None
        if page_token is None:
            break
    rows.sort(key=lambda item: (not item["primary"], item["display_name"].casefold(), item["id"]))
    return {"calendars": rows, "truncated": page_token is not None}


def fetch_selected_calendar_events(service: Any, *, calendar_ids: tuple[str, ...], days: int = 7, show_calendar_names: bool = True) -> CalendarFetchResult:
    """Read each selected calendar independently, retaining successful results."""
    clamped_days = max(1, min(14, days))
    if not calendar_ids:
        return CalendarFetchResult([], 0, 0, 0)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if DEMO_MODE:
        event = {"summary": "Demo planning session", "start": (now + timedelta(hours=2)).isoformat(), "end": None, "all_day": False, "time_zone": "UTC"}
        if show_calendar_names:
            event["calendar_name"] = "Personal"
        return CalendarFetchResult([event], len(calendar_ids), len(calendar_ids), 0)
    names: dict[str, str] = {}
    try:
        names = {item["id"]: item["display_name"] for item in list_readable_calendars(service)["calendars"]}
    except Exception:
        pass
    all_events: list[dict[str, Any]] = []
    succeeded = failed = 0
    truncated = False
    for calendar_id in calendar_ids:
        page_token: str | None = None
        calendar_events: list[dict[str, Any]] = []
        try:
            request_count = 0
            while len(calendar_events) < _PER_CALENDAR_EVENT_CAP and request_count < _PER_CALENDAR_EVENT_PAGE_CAP:
                response = service.events().list(calendarId=calendar_id, timeMin=now.isoformat(), timeMax=(now + timedelta(days=clamped_days)).isoformat(), singleEvents=True, orderBy="startTime", maxResults=_PER_CALENDAR_EVENT_CAP - len(calendar_events), pageToken=page_token).execute()
                request_count += 1
                items = response.get("items") if isinstance(response, dict) else None
                calendar_time_zone = response.get("timeZone") if isinstance(response, dict) else None
                if not isinstance(calendar_time_zone, str):
                    calendar_time_zone = None
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            event = _normalize_event(item, calendar_time_zone=calendar_time_zone, calendar_name=names.get(calendar_id, "Saved calendar") if show_calendar_names else None)
                            if event is not None:
                                calendar_events.append(event)
                                if len(calendar_events) >= _PER_CALENDAR_EVENT_CAP:
                                    break
                token = response.get("nextPageToken") if isinstance(response, dict) else None
                page_token = token if isinstance(token, str) and token else None
                if (len(calendar_events) >= _PER_CALENDAR_EVENT_CAP or request_count >= _PER_CALENDAR_EVENT_PAGE_CAP) and page_token is not None:
                    truncated = True
                if page_token is None:
                    break
            succeeded += 1
            all_events.extend(calendar_events)
        except Exception:
            failed += 1
    if is_dev_mode():
        event = {"summary": _DEV_MASKED_SUMMARY if succeeded else _DEV_OFFLINE_SUMMARY, "start": now.isoformat(), "end": None, "all_day": False, "time_zone": "UTC"}
        if show_calendar_names:
            event["calendar_name"] = "Calendar"
        return CalendarFetchResult([event], len(calendar_ids), succeeded, failed)
    all_events.sort(key=_event_sort_key)
    return CalendarFetchResult(all_events, len(calendar_ids), succeeded, failed, truncated)
