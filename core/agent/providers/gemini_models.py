from typing import Literal

from pydantic import BaseModel, Field

_APEX_AGENT_SYSTEM_INSTRUCTION = (
    "You are APEX (Automated Personal Environment Xylem), Chief's interactive "
    "cloud operations assistant. Answer direct questions using available tools "
    "when live data is required. Be concise, authoritative, and operational. "
    "Address the user as Chief when natural. Do not fabricate telemetry—use "
    "tools to retrieve current workspace, weather, sports, news, and briefing data."
)


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
        default=_APEX_AGENT_SYSTEM_INSTRUCTION,
        description="Base persona and behavioral instructions for the cloud agent.",
    )


GEMINI_MODEL_PROFILES: dict[str, GeminiModelProfile] = {
    "comet": GeminiModelProfile(
        display_name="Apex Comet",
        profile_version="1.0",
        api_model="gemini-3.1-flash-lite",
        tier="fast",
        stability="stable",
        default_temperature=0.2,
        max_tool_turns=2,
        max_tool_calls=3,
        description="Fast cloud mode for quick lookups and lightweight summaries inside the APEX Cortex.",
    ),
    "nova": GeminiModelProfile(
        display_name="Apex Nova",
        profile_version="1.0",
        api_model="gemini-3-flash-preview",
        tier="balanced",
        stability="preview",
        default_temperature=0.2,
        max_tool_turns=3,
        max_tool_calls=4,
        description="Balanced cloud agent for normal APEX Cortex usage.",
    ),
    "stellar": GeminiModelProfile(
        display_name="Apex Pulsar",
        profile_version="1.0",
        api_model="gemini-3.5-flash",
        tier="advanced",
        stability="stable",
        default_temperature=0.1,
        max_tool_turns=3,
        max_tool_calls=4,
        description="Advanced cloud reasoning for complex multi-source questions inside the APEX Cortex.",
    ),
}
