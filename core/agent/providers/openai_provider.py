"""OpenAI Responses API provider adapter."""

from __future__ import annotations

from core.agent.capabilities import CapabilityDescriptor
from core.agent.providers.contract import ProviderTurnResult, ProviderStreamObserver
from typing import Any
from core.agent.providers.responses_api import (
    ResponsesApiProvider,
    ResponsesModelProfile,
)
from core.agent.types import AgentMessage

class OpenAIProvider:
    """OpenAI Responses API adapter."""

    def __init__(self, api_key: str) -> None:
        self._delegate = ResponsesApiProvider(
            api_key=api_key,
            base_url=None,
            provider_kind="openai",
        )

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
        output_token_limit: int | None = None,
    ) -> ProviderTurnResult:
        return self._delegate.generate_turn(
            messages,
            tools,
            profile,
            system_instruction_override=system_instruction_override,
            execution_control=execution_control,
            stream_observer=stream_observer,
            output_schema=output_schema,
            output_token_limit=output_token_limit,
        )
