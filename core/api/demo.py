"""DEMO_MODE mock payload loading and deterministic assistant responses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from core.agent.providers.gemini_models import GEMINI_MODEL_PROFILES, GeminiModelProfile
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES, OllamaModelProfile
from core.agent.types import AgentQueryRequest, AgentQueryResponse
from core.api.models import DigestPayload, TelemetryPayload, parse_digest_payload

_MOCK_TELEMETRY_PATH = Path(__file__).resolve().parent.parent / "mock" / "telemetry.json"
_MOCK_ASSISTANT_PATH = Path(__file__).resolve().parent.parent / "mock" / "assistant.json"


def _validate_mock_agent_response(
    response: Any,
    *,
    require_keywords: bool,
) -> dict[str, Any]:
    """Validate one deterministic demo assistant response."""
    if not isinstance(response, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo assistant response must be a JSON object.",
        )

    answer = response.get("answer")
    tool_trace = response.get("tool_trace")
    tool_outputs = response.get("tool_outputs", [])
    keywords = response.get("keywords")

    if not isinstance(answer, str):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo assistant response must include string 'answer'.",
        )
    if not isinstance(tool_trace, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo assistant response must include list 'tool_trace'.",
        )
    if require_keywords:
        if not isinstance(keywords, list) or not all(
            isinstance(keyword, str) for keyword in keywords
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Demo assistant response must include list of string "
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
            detail="Demo assistant response must include list 'tool_outputs'.",
        )

    required_tool_output_keys = {"name", "status", "duration_ms", "output"}
    for index, entry in enumerate(tool_outputs):
        if not isinstance(entry, dict):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Demo assistant tool_outputs[{index}] must be a JSON object.",
            )
        missing_keys = required_tool_output_keys - entry.keys()
        if missing_keys:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Demo assistant tool_outputs entries must include "
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
                    f"Demo assistant tool_outputs[{index}] must include string 'name' and 'status'."
                ),
            )
        duration_ms = entry.get("duration_ms")
        if not isinstance(duration_ms, (int, float)):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    f"Demo assistant tool_outputs[{index}] must include numeric 'duration_ms'."
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
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Demo telemetry payload unavailable: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo telemetry payload must be a JSON object.",
        )

    digest = parse_digest_payload(payload.get("digest"))

    try:
        telemetry = TelemetryPayload(**payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Demo telemetry payload failed schema validation: {exc}",
        ) from exc

    return telemetry, digest


def load_mock_agent_responses() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load deterministic assistant responses from ``core/mock/assistant.json``."""
    try:
        with open(_MOCK_ASSISTANT_PATH, encoding="utf-8") as mock_file:
            payload = json.load(mock_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Demo assistant payload unavailable: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo assistant payload must be a JSON object.",
        )

    responses = payload.get("responses")
    if not isinstance(responses, list):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo assistant payload must include list 'responses'.",
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
                "Greetings Chief. APEX simulation controls are operational. "
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
        "Greetings Chief. APEX simulation controls are operational. "
        "Atmospheric sensors report seventy-two degrees with clear skies. "
        "The Monaco Grand Prix is scheduled for this week, with the main race running on Sunday. "
        "Your inbox has two unread primary messages, and your next calendar item, "
        "Demo Presentation, begins at three PM. All local databases are fully synchronized."
    )


def run_demo_agent_query(payload: AgentQueryRequest) -> AgentQueryResponse:
    """Return deterministic assistant responses when ``DEMO_MODE`` is active."""
    profile: GeminiModelProfile | OllamaModelProfile | None = None
    if payload.profile in GEMINI_MODEL_PROFILES:
        profile = GEMINI_MODEL_PROFILES[payload.profile]
    elif payload.profile in OLLAMA_MODEL_PROFILES:
        profile = OLLAMA_MODEL_PROFILES[payload.profile]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown agent profile: {payload.profile!r}",
        )

    prompt_lower = payload.prompt.lower()
    responses, fallback = load_mock_agent_responses()
    selected_response = fallback
    for response in responses:
        if any(keyword in prompt_lower for keyword in response["keywords"]):
            selected_response = response
            break

    return AgentQueryResponse(
        answer=selected_response["answer"],
        profile_used=profile.model_dump(),
        tool_trace=selected_response["tool_trace"],
        tool_outputs=selected_response.get("tool_outputs", []),
        session_id=payload.session_id,
        error=None,
    )
