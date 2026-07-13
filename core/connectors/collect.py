"""Typed collectors for email, calendar, and reminders briefing connectors."""

from __future__ import annotations

from typing import Any

from clients import calendar_client, gmail_client, google_auth
from core import database
from core.connectors.models import ConnectorResult, utc_now_iso


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
        print("[SYSTEM]: Email fetch failed: connection_error")
        return ConnectorResult(
            name="email",
            status="unavailable",
            freshness="none",
            reason_code="connection_error",
            observed_at=observed_at,
            display_text="ERROR: Check connection",
            data={"count": 0, "emails": []},
        )


def collect_calendar() -> ConnectorResult:
    """Collect upcoming calendar events as a typed connector result."""
    observed_at = utc_now_iso()
    try:
        calendar_service = google_auth.get_service("calendar", "v3")
        calendar_data = calendar_client.get_upcoming_calendar_events(calendar_service)
        if not isinstance(calendar_data, list):
            calendar_data = []

        events: list[dict[str, Any]] = []
        for event in calendar_data:
            if not isinstance(event, dict):
                continue
            events.append(
                {
                    "summary": str(event.get("summary", "Untitled event")),
                    "start": str(event.get("start", "")),
                }
            )

        if events:
            calendar_entries = [
                f"'{event['summary']}' at {event['start']}" for event in events
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
            data={"events": events, "count": len(events)},
        )
    except Exception:
        print("[SYSTEM]: Calendar fetch failed: connection_error")
        return ConnectorResult(
            name="calendar",
            status="unavailable",
            freshness="none",
            reason_code="connection_error",
            observed_at=observed_at,
            display_text="ERROR: Check connection",
            data={"events": [], "count": 0},
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
    except Exception:
        print("[SYSTEM]: Reminders fetch failed: database_error")
        return ConnectorResult(
            name="reminders",
            status="unavailable",
            freshness="none",
            reason_code="database_error",
            observed_at=observed_at,
            display_text="ERROR: Reminders unavailable",
            data={"count": 0, "notes": [], "records": []},
        )
