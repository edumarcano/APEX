"""Registered model profiles for the native Apex Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.agent.providers.contract import InferenceProvider
from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS
from core.agent.types import LocalReasoningMode
from core.config import (
    GEMINI_AGENT_MAX_TOOL_CALLS,
    GEMINI_AGENT_MAX_TURNS,
)

ModelStability = Literal["stable", "preview", "experimental"]
CloudProvider = Literal["openai", "openrouter", "gemini"]
LocalRuntime = Literal["ollama", "llama_cpp"]
HostedTool = Literal["google_search", "google_maps"]

@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Replaceable provider/runtime model configuration."""

    model_id: str
    display_name: str
    provider: InferenceProvider
    runtime: Literal["cloud", "local"]
    stability: ModelStability
    credential_env: str | None
    max_tool_turns: int
    max_tool_calls: int
    supports_encrypted_reasoning: bool
    hosted_capabilities: frozenset[HostedTool]
    reasoning_options: tuple[str, ...] = ()
    default_reasoning: str | None = None
    dev_only: bool = False
    maximum_context_window: int | None = None

    def __post_init__(self) -> None:
        if self.provider == "gemini":
            from core.agent.pricing import is_free_tier_model

            if is_free_tier_model(self.model_id):
                object.__setattr__(self, "credential_env", "GEMINI_SANDBOX_API_KEY")


