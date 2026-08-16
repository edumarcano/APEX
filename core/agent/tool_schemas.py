"""Shared model-facing tool-schema serialization and token estimation."""

from __future__ import annotations

import json
import math
from typing import Any

from core.agent.capabilities import CapabilityDescriptor


def descriptor_to_openai_schema(
    descriptor: CapabilityDescriptor,
) -> dict[str, Any]:
    """Convert a capability descriptor into an OpenAI Chat Completions tool schema."""
    parameters = dict(descriptor.input_schema)
    parameters.setdefault("type", "object")
    parameters.setdefault("properties", {})
    return {
        "type": "function",
        "function": {
            "name": descriptor.name,
            "description": descriptor.description,
            "parameters": parameters,
        },
    }


def descriptor_to_responses_tool(
    descriptor: CapabilityDescriptor,
) -> dict[str, Any]:
    """Convert a capability descriptor into a Responses API function tool."""
    parameters = dict(descriptor.input_schema)
    parameters.setdefault("type", "object")
    parameters.setdefault("properties", {})
    return {
        "type": "function",
        "name": descriptor.name,
        "description": descriptor.description,
        "parameters": parameters,
    }


_COMPACT_BRAVE_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The concise web search query.",
            "minLength": 1,
        },
        "count": {
            "type": "integer",
            "description": "Maximum results to return.",
            "minimum": 1,
            "maximum": 10,
            "default": 5,
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

_LOCAL_READ_ONLY_TOOL_GUIDANCE = (
    "Read-only; use directly when needed without asking for confirmation."
)


def project_descriptor_for_agent(
    agent_key: str,
    descriptor: CapabilityDescriptor,
) -> CapabilityDescriptor:
    """Return an Agent-specific model schema without mutating registry state.

    Local models benefit from a compact Brave search contract and explicit
    read-only guidance. The projection belongs to the shared schema boundary so
    every Agent, catalog view, preflight estimate, and provider turn uses the
    same descriptor.
    """
    projected = descriptor
    uses_compact_brave = False
    if agent_key == "felis" and descriptor.name == "brave_brave_web_search":
        import core.agent.catalog as catalog

        uses_compact_brave = catalog.resolve_felis_runtime() == "ollama"
    elif (
        agent_key in {"sorex", "mus"}
        and descriptor.name == "brave_brave_web_search"
    ):
        uses_compact_brave = True
    if uses_compact_brave:
        projected = descriptor.model_copy(
            update={
                "description": (
                    "Search the public web for current information. Use a concise "
                    "query and request no more results than needed."
                ),
                "input_schema": _COMPACT_BRAVE_SEARCH_SCHEMA,
            }
        )

    from core.agent.catalog import is_local_agent_key

    if is_local_agent_key(agent_key) and projected.risk == "read":
        projected = projected.model_copy(
            update={
                "description": (
                    f"{_LOCAL_READ_ONLY_TOOL_GUIDANCE} "
                    f"{projected.description}"
                )
            }
        )
    return projected


def estimate_json_tokens(
    payload: Any,
    *,
    bytes_per_token: int = 3,
    allowance_tokens: int = 0,
) -> int:
    """Conservatively estimate tokens from compact UTF-8 JSON size."""
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    byte_count = len(serialized.encode("utf-8"))
    return math.ceil(byte_count / bytes_per_token) + allowance_tokens
