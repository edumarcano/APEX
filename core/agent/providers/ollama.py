import json
import logging
import re
import time
from typing import Any

import requests
from requests.exceptions import RequestException

from core.agent.capabilities import CapabilityDescriptor
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.contract import ProviderTurnResult, merge_token_usage
from core.agent.providers.ollama_lifecycle import (
    get_http_session,
    get_keep_alive_duration,
    register_activity,
)
from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.tool_schemas import descriptor_to_openai_schema, estimate_json_tokens
from core.agent.types import AgentMessage, TokenUsage, ToolCall, ToolResult
from core.config import OLLAMA_HOST

_LOGGER = logging.getLogger(__name__)
_PROMPT_BYTES_PER_TOKEN = 3
_PROMPT_TEMPLATE_ALLOWANCE_TOKENS = 128
_PROMPT_SAFETY_MARGIN_TOKENS = 512

def _descriptor_to_openai_schema(descriptor: CapabilityDescriptor) -> dict[str, Any]:
    """Compatibility wrapper for the shared schema serializer."""
    return descriptor_to_openai_schema(descriptor)


def _serialize_tool_output(output: Any) -> str:
    """Serialize tool output as stable JSON when possible."""
    try:
        return json.dumps(output, default=str)
    except (TypeError, ValueError):
        return str(output)


def _wrap_untrusted_tool_output(result: ToolResult) -> str:
    """Wrap local tool output in the same untrusted boundary used by Gemini."""
    return (
        f"<untrusted_tool_output name='{result.name}'>\n"
        f"{_serialize_tool_output(result.output)}\n"
        f"</untrusted_tool_output>"
    )


def _messages_to_ollama(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    """Translate APEX AgentMessage history into Ollama /api/chat payload entries."""
    ollama_messages: list[dict[str, Any]] = []

    for message in messages:
        if message.role == "user":
            ollama_messages.append(
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
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    }
                    for call in message.tool_calls
                ]
            ollama_messages.append(payload)

        elif message.role == "tool":
            if not message.tool_results:
                continue
            for result in message.tool_results:
                ollama_messages.append(
                    {
                        "role": "tool",
                        "tool_name": result.name,
                        "content": _wrap_untrusted_tool_output(result),
                    }
                )

    return ollama_messages


