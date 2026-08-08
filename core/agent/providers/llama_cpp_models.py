"""Generic Apex local-agent profiles and runtime configuration for llama.cpp."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from core.config import (
    LLAMA_CPP_REQUEST_TIMEOUT_SECONDS,
    LLAMA_CPP_RESOURCE_GATES,
    LOCAL_AGENT_SYSTEM_PROMPT,
)
from core.agent.types import LocalReasoningMode


class LlamaCppRuntimeConfig(BaseModel):
    """Data-driven runtime capabilities for one registered llama.cpp Agent."""

    default_temperature: float = Field(
        description="Sampling temperature used by this local runtime profile."
    )
    allowed_context_windows: tuple[int, ...] = Field(
        description="Discrete context presets exposed by the HUD."
    )
    default_context_window: int = Field(
        description="Context preset used when no persisted preference exists."
    )
    high_resource_context_options: tuple[int, ...] = Field(
        description="Context presets that receive a high-resource UI label."
    )
    supported_reasoning_modes: tuple[LocalReasoningMode, ...] = Field(
        description="Provider-supported local reasoning modes for this Agent."
    )
    default_reasoning_mode: LocalReasoningMode = Field(
        default="none",
        description="Reasoning mode used when no persisted preference exists.",
    )
    maximum_context_window: int = Field(
        description="Native model context metadata, not an exposed preset."
    )
    runtime_model_ids: dict[int, str] = Field(
        description="Context-window-to-router-alias mapping for this Agent."
    )
    tool_select_max_tokens: int = Field(
        description="Token ceiling when the model is selecting a tool."
    )
    final_answer_max_tokens: int = Field(
        description="Token ceiling for the final text response."
    )
    focused_tool_select_max_tokens: int = Field(
        description=(
            "Completion ceiling for tool selection when native reasoning is enabled."
        )
    )
    focused_final_answer_max_tokens: int = Field(
        description=(
            "Completion ceiling for final answers when native reasoning is enabled."
        )
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
    parallel_tool_calls: bool = Field(
        description="Whether the provider may emit multiple structured tool calls."
    )

    @model_validator(mode="after")
    def _validate_runtime_contract(self) -> LlamaCppRuntimeConfig:
        if self.default_context_window not in self.allowed_context_windows:
            raise ValueError(
                "default_context_window must be one of allowed_context_windows"
            )
        if self.maximum_context_window < max(self.allowed_context_windows):
            raise ValueError(
                "maximum_context_window must be at least every allowed context value"
            )
        if set(self.runtime_model_ids) != set(self.allowed_context_windows):
            raise ValueError(
                "runtime_model_ids must provide exactly one alias per allowed context"
            )
        if not set(self.high_resource_context_options).issubset(
            self.allowed_context_windows
        ):
            raise ValueError(
                "high_resource_context_options must be allowed context presets"
            )
        if not self.supported_reasoning_modes:
            raise ValueError("supported_reasoning_modes must not be empty")
        if "none" not in self.supported_reasoning_modes:
            raise ValueError("supported_reasoning_modes must include 'none'")
        if self.default_reasoning_mode not in self.supported_reasoning_modes:
            raise ValueError(
                "default_reasoning_mode must be a supported reasoning mode"
            )
        return self


class LlamaCppModelProfile(BaseModel):
    """Concrete runtime profile for a registered Agent through llama.cpp."""

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
    stability: Literal["stable", "preview", "experimental"] = Field(
        description="Release stage classification of the target model."
    )
    default_temperature: float = Field(
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
    default_context_window: int = Field(
        description="Context preset used when no persisted preference exists."
    )
    maximum_context_window: int = Field(
        description="Model maximum context metadata; not a selectable preset.",
    )
    allowed_context_windows: tuple[int, ...] = Field(
        description="Discrete selectable context presets for this Agent.",
    )
    high_resource_context_options: tuple[int, ...] = Field(
        description="Context presets that receive a high-resource UI label."
    )
    supported_reasoning_modes: tuple[LocalReasoningMode, ...] = Field(
        description="Provider-supported local reasoning modes for this Agent."
    )
    default_reasoning_mode: LocalReasoningMode = Field(
        description="Reasoning mode used when no persisted preference exists."
    )
    reasoning_mode: LocalReasoningMode = Field(
        description="Resolved reasoning mode for the next provider request."
    )
    runtime_model_id: str = Field(
        description="Resolved llama.cpp router alias used for load and residency checks."
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
    parallel_tool_calls: bool = Field(
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
        if self.default_context_window not in self.allowed_context_windows:
            raise ValueError(
                "default_context_window must be one of allowed_context_windows"
            )
        if not set(self.high_resource_context_options).issubset(
            self.allowed_context_windows
        ):
            raise ValueError(
                "high_resource_context_options must be allowed context presets"
            )
        if self.maximum_context_window < max(self.allowed_context_windows):
            raise ValueError(
                "maximum_context_window must be at least every allowed context value"
            )
        if not self.runtime_model_id.strip():
            raise ValueError("runtime_model_id must not be empty")
        if not self.supported_reasoning_modes:
            raise ValueError("supported_reasoning_modes must not be empty")
        if "none" not in self.supported_reasoning_modes:
            raise ValueError("supported_reasoning_modes must include 'none'")
        if self.default_reasoning_mode not in self.supported_reasoning_modes:
            raise ValueError(
                "default_reasoning_mode must be a supported reasoning mode"
            )
        if self.reasoning_mode not in self.supported_reasoning_modes:
            raise ValueError("reasoning_mode must be a supported reasoning mode")
        return self


def llama_cpp_runtime_config(agent_key: str) -> LlamaCppRuntimeConfig:
    """Return the registered llama.cpp runtime configuration for an Agent."""
    try:
        return LLAMA_CPP_RUNTIME_CONFIGS[agent_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported llama.cpp Agent: {agent_key!r}") from exc


def resolve_llama_cpp_context_window(agent_key: str, value: int | None) -> int:
    """Resolve a persisted context preference using the Agent's runtime data."""
    runtime = llama_cpp_runtime_config(agent_key)
    if value is None:
        return runtime.default_context_window
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(
            f"Unsupported llama.cpp context window for {agent_key}: {value!r}"
        )
    if value not in runtime.allowed_context_windows:
        raise ValueError(
            f"Unsupported llama.cpp context window for {agent_key}: {value!r}"
        )
    return value


