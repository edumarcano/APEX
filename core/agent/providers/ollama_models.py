from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from core.agent.types import LocalReasoningMode
from core.config import (
    LOCAL_AGENT_SYSTEM_PROMPT,
    OLLAMA_RESOURCE_GATES,
)


class OllamaModelProfile(BaseModel):
    provider: ClassVar[Literal["ollama"]] = "ollama"
    runtime: ClassVar[Literal["local"]] = "local"
    display_name: str = Field(description="Visual name surfaced in HUD UI components.")
    api_model: str = Field(description="Exact Ollama model tag string.")
    stability: Literal["stable", "preview", "experimental"] = Field(
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
    supported_reasoning_modes: tuple[LocalReasoningMode, ...] = Field(
        default=("none",),
        description="Provider-supported local reasoning modes for this Agent.",
    )
    default_reasoning_mode: LocalReasoningMode = Field(
        default="none",
        description="Reasoning mode used when no persisted preference exists.",
    )
    reasoning_mode: LocalReasoningMode = Field(
        default="none",
        description="Resolved reasoning mode for the next provider request.",
    )
    ram_limit: float = Field(
        description="Maximum host RAM utilization percentage before load is gated."
    )
    cpu_limit: float = Field(
        description="Maximum host CPU utilization percentage before load is gated."
    )
    high_resource: bool = Field(
        default=False,
        description="Whether cold loads of this Agent warrant a high-resource warning.",
    )
    system_instruction: str = Field(
        description="Base persona and behavioral instructions for the local agent.",
    )

    @property
    def runtime_model_id(self) -> str:
        """Provider runtime identifier used for load, unload, and residency checks."""
        return self.api_model


class OllamaRuntimeConfig(BaseModel):
    """Runtime execution, context, and resource tuning for a local model."""

    default_temperature: float = Field(
        default=0.2,
        description="Lower temperature values minimize tool-calling hallucinations.",
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
    supported_reasoning_modes: tuple[LocalReasoningMode, ...] = Field(
        default=("none",),
        description="Provider-supported local reasoning modes for this Agent.",
    )
    default_reasoning_mode: LocalReasoningMode = Field(
        default="none",
        description="Reasoning mode used when no persisted preference exists.",
    )
    ram_limit: float = Field(
        description="Maximum host RAM utilization percentage before load is gated."
    )
    cpu_limit: float = Field(
        description="Maximum host CPU utilization percentage before load is gated."
    )
    system_instruction: str = Field(
        default=LOCAL_AGENT_SYSTEM_PROMPT,
        description="Base persona and behavioral instructions for the local agent.",
    )


OLLAMA_RUNTIME_CONFIGS: dict[str, OllamaRuntimeConfig] = {
    "qwen3:1.7b": OllamaRuntimeConfig(
        default_temperature=0.2,
        context_window=4096,
        tool_select_max_tokens=128,
        final_answer_max_tokens=512,
        num_thread=4,
        generation_timeout=120,
        think=False,
        ram_limit=OLLAMA_RESOURCE_GATES["qwen3:1.7b"][0],
        cpu_limit=OLLAMA_RESOURCE_GATES["qwen3:1.7b"][1],
    ),
    "qwen3:4b-instruct": OllamaRuntimeConfig(
        default_temperature=0.2,
        context_window=4096,
        tool_select_max_tokens=128,
        final_answer_max_tokens=768,
        num_thread=6,
        generation_timeout=150,
        think=False,
        ram_limit=OLLAMA_RESOURCE_GATES["qwen3:4b-instruct"][0],
        cpu_limit=OLLAMA_RESOURCE_GATES["qwen3:4b-instruct"][1],
    ),
}

OLLAMA_HIGH_RESOURCE_MODELS: frozenset[str] = frozenset({"qwen3:4b-instruct"})
