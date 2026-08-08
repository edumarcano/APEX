from typing import Literal

from pydantic import BaseModel, Field

GeminiThinkingLevel = Literal["low", "medium", "high"]


class GeminiModelProfile(BaseModel):
    display_name: str = Field(description="Visual name surfaced in HUD UI components.")
    agent_version: str = Field(
        description="Version of the named Apex Agent product identity."
    )
    api_model: str = Field(description="Exact Gemini API model identifier string.")
    tier: Literal["fast", "balanced", "advanced"] = Field(
        description="Computational performance classification."
    )
    stability: Literal["stable", "preview", "experimental"] = Field(
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
        description="Base persona and behavioral instructions for the cloud agent.",
    )
    hosted_tools: frozenset[Literal["google_search", "google_maps"]] = Field(
        default_factory=frozenset,
        description="Provider-hosted grounding tools enabled for this profile.",
    )
