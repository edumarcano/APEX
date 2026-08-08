"""DEMO_MODE mock payload loading and deterministic Agent responses."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from core.agent.types import (
    AgentQueryRequest,
    AgentQueryResponse,
    ToolSelectionDiagnostics,
)
from core.api.models import DigestPayload, TelemetryPayload
from core.mock.demo_fixture import DemoBundle, DemoFixtureError, load_demo_bundle

_MOCK_ASSISTANT_PATH = Path(__file__).resolve().parent.parent / "mock" / "assistant.json"


def _validate_mock_agent_response(
    response: Any,
    *,
    require_keywords: bool,
) -> dict[str, Any]:
    """Validate one deterministic demo Agent response."""
    if not isinstance(response, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo Agent response must be a JSON object.",
        )

    answer = response.get("answer")
    tool_trace = response.get("tool_trace")
    tool_outputs = response.get("tool_outputs", [])
    keywords = response.get("keywords")

    if not isinstance(answer, str):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo Agent response must include string 'answer'.",
        )
    if not isinstance(tool_trace, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo Agent response must include list 'tool_trace'.",
        )
    if require_keywords:
        if not isinstance(keywords, list) or not all(
            isinstance(keyword, str) for keyword in keywords
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Demo Agent response must include list of string "
                    "'keywords'."
                ),
            )
    else:
        keywords = []

    if tool_outputs is None:
        tool_outputs = []
    if not isinstance(tool_outputs, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo Agent response must include list 'tool_outputs'.",
        )

    required_tool_output_keys = {"name", "status", "duration_ms", "output"}
    for index, entry in enumerate(tool_outputs):
        if not isinstance(entry, dict):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Demo Agent tool_outputs[{index}] must be a JSON object.",
            )
        missing_keys = required_tool_output_keys - entry.keys()
        if missing_keys:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Demo Agent tool_outputs entries must include "
                    f"{sorted(required_tool_output_keys)}; "
                    f"entry {index} missing {sorted(missing_keys)}."
                ),
            )

        if not isinstance(entry.get("name"), str) or not isinstance(
            entry.get("status"), str
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Demo Agent tool_outputs[{index}] must include string 'name' and 'status'."
                ),
            )
        duration_ms = entry.get("duration_ms")
        if not isinstance(duration_ms, (int, float)):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Demo Agent tool_outputs[{index}] must include numeric 'duration_ms'."
                ),
            )
    return {
        "answer": answer,
        "tool_trace": tool_trace,
        "tool_outputs": tool_outputs,
        "keywords": keywords,
    }


def load_demo_bundle_or_raise() -> DemoBundle:
    """Load the normalized DEMO_MODE bundle or raise an HTTP 500."""
    try:
        return load_demo_bundle()
    except DemoFixtureError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from None


def load_mock_telemetry() -> tuple[TelemetryPayload, DigestPayload]:
    """Load static demo telemetry and digest from ``core/mock/telemetry.json``."""
    bundle = load_demo_bundle_or_raise()
    return bundle.telemetry, bundle.digest


def load_mock_agent_responses() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load deterministic Agent responses from ``core/mock/assistant.json``."""
    try:
        with open(_MOCK_ASSISTANT_PATH, encoding="utf-8") as mock_file:
            payload = json.load(mock_file)
    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo Agent payload unavailable.",
        ) from None

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo Agent payload must be a JSON object.",
        )

    responses = payload.get("responses")
    if not isinstance(responses, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo Agent payload must include list 'responses'.",
        )

    fallback = payload.get("fallback")
    return (
        [
            _validate_mock_agent_response(response, require_keywords=True)
            for response in responses
        ],
        _validate_mock_agent_response(fallback, require_keywords=False),
    )