def llama_cpp_runtime_model_id(agent_key: str, context_window: int) -> str:
    """Return the stable router alias for an Agent's selected context."""
    runtime = llama_cpp_runtime_config(agent_key)
    resolved_context = resolve_llama_cpp_context_window(agent_key, context_window)
    return runtime.runtime_model_ids[resolved_context]


def llama_cpp_context_window_for_runtime_model_id(
    agent_key: str,
    runtime_model_id: str,
) -> int | None:
    """Return the configured context for a resident llama.cpp router alias."""
    runtime = llama_cpp_runtime_config(agent_key)
    for context_window, model_id in runtime.runtime_model_ids.items():
        if model_id == runtime_model_id:
            return context_window
    return None


def resolve_llama_cpp_reasoning_mode(
    agent_key: str,
    value: str | None,
) -> LocalReasoningMode:
    """Resolve a persisted reasoning preference against runtime capabilities."""
    runtime = llama_cpp_runtime_config(agent_key)
    if value is None:
        return runtime.default_reasoning_mode
    if value not in runtime.supported_reasoning_modes:
        raise ValueError(
            f"Unsupported llama.cpp reasoning mode for {agent_key}: {value!r}"
        )
    return value  # type: ignore[return-value]


def _resource_limits(agent_key: str) -> tuple[float, float]:
    """Return configured resource gates without embedding Agent conditionals."""
    return LLAMA_CPP_RESOURCE_GATES.get(agent_key, (82.0, 92.0))


def build_llama_cpp_profile(
    agent_key: str,
    *,
    display_name: str,
    agent_version: str,
    api_model: str,
    tier: Literal["lightweight", "balanced", "capable"],
    stability: Literal["stable", "preview", "experimental"],
    max_tool_turns: int,
    max_tool_calls: int,
    system_instruction: str,
    context_window: int | None = None,
    reasoning_mode: LocalReasoningMode | None = None,
) -> LlamaCppModelProfile:
    """Build one concrete profile from the registered Agent runtime data."""
    runtime = llama_cpp_runtime_config(agent_key)
    resolved_context = resolve_llama_cpp_context_window(agent_key, context_window)
    resolved_reasoning = resolve_llama_cpp_reasoning_mode(agent_key, reasoning_mode)
    if resolved_reasoning == "focused":
        tool_select_max_tokens = runtime.focused_tool_select_max_tokens
        final_answer_max_tokens = runtime.focused_final_answer_max_tokens
    else:
        tool_select_max_tokens = runtime.tool_select_max_tokens
        final_answer_max_tokens = runtime.final_answer_max_tokens
    return LlamaCppModelProfile(
        display_name=display_name,
        agent_version=agent_version,
        api_model=api_model,
        tier=tier,
        stability=stability,
        default_temperature=runtime.default_temperature,
        max_tool_turns=max_tool_turns,
        max_tool_calls=max_tool_calls,
        context_window=resolved_context,
        default_context_window=runtime.default_context_window,
        maximum_context_window=runtime.maximum_context_window,
        allowed_context_windows=runtime.allowed_context_windows,
        high_resource_context_options=runtime.high_resource_context_options,
        supported_reasoning_modes=runtime.supported_reasoning_modes,
        default_reasoning_mode=runtime.default_reasoning_mode,
        reasoning_mode=resolved_reasoning,
        runtime_model_id=llama_cpp_runtime_model_id(agent_key, resolved_context),
        tool_select_max_tokens=tool_select_max_tokens,
        final_answer_max_tokens=final_answer_max_tokens,
        generation_timeout=runtime.generation_timeout,
        ram_limit=runtime.ram_limit,
        cpu_limit=runtime.cpu_limit,
        high_resource=resolved_context in runtime.high_resource_context_options,
        parallel_tool_calls=runtime.parallel_tool_calls,
        system_instruction=system_instruction or LOCAL_AGENT_SYSTEM_PROMPT,
    )


