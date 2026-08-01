import base64
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError

from core.agent.capabilities import CapabilityDescriptor
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.providers.retries import (
    call_with_bounded_retries,
    exponential_backoff_seconds,
    fixed_backoff_seconds,
)
from core.agent.types import AgentMessage, TokenUsage, ToolCall, ToolResult

def _wrap_untrusted_tool_output(result: ToolResult) -> str:
    return (
        f"<untrusted_tool_output name='{result.name}'>\n"
        f"{result.output}\n"
        f"</untrusted_tool_output>"
    )


def _messages_to_contents(messages: list[AgentMessage]) -> list[types.Content]:
    contents: list[types.Content] = []

    for message in messages:
        parts: list[types.Part] = []

        if message.role == "user":
            if message.content:
                parts.append(types.Part.from_text(text=message.content))
            if parts:
                contents.append(types.Content(role="user", parts=parts))

        elif message.role == "model":
            if message.content:
                parts.append(types.Part.from_text(text=message.content))
            if message.tool_calls:
                for call in message.tool_calls:
                    part = types.Part.from_function_call(
                        name=call.name, args=call.arguments
                    )
                    if call.thought_signature:
                        try:
                            part.thought_signature = base64.b64decode(
                                call.thought_signature
                            )
                        except Exception:
                            pass
                    parts.append(part)
            if parts:
                contents.append(types.Content(role="model", parts=parts))

        elif message.role == "tool":
            if message.tool_results:
                for result in message.tool_results:
                    wrapped_output = _wrap_untrusted_tool_output(result)
                    parts.append(
                        types.Part.from_function_response(
                            name=result.name,
                            response={"result": wrapped_output},
                        )
                    )
                contents.append(types.Content(role="user", parts=parts))

    return contents


def _content_to_agent_message(content: types.Content) -> AgentMessage:
    text_segments: list[str] = []
    tool_calls: list[ToolCall] = []

    for part in content.parts or []:
        if part.text:
            text_segments.append(part.text)
        if part.function_call is not None:
            function_call = part.function_call
            call_id = function_call.id or f"{function_call.name}-{len(tool_calls)}"
            ts = getattr(part, "thought_signature", None)
            ts_str: str | None
            if isinstance(ts, bytes):
                ts_str = base64.b64encode(ts).decode("utf-8")
            elif isinstance(ts, str):
                ts_str = ts
            else:
                ts_str = None
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=function_call.name,
                    arguments=function_call.args or {},
                    thought_signature=ts_str,
                )
            )

    combined_content = "".join(text_segments) if text_segments else None
    return AgentMessage(
        role="model",
        content=combined_content,
        tool_calls=tool_calls or None,
    )


def _descriptors_to_gemini_tools(
    descriptors: list[CapabilityDescriptor],
) -> list[types.Tool]:
    """Convert capability descriptors into Gemini function declarations."""
    declarations = [
        types.FunctionDeclaration(
            name=descriptor.name,
            description=descriptor.description,
            parameters_json_schema=descriptor.input_schema,
        )
        for descriptor in descriptors
    ]
    return [types.Tool(function_declarations=declarations)]


def _parse_gemini_usage(response: Any) -> TokenUsage | None:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return None

    input_tokens = getattr(metadata, "prompt_token_count", None)
    output_tokens = getattr(metadata, "candidates_token_count", None)
    total_tokens = getattr(metadata, "total_token_count", None)
    cached_tokens = getattr(metadata, "cached_content_token_count", None)
    reasoning_tokens = getattr(metadata, "thoughts_token_count", None)

    if all(
        value is None
        for value in (
            input_tokens,
            output_tokens,
            total_tokens,
            cached_tokens,
            reasoning_tokens,
        )
    ):
        return None

    def _as_int(value: Any) -> int | None:
        return value if isinstance(value, int) else None

    return TokenUsage(
        input_tokens=_as_int(input_tokens),
        cached_input_tokens=_as_int(cached_tokens),
        reasoning_tokens=_as_int(reasoning_tokens),
        output_tokens=_as_int(output_tokens),
        total_tokens=_as_int(total_tokens),
    )


def _is_retryable_gemini_error(exc: BaseException) -> bool:
    return isinstance(exc, APIError) and exc.code in {429, 500, 502, 503, 504}


def _gemini_wait_seconds(attempt: int, exc: BaseException) -> float:
    if isinstance(exc, APIError) and exc.code == 429:
        return exponential_backoff_seconds(attempt)
    return fixed_backoff_seconds(attempt)


class GeminiProvider:
    def __init__(self, api_key: str) -> None:
        self.client = genai.Client(api_key=api_key)

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: GeminiModelProfile,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        contents = _messages_to_contents(messages)

        config_kwargs: dict[str, Any] = {
            "system_instruction": (
                system_instruction_override or profile.system_instruction
            )
            + SECURITY_BOUNDARY_DIRECTIVE,
            "thinking_config": types.ThinkingConfig(
                thinking_level=profile.thinking_level,
            ),
        }
        if tools:
            config_kwargs["tools"] = _descriptors_to_gemini_tools(tools)
            config_kwargs["automatic_function_calling"] = (
                types.AutomaticFunctionCallingConfig(disable=True)
            )

        config = types.GenerateContentConfig(**config_kwargs)

        def _generate() -> Any:
            return self.client.models.generate_content(
                model=profile.api_model,
                contents=contents,
                config=config,
            )

        started = time.perf_counter()
        response, retry_count = call_with_bounded_retries(
            _generate,
            is_retryable=_is_retryable_gemini_error,
            wait_seconds=_gemini_wait_seconds,
            log_label="gemini",
        )
        provider_ms = round((time.perf_counter() - started) * 1000, 2)

        if not response.candidates:
            raise ValueError("Gemini returned no response candidates.")

        candidate_content = response.candidates[0].content
        if candidate_content is None:
            raise ValueError("Gemini returned empty candidate content.")

        message = _content_to_agent_message(candidate_content)
        resolved_model = (
            getattr(response, "model_version", None)
            or getattr(response, "model", None)
            or profile.api_model
        )
        if not isinstance(resolved_model, str):
            resolved_model = profile.api_model

        return ProviderTurnResult(
            message=message,
            resolved_model=resolved_model,
            usage=_parse_gemini_usage(response),
            provider_ms=provider_ms,
            retry_count=retry_count,
        )
