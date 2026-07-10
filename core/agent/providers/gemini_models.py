from typing import Literal

from pydantic import BaseModel, Field

from core.config import AGENT_MAX_TOOL_CALLS, AGENT_MAX_TURNS, DEFAULT_AGENT_SYSTEM_PROMPT


GeminiThinkingLevel = Literal["minimal", "low", "medium", "high"]


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
            "Gemini thinking effort for GenerateContentConfig.thinking_config. "
            "Tied to the profile; not independently selectable in the HUD."
        ),
    )
    default_temperature: float = Field(
        default=0.2,
        description="Lower temperature values minimize tool-calling hallucinations.",
    )
    max_tool_turns: int = Field(
        default=3, description="Turn boundary ceiling to prevent infinite loops."
    )
    max_tool_calls: int = Field(
        default=4,
        description="Maximum individual tool executions allowed per session.",
    )
    description: str = Field(
        description="Contextual helper text describing the model tier's operational role."
    )
    system_instruction: str = Field(
        default=DEFAULT_AGENT_SYSTEM_PROMPT,
        description="Base persona and behavioral instructions for the cloud agent.",
    )


GEMINI_MODEL_PROFILES: dict[str, GeminiModelProfile] = {
    "comet": GeminiModelProfile(
        display_name="Apex Comet",
        profile_version="1.0",
        api_model="gemini-3.1-flash-lite",
        tier="fast",
        stability="stable",
        thinking_level="minimal",
        default_temperature=0.2,
        max_tool_turns=min(2, AGENT_MAX_TURNS),
        max_tool_calls=min(3, AGENT_MAX_TOOL_CALLS),
        description="Fast cloud mode for quick lookups and lightweight summaries inside APEX.",
    ),
    "nova": GeminiModelProfile(
        display_name="Apex Nova",
        profile_version="1.0",
        api_model="gemini-3-flash-preview",
        tier="balanced",
        stability="preview",
        thinking_level="low",
        default_temperature=0.2,
        max_tool_turns=AGENT_MAX_TURNS,
        max_tool_calls=AGENT_MAX_TOOL_CALLS,
        description="Balanced cloud agent for normal APEX usage.",
    ),
    "pulsar": GeminiModelProfile(
        display_name="Apex Pulsar",
        profile_version="1.0",
        api_model="gemini-3.5-flash",
        tier="advanced",
        stability="stable",
        thinking_level="medium",
        default_temperature=0.1,
        max_tool_turns=AGENT_MAX_TURNS,
        max_tool_calls=AGENT_MAX_TOOL_CALLS,
        description="Advanced cloud reasoning for complex multi-source questions inside APEX.",
    ),
}
