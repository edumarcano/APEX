"""Typed collectors for email, calendar, and reminders briefing connectors."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clients import calendar_client, gmail_client, google_auth
from core import database
from core.connectors.models import ConnectorResult, utc_now_iso

_LOGGER = logging.getLogger(__name__)


def collect_email() -> ConnectorResult:
    """Collect unread Gmail telemetry as a typed connector result."""
    observed_at = utc_now_iso()
    try:
        email_service = google_auth.get_service("gmail", "v1")
        email_data = gmail_client.get_unread_gmail_data(email_service)
        count = int(email_data.get("count", 0) or 0)
        items = email_data.get("emails", [])
        if not isinstance(items, list):
            items = []

        recent: list[dict[str, str]] = []
        for email in items[:3]:
            if not isinstance(email, dict):
                continue
            recent.append(
                {
                    "subject": str(email.get("subject", "")),
                    "time": str(email.get("time", "")),
                }
            )

        if recent:
            recent_emails = [
                f"'{item['subject']}' at {item['time']}" for item in recent
            ]
            recent_emails_str = ", ".join(recent_emails)
        else:
            recent_emails_str = "Email Telemetry (24h): No unread emails"

        display = (
            f"Email Telemetry: {count} unread primary emails. "
            f"Most recent: {recent_emails_str}"
        )
        return ConnectorResult(
            name="email",
            status="healthy",
            freshness="live",
            reason_code="ok",
            observed_at=observed_at,
            display_text=display,
            data={"count": count, "emails": recent},
        )
    except Exception:
        _LOGGER.warning("Email fetch failed: connection_error")
        return ConnectorResult(
            name="email",
            status="unavailable",
            freshness="none",
            reason_code="connection_error",
            observed_at=observed_at,
            display_text="ERROR: Check connection",
            data={"count": 0, "emails": []},
        )


_CALENDAR_WINDOW_DAYS = 7
_CALENDAR_DISPLAY_WINDOW_HOURS = 48


def _calendar_event_start(event: dict[str, Any]) -> datetime | None:
    raw_start = event.get("start")
    if not isinstance(raw_start, str) or not raw_start:
        return None

    try:
        if bool(event.get("all_day")):
            parsed_date = date.fromisoformat(raw_start)
            time_zone = event.get("time_zone")
            try:
                tzinfo = (
                    ZoneInfo(time_zone)
                    if isinstance(time_zone, str) and time_zone
                    else timezone.utc
                )
            except ZoneInfoNotFoundError:
                tzinfo = timezone.utc
            return datetime.combine(parsed_date, datetime.min.time(), tzinfo)

        parsed = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _calendar_data(
    calendar_data: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("Calendar window boundary must be timezone-aware.")

    events: list[dict[str, Any]] = []
    for event in calendar_data:
        if not isinstance(event, dict) or _calendar_event_start(event) is None:
            continue
        events.append(
            {
                "summary": str(event.get("summary") or "Untitled event"),
                "start": str(event["start"]),
                "end": (
                    str(event["end"])
                    if isinstance(event.get("end"), str)
                    else None
                ),
                "all_day": bool(event.get("all_day")),
                "time_zone": (
                    str(event["time_zone"])
                    if isinstance(event.get("time_zone"), str)
                    else None
                ),
            }
        )

    display_end = now + timedelta(hours=_CALENDAR_DISPLAY_WINDOW_HOURS)
    display_events = [
        event
        for event in events
        if (start := _calendar_event_start(event)) is not None
        and start >= now
        and start < display_end
    ]
    return {
        "window_days": _CALENDAR_WINDOW_DAYS,
        "display_window_hours": _CALENDAR_DISPLAY_WINDOW_HOURS,
        "events": events,
        "display_events": display_events,
        "total_count": len(events),
        "display_count": len(display_events),
        "overflow_count": len(events) - len(display_events),
    }


def collect_calendar(*, now: datetime | None = None) -> ConnectorResult:
    """Collect upcoming calendar events as a typed connector result."""
    observed_at = utc_now_iso()
    try:
        calendar_service = google_auth.get_service("calendar", "v3")
        calendar_data = calendar_client.get_upcoming_calendar_events(
            calendar_service,
            days=_CALENDAR_WINDOW_DAYS,
        )
        if not isinstance(calendar_data, list):
            calendar_data = []

        data = _calendar_data(
            calendar_data,
            now=now or datetime.now(timezone.utc),
        )
        display_events = data["display_events"]

        if display_events:
            calendar_entries = [
                f"'{event['summary']}' at {event['start']}"
                for event in display_events
            ]
            display = "Calendar Telemetry (48h): " + " | ".join(calendar_entries)
        else:
            display = "Calendar Telemetry (48h): No upcoming events"

        return ConnectorResult(
            name="calendar",
            status="healthy",
            freshness="live",
            reason_code="ok",
            observed_at=observed_at,
            display_text=display,
            data=data,
        )
    except Exception:
        _LOGGER.warning("Calendar fetch failed: connection_error")
        return ConnectorResult(
            name="calendar",
            status="unavailable",
            freshness="none",
            reason_code="connection_error",
            observed_at=observed_at,
            display_text="ERROR: Check connection",
            data={
                "window_days": _CALENDAR_WINDOW_DAYS,
                "display_window_hours": _CALENDAR_DISPLAY_WINDOW_HOURS,
                "events": [],
                "display_events": [],
                "total_count": 0,
                "display_count": 0,
                "overflow_count": 0,
            },
        )


def collect_reminders() -> ConnectorResult:
    """Collect pending reminders as a typed connector result."""
    observed_at = utc_now_iso()
    try:
        unread_records = database.fetch_unread_reminders()
        notes = [str(note) for _, note in unread_records]
        if notes:
            display = f"Pending Reminders: {', '.join(notes)}"
        else:
            display = "No pending reminders."
        return ConnectorResult(
            name="reminders",
            status="healthy",
            freshness="live",
            reason_code="ok",
            observed_at=observed_at,
            display_text=display,
            data={
                "count": len(notes),
                "notes": notes,
                "records": [{"id": row_id, "note": note} for row_id, note in unread_records],
            },
        )
    except sqlite3.Error:
        _LOGGER.warning("Reminders fetch failed: database_error")
        return ConnectorResult(
            name="reminders",
            status="unavailable",
            freshness="none",
            reason_code="database_error",
            observed_at=observed_at,
            display_text="ERROR: Reminders unavailable",
            data={"count": 0, "notes": [], "records": []},
        )
