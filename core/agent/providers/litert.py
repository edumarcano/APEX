"""LiteRT-LM provider adapter using request-scoped native conversations."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from core.agent.capabilities import CapabilityDescriptor
from core.agent.local_runtime import LOCAL_RUNTIME
from core.agent.prompting import FINAL_ANSWER_INSTRUCTION
from core.agent.local_context import wrap_untrusted_tool_output
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.litert_models import LiteRTModelProfile
from core.agent.providers.litert_protocol import (
    LiteRTInferenceAmbiguousError,
    LiteRTProtocolError,
)
from core.agent.providers.litert_runtime import LiteRTRuntimeManager
from core.agent.tool_schemas import descriptor_to_openai_schema
from core.agent.types import AgentMessage, ToolCall, ToolResult


_LOGGER = logging.getLogger(__name__)
_CALL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class LiteRTProviderError(RuntimeError):
    """Sanitized provider normalization or lifecycle failure."""


def _text_from_response(response: Mapping[str, Any]) -> str:
    content = response.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if isinstance(item, str):
            chunks.append(item)
        elif isinstance(item, Mapping) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks).strip()


def normalize_litert_response(
    response: Mapping[str, Any],
    *,
    conversation_id: str,
    turn_number: int,
) -> tuple[str, list[ToolCall]]:
    """Extract text and native structured tool calls without text parsing."""
    raw_calls = response.get("tool_calls", [])
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list):
        raise LiteRTProviderError("LiteRT returned an invalid structured tool-call list.")
    calls: list[ToolCall] = []
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, Mapping):
            raise LiteRTProviderError("LiteRT returned a malformed structured tool call.")
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            raise LiteRTProviderError("LiteRT returned a malformed structured tool call.")
        name = function.get("name")
        arguments = function.get("arguments", {})
        if not isinstance(name, str) or not _CALL_NAME_PATTERN.fullmatch(name):
            raise LiteRTProviderError("LiteRT returned an invalid capability name.")
        if not isinstance(arguments, Mapping):
            raise LiteRTProviderError("LiteRT returned non-object capability arguments.")
        call_id = f"litert:{conversation_id}:{turn_number}:{index}"
        calls.append(
            ToolCall(id=call_id, name=name, arguments=dict(arguments))
        )
    return _text_from_response(response), calls


def _native_message(
    message: AgentMessage,
    *,
    appended_instruction: str | None = None,
) -> dict[str, Any]:
    if message.role == "user":
        content = message.content or ""
        if appended_instruction:
            content = f"{content}\n\n{appended_instruction}"
        return {"role": "user", "content": content}
    if message.role == "agent":
        payload: dict[str, Any] = {
            "role": "model",
            "content": message.content or "",
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
        return payload
    if message.role == "tool":
        return _native_tool_result_message(message.tool_results or [])
    raise LiteRTProviderError("LiteRT received an unsupported APEX message role.")


def _native_tool_result_message(
    results: Sequence[ToolResult],
    *,
    appended_instruction: str | None = None,
) -> dict[str, Any]:
    if not results:
        raise LiteRTProviderError("LiteRT tool-result message cannot be empty.")
    content: list[dict[str, Any]] = [
        {
            "type": "tool_response",
            "name": result.name,
            "response": wrap_untrusted_tool_output(result),
        }
        for result in results
    ]
    if appended_instruction:
        content.append({"type": "text", "text": appended_instruction})
    return {
        "role": "tool",
        "content": content,
    }


class LiteRTProviderSession:
    """One request-scoped native conversation and its APEX-side bookkeeping."""

    def __init__(
        self,
        runtime: LiteRTRuntimeManager,
        profile: LiteRTModelProfile,
        *,
        tools: Sequence[CapabilityDescriptor] = (),
        system_instruction: str | None = None,
    ) -> None:
        self.runtime = runtime
        self.profile = profile
        self.conversation_id = f"litert:{uuid.uuid4().hex}"
        self._tools = tuple(tools)
        self._system_instruction = (
            system_instruction or profile.system_instruction
        ) + SECURITY_BOUNDARY_DIRECTIVE
        self._opened = False
        self._closed = False
        self._poisoned = False
        self._history: list[AgentMessage] = []
        self._turn_number = 0
        self._outstanding_calls: dict[str, tuple[str, int]] = {}

    @property
    def turn_number(self) -> int:
        return self._turn_number

    @property
    def outstanding_call_ids(self) -> tuple[str, ...]:
        return tuple(self._outstanding_calls)

    @property
    def is_usable(self) -> bool:
        return not self._closed and not self._poisoned

    def _open(self, messages: list[AgentMessage]) -> None:
        if not messages or messages[-1].role != "user":
            raise LiteRTProviderError("LiteRT requests must begin with a user message.")
        prefix = messages[:-1]
        self._history = list(prefix)
        self.runtime.open_conversation(
            conversation_id=self.conversation_id,
            system_instruction=self._system_instruction,
            tools=[descriptor_to_openai_schema(tool) for tool in self._tools],
            initial_messages=[_native_message(message) for message in prefix],
            max_output_tokens=self.profile.final_answer_max_tokens,
        )
        self._opened = True

    def _validate_history_prefix(self, messages: list[AgentMessage]) -> AgentMessage:
        if len(messages) <= len(self._history):
            raise LiteRTProviderError("LiteRT request history is missing its current message.")
        if messages[: len(self._history)] != self._history:
            raise LiteRTProviderError("LiteRT request history diverged from its provider session.")
        tail = messages[len(self._history) :]
        if len(tail) != 1:
            raise LiteRTProviderError("LiteRT provider sessions accept one new message per turn.")
        return tail[0]

    def _tool_message(
        self,
        message: AgentMessage,
        *,
        appended_instruction: str | None = None,
    ) -> dict[str, Any]:
        if message.role != "tool" or not message.tool_results:
            raise LiteRTProviderError("LiteRT expected one structured tool-result message.")
        results = message.tool_results
        seen: set[str] = set()
        for result in results:
            if result.id in seen or result.id not in self._outstanding_calls:
                raise LiteRTProviderError("LiteRT tool result did not match an outstanding call.")
            expected_name, _index = self._outstanding_calls[result.id]
            if result.name != expected_name:
                raise LiteRTProviderError("LiteRT tool result name did not match its call.")
            seen.add(result.id)
        if seen != set(self._outstanding_calls):
            raise LiteRTProviderError("LiteRT tool results did not cover all outstanding calls.")
        return _native_tool_result_message(
            results,
            appended_instruction=appended_instruction,
        )

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: LiteRTModelProfile,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        del tools, profile
        if not self.is_usable:
            raise LiteRTProviderError("LiteRT provider session is no longer usable.")
        final_instruction = (
            FINAL_ANSWER_INSTRUCTION
            if system_instruction_override
            and FINAL_ANSWER_INSTRUCTION in system_instruction_override
            else None
        )
        if not self._opened:
            self._open(messages)
            current = messages[-1]
            native_message: Mapping[str, Any] | str = _native_message(
                current,
                appended_instruction=final_instruction,
            )
            self._history.append(current)
        else:
            current = self._validate_history_prefix(messages)
            native_message = self._tool_message(
                current,
                appended_instruction=final_instruction,
            )
            self._history.append(current)
            self._outstanding_calls.clear()

        started = time.perf_counter()
        try:
            response = self.runtime.send_message(
                self.conversation_id,
                native_message,
                timeout=self.profile.generation_timeout,
            )
        except LiteRTInferenceAmbiguousError:
            self._poisoned = True
            raise
        self._turn_number += 1
        text, calls = normalize_litert_response(
            response,
            conversation_id=self.conversation_id,
            turn_number=self._turn_number,
        )
        model_message = AgentMessage(
            role="agent",
            content=text or None,
            tool_calls=calls or None,
        )
        self._history.append(model_message)
        self._outstanding_calls = {
            call.id: (call.name, index) for index, call in enumerate(calls)
        }
        LOCAL_RUNTIME.register_activity("litert", self.profile.api_model)
        return ProviderTurnResult(
            message=model_message,
            resolved_model=self.profile.api_model,
            usage=None,
            provider_ms=round((time.perf_counter() - started) * 1000, 2),
            retry_count=0,
        )

    def close(self) -> None:
        """Close this session's conversation exactly once."""
        if self._closed:
            return
        self._closed = True
        if not self._opened or self._poisoned:
            return
        try:
            self.runtime.close_conversation(self.conversation_id)
        except Exception as exc:
            _LOGGER.warning("LiteRT conversation cleanup failed: %s", type(exc).__name__)

    def __enter__(self) -> "LiteRTProviderSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class LiteRTProvider:
    """APEX provider facade backed by a shared, lazily started worker."""

    def __init__(self, runtime: LiteRTRuntimeManager | None = None) -> None:
        self.runtime = runtime or LiteRTRuntimeManager()

    def create_session(
        self,
        profile: LiteRTModelProfile,
        tools: Sequence[CapabilityDescriptor] = (),
        *,
        system_instruction: str | None = None,
        system_instruction_override: str | None = None,
    ) -> LiteRTProviderSession:
        return LiteRTProviderSession(
            self.runtime,
            profile,
            tools=tools,
            system_instruction=system_instruction_override or system_instruction,
        )

    def generate_turn(
        self,
        messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        profile: LiteRTModelProfile,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        """Run one isolated turn for callers that do not use the APEX loop."""
        session = self.create_session(
            profile,
            tools,
            system_instruction_override=system_instruction_override,
        )
        try:
            return session.generate_turn(
                messages,
                tools,
                profile,
                system_instruction_override=system_instruction_override,
            )
        finally:
            session.close()
