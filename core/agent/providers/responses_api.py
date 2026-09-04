"""OpenAI-compatible Responses API adapter.

Browser-owned history remains authoritative. Providers always send
``store=False`` and never persist provider response IDs across browser turns.
Custom APEX function tools are supported. General provider web search remains
forbidden.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from core.agent.capabilities import CapabilityDescriptor
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.contract import (
    ProviderTurnResult,
    ProviderToolEvent,
    ProviderStreamEvent,
    ProviderStreamObserver,
)
from core.agent.providers.retries import (
    call_with_bounded_retries,
    exponential_backoff_seconds,
    fixed_backoff_seconds,
)
from core.agent.tool_schemas import descriptor_to_responses_tool
from core.agent.types import AgentMessage, Citation, TokenUsage, ToolCall, ToolResult

_LOGGER = logging.getLogger(__name__)
RESPONSES_REQUEST_TIMEOUT_SECONDS = 120.0

ResponsesProviderKind = Literal["openai"]

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
        api_model: str,
        max_tool_turns: int,
        max_tool_calls: int,
        system_instruction: str,
        reasoning_effort: (
            Literal["none", "minimal", "low", "medium", "high", "xhigh"] | str | None
        ) = None,
        hosted_tools: frozenset[str] = frozenset(),
        supports_encrypted_reasoning: bool = True,
    ) -> None:
        self.provider = provider
        self.display_name = display_name
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
        if item_type in {"web_search_call", "mcp_call"}:
            name = {
                "web_search_call": "web_search",
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
    """Shared Responses API client used by OpenAI adapter."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        provider_kind: ResponsesProviderKind,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.provider_kind = provider_kind
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": RESPONSES_REQUEST_TIMEOUT_SECONDS,
        }
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
        *,
        execution_control: Any | None = None,
        stream_observer: ProviderStreamObserver | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> ProviderTurnResult:
        system_instruction = (
            system_instruction_override or profile.system_instruction
        ) + SECURITY_BOUNDARY_DIRECTIVE

        input_items = _messages_to_responses_input(messages)
        request_tools = [descriptor_to_responses_tool(tool) for tool in tools]
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
        schema_applied = bool(output_schema and not tools)
        if schema_applied and self.provider_kind == "openai":
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "apex_output",
                    "schema": output_schema,
                    "strict": True,
                }
            }

        def _create() -> Any:
            if execution_control is not None:
                execution_control.before_provider_attempt()
            call_request = dict(request)
            if execution_control is not None:
                call_request["timeout"] = min(
                    RESPONSES_REQUEST_TIMEOUT_SECONDS,
                    max(0.1, execution_control.remaining_seconds()),
                )
            try:
                return self.client.responses.create(**call_request, stream=True)
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

        def _consume() -> Any:
            stream = _create()
            # Compatibility with lightweight fakes and providers that return a
            # completed response despite stream=True.
            completed_output = getattr(stream, "output", None)
            if isinstance(completed_output, list) and completed_output:
                return stream
            text_parts: list[str] = []
            stream_started = time.perf_counter()
            ttft_ms: float | None = None
            tool_state: dict[int, dict[str, Any]] = {}
            output_items: list[dict[str, Any]] = []
            final_model: str | None = None
            final_usage: Any = None
            try:
                for raw_event in stream:
                    if execution_control is not None:
                        execution_control.before_provider_attempt()
                    event = _item_to_dict(raw_event)
                    event_type = str(event.get("type") or "")
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            text_parts.append(delta)
                            if ttft_ms is None:
                                ttft_ms = round((time.perf_counter() - stream_started) * 1000, 2)
                            if stream_observer is not None:
                                stream_observer(ProviderStreamEvent(kind="text", text=delta))
                    elif event_type == "response.output_item.added":
                        item = event.get("item")
                        item = _item_to_dict(item) if item is not None and not isinstance(item, dict) else (item or {})
                        if item.get("type") == "function_call":
                            index = int(event.get("output_index", len(tool_state)))
                            tool_state[index] = {
                                "id": item.get("call_id") or item.get("id") or f"call_{index}",
                                "name": item.get("name") or "",
                                "arguments": "",
                            }
                            if text_parts and stream_observer is not None:
                                stream_observer(ProviderStreamEvent(kind="reset"))
                    elif event_type == "response.function_call_arguments.delta":
                        index = int(event.get("output_index", event.get("item_id", 0)) if str(event.get("output_index", "")).isdigit() else 0)
                        state = tool_state.setdefault(index, {"id": f"call_{index}", "name": "", "arguments": ""})
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            state["arguments"] += delta
                    elif event_type == "response.output_item.done":
                        item = event.get("item")
                        item = _item_to_dict(item) if item is not None and not isinstance(item, dict) else (item or {})
                        if item.get("type") == "function_call":
                            index = int(event.get("output_index", len(tool_state)))
                            state = tool_state.setdefault(index, {})
                            state.update(item)
                    elif event_type in {"response.completed", "response.done"}:
                        response = event.get("response") or event
                        if isinstance(response, dict):
                            if isinstance(response.get("output"), list):
                                output_items = response["output"]
                            final_model = response.get("model") if isinstance(response.get("model"), str) else None
                            final_usage = response.get("usage")
                response_obj = type("StreamResponse", (), {})()
                response_obj.output = output_items
                response_obj.model = final_model or profile.api_model
                response_obj.usage = final_usage
                response_obj._stream_text = "".join(text_parts)
                response_obj._stream_tools = tool_state
                response_obj._stream_measurements = {
                    "ttft_ms": ttft_ms,
                } if ttft_ms is not None else {}
                return response_obj
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

        started = time.perf_counter()
        response, retry_count = call_with_bounded_retries(
            _consume,
            is_retryable=_is_retryable_responses_error,
            wait_seconds=_responses_wait_seconds,
            log_label=f"{self.provider_kind}-responses",
            check=execution_control.before_provider_attempt if execution_control is not None else None,
            before_retry=execution_control.before_retry if execution_control is not None else None,
            remaining_seconds=execution_control.remaining_seconds if execution_control is not None else None,
            execution_control=execution_control,
        )
        provider_ms = round((time.perf_counter() - started) * 1000, 2)

        output = list(getattr(response, "output", None) or [])
        content, tool_calls, serialized_items = _extract_text_and_tools(output)
        streamed_text = getattr(response, "_stream_text", None)
        if isinstance(streamed_text, str):
            content = streamed_text or None
            stream_tools = getattr(response, "_stream_tools", {})
            tool_calls = []
            for index, item in (sorted(stream_tools.items()) if isinstance(stream_tools, dict) else []):
                if not isinstance(item, dict):
                    continue
                tool_calls.append(ToolCall(
                    id=str(item.get("call_id") or item.get("id") or f"call_{index}"),
                    name=str(item.get("name") or ""),
                    arguments=_parse_arguments(item.get("arguments", "")),
                ))
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
        if stream_observer is not None:
            stream_observer(ProviderStreamEvent(kind="completed"))

        stream_measurements = getattr(response, "_stream_measurements", None)
        if not isinstance(stream_measurements, dict):
            stream_measurements = {}
        return ProviderTurnResult(
            message=message,
            resolved_model=resolved_model if isinstance(resolved_model, str) else None,
            usage=usage,
            provider_ms=provider_ms,
            citations=citations,
            provider_tool_events=provider_tool_events,
            retry_count=retry_count,
            output_schema_applied=schema_applied,
            runtime_measurements={
                "total_duration_ms": provider_ms,
                **stream_measurements,
            },
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
