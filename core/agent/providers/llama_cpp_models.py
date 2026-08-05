"""Apex Apodemus profile and runtime configuration for llama.cpp."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from core.config import (
    APODEMUS_CPU_LIMIT,
    APODEMUS_RAM_LIMIT,
    LLAMA_CPP_REQUEST_TIMEOUT_SECONDS,
    LOCAL_AGENT_SYSTEM_PROMPT,
)

APODEMUS_ALLOWED_CONTEXT_WINDOWS: tuple[int, ...] = (4096, 8192, 16384, 32768)
APODEMUS_DEFAULT_CONTEXT_WINDOW: int = 8192
APODEMUS_MAX_CONTEXT_WINDOW: int = 131072

APODEMUS_DEFAULT_TEMPERATURE: float = 0.2
APODEMUS_MAX_TOOL_TURNS: int = 3
APODEMUS_MAX_TOOL_CALLS: int = 4
APODEMUS_TOOL_SELECT_MAX_TOKENS: int = 256
APODEMUS_FINAL_ANSWER_MAX_TOKENS: int = 768

APODEMUS_RUNTIME_MODEL_IDS: dict[int, str] = {
    4096: "apodemus-4k",
    8192: "apodemus-8k",
    16384: "apodemus-16k",
    32768: "apodemus-32k",
}

APODEMUS_CONFIGURED_MODEL: str = "gemma-4-E2B-Q4_K_M.gguf"


def apodemus_runtime_model_id(context_window: int) -> str:
    """Return the stable llama.cpp router alias for a selectable context."""
    try:
        return APODEMUS_RUNTIME_MODEL_IDS[context_window]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported Apodemus context window: {context_window!r}"
        ) from exc


def resolve_apodemus_context_window(value: int | None) -> int:
    """Resolve an Apodemus context preference, defaulting to 8K."""
    if value is None:
        return APODEMUS_DEFAULT_CONTEXT_WINDOW
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Unsupported Apodemus context window: {value!r}")
    if value not in APODEMUS_ALLOWED_CONTEXT_WINDOWS:
        raise ValueError(f"Unsupported Apodemus context window: {value!r}")
    return value


class LlamaCppModelProfile(BaseModel):
    """Concrete runtime profile for Apex Apodemus through llama.cpp."""

    provider: ClassVar[Literal["llama_cpp"]] = "llama_cpp"
    runtime: ClassVar[Literal["local"]] = "local"

    display_name: str = Field(description="Visual name surfaced in HUD UI components.")
    agent_version: str = Field(
        description="Version of the named Apex Agent product identity."
    )
    api_model: str = Field(
        description="Configured GGUF model identity shown in Agent metadata."
    )
    tier: Literal["lightweight", "balanced", "capable"] = Field(
        description="Computational performance classification for local inference."
    )
    stability: Literal["stable", "preview"] = Field(
        description="Release stage classification of the target model."
    )
    default_temperature: float = Field(
        default=APODEMUS_DEFAULT_TEMPERATURE,
        description="Lower temperature values minimize tool-calling hallucinations.",
    )
    max_tool_turns: int = Field(
        description="Turn boundary ceiling to prevent infinite loops."
    )
    max_tool_calls: int = Field(
        description="Maximum individual tool executions allowed per session.",
    )
    context_window: int = Field(
        description="Selected input token context window for this load."
    )
    maximum_context_window: int = Field(
        default=APODEMUS_MAX_CONTEXT_WINDOW,
        description="Model maximum context metadata; not a selectable preset.",
    )
    allowed_context_windows: tuple[int, ...] = Field(
        default=APODEMUS_ALLOWED_CONTEXT_WINDOWS,
        description="Discrete selectable context presets for this Agent.",
    )
    tool_select_max_tokens: int = Field(
        description="Token ceiling when the model is selecting a tool."
    )
    final_answer_max_tokens: int = Field(
        description="Token ceiling for the final text response."
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
    high_resource: bool = Field(
        default=False,
        description="Whether cold loads of this Agent warrant a high-resource warning.",
    )
    reasoning_mode: Literal["off"] = Field(
        default="off",
        description="Apodemus keeps reasoning disabled as part of its runtime contract.",
    )
    parallel_tool_calls: bool = Field(
        default=True,
        description="Whether the provider may emit multiple structured tool calls.",
    )
    system_instruction: str = Field(
        description="Base persona and behavioral instructions for the local agent.",
    )

    @model_validator(mode="after")
    def _validate_context_contract(self) -> LlamaCppModelProfile:
        if self.context_window not in self.allowed_context_windows:
            raise ValueError(
                f"context_window {self.context_window} is not in "
                f"allowed_context_windows {self.allowed_context_windows}"
            )
        if self.maximum_context_window < max(self.allowed_context_windows):
            raise ValueError(
                "maximum_context_window must be at least every allowed context value"
            )
        if self.reasoning_mode != "off":
            raise ValueError("Apodemus reasoning_mode must remain off")
        return self

    @property
    def runtime_model_id(self) -> str:
        """Provider runtime identifier used for load, unload, and residency checks."""
        return apodemus_runtime_model_id(self.context_window)


def build_apodemus_profile(
    *,
    display_name: str,
    agent_version: str,
    api_model: str,
    tier: Literal["lightweight", "balanced", "capable"],
    stability: Literal["stable", "preview"],
    max_tool_turns: int,
    max_tool_calls: int,
    system_instruction: str,
    context_window: int | None = None,
) -> LlamaCppModelProfile:
    """Build a concrete Apodemus profile for the selected context preset."""
    resolved_context = resolve_apodemus_context_window(context_window)
    return LlamaCppModelProfile(
        display_name=display_name,
        agent_version=agent_version,
        api_model=api_model,
        tier=tier,
        stability=stability,
        default_temperature=APODEMUS_DEFAULT_TEMPERATURE,
        max_tool_turns=max_tool_turns,
        max_tool_calls=max_tool_calls,
        context_window=resolved_context,
        maximum_context_window=APODEMUS_MAX_CONTEXT_WINDOW,
        allowed_context_windows=APODEMUS_ALLOWED_CONTEXT_WINDOWS,
        tool_select_max_tokens=APODEMUS_TOOL_SELECT_MAX_TOKENS,
        final_answer_max_tokens=APODEMUS_FINAL_ANSWER_MAX_TOKENS,
        generation_timeout=int(LLAMA_CPP_REQUEST_TIMEOUT_SECONDS),
        ram_limit=APODEMUS_RAM_LIMIT,
        cpu_limit=APODEMUS_CPU_LIMIT,
        high_resource=resolved_context >= 32768,
        reasoning_mode="off",
        parallel_tool_calls=True,
        system_instruction=system_instruction or LOCAL_AGENT_SYSTEM_PROMPT,
    )