def mock_briefing_history() -> list[dict[str, Any]]:
    """Static briefing ledger for DEMO_MODE history responses."""
    return [
        {
            "id": 3,
            "timestamp": "2026-06-08T08:15:00",
            "briefing": (
                "APEX simulation controls are operational. "
                "Atmospheric sensors report seventy-two degrees with clear skies. "
                "Inbox has two unread primary messages, and the next calendar item, "
                "Demo Presentation, begins at three PM."
            ),
            "digest": {
                "weather_archetype": "clear_day",
                "unread_emails_count": 2,
                "upcoming_events_count": 1,
                "f1_sprint_active": False,
                "reminders_pending_count": 2,
                "sync_health_score": 100.0,
                "confidence_score": 100.0,
                "failed_connectors": [],
                "connector_health": [],
            },
        },
        {
            "id": 2,
            "timestamp": "2026-06-07T07:30:00",
            "briefing": (
                "Morning briefing. Overnight precipitation cleared; current conditions are "
                "partly cloudy at sixty-eight degrees. Three unread emails require attention, "
                "including a budget review thread. Sprint qualifying for the Monaco Grand Prix "
                "is scheduled this afternoon."
            ),
            "digest": {
                "weather_archetype": "partly_cloudy",
                "unread_emails_count": 3,
                "upcoming_events_count": 2,
                "f1_sprint_active": True,
                "reminders_pending_count": 1,
                "sync_health_score": 92.5,
                "confidence_score": 92.5,
                "failed_connectors": ["news"],
                "connector_health": [],
            },
        },
        {
            "id": 1,
            "timestamp": "2026-06-06T06:45:00",
            "briefing": (
                "System status nominal. Light rain expected through mid-morning with temperatures "
                "near sixty-one degrees. Calendar is clear until afternoon stand-up. One reminder "
                "pending: submit quarterly metrics before end of day."
            ),
            "digest": {
                "weather_archetype": "light_rain",
                "unread_emails_count": 0,
                "upcoming_events_count": 0,
                "f1_sprint_active": False,
                "reminders_pending_count": 1,
                "sync_health_score": 78.0,
                "confidence_score": 78.0,
                "failed_connectors": ["email", "calendar"],
                "connector_health": [],
            },
        },
    ]


def build_demo_briefing(telemetry: TelemetryPayload) -> str:
    """Compose a deterministic briefing string from mock telemetry fields."""
    bundle = load_demo_bundle_or_raise()
    # Keep the legacy signature for compatibility callers that pass telemetry only.
    _ = telemetry
    weather = bundle.modules["weather"].data
    email = bundle.modules["email"].data
    calendar = bundle.modules["calendar"].data
    f1_map = bundle.modules["f1"].data.get("f1_map", {})
    reminders = bundle.modules["reminders"].data

    temp_f = weather.get("temp_f")
    condition = weather.get("condition", "current conditions")
    weather_clause = (
        f"Atmospheric sensors report {temp_f} degrees with {condition}."
        if temp_f is not None
        else f"Atmospheric sensors report {condition}."
    )

    email_count = int(email.get("count", 0) or 0)
    email_clause = (
        f"Inbox has {email_count} unread primary message"
        f"{'s' if email_count != 1 else ''}."
        if email_count
        else "Inbox has no unread primary messages."
    )

    events = calendar.get("events") if isinstance(calendar.get("events"), list) else []
    if events and isinstance(events[0], dict):
        next_event = events[0]
        event_time = _format_demo_event_time(
            next_event,
            now=datetime.fromisoformat(bundle.collected_at),
        )
        calendar_clause = (
            f"Next calendar item is {next_event.get('summary', 'an event')}, "
            f"scheduled for {event_time}."
        )
    else:
        calendar_clause = "Calendar is clear for the next seven days."

    sports_clause = ""
    if isinstance(f1_map, dict) and f1_map.get("relativeWeek") == "This week":
        race_name = f1_map.get("raceName", "the upcoming Grand Prix")
        race_time = f1_map.get("raceDateTimeEST", "later this week")
        sports_clause = (
            f"F1 status: {race_name} is scheduled for this week, with the main race on {race_time}. "
        )

    reminder_count = int(reminders.get("count", 0) or 0)
    reminder_clause = (
        f"{reminder_count} reminder{'s' if reminder_count != 1 else ''} remain pending."
        if reminder_count
        else "No reminders are pending."
    )

    health_score = bundle.digest.sync_health_score
    health_clause = (
        "Connector sync health is nominal."
        if health_score is not None and health_score >= 95.0
        else "Connector sync health reports minor degradation."
    )

    return (
        "APEX simulation controls are operational. "
        f"{weather_clause} {sports_clause}{email_clause} {calendar_clause} "
        f"{reminder_clause} {health_clause}"
    )


