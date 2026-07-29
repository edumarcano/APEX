"""Shared model-facing tool-schema serialization and token estimation."""

from __future__ import annotations

import json
import math
from typing import Any

from core.agent.capabilities import CapabilityDescriptor


def descriptor_to_openai_schema(
    descriptor: CapabilityDescriptor,
) -> dict[str, Any]:
    """Convert a capability descriptor into an OpenAI-compatible tool schema."""
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