def _strip_thinking_tags(content: str | None) -> str:
    """Remove Qwen-style reasoning blocks from assistant content."""
    if not content:
        return ""

    think_open = "<" + "think" + ">"
    think_close = "</" + "think" + ">"
    content = re.sub(rf"{re.escape(think_open)}[\s\S]*?{re.escape(think_close)}", "", content)
    content = re.sub(rf"{re.escape(think_open)}[\s\S]*$", "", content)
    content = re.sub(rf"^[\s\S]*?{re.escape(think_close)}", "", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    return content.strip()


def _parse_tool_call_arguments(raw_arguments: Any) -> dict[str, Any]:
    """Normalize Ollama tool-call arguments to a dictionary."""
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            _LOGGER.warning(
                "[AGENT][OLLAMA] Failed to parse tool-call arguments JSON: %s",
                raw_arguments,
            )
    return {}


def _ollama_message_to_agent_message(message: dict[str, Any]) -> AgentMessage:
    """Map an Ollama /api/chat message object to a validated AgentMessage."""
    content = message.get("content")
    raw_tool_calls = message.get("tool_calls") or []
    tool_calls: list[ToolCall] = []

    for idx, raw_call in enumerate(raw_tool_calls):
        function_block = raw_call.get("function") or {}
        call_name = function_block.get("name") or ""
        arguments = _parse_tool_call_arguments(function_block.get("arguments"))
        call_id = raw_call.get("id") or f"call_{call_name}_{idx}"
        tool_calls.append(
            ToolCall(id=call_id, name=call_name, arguments=arguments)
        )

    return AgentMessage(
        role="agent",
        content=content if content else None,
        tool_calls=tool_calls or None,
    )


def _post_chat(payload: dict[str, Any], profile: OllamaModelProfile) -> dict[str, Any]:
    """POST a chat payload to Ollama, log telemetry, and return the parsed body."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"

    try:
        response = get_http_session().post(
            url,
            json=payload,
            timeout=profile.generation_timeout,
        )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise RuntimeError(
            f"Ollama generation timed out after {profile.generation_timeout}s "
            f"for model {profile.api_model!r}."
        ) from exc
    except requests.ConnectionError as exc:
        raise RuntimeError(
            f"Failed to connect to Ollama at {OLLAMA_HOST}. "
            "Ensure the local Ollama daemon is running."
        ) from exc
    except RequestException as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        detail = ""
        if exc.response is not None:
            try:
                raw_detail = exc.response.json().get("error")
                if isinstance(raw_detail, str):
                    detail = " ".join(raw_detail.split())[:300]
            except (ValueError, AttributeError):
                pass
        status_detail = f" (HTTP {status_code})" if status_code is not None else ""
        raise OllamaRequestError(
            f"Ollama request failed for model {profile.api_model!r}"
            f"{status_detail}{f': {detail}' if detail else '.'}",
            status_code=status_code,
            detail=detail,
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Ollama returned non-JSON response (HTTP {response.status_code})."
        ) from exc

    load_duration_ns = data.get("load_duration")
    prompt_eval_duration_ns = data.get("prompt_eval_duration")
    eval_count = data.get("eval_count")
    eval_duration_ns = data.get("eval_duration")

    if any(
        v is not None
        for v in (
            data.get("total_duration"),
            load_duration_ns,
            data.get("prompt_eval_count"),
            prompt_eval_duration_ns,
            eval_count,
            eval_duration_ns,
        )
    ):
        load_s = (
            load_duration_ns / 1e9
            if isinstance(load_duration_ns, (int, float))
            else 0.0
        )
        prompt_eval_s = (
            prompt_eval_duration_ns / 1e9
            if isinstance(prompt_eval_duration_ns, (int, float))
            else 0.0
        )
        token_count = eval_count if isinstance(eval_count, int) else 0
        tps = 0.0
        if (
            isinstance(eval_duration_ns, (int, float))
            and eval_duration_ns > 0
            and isinstance(eval_count, int)
        ):
            tps = (eval_count / eval_duration_ns) * 1e9
        _LOGGER.info(
            "[AGENT][OLLAMA] Telemetry: load=%.3fs, prompt_eval=%.3fs, "
            "generation=%d tokens at %.2f t/s",
            load_s,
            prompt_eval_s,
            token_count,
            tps,
        )

    return data


class OllamaRequestError(RuntimeError):
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
        return self.status_code == 400 and any(
            marker in normalized
            for marker in (
                "context length",
                "context window",
                "too many tokens",
                "prompt is too long",
                "input length",
            )
        )


def _estimate_payload_tokens(payload: dict[str, Any]) -> int:
    """Estimate serialized request tokens without retaining prompt content."""
    return estimate_json_tokens(
        payload,
        bytes_per_token=_PROMPT_BYTES_PER_TOKEN,
        allowance_tokens=_PROMPT_TEMPLATE_ALLOWANCE_TOKENS,
    )


def _current_turn_start(messages: list[AgentMessage]) -> int:
    """Return the user-message index that starts the current interaction."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return index
    return 0


def _build_payload(
    messages: list[AgentMessage],
    tools: list[CapabilityDescriptor],
    profile: OllamaModelProfile,
    system_instruction: str,
    *,
    num_predict: int,
) -> dict[str, Any]:
    ollama_messages = _messages_to_ollama(messages)
    if system_instruction:
        ollama_messages.insert(
            0,
            {
                "role": "system",
                "content": system_instruction + SECURITY_BOUNDARY_DIRECTIVE,
            },
        )
    payload: dict[str, Any] = {
        "model": profile.api_model,
        "messages": ollama_messages,
        "stream": False,
        "options": {
            "temperature": profile.default_temperature,
            "num_predict": num_predict,
            "num_thread": profile.num_thread,
            "num_ctx": profile.context_window,
        },
        "think": profile.think,
        "keep_alive": get_keep_alive_duration(),
    }
    if tools:
        payload["tools"] = [_descriptor_to_openai_schema(tool) for tool in tools]
    return payload


def _budget_payload(
    messages: list[AgentMessage],
    tools: list[CapabilityDescriptor],
    profile: OllamaModelProfile,
    system_instruction: str,
    *,
    num_predict: int,
) -> tuple[dict[str, Any], int, int]:
    """Trim complete historical interactions until the local prompt fits."""
    current_start = _current_turn_start(messages)
    historical = list(messages[:current_start])
    current = list(messages[current_start:])
    dropped = 0
    target = profile.context_window - num_predict - _PROMPT_SAFETY_MARGIN_TOKENS

    while True:
        payload = _build_payload(
            historical + current,
            tools,
            profile,
            system_instruction,
            num_predict=num_predict,
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


def _extract_message(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and return the 'message' object from an Ollama chat response."""
    message = data.get("message")
    if not isinstance(message, dict):
        raise RuntimeError(
            f"Ollama response missing 'message' object: {data!r}"
        )
    return message


def _parse_ollama_usage(data: dict[str, Any]) -> TokenUsage | None:
    prompt_tokens = data.get("prompt_eval_count")
    output_tokens = data.get("eval_count")
    if not isinstance(prompt_tokens, int) and not isinstance(output_tokens, int):
        return None
    input_tokens = prompt_tokens if isinstance(prompt_tokens, int) else None
    completion_tokens = output_tokens if isinstance(output_tokens, int) else None
    total = None
    if input_tokens is not None or completion_tokens is not None:
        total = (input_tokens or 0) + (completion_tokens or 0)
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=completion_tokens,
        total_tokens=total,
    )


class OllamaProvider:
    """Local Ollama agent provider backed by the /api/chat REST endpoint."""

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: OllamaModelProfile,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        system_instruction = system_instruction_override or profile.system_instruction
        resolved_num_predict = (
            profile.tool_select_max_tokens
            if tools
            else profile.final_answer_max_tokens
        )
        payload, estimated_tokens, dropped_messages = _budget_payload(
            messages,
            tools,
            profile,
            system_instruction,
            num_predict=resolved_num_predict,
        )
        budget_messages = messages
        peak_estimated_tokens = estimated_tokens
        retry_count = 0

        _LOGGER.info(
            "[AGENT][OLLAMA] generate_turn — model=%s messages=%d tools=%d "
            "estimated_prompt_tokens=%d history_messages_dropped=%d "
            "context_window=%d",
            profile.api_model,
            len(payload["messages"]),
            len(tools),
            estimated_tokens,
            dropped_messages,
            profile.context_window,
        )

        started = time.perf_counter()
        try:
            data = _post_chat(payload, profile)
        except OllamaRequestError as exc:
            current_messages = messages[_current_turn_start(messages):]
            if not exc.is_context_overflow or len(current_messages) == len(messages):
                raise
            _LOGGER.warning(
                "[AGENT][OLLAMA] Context overflow; retrying once without prior "
                "history model=%s context_window=%d",
                profile.api_model,
                profile.context_window,
            )
            payload, estimated_tokens, retry_dropped = _budget_payload(
                current_messages,
                tools,
                profile,
                system_instruction,
                num_predict=resolved_num_predict,
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

        register_activity(profile.api_model)
        peak_prompt_tokens = (
            data.get("prompt_eval_count")
            if isinstance(data.get("prompt_eval_count"), int)
            else None
        )
        usage = _parse_ollama_usage(data)

        message = _extract_message(data)

        # A tool-select turn that hit the num_predict ceiling without emitting
        # a tool call produced a truncated prose answer. Regenerate once
        # without tools under the final-answer token budget.
        if (
            tools
            and data.get("done_reason") == "length"
            and not message.get("tool_calls")
        ):
            _LOGGER.info(
                "[AGENT][OLLAMA] Tool-select turn truncated at %s tokens without "
                "a tool call; regenerating as final answer",
                payload["options"].get("num_predict"),
            )
            retry_payload, retry_estimated, retry_dropped = _budget_payload(
                budget_messages,
                [],
                profile,
                system_instruction,
                num_predict=profile.final_answer_max_tokens,
            )
            if budget_messages is messages:
                dropped_messages = max(dropped_messages, retry_dropped)
            else:
                dropped_messages = max(
                    dropped_messages,
                    len(messages) - len(budget_messages) + retry_dropped,
                )
            peak_estimated_tokens = max(
                peak_estimated_tokens,
                retry_estimated,
            )

            data = _post_chat(retry_payload, profile)
            register_activity(profile.api_model)
            retry_count += 1
            if isinstance(data.get("prompt_eval_count"), int):
                peak_prompt_tokens = max(
                    peak_prompt_tokens or 0,
                    data["prompt_eval_count"],
                )
            # Both posts evaluated a prompt, so the turn's cost is their sum.
            usage = merge_token_usage(usage, _parse_ollama_usage(data))
            message = _extract_message(data)

        provider_ms = round((time.perf_counter() - started) * 1000, 2)
        raw_content = message.get("content")
        if isinstance(raw_content, str) and raw_content:
            message["content"] = _strip_thinking_tags(raw_content)

        agent_message = _ollama_message_to_agent_message(message)
        agent_message.prompt_tokens = peak_prompt_tokens
        agent_message.estimated_prompt_tokens = peak_estimated_tokens
        agent_message.history_messages_dropped = dropped_messages
        resolved_model = data.get("model")
        if not isinstance(resolved_model, str):
            resolved_model = profile.api_model

        return ProviderTurnResult(
            message=agent_message,
            resolved_model=resolved_model,
            usage=usage,
            provider_ms=provider_ms,
            retry_count=retry_count,
            estimated_prompt_tokens=peak_estimated_tokens,
            history_messages_dropped=dropped_messages,
        )
