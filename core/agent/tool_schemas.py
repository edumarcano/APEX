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


_LOCAL_READ_ONLY_TOOL_GUIDANCE = (
    "Read-only; use directly when needed without asking for confirmation."
)


def project_descriptor_for_model(
    model_id: str,
    descriptor: CapabilityDescriptor,
) -> CapabilityDescriptor:
    """Return a model-specific schema without mutating registry state.

    Local models benefit from explicit read-only guidance. The projection belongs
    to the shared schema boundary so every Agent, catalog view, preflight estimate,
    and provider turn uses the same descriptor.
    """
    projected = descriptor
    from core.agent.model_catalog import get_model_profile

    profile = get_model_profile(model_id)
    if profile is None:
        raise ValueError(f"Unknown model {model_id!r}")

    if profile.runtime == "local" and projected.risk == "read":
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
