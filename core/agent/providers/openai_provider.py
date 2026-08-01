"""Unexposed OpenAI Responses API provider adapter."""

from __future__ import annotations

from core.agent.capabilities import CapabilityDescriptor
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.responses_api import (
    ResponsesApiProvider,
    ResponsesModelProfile,
)
from core.agent.types import AgentMessage

# Internal-only profiles for adapter tests. Not registered in the public roster.
OPENAI_INTERNAL_PROFILES: dict[str, ResponsesModelProfile] = {
    "openai_default": ResponsesModelProfile(
        provider="openai",
        display_name="OpenAI Default",
        profile_version="0.1",
        api_model="gpt-4.1-mini",
        max_tool_turns=4,
        max_tool_calls=6,
        system_instruction="You are an APEX assistant.",
        reasoning_effort="medium",
    ),
}


class OpenAIProvider:
    """OpenAI Responses API adapter. Not wired into the public profile roster."""

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
    ) -> ProviderTurnResult:
        return self._delegate.generate_turn(
            messages,
            tools,
            profile,
            system_instruction_override=system_instruction_override,
        )
