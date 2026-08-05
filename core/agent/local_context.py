"""Provider-neutral helpers shared by local Agent adapters.

The local runtime coordinator owns admission and residency, while this module
contains only prompt-boundary and local-provider classification helpers.  It
does not execute capabilities or retain conversation state.
"""

from __future__ import annotations

import json
from typing import Any

from core.agent.providers.contract import resolve_inference_provider
from core.agent.types import AgentMessage, ToolResult


LOCAL_INFERENCE_PROVIDERS = frozenset({"ollama", "litert"})


def is_local_profile(profile: object) -> bool:
    """Return whether a profile is served by a local provider backend."""
    try:
        return resolve_inference_provider(profile) in LOCAL_INFERENCE_PROVIDERS
    except TypeError:
        return False


def serialize_tool_output(output: Any) -> str:
    """Serialize tool output without leaking provider exception details."""
    try:
        return json.dumps(output, default=str)
    except (TypeError, ValueError):
        return str(output)


def wrap_untrusted_tool_output(result: ToolResult) -> str:
    """Mark host capability output as data, never as model instructions."""
    return (
        f"<untrusted_tool_output name='{result.name}'>\n"
        f"{serialize_tool_output(result.output)}\n"
        f"</untrusted_tool_output>"
    )


def current_turn_start(messages: list[AgentMessage]) -> int:
    """Return the user-message index that starts the current interaction."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return index
    return 0