def _runtime_config(
    *,
    allowed_context_windows: tuple[int, ...],
    high_resource_context_options: tuple[int, ...],
    supported_reasoning_modes: tuple[LocalReasoningMode, ...],
    default_context_window: int,
    maximum_context_window: int,
    runtime_model_ids: dict[int, str],
    resource_limits: tuple[float, float],
    tool_select_max_tokens: int,
    final_answer_max_tokens: int,
    focused_tool_select_max_tokens: int,
    focused_final_answer_max_tokens: int,
) -> LlamaCppRuntimeConfig:
    """Create a compact immutable-in-practice runtime data entry."""
    return LlamaCppRuntimeConfig(
        default_temperature=0.2,
        allowed_context_windows=allowed_context_windows,
        high_resource_context_options=high_resource_context_options,
        supported_reasoning_modes=supported_reasoning_modes,
        default_context_window=default_context_window,
        maximum_context_window=maximum_context_window,
        runtime_model_ids=runtime_model_ids,
        tool_select_max_tokens=tool_select_max_tokens,
        final_answer_max_tokens=final_answer_max_tokens,
        focused_tool_select_max_tokens=focused_tool_select_max_tokens,
        focused_final_answer_max_tokens=focused_final_answer_max_tokens,
        generation_timeout=int(LLAMA_CPP_REQUEST_TIMEOUT_SECONDS),
        ram_limit=resource_limits[0],
        cpu_limit=resource_limits[1],
        parallel_tool_calls=True,
    )


LLAMA_CPP_RUNTIME_CONFIGS: dict[str, LlamaCppRuntimeConfig] = {
    "apodemus": _runtime_config(
        allowed_context_windows=(4096, 16384, 32768, 131072),
        high_resource_context_options=(131072,),
        supported_reasoning_modes=("none", "focused"),
        default_context_window=16384,
        maximum_context_window=131072,
        runtime_model_ids={
            4096: "apodemus-4k",
            16384: "apodemus-16k",
            32768: "apodemus-32k",
            131072: "apodemus-132k",
        },
        resource_limits=_resource_limits("apodemus"),
        tool_select_max_tokens=256,
        final_answer_max_tokens=768,
        focused_tool_select_max_tokens=1536,
        focused_final_answer_max_tokens=1536,
    ),
    "neotoma": _runtime_config(
        allowed_context_windows=(4096, 16384, 32768, 65536),
        high_resource_context_options=(65536,),
        supported_reasoning_modes=("none", "focused"),
        default_context_window=16384,
        maximum_context_window=262144,
        runtime_model_ids={
            4096: "neotoma-4k",
            16384: "neotoma-16k",
            32768: "neotoma-32k",
            65536: "neotoma-64k",
        },
        resource_limits=_resource_limits("neotoma"),
        tool_select_max_tokens=256,
        final_answer_max_tokens=768,
        focused_tool_select_max_tokens=1536,
        focused_final_answer_max_tokens=1536,
    ),
    "unnamed-experimental-agent": _runtime_config(
        allowed_context_windows=(4096, 16384, 32768),
        high_resource_context_options=(),
        supported_reasoning_modes=("none", "focused"),
        default_context_window=16384,
        maximum_context_window=131072,
        runtime_model_ids={
            4096: "unnamed-experimental-agent-4k",
            16384: "unnamed-experimental-agent-16k",
            32768: "unnamed-experimental-agent-32k",
        },
        resource_limits=_resource_limits("unnamed-experimental-agent"),
        tool_select_max_tokens=256,
        final_answer_max_tokens=768,
        focused_tool_select_max_tokens=1536,
        focused_final_answer_max_tokens=1536,
    ),
}
