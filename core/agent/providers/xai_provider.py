"""Unexposed xAI Responses API provider adapter."""

from __future__ import annotations

from core.agent.capabilities import CapabilityDescriptor
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.responses_api import (
    ResponsesApiProvider,
    ResponsesModelProfile,
)
from core.agent.types import AgentMessage

XAI_API_BASE_URL = "https://api.x.ai/v1"

# Internal-only profiles for adapter tests. Not registered in the public roster.
XAI_INTERNAL_PROFILES: dict[str, ResponsesModelProfile] = {
    "xai_default": ResponsesModelProfile(
        provider="xai",
        display_name="xAI Default",
        agent_version="0.1",
        api_model="grok-4",
        max_tool_turns=4,
        max_tool_calls=6,
        system_instruction="",
        # Grok 4 exposes no reasoning-effort control.
        reasoning_effort=None,
    ),
}


class XAIProvider:
    """xAI Responses API adapter. Not wired into the public profile roster."""

    def __init__(self, api_key: str, *, base_url: str = XAI_API_BASE_URL) -> None:
        self._delegate = ResponsesApiProvider(
            api_key=api_key,
            base_url=base_url,
            provider_kind="xai",
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
