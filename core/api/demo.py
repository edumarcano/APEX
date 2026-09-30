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
from core.agent.model_catalog import ModelProfile
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


def run_demo_agent_query(
    payload: AgentQueryRequest,
    *,
    model_profile: ModelProfile,
    resolved_effort: str | None,
    tool_selection: ToolSelectionDiagnostics | None = None,
) -> AgentQueryResponse:
    """Return deterministic Agent responses when ``DEMO_MODE`` is active."""
    from core.agent.catalog import (
        AGENT_SPECS,
        build_provider_profile,
        build_agent_used_metadata,
        is_agent_visible,
    )

    agent_key = payload.agent
    if agent_key not in AGENT_SPECS or not is_agent_visible(agent_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_key!r} is not available.",
        )

    agent = build_provider_profile(
        native_effort=resolved_effort,
        model_id=model_profile.model_id,
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
        agent_used=build_agent_used_metadata(
            agent_key,
            provider=agent.provider,
            configured_model=agent.api_model,
            resolved_model=agent.api_model,
            requested_effort=payload.effort,
            resolved_effort=resolved_effort,
            runtime=model_profile.runtime,
            model_stability=getattr(agent, "stability", None),
            hosted_tools=getattr(agent, "hosted_tools", None),
        ),
        tool_trace=selected_response["tool_trace"],
        tool_outputs=selected_response.get("tool_outputs", []),
        error=None,
        resolved_tool_selection=tool_selection or ToolSelectionDiagnostics(),
    )
