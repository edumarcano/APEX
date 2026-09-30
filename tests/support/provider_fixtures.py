"""Provider fixtures that are deliberately kept out of production modules."""

from __future__ import annotations

from core.agent.providers.responses_api import ResponsesModelProfile


OPENAI_INTERNAL_PROFILES: dict[str, ResponsesModelProfile] = {
    "openai_default": ResponsesModelProfile(
        provider="openai",
        display_name="OpenAI Default",
        api_model="gpt-5.6-luna",
        max_tool_turns=4,
        max_tool_calls=6,
        system_instruction="",
        reasoning_effort="medium",
    ),
}


def response_event_stream(
    *,
    text: str = "",
    model: str = "gpt-5.6-luna",
    usage: dict[str, int] | None = None,
    output: list[dict] | None = None,
) -> list[dict]:
    """Build the SDK's iterable event shape for simple final message responses."""
    events: list[dict] = []
    if text:
        events.append({"type": "response.output_text.delta", "delta": text})
    response: dict = {"model": model, "output": output or []}
    if usage is not None:
        response["usage"] = usage
    events.append({"type": "response.completed", "response": response})
    return events
