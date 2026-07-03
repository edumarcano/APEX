from typing import Literal

from pydantic import BaseModel, Field

from core.config import (
    ACINONYX_CPU_LIMIT,
    ACINONYX_RAM_LIMIT,
    AGENT_MAX_TOOL_CALLS,
    AGENT_MAX_TURNS,
    LYNX_CPU_LIMIT,
    LYNX_RAM_LIMIT,
    NEOFELIS_CPU_LIMIT,
    NEOFELIS_RAM_LIMIT,
)

_APEX_LOCAL_AGENT_SYSTEM_INSTRUCTION = (
    "You are APEX (Automated Personal Environment Xylem), Chief's interactive "
    "local operations assistant. Answer direct questions using available tools "
    "when live data is required. Be concise, authoritative, and operational. "
    "Address the user as Chief when natural. Do not fabricate telemetry—use "
    "tools to retrieve current workspace, weather, sports, news, and briefing data."
)


class OllamaModelProfile(BaseModel):
    display_name: str = Field(description="Visual name surfaced in HUD UI components.")
    profile_version: str = Field(description="Internal configuration profile version.")
    api_model: str = Field(description="Exact Ollama model tag string.")
    tier: Literal["lightweight", "fast", "capable"] = Field(
        description="Computational performance classification for local inference."
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
    context_window: int = Field(
        description="Maximum input token context window for the local model."
    )
    max_output_tokens: int = Field(
        description="Maximum generation tokens per response."
    )
    generation_timeout: int = Field(
        description="Hard timeout in seconds for a single model generation call."
    )
    ram_limit: float = Field(
        description="Maximum host RAM utilization percentage before load is gated."
    )
    cpu_limit: float = Field(
        description="Maximum host CPU utilization percentage before load is gated."
    )
    description: str = Field(
        description="Contextual helper text describing the model tier's operational role."
    )
    system_instruction: str = Field(
        default=_APEX_LOCAL_AGENT_SYSTEM_INSTRUCTION,
        description="Base persona and behavioral instructions for the local agent.",
    )


OLLAMA_MODEL_PROFILES: dict[str, OllamaModelProfile] = {
    "lynx": OllamaModelProfile(
        display_name="Apex Lynx",
        profile_version="1.0",
        api_model="qwen3:1.7b",
        tier="lightweight",
        stability="stable",
        default_temperature=0.2,
        max_tool_turns=min(2, AGENT_MAX_TURNS),
        max_tool_calls=min(3, AGENT_MAX_TOOL_CALLS),
        context_window=4096,
        max_output_tokens=512,
        generation_timeout=60,
        ram_limit=LYNX_RAM_LIMIT,
        cpu_limit=LYNX_CPU_LIMIT,
        description="Lightweight local mode for quick lookups and minimal resource usage.",
    ),
    "acinonyx": OllamaModelProfile(
        display_name="Apex Acinonyx",
        profile_version="1.0",
        api_model="qwen3:4b",
        tier="fast",
        stability="stable",
        default_temperature=0.2,
        max_tool_turns=AGENT_MAX_TURNS,
        max_tool_calls=AGENT_MAX_TOOL_CALLS,
        context_window=8192,
        max_output_tokens=768,
        generation_timeout=90,
        ram_limit=ACINONYX_RAM_LIMIT,
        cpu_limit=ACINONYX_CPU_LIMIT,
        description="Fast local agent for normal APEX usage with balanced resource cost.",
    ),
    "neofelis": OllamaModelProfile(
        display_name="Apex Neofelis",
        profile_version="1.0",
        api_model="qwen3:8b",
        tier="capable",
        stability="stable",
        default_temperature=0.1,
        max_tool_turns=AGENT_MAX_TURNS,
        max_tool_calls=AGENT_MAX_TOOL_CALLS,
        context_window=8192,
        max_output_tokens=1024,
        generation_timeout=150,
        ram_limit=NEOFELIS_RAM_LIMIT,
        cpu_limit=NEOFELIS_CPU_LIMIT,
        description="Capable local reasoning for complex multi-source questions inside APEX.",
    ),
}
