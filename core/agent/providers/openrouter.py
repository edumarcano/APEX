"""OpenRouter Chat Completions adapter with mandatory privacy routing."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from core.agent.capabilities import CapabilityDescriptor
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.retries import (
    call_with_bounded_retries,
    exponential_backoff_seconds,
    fixed_backoff_seconds,
)
from core.agent.tool_schemas import descriptor_to_openai_schema
from core.agent.types import AgentMessage, TokenUsage, ToolCall, ToolResult

OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_REQUEST_TIMEOUT_SECONDS = 120.0
_LOGGER = logging.getLogger(__name__)

# This policy is intentionally not configurable. Every retry reuses the same
# request object, so no failure path can silently broaden personal-data routing.
OPENROUTER_PRIVACY_POLICY: dict[str, Any] = {
    "provider": {
        "zdr": True,
        "data_collection": "deny",
        "require_parameters": True,
    }
}


class OpenRouterModelProfile:
    """Concrete Panthera profile for OpenRouter Chat Completions."""

    provider: Literal["openrouter"] = "openrouter"

    def __init__(
        self,
        *,
        display_name: str,
        api_model: str,
        max_tool_turns: int,
        max_tool_calls: int,
        system_instruction: str,
        reasoning_effort: str | None,
    ) -> None:
        self.display_name = display_name
        self.api_model = api_model
        self.max_tool_turns = max_tool_turns
        self.max_tool_calls = max_tool_calls
        self.system_instruction = system_instruction
        self.reasoning_effort = reasoning_effort
        self.hosted_tools: frozenset[str] = frozenset()
        self.supports_encrypted_reasoning = False

    def model_dump(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "display_name": self.display_name,
            "api_model": self.api_model,
            "max_tool_turns": self.max_tool_turns,
            "max_tool_calls": self.max_tool_calls,
            "system_instruction": self.system_instruction,
            "reasoning_effort": self.reasoning_effort,
            "hosted_tools": [],
            "supports_encrypted_reasoning": False,
        }


class OpenRouterProvider:
    """OpenRouter adapter restricted to ZDR, no-data-collection endpoints."""

    def __init__(self, api_key: str, *, base_url: str = OPENROUTER_API_BASE_URL) -> None:
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            timeout=OPENROUTER_REQUEST_TIMEOUT_SECONDS,
        )

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: OpenRouterModelProfile,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        request: dict[str, Any] = {
            "model": profile.api_model,
            "messages": _messages_to_chat(messages, system_instruction_override or profile.system_instruction),
            # OpenRouter extends the Chat Completions JSON body with
            # ``reasoning``.  The OpenAI SDK rejects that extension as a
            # top-level keyword, so keep it inside its supported extra_body
            # escape hatch alongside the immutable privacy routing policy.
            "extra_body": dict(OPENROUTER_PRIVACY_POLICY),
        }
        if tools:
            request["tools"] = [descriptor_to_openai_schema(tool) for tool in tools]
        if profile.reasoning_effort is not None:
            request["extra_body"]["reasoning"] = {"effort": profile.reasoning_effort}

        def _create() -> Any:
            return self.client.chat.completions.create(**request)

        started = time.perf_counter()
        response, retry_count = call_with_bounded_retries(
            _create,
            is_retryable=_is_retryable_error,
            wait_seconds=_wait_seconds,
            log_label="openrouter-chat",
        )
        provider_ms = round((time.perf_counter() - started) * 1000, 2)
        payload = _as_dict(response)
        choice = _first_choice(payload)
        message_data = choice.get("message") if choice else {}
        if not isinstance(message_data, dict):
            message_data = {}
        content = message_data.get("content")
        tool_calls = _parse_tool_calls(message_data.get("tool_calls"))
        reasoning_details = message_data.get("reasoning_details")
        if not isinstance(reasoning_details, list):
            reasoning_details = None
        message = AgentMessage(
            role="agent",
            content=content if isinstance(content, str) else None,
            tool_calls=tool_calls or None,
            provider_reasoning_details=reasoning_details,
        )
        resolved_model = payload.get("model")
        return ProviderTurnResult(
            message=message,
            resolved_model=resolved_model if isinstance(resolved_model, str) else profile.api_model,
            usage=_parse_usage(payload.get("usage")),
            provider_ms=provider_ms,
            retry_count=retry_count,
        )


def _messages_to_chat(messages: list[AgentMessage], system_instruction: str) -> list[dict[str, Any]]:
    chat: list[dict[str, Any]] = [{"role": "system", "content": system_instruction + SECURITY_BOUNDARY_DIRECTIVE}]
    for message in messages:
        if message.role == "user":
            chat.append({"role": "user", "content": message.content or ""})
        elif message.role == "agent":
            assistant: dict[str, Any] = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                assistant["tool_calls"] = [
                    {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments)}}
                    for call in message.tool_calls
                ]
            if message.provider_reasoning_details:
                assistant["reasoning_details"] = message.provider_reasoning_details
            chat.append(assistant)
        elif message.tool_results:
            for result in message.tool_results:
                chat.append({
                    "role": "tool",
                    "tool_call_id": result.id,
                    "content": _wrap_untrusted_tool_output(result),
                })
    return chat


def _wrap_untrusted_tool_output(result: ToolResult) -> str:
    try:
        rendered = json.dumps(result.output, default=str)
    except (TypeError, ValueError):
        rendered = str(result.output)
    return f"<untrusted_tool_output name='{result.name}'>\n{rendered}\n</untrusted_tool_output>"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(exclude_none=True)
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _first_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    return choices[0] if isinstance(choices[0], dict) else _as_dict(choices[0])


def _parse_tool_calls(value: Any) -> list[ToolCall]:
    if not isinstance(value, list):
        return []
    calls: list[ToolCall] = []
    for raw in value:
        item = _as_dict(raw)
        function = item.get("function")
        function = function if isinstance(function, dict) else {}
        arguments = function.get("arguments")
        parsed: dict[str, Any] = {}
        if isinstance(arguments, dict):
            parsed = arguments
        elif isinstance(arguments, str):
            try:
                decoded = json.loads(arguments)
                parsed = decoded if isinstance(decoded, dict) else {}
            except json.JSONDecodeError:
                _LOGGER.warning("[AGENT][OPENROUTER] Failed to parse tool-call arguments")
        name = function.get("name")
        call_id = item.get("id")
        if isinstance(name, str) and name and isinstance(call_id, str) and call_id:
            calls.append(ToolCall(id=call_id, name=name, arguments=parsed))
    return calls


def _parse_usage(value: Any) -> TokenUsage | None:
    data = _as_dict(value)
    if not data:
        return None
    prompt = data.get("prompt_tokens")
    completion = data.get("completion_tokens")
    total = data.get("total_tokens")
    prompt_details = data.get("prompt_tokens_details")
    completion_details = data.get("completion_tokens_details")
    cached = prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
    reasoning = completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else None
    if not any(isinstance(item, int) for item in (prompt, completion, total, cached, reasoning)):
        return None
    visible = completion if isinstance(completion, int) else None
    if visible is not None and isinstance(reasoning, int):
        visible = max(visible - reasoning, 0)
    return TokenUsage(
        input_tokens=prompt if isinstance(prompt, int) else None,
        cached_input_tokens=cached if isinstance(cached, int) else None,
        reasoning_tokens=reasoning if isinstance(reasoning, int) else None,
        output_tokens=visible,
        total_tokens=total if isinstance(total, int) else None,
    )


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
        return True
    return isinstance(exc, APIStatusError) and exc.status_code in {429, 500, 502, 503, 504}


def _wait_seconds(attempt: int, exc: BaseException) -> float:
    if isinstance(exc, RateLimitError) or (isinstance(exc, APIStatusError) and exc.status_code == 429):
        return exponential_backoff_seconds(attempt)
    return fixed_backoff_seconds(attempt)