def _format_demo_event_time(event: dict[str, Any], *, now: datetime) -> str:
    """Render a normalized demo calendar timestamp as natural briefing text."""
    raw_start = event.get("start")
    if not isinstance(raw_start, str) or not raw_start.strip():
        return "the scheduled time"

    time_zone_name = event.get("time_zone")
    try:
        event_zone = ZoneInfo(time_zone_name) if isinstance(time_zone_name, str) else timezone.utc
    except (KeyError, ValueError):
        event_zone = timezone.utc

    if event.get("all_day") is True:
        try:
            event_date = date.fromisoformat(raw_start)
        except ValueError:
            return raw_start
        local_now = now.astimezone(event_zone).date()
        if event_date == local_now:
            return "today (all day)"
        return f"{_natural_date_label(event_date, local_now=local_now)} (all day)"

    try:
        event_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
    except ValueError:
        return raw_start
    if event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=timezone.utc)
    event_start = event_start.astimezone(event_zone)
    local_now = now.astimezone(event_zone)
    if event_start.date() == local_now.date():
        day_label = "today"
    elif (event_start.date() - local_now.date()).days == 1:
        day_label = "tomorrow"
    else:
        day_label = _natural_date_label(event_start.date(), local_now=local_now.date())
    time_label = event_start.strftime("%I:%M %p").lstrip("0")
    zone_label = event_start.tzname() or str(event_zone)
    return f"{day_label} at {time_label} {zone_label}"


def _natural_date_label(value: date, *, local_now: date) -> str:
    """Format a calendar date without platform-specific ``%-d`` directives."""
    if value.year == local_now.year:
        return f"{value.strftime('%A, %B')} {value.day}"
    return f"{value.strftime('%A, %B')} {value.day}, {value.year}"


def run_demo_agent_query(
    payload: AgentQueryRequest,
    *,
    tool_selection: ToolSelectionDiagnostics | None = None,
) -> AgentQueryResponse:
    """Return deterministic Agent responses when ``DEMO_MODE`` is active."""
    from core.agent.catalog import (
        AGENT_SPECS,
        build_concrete_agent,
        build_agent_used_metadata,
        is_agent_visible,
        resolve_effort,
    )

    agent_key = payload.agent
    if agent_key not in AGENT_SPECS or not is_agent_visible(agent_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_key!r} is not available.",
        )

    resolved_apex_effort, resolved_native_effort = resolve_effort(
        agent_key, payload.effort
    )
    agent = build_concrete_agent(agent_key, native_effort=resolved_native_effort)

    prompt_lower = payload.prompt.lower()
    responses, fallback = load_mock_agent_responses()
    selected_response = fallback
    for response in responses:
        if any(keyword in prompt_lower for keyword in response["keywords"]):
            selected_response = response
            break

    return AgentQueryResponse(
        answer=selected_response["answer"],
        agent_used=build_agent_used_metadata(
            agent_key,
            configured_model=agent.api_model,
            resolved_model=agent.api_model,
            requested_effort=payload.effort,
            resolved_apex_effort=resolved_apex_effort,
            resolved_native_effort=resolved_native_effort,
        ),
        tool_trace=selected_response["tool_trace"],
        tool_outputs=selected_response.get("tool_outputs", []),
        session_id=payload.session_id,
        error=None,
        resolved_tool_selection=tool_selection or ToolSelectionDiagnostics(),
        requested_tool_names=(
            tool_selection.requested_tool_names if tool_selection is not None else []
        ),
        offered_tool_names=(
            tool_selection.offered_tool_names if tool_selection is not None else []
        ),
        rejected_tool_names=(
            tool_selection.rejected_tool_names if tool_selection is not None else []
        ),
        selected_schema_tokens=(
            tool_selection.selected_schema_tokens if tool_selection is not None else 0
        ),
        active_tool_profile_id=(
            tool_selection.active_profile_id if tool_selection is not None else None
        ),
        active_tool_profile_name=(
            tool_selection.active_profile_name if tool_selection is not None else None
        ),
    )
