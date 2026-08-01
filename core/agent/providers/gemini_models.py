from typing import Literal

from pydantic import BaseModel, Field

from core.config import (
    DEFAULT_AGENT_SYSTEM_PROMPT,
    GEMINI_AGENT_MAX_TOOL_CALLS,
    GEMINI_AGENT_MAX_TURNS,
)


GeminiThinkingLevel = Literal["low", "medium", "high"]


class GeminiModelProfile(BaseModel):
    display_name: str = Field(description="Visual name surfaced in HUD UI components.")
    profile_version: str = Field(description="Internal configuration profile version.")
    api_model: str = Field(description="Exact Gemini API model identifier string.")
    tier: Literal["fast", "balanced", "advanced"] = Field(
        description="Computational performance classification."
    )
    stability: Literal["stable", "preview"] = Field(
        description="Release stage classification of the target model."
    )
    thinking_level: GeminiThinkingLevel = Field(
        description=(
            "Gemini thinking effort for GenerateContentConfig.thinking_config, "
            "resolved from the selected APEX effort tier."
        ),
    )
    max_tool_turns: int = Field(
        default=3, description="Turn boundary ceiling to prevent infinite loops."
    )
    max_tool_calls: int = Field(
        default=4,
        description="Maximum individual tool executions allowed per session.",
    )
    system_instruction: str = Field(
        default=DEFAULT_AGENT_SYSTEM_PROMPT,
        description="Base persona and behavioral instructions for the cloud agent.",
    )
