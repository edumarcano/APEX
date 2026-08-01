from typing import Literal

from pydantic import BaseModel, Field

from core.config import (
    DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT,
    MUS_CPU_LIMIT,
    MUS_RAM_LIMIT,
    SOREX_CPU_LIMIT,
    SOREX_RAM_LIMIT,
)


class OllamaModelProfile(BaseModel):
    display_name: str = Field(description="Visual name surfaced in HUD UI components.")
    profile_version: str = Field(description="Internal configuration profile version.")
    api_model: str = Field(description="Exact Ollama model tag string.")
    tier: Literal["lightweight", "balanced", "capable"] = Field(
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
    tool_select_max_tokens: int = Field(
        description="Token ceiling when the model is selecting a tool."
    )
    final_answer_max_tokens: int = Field(
        description="Token ceiling for the final text response."
    )
    num_thread: int = Field(
        description="Maximum CPU threads allocated to local inference."
    )
    generation_timeout: int = Field(
        description="Hard timeout in seconds for a single model generation call."
    )
    think: bool = Field(
        default=False,
        description="Whether to enable Ollama's local reasoning and chain-of-thought phase.",
    )
    ram_limit: float = Field(
        description="Maximum host RAM utilization percentage before load is gated."
    )
    cpu_limit: float = Field(
        description="Maximum host CPU utilization percentage before load is gated."
    )
    system_instruction: str = Field(
        default=DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT,
        description="Base persona and behavioral instructions for the local agent.",
    )


OLLAMA_MODEL_PROFILES: dict[str, OllamaModelProfile] = {
    "sorex": OllamaModelProfile(
        display_name="Apex Sorex",
        profile_version="2.0",
        api_model="qwen3:1.7b",
        tier="lightweight",
        stability="stable",
        default_temperature=0.2,
        max_tool_turns=2,
        max_tool_calls=3,
        context_window=4096,
        tool_select_max_tokens=128,
        final_answer_max_tokens=512,
        num_thread=4,
        generation_timeout=120,
        think=False,
        ram_limit=SOREX_RAM_LIMIT,
        cpu_limit=SOREX_CPU_LIMIT,
    ),
    "mus": OllamaModelProfile(
        display_name="Apex Mus",
        profile_version="2.0",
        api_model="qwen3:4b-instruct",
        tier="balanced",
        stability="stable",
        default_temperature=0.2,
        max_tool_turns=3,
        max_tool_calls=4,
        context_window=4096,
        tool_select_max_tokens=128,
        final_answer_max_tokens=768,
        num_thread=6,
        generation_timeout=150,
        think=False,
        ram_limit=MUS_RAM_LIMIT,
        cpu_limit=MUS_CPU_LIMIT,
    ),
}
