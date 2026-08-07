"""llama.cpp OpenAI-compatible Chat Completions provider for Apex local Agents."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from requests.exceptions import RequestException

from core.agent.capabilities import CapabilityDescriptor
from core.agent.local_runtime.contract import LocalModelRef
from core.agent.local_runtime.coordinator import register_local_activity
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.contract import ProviderTurnResult, merge_token_usage
from core.agent.providers.llama_cpp_lifecycle import get_auth_headers, get_http_session
from core.agent.providers.llama_cpp_models import LlamaCppModelProfile
from core.agent.tool_schemas import descriptor_to_openai_schema, estimate_json_tokens
from core.agent.types import AgentMessage, TokenUsage, ToolCall, ToolResult
from core.agent.providers.llama_cpp_runtime import get_llama_cpp_host

_LOGGER = logging.getLogger(__name__)
_PROMPT_BYTES_PER_TOKEN = 3
_PROMPT_TEMPLATE_ALLOWANCE_TOKENS = 128
_PROMPT_SAFETY_MARGIN_TOKENS = 512


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


def _strip_thinking_tags(content: str | None) -> str:
    """Remove hidden-reasoning style blocks from assistant content."""
    if not content:
        return ""
    think_open = "<" + "think" + ">"
    think_close = "</" + "think" + ">"
    content = re.sub(
        rf"{re.escape(think_open)}[\s\S]*?{re.escape(think_close)}", "", content
    )
    content = re.sub(rf"{re.escape(think_open)}[\s\S]*$", "", content)
    content = re.sub(rf"^[\s\S]*?{re.escape(think_close)}", "", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    return content.strip()


def _parse_tool_call_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                return parsed
            _LOGGER.warning(
                "[AGENT][LLAMA_CPP] Tool-call arguments decoded to non-object; "
                "using empty object"
            )
        except json.JSONDecodeError:
            _LOGGER.warning(
                "[AGENT][LLAMA_CPP] Failed to parse tool-call arguments JSON"
            )
    return {}


def _messages_to_openai(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    openai_messages: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "user":
            openai_messages.append(
                {
                    "role": "user",
                    "content": message.content if message.content is not None else "",
                }
            )
        elif message.role == "agent":
            payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.content if message.content is not None else "",
            }
            if message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(
                                call.arguments, separators=(",", ":")
                            ),
                        },
                    }
                    for call in message.tool_calls
                ]
            openai_messages.append(payload)
        elif message.role == "tool":
            if not message.tool_results:
                continue
            for result in message.tool_results:
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.id,
                        "name": result.name,
                        "content": _wrap_untrusted_tool_output(result),
                    }
                )
    return openai_messages


def _openai_message_to_agent_message(message: dict[str, Any]) -> AgentMessage:
    content = message.get("content")
    if isinstance(content, list):
        # Some servers return content parts; keep text only.
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
            elif isinstance(part, str):
                text_parts.append(part)
        content = "".join(text_parts)

    # Never expose hidden reasoning fields.
    if isinstance(message.get("reasoning_content"), str):
        message = {**message, "reasoning_content": None}

    raw_tool_calls = message.get("tool_calls") or []
    tool_calls: list[ToolCall] = []
    if isinstance(raw_tool_calls, list):
        for idx, raw_call in enumerate(raw_tool_calls):
            if not isinstance(raw_call, dict):
                continue
            function_block = raw_call.get("function") or {}
            if not isinstance(function_block, dict):
                function_block = {}
            call_name = function_block.get("name") or ""
            if not isinstance(call_name, str):
                call_name = ""
            arguments = _parse_tool_call_arguments(function_block.get("arguments"))
            call_id = raw_call.get("id") or f"call_{call_name}_{idx}"
            if not isinstance(call_id, str) or not call_id:
                call_id = f"call_{call_name}_{idx}"
            tool_calls.append(
                ToolCall(id=call_id, name=call_name, arguments=arguments)
            )

    cleaned = content if isinstance(content, str) and content else None
    if cleaned:
        cleaned = _strip_thinking_tags(cleaned) or None

    return AgentMessage(
        role="agent",
        content=cleaned,
        tool_calls=tool_calls or None,
    )


class LlamaCppRequestError(RuntimeError):
    """Sanitized provider failure with enough detail to identify overflow."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail

    @property
    def is_context_overflow(self) -> bool:
        normalized = self.detail.lower()
        markers = (
            "context length",
            "context window",
            "too many tokens",
            "prompt is too long",
            "prompt too long",
            "input length",
            "exceeds the available context",
        )
        if any(marker in normalized for marker in markers):
            return True
        return self.status_code in {400, 413} and any(
            marker in normalized for marker in markers
        )


def _extract_error_detail(response: requests.Response | None) -> str:
    if response is None:
        return ""
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return " ".join(message.split())[:300]
        if isinstance(error, str):
            return " ".join(error.split())[:300]
        message = payload.get("message")
        if isinstance(message, str):
            return " ".join(message.split())[:300]
    return ""


