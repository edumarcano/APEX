"""Shared OpenAI-compatible Responses API adapter (OpenAI and xAI).

Browser-owned history remains authoritative. Providers always send
``store=False`` and never persist provider response IDs across browser turns.
Custom APEX function tools are supported. General provider web search remains
forbidden; xAI profiles may opt into X Search explicitly.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from core.agent.capabilities import CapabilityDescriptor
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.contract import ProviderTurnResult, ProviderToolEvent
from core.agent.providers.retries import (
    call_with_bounded_retries,
    exponential_backoff_seconds,
    fixed_backoff_seconds,
)
from core.agent.tool_schemas import descriptor_to_responses_tool
from core.agent.types import AgentMessage, Citation, TokenUsage, ToolCall, ToolResult

_LOGGER = logging.getLogger(__name__)

ResponsesProviderKind = Literal["openai", "xai"]

# Native hosted tools that must never be attached by APEX adapters in v1.19
# branch 1 (Brave remains the general search path when connected later).
_FORBIDDEN_NATIVE_TOOLS = frozenset(
    {
        "web_search",
        "web_search_preview",
        "browser",
        "browser_search",
    }
)


class ResponsesModelProfile:
    """Minimal profile surface accepted by Responses-compatible providers."""

    def __init__(
        self,
        *,
        provider: ResponsesProviderKind,
        display_name: str,
        agent_version: str,
        api_model: str,
        max_tool_turns: int,
        max_tool_calls: int,
        system_instruction: str,
        reasoning_effort: Literal["low", "medium", "high"] | None = None,
        hosted_tools: frozenset[Literal["x_search"]] = frozenset(),
        supports_encrypted_reasoning: bool = True,
    ) -> None:
        self.provider = provider
        self.display_name = display_name
        self.agent_version = agent_version
        self.api_model = api_model
        self.max_tool_turns = max_tool_turns
        self.max_tool_calls = max_tool_calls
        self.system_instruction = system_instruction
        self.reasoning_effort = reasoning_effort
        self.hosted_tools = hosted_tools
        self.supports_encrypted_reasoning = supports_encrypted_reasoning

    def model_dump(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "display_name": self.display_name,
            "agent_version": self.agent_version,
            "api_model": self.api_model,
            "max_tool_turns": self.max_tool_turns,
            "max_tool_calls": self.max_tool_calls,
            "system_instruction": self.system_instruction,
            "reasoning_effort": self.reasoning_effort,
            "hosted_tools": sorted(self.hosted_tools),
            "supports_encrypted_reasoning": self.supports_encrypted_reasoning,
        }


def _serialize_tool_output(output: Any) -> str:
    try:
        return json.dumps(output, default=str)
    except (TypeError, ValueError):
        return str(output)


def _wrap_untrusted_tool_output(result: ToolResult) -> str:
    return (
        f"<untrusted_tool_output name='{result.name}'>\n"
        f"{_serialize_tool_output(result.output)}\n"
        f"</untrusted_tool_output>"
    )


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(exclude_none=True)
    if hasattr(item, "to_dict"):
        return item.to_dict()
    raise TypeError(f"Unsupported Responses output item type: {type(item)!r}")


def _messages_to_responses_input(
    messages: list[AgentMessage],
) -> list[dict[str, Any]]:
    """Convert APEX history into Responses API input items."""
    items: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "user":
            items.append(
                {
                    "role": "user",
                    "content": message.content if message.content is not None else "",
                }
            )
            continue

        if message.role == "agent":
            if message.provider_output_items:
                items.extend(message.provider_output_items)
                continue
            # Fallback reconstruction when opaque items are unavailable
            # (e.g. browser-trimmed history without provider payloads).
            if message.content:
                items.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                    }
                )
            if message.tool_calls:
                for call in message.tool_calls:
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call.id,
                            "name": call.name,
                            "arguments": json.dumps(call.arguments),
                        }
                    )
            continue

        if message.role == "tool" and message.tool_results:
            for result in message.tool_results:
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": result.id,
                        "output": _wrap_untrusted_tool_output(result),
                    }
                )

    return items


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            _LOGGER.warning(
                "[AGENT][RESPONSES] Failed to parse tool-call arguments JSON"
            )
    return {}


def _extract_text_and_tools(
    output_items: list[Any],
) -> tuple[str | None, list[ToolCall], list[dict[str, Any]]]:
    text_segments: list[str] = []
    tool_calls: list[ToolCall] = []
    serialized_items: list[dict[str, Any]] = []

    for raw_item in output_items:
        item = _item_to_dict(raw_item)
        serialized_items.append(item)
        item_type = item.get("type")

        if item_type in {"message", "output_message"}:
            content = item.get("content") or []
            if isinstance(content, str):
                text_segments.append(content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") in {"output_text", "text"} and block.get(
                        "text"
                    ):
                        text_segments.append(str(block["text"]))
            continue

        if item_type == "function_call":
            name = str(item.get("name") or "")
            call_id = str(item.get("call_id") or item.get("id") or f"call_{name}")
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=_parse_arguments(item.get("arguments")),
                )
            )

    combined = "".join(text_segments).strip() or None
    return combined, tool_calls, serialized_items


def _parse_usage(raw_usage: Any) -> TokenUsage | None:
    if raw_usage is None:
        return None
    if hasattr(raw_usage, "model_dump"):
        data = raw_usage.model_dump()
    elif isinstance(raw_usage, dict):
        data = raw_usage
    else:
        data = {
            "input_tokens": getattr(raw_usage, "input_tokens", None),
            "output_tokens": getattr(raw_usage, "output_tokens", None),
            "total_tokens": getattr(raw_usage, "total_tokens", None),
        }

    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    total_tokens = data.get("total_tokens")

    cached = None
    input_details = data.get("input_tokens_details") or {}
    if isinstance(input_details, dict):
        cached = input_details.get("cached_tokens")

    reasoning = None
    output_details = data.get("output_tokens_details") or {}
    if isinstance(output_details, dict):
        reasoning = output_details.get("reasoning_tokens")

    if all(
        value is None
        for value in (input_tokens, output_tokens, total_tokens, cached, reasoning)
    ):
        return None

    visible_output = output_tokens if isinstance(output_tokens, int) else None
    if visible_output is not None and isinstance(reasoning, int):
        # The Responses API nests reasoning inside output_tokens; TokenUsage
        # keeps them separate so cost is not charged twice.
        visible_output = max(visible_output - reasoning, 0)

    return TokenUsage(
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        cached_input_tokens=cached if isinstance(cached, int) else None,
        reasoning_tokens=reasoning if isinstance(reasoning, int) else None,
        output_tokens=visible_output,
        total_tokens=total_tokens if isinstance(total_tokens, int) else None,
    )


def _extract_citations(output_items: list[dict[str, Any]]) -> list[Citation]:
    citations: list[Citation] = []
    for item in output_items:
        # Provider-hosted search annotations appear on message content parts.
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            annotations = block.get("annotations") or []
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue
                uri = annotation.get("url") or annotation.get("uri")
                title = annotation.get("title")
                if uri or title:
                    citations.append(
                        Citation(
                            title=title if isinstance(title, str) else None,
                            uri=uri if isinstance(uri, str) else None,
                            source=annotation.get("type")
                            if isinstance(annotation.get("type"), str)
                            else None,
                        )
                    )
    return citations


def _extract_provider_tool_events(
    output_items: list[dict[str, Any]],
) -> list[ProviderToolEvent]:
    events: list[ProviderToolEvent] = []
    for item in output_items:
        item_type = item.get("type")
        if item_type in {"web_search_call", "x_search_call", "mcp_call"}:
            name = {
                "web_search_call": "web_search",
                "x_search_call": "x_search",
                "mcp_call": str(item.get("name") or "mcp_call"),
            }[item_type]
            status_raw = item.get("status")
            status: Literal["ok", "error", "unknown"]
            if status_raw in {"completed", "ok"}:
                status = "ok"
            elif status_raw in {"failed", "error"}:
                status = "error"
            else:
                status = "unknown"
            events.append(
                ProviderToolEvent(
                    name=name,
                    status=status,
                    billable_units=1 if status == "ok" else 0,
                )
            )
    return events


def _attribute_hosted_durations(
    events: list[ProviderToolEvent], provider_ms: float
) -> None:
    """Share the measured turn duration across hosted calls.

    The Responses API reports no per-call timing, so an even share of the
    turn's wall clock is the only measured value available.
    """
    if not events:
        return
    share = round(provider_ms / len(events), 2)
    for event in events:
        event.duration_ms = share


def assert_no_forbidden_native_tools(tools: list[dict[str, Any]]) -> None:
    """Reject accidental attachment of provider-native web search tools."""
    for tool in tools:
        tool_type = str(tool.get("type") or "").lower()
        if tool_type in _FORBIDDEN_NATIVE_TOOLS:
            raise ValueError(
                f"Native web-search tool {tool_type!r} is not permitted "
                "on APEX Responses adapters."
            )


class ResponsesApiProvider:
    """Shared Responses API client used by OpenAI and xAI adapters."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        provider_kind: ResponsesProviderKind,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.provider_kind = provider_kind
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        if default_headers:
            client_kwargs["default_headers"] = default_headers
        self.client = OpenAI(**client_kwargs)

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: ResponsesModelProfile,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        system_instruction = (
            system_instruction_override or profile.system_instruction
        ) + SECURITY_BOUNDARY_DIRECTIVE

        input_items = _messages_to_responses_input(messages)
        request_tools = [descriptor_to_responses_tool(tool) for tool in tools]
        if "x_search" in profile.hosted_tools:
            if self.provider_kind != "xai":
                raise ValueError("X Search may only be attached to xAI profiles.")
            request_tools.append({"type": "x_search"})
        assert_no_forbidden_native_tools(request_tools)

        request: dict[str, Any] = {
            "model": profile.api_model,
            "input": input_items,
            "instructions": system_instruction,
            "store": False,
        }
        if request_tools:
            request["tools"] = request_tools
        if profile.reasoning_effort:
            # Only reasoning models accept these fields; sending them to a
            # non-reasoning model is rejected by the API.
            request["reasoning"] = {"effort": profile.reasoning_effort}
            if profile.supports_encrypted_reasoning:
                request["include"] = ["reasoning.encrypted_content"]

        def _create() -> Any:
            try:
                return self.client.responses.create(**request)
            except APIStatusError as exc:
                if exc.status_code == 400:
                    _LOGGER.warning(
                        "%s Responses API 400 Bad Request for model %s: %s (body=%s, request_keys=%s)",
                        self.provider_kind,
                        profile.api_model,
                        getattr(exc, "message", str(exc)),
                        getattr(exc, "body", None),
                        sorted(request.keys()),
                    )
                raise

        started = time.perf_counter()
        response, retry_count = call_with_bounded_retries(
            _create,
            is_retryable=_is_retryable_responses_error,
            wait_seconds=_responses_wait_seconds,
            log_label=f"{self.provider_kind}-responses",
        )
        provider_ms = round((time.perf_counter() - started) * 1000, 2)

        output = list(getattr(response, "output", None) or [])
        content, tool_calls, serialized_items = _extract_text_and_tools(output)
        message = AgentMessage(
            role="agent",
            content=content,
            tool_calls=tool_calls or None,
            provider_output_items=serialized_items or None,
        )

        resolved_model = getattr(response, "model", None) or profile.api_model
        usage = _parse_usage(getattr(response, "usage", None))
        citations = _extract_citations(serialized_items)
        provider_tool_events = _extract_provider_tool_events(serialized_items)
        _attribute_hosted_durations(provider_tool_events, provider_ms)

        return ProviderTurnResult(
            message=message,
            resolved_model=resolved_model if isinstance(resolved_model, str) else None,
            usage=usage,
            provider_ms=provider_ms,
            citations=citations,
            provider_tool_events=provider_tool_events,
            retry_count=retry_count,
        )


def _is_retryable_responses_error(exc: BaseException) -> bool:
    if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in {429, 500, 502, 503, 504}
    return False


def _responses_wait_seconds(attempt: int, exc: BaseException) -> float:
    if isinstance(exc, RateLimitError):
        return exponential_backoff_seconds(attempt)
    if isinstance(exc, APIStatusError) and exc.status_code == 429:
        return exponential_backoff_seconds(attempt)
    return fixed_backoff_seconds(attempt)