# Cloud models available to Apex Agent.
CLOUD_MODEL_PROFILES: dict[str, ModelProfile] = {
    "deepseek/deepseek-v4-flash-0731": ModelProfile(
        model_id="deepseek/deepseek-v4-flash-0731",
        display_name="DeepSeek V4 Flash 0731",
        provider="openrouter",
        runtime="cloud",
        stability="stable",
        credential_env="OPENROUTER_API_KEY",
        max_tool_turns=min(6, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(10, GEMINI_AGENT_MAX_TOOL_CALLS),
        reasoning_options=("none", "low", "high", "max"),
        default_reasoning="high",
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset(),
        maximum_context_window=1_310_720,
    ),
    "gpt-5.6-luna": ModelProfile(
        model_id="gpt-5.6-luna",
        display_name="GPT-5.6 Luna",
        provider="openai",
        runtime="cloud",
        stability="stable",
        credential_env="OPENAI_API_KEY",
        max_tool_turns=min(6, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(10, GEMINI_AGENT_MAX_TOOL_CALLS),
        reasoning_options=("none", "minimal", "low", "medium", "high", "xhigh"),
        default_reasoning="medium",
        supports_encrypted_reasoning=True,
        hosted_capabilities=frozenset(),
    ),
    "gemini-3.5-flash-lite": ModelProfile(
        model_id="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash Lite",
        provider="gemini",
        runtime="cloud",
        stability="stable",
        credential_env="GEMINI_SANDBOX_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        reasoning_options=("minimal", "low", "medium", "high"),
        default_reasoning="medium",
        supports_encrypted_reasoning=True,
        hosted_capabilities=frozenset(),
        dev_only=True,
        maximum_context_window=1_048_576,
    ),
    "gemini-3.6-flash": ModelProfile(
        model_id="gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        provider="gemini",
        runtime="cloud",
        stability="stable",
        credential_env="GEMINI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        reasoning_options=("minimal", "low", "medium", "high"),
        default_reasoning="medium",
        supports_encrypted_reasoning=True,
        hosted_capabilities=frozenset({"google_search", "google_maps"}),
        dev_only=True,
        maximum_context_window=1_048_576,
    ),
}

# Local models available to Apex Agent.
LOCAL_MODEL_PROFILES: dict[str, ModelProfile] = {
    "gemma-4-E2B-Q4_K_M.gguf": ModelProfile(
        model_id="gemma-4-E2B-Q4_K_M.gguf",
        display_name="Gemma 4 E2B",
        provider="llama_cpp",
        runtime="local",
        stability="stable",
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset(),
    ),
    "gemma-4-E4B-Q4_K_M.gguf": ModelProfile(
        model_id="gemma-4-E4B-Q4_K_M.gguf",
        display_name="Gemma 4 E4B",
        provider="llama_cpp",
        runtime="local",
        stability="experimental",
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset(),
    ),
    "qwen3:1.7b": ModelProfile(
        model_id="qwen3:1.7b",
        display_name="Qwen3 1.7B",
        provider="ollama",
        runtime="local",
        stability="stable",
        credential_env=None,
        max_tool_turns=2,
        max_tool_calls=3,
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset(),
        dev_only=True,
        maximum_context_window=4096,
    ),
    "qwen3:4b-instruct": ModelProfile(
        model_id="qwen3:4b-instruct",
        display_name="Qwen3 4B Instruct",
        provider="ollama",
        runtime="local",
        stability="stable",
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset(),
        dev_only=True,
        maximum_context_window=4096,
    ),
    "Qwen3.5-4B-Q4_K_M.gguf": ModelProfile(
        model_id="Qwen3.5-4B-Q4_K_M.gguf",
        display_name="Qwen3.5 4B",
        provider="llama_cpp",
        runtime="local",
        stability="experimental",
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset(),
    ),
}

ALL_MODEL_PROFILES: dict[str, ModelProfile] = {
    **CLOUD_MODEL_PROFILES,
    **LOCAL_MODEL_PROFILES,
}

DEFAULT_APEX_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_CLOUD_MODEL = DEFAULT_APEX_MODEL
FOCUSED_BRIEFING_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_LOCAL_MODEL = "gemma-4-E2B-Q4_K_M.gguf"
DEFAULT_LOCAL_RUNTIME: LocalRuntime = "llama_cpp"



def get_model_profile(model_id: str) -> ModelProfile | None:
    return ALL_MODEL_PROFILES.get(model_id)


def visible_cloud_models(*, dev_mode: bool = False) -> tuple[ModelProfile, ...]:
    return tuple(
        profile
        for profile in CLOUD_MODEL_PROFILES.values()
        if not profile.dev_only or dev_mode
    )


def visible_local_models(*, dev_mode: bool = False) -> tuple[ModelProfile, ...]:
    return tuple(
        profile
        for profile in LOCAL_MODEL_PROFILES.values()
        if not profile.dev_only or dev_mode
    )


def model_has_credentials(profile: ModelProfile) -> bool:
    if profile.credential_env is None:
        return True
    import os

    return bool(os.getenv(profile.credential_env))


def model_display_label(model_id: str) -> str:
    profile = ALL_MODEL_PROFILES.get(model_id)
    return profile.display_name if profile is not None else model_id


def reconcile_cloud_model(
    model: str,
    *,
    dev_mode: bool = False,
) -> str:
    """Return a supported cloud model, falling back to the default cloud model."""
    profile = get_model_profile(model)
    if (
        profile is not None
        and profile.runtime == "cloud"
        and (not profile.dev_only or dev_mode)
    ):
        return model
    return DEFAULT_CLOUD_MODEL


def reconcile_local_model(
    model: str,
    *,
    dev_mode: bool = False,
) -> str:
    """Return a supported local model, falling back to the default local model."""
    profile = get_model_profile(model)
    if (
        profile is not None
        and profile.runtime == "local"
        and (not profile.dev_only or dev_mode)
    ):
        return model
    return DEFAULT_LOCAL_MODEL


def reconcile_local_context_window(
    runtime: LocalRuntime,
    model: str,
    context_window: int,
) -> int:
    """Keep the context preset when supported; otherwise use the model default."""
    if runtime != "llama_cpp":
        return context_window
    llama_runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(model)
    if llama_runtime is None:
        return context_window
    if context_window in llama_runtime.allowed_context_windows:
        return context_window
    return llama_runtime.default_context_window


def reconcile_local_reasoning_mode(
    model: str,
    reasoning_mode: LocalReasoningMode,
) -> LocalReasoningMode:
    """Keep the reasoning mode when supported; otherwise use the model default."""
    from core.agent.catalog import local_reasoning_modes_for_model

    supported = local_reasoning_modes_for_model(model)
    if reasoning_mode in supported:
        return reasoning_mode
    if not supported:
        return "none"
    return supported[0]


def reconcile_model_reasoning(
    model: str,
    reasoning: str | None,
) -> str | None:
    """Keep the reasoning level when supported by the model; otherwise use model default."""
    profile = get_model_profile(model)
    if profile is None or not profile.reasoning_options:
        return None
    if reasoning in profile.reasoning_options:
        return reasoning
    return profile.default_reasoning