def _post_chat(
    payload: dict[str, Any],
    profile: LlamaCppModelProfile,
) -> dict[str, Any]:
    host = get_llama_cpp_host()
    url = f"{host.rstrip('/')}/v1/chat/completions"
    try:
        response = get_http_session().post(
            url,
            params={"autoload": "false"},
            json=payload,
            headers=get_auth_headers(),
            timeout=profile.generation_timeout,
        )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise RuntimeError(
            f"llama.cpp generation timed out after {profile.generation_timeout}s "
            f"for model {profile.runtime_model_id!r}."
        ) from exc
    except requests.ConnectionError as exc:
        raise RuntimeError(
            f"Failed to connect to llama.cpp at {host}. "
            "Ensure the local llama.cpp router is running."
        ) from exc
    except RequestException as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        detail = _extract_error_detail(exc.response)
        status_detail = f" (HTTP {status_code})" if status_code is not None else ""
        raise LlamaCppRequestError(
            f"llama.cpp request failed for model {profile.runtime_model_id!r}"
            f"{status_detail}{f': {detail}' if detail else '.'}",
            status_code=status_code,
            detail=detail,
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"llama.cpp returned non-JSON response (HTTP {response.status_code})."
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError("llama.cpp returned a non-object JSON chat response.")
    return data


def _estimate_payload_tokens(payload: dict[str, Any]) -> int:
    return estimate_json_tokens(
        payload,
        bytes_per_token=_PROMPT_BYTES_PER_TOKEN,
        allowance_tokens=_PROMPT_TEMPLATE_ALLOWANCE_TOKENS,
    )


def _current_turn_start(messages: list[AgentMessage]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return index
    return 0


def _build_payload(
    messages: list[AgentMessage],
    tools: list[CapabilityDescriptor],
    profile: LlamaCppModelProfile,
    system_instruction: str,
    *,
    max_tokens: int,
) -> dict[str, Any]:
    openai_messages = _messages_to_openai(messages)
    if system_instruction:
        openai_messages.insert(
            0,
            {
                "role": "system",
                "content": system_instruction + SECURITY_BOUNDARY_DIRECTIVE,
            },
        )
    payload: dict[str, Any] = {
        "model": profile.runtime_model_id,
        "messages": openai_messages,
        "stream": False,
        "temperature": profile.default_temperature,
        "max_tokens": max_tokens,
    }
    if profile.reasoning_mode == "none":
        payload["reasoning_effort"] = "none"
    if tools:
        payload["tools"] = [descriptor_to_openai_schema(tool) for tool in tools]
        payload["tool_choice"] = "auto"
        if profile.parallel_tool_calls:
            payload["parallel_tool_calls"] = True
    return payload


def _budget_payload(
    messages: list[AgentMessage],
    tools: list[CapabilityDescriptor],
    profile: LlamaCppModelProfile,
    system_instruction: str,
    *,
    max_tokens: int,
) -> tuple[dict[str, Any], int, int]:
    current_start = _current_turn_start(messages)
    historical = list(messages[:current_start])
    current = list(messages[current_start:])
    dropped = 0
    target = profile.context_window - max_tokens - _PROMPT_SAFETY_MARGIN_TOKENS

    while True:
        payload = _build_payload(
            historical + current,
            tools,
            profile,
            system_instruction,
            max_tokens=max_tokens,
        )
        estimated = _estimate_payload_tokens(payload)
        if estimated <= target:
            return payload, estimated, dropped
        if not historical:
            raise RuntimeError(
                "Local prompt budget exceeded after removing prior history "
                f"(estimated={estimated}, budget={target}, "
                f"context_window={profile.context_window})."
            )
        next_user = next(
            (
                index
                for index, message in enumerate(historical[1:], start=1)
                if message.role == "user"
            ),
            len(historical),
        )
        dropped += next_user
        historical = historical[next_user:]


def _extract_choice_message(data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("llama.cpp response missing choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("llama.cpp response choice is malformed.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("llama.cpp response missing message object.")
    finish_reason = first.get("finish_reason")
    if not isinstance(finish_reason, str):
        finish_reason = None
    return message, finish_reason


def _parse_usage(data: dict[str, Any]) -> TokenUsage | None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    cached_tokens = None
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict):
        cached_raw = details.get("cached_tokens")
        if isinstance(cached_raw, int):
            cached_tokens = cached_raw
    if not isinstance(prompt_tokens, int):
        prompt_tokens = None
    if not isinstance(completion_tokens, int):
        completion_tokens = None
    if not isinstance(total_tokens, int):
        total_tokens = None
        if prompt_tokens is not None or completion_tokens is not None:
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    return TokenUsage(
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached_tokens,
    )


def _log_timings(data: dict[str, Any], *, model: str, usage: TokenUsage | None) -> None:
    timings = data.get("timings")
    prompt_ms = None
    predicted_ms = None
    predicted_per_second = None
    if isinstance(timings, dict):
        prompt_ms = timings.get("prompt_ms")
        predicted_ms = timings.get("predicted_ms")
        predicted_per_second = timings.get("predicted_per_second")
    _LOGGER.info(
        "[AGENT][LLAMA_CPP] Telemetry: model=%s prompt_tokens=%s output_tokens=%s "
        "prompt_ms=%s generation_ms=%s tokens_per_sec=%s",
        model,
        usage.input_tokens if usage else None,
        usage.output_tokens if usage else None,
        prompt_ms,
        predicted_ms,
        predicted_per_second,
    )


class LlamaCppProvider:
    """Local llama.cpp provider backed by OpenAI-compatible Chat Completions."""

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: LlamaCppModelProfile,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        system_instruction = system_instruction_override or profile.system_instruction
        resolved_max_tokens = (
            profile.tool_select_max_tokens if tools else profile.final_answer_max_tokens
        )
        payload, estimated_tokens, dropped_messages = _budget_payload(
            messages,
            tools,
            profile,
            system_instruction,
            max_tokens=resolved_max_tokens,
        )
        budget_messages = messages
        peak_estimated_tokens = estimated_tokens
        retry_count = 0

        _LOGGER.info(
            "[AGENT][LLAMA_CPP] generate_turn — model=%s messages=%d tools=%d "
            "estimated_prompt_tokens=%d history_messages_dropped=%d "
            "context_window=%d",
            profile.runtime_model_id,
            len(payload["messages"]),
            len(tools),
            estimated_tokens,
            dropped_messages,
            profile.context_window,
        )

        started = time.perf_counter()
        try:
            data = _post_chat(payload, profile)
        except LlamaCppRequestError as exc:
            current_messages = messages[_current_turn_start(messages) :]
            if not exc.is_context_overflow or len(current_messages) == len(messages):
                raise
            _LOGGER.warning(
                "[AGENT][LLAMA_CPP] Context overflow; retrying once without prior "
                "history model=%s context_window=%d",
                profile.runtime_model_id,
                profile.context_window,
            )
            payload, estimated_tokens, retry_dropped = _budget_payload(
                current_messages,
                tools,
                profile,
                system_instruction,
                max_tokens=resolved_max_tokens,
            )
            budget_messages = current_messages
            overflow_dropped = len(messages) - len(current_messages)
            dropped_messages = max(
                dropped_messages,
                overflow_dropped + retry_dropped,
            )
            peak_estimated_tokens = max(peak_estimated_tokens, estimated_tokens)
            retry_count += 1
            data = _post_chat(payload, profile)

        register_local_activity(
            LocalModelRef(provider="llama_cpp", model=profile.runtime_model_id)
        )
        usage = _parse_usage(data)
        _log_timings(data, model=profile.runtime_model_id, usage=usage)
        message, finish_reason = _extract_choice_message(data)
        peak_prompt_tokens = usage.input_tokens if usage is not None else None

        if tools and finish_reason == "length" and not message.get("tool_calls"):
            _LOGGER.info(
                "[AGENT][LLAMA_CPP] Tool-select turn truncated without a tool call; "
                "regenerating as final answer"
            )
            retry_payload, retry_estimated, retry_dropped = _budget_payload(
                budget_messages,
                [],
                profile,
                system_instruction,
                max_tokens=profile.final_answer_max_tokens,
            )
            if budget_messages is messages:
                dropped_messages = max(dropped_messages, retry_dropped)
            else:
                dropped_messages = max(
                    dropped_messages,
                    len(messages) - len(budget_messages) + retry_dropped,
                )
            peak_estimated_tokens = max(peak_estimated_tokens, retry_estimated)
            data = _post_chat(retry_payload, profile)
            register_local_activity(
                LocalModelRef(provider="llama_cpp", model=profile.runtime_model_id)
            )
            retry_count += 1
            retry_usage = _parse_usage(data)
            usage = merge_token_usage(usage, retry_usage)
            if retry_usage is not None and isinstance(retry_usage.input_tokens, int):
                peak_prompt_tokens = max(
                    peak_prompt_tokens or 0,
                    retry_usage.input_tokens,
                )
            message, _ = _extract_choice_message(data)

        provider_ms = round((time.perf_counter() - started) * 1000, 2)
        agent_message = _openai_message_to_agent_message(message)
        agent_message.prompt_tokens = peak_prompt_tokens
        agent_message.estimated_prompt_tokens = peak_estimated_tokens
        agent_message.history_messages_dropped = dropped_messages
        resolved_model = data.get("model")
        if not isinstance(resolved_model, str) or not resolved_model:
            resolved_model = profile.runtime_model_id

        return ProviderTurnResult(
            message=agent_message,
            resolved_model=resolved_model,
            usage=usage,
            provider_ms=provider_ms,
            retry_count=retry_count,
            estimated_prompt_tokens=peak_estimated_tokens,
            history_messages_dropped=dropped_messages,
        )
