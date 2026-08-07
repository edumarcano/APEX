"""DEMO_MODE mock payload loading and deterministic Agent responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from core.agent.types import (
    AgentQueryRequest,
    AgentQueryResponse,
    ToolSelectionDiagnostics,
)
from core.api.models import DigestPayload, TelemetryPayload, parse_digest_payload

_MOCK_TELEMETRY_PATH = Path(__file__).resolve().parent.parent / "mock" / "telemetry.json"
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


def load_mock_telemetry() -> tuple[TelemetryPayload, DigestPayload]:
    """Load static demo telemetry and digest from ``core/mock/telemetry.json``."""
    try:
        with open(_MOCK_TELEMETRY_PATH, encoding="utf-8") as mock_file:
            payload = json.load(mock_file)
    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo telemetry payload unavailable.",
        ) from None

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo telemetry payload must be a JSON object.",
        )

    digest = parse_digest_payload(payload.get("digest"))

    try:
        telemetry = TelemetryPayload(**payload)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo telemetry payload failed schema validation.",
        ) from None

    return telemetry, digest


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
    greeting = _demo_greeting()
    return [
        {
            "id": 3,
            "timestamp": "2026-06-08T08:15:00",
            "briefing": (
                f"{greeting} APEX simulation controls are operational. "
                "Atmospheric sensors report seventy-two degrees with clear skies. "
                "Your inbox has two unread primary messages, and your next calendar item, "
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
    return (
        f"{_demo_greeting()} APEX simulation controls are operational. "
        "Atmospheric sensors report seventy-two degrees with clear skies. "
        "The Monaco Grand Prix is scheduled for this week, with the main race running on Sunday. "
        "Your inbox has two unread primary messages, and your next calendar item, "
        "Demo Presentation, begins at three PM. All local databases are fully synchronized."
    )


def _demo_greeting() -> str:
    """Return a demo greeting using the optional local user designation."""
    from core.settings import get_settings_store

    designation = get_settings_store().get_snapshot().user_designation
    return f"Greetings {designation}." if designation else "Greetings."


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
