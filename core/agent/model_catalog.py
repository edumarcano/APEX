"""Registered model profiles for Panthera and Lynx execution."""

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
CloudProvider = Literal["openai", "gemini", "xai"]
LocalRuntime = Literal["ollama", "llama_cpp"]
HostedTool = Literal["google_search", "google_maps", "x_search"]

VALID_CLOUD_PROVIDERS: frozenset[str] = frozenset({"openai", "gemini", "xai"})
VALID_LOCAL_RUNTIMES: frozenset[str] = frozenset({"ollama", "llama_cpp"})


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

    @property
    def supports_effort(self) -> bool:
        return bool(self.reasoning_options)

    @property
    def default_effort(self) -> str | None:
        return self.default_reasoning

    def __post_init__(self) -> None:
        if self.provider == "gemini":
            from core.agent.pricing import is_free_tier_model

            if is_free_tier_model(self.model_id):
                object.__setattr__(self, "credential_env", "GEMINI_SANDBOX_API_KEY")


# Cloud models available under Panthera
CLOUD_MODEL_PROFILES: dict[str, ModelProfile] = {
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
    "grok-4.3": ModelProfile(
        model_id="grok-4.3",
        display_name="Grok 4.3",
        provider="xai",
        runtime="cloud",
        stability="stable",
        credential_env="XAI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        reasoning_options=("low", "medium", "high"),
        default_reasoning="medium",
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset({"x_search"}),
        dev_only=True,
        maximum_context_window=200_000,
    ),
    "grok-4.5": ModelProfile(
        model_id="grok-4.5",
        display_name="Grok 4.5",
        provider="xai",
        runtime="cloud",
        stability="stable",
        credential_env="XAI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        reasoning_options=("low", "medium", "high"),
        default_reasoning="high",
        supports_encrypted_reasoning=False,
        hosted_capabilities=frozenset({"x_search"}),
        dev_only=True,
        maximum_context_window=200_000,
    ),
}

# Local models available under Lynx
LOCAL_MODEL_PROFILES: dict[str, ModelProfile] = {
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
    ),
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
        dev_only=True,
    ),
}

ALL_MODEL_PROFILES: dict[str, ModelProfile] = {
    **CLOUD_MODEL_PROFILES,
    **LOCAL_MODEL_PROFILES,
}

DEFAULT_PANTHERA_MODEL = "gpt-5.6-luna"
DEFAULT_LYNX_MODEL = "gemma-4-E2B-Q4_K_M.gguf"
DEFAULT_LYNX_RUNTIME: LocalRuntime = "llama_cpp"

# Legacy agent key → (agent, provider/runtime, model) for schema-15 migration
LEGACY_AGENT_MIGRATION: dict[str, tuple[str, str, str]] = {
    "acinonyx": ("panthera", "gemini", "gemini-3.5-flash-lite"),
    "panthera": ("panthera", "openai", "gpt-5.6-luna"),
    "neofelis": ("panthera", "gemini", "gemini-3.6-flash"),
    "delphinus": ("panthera", "xai", "grok-4.3"),
    "orcinus": ("panthera", "xai", "grok-4.5"),
    "sorex": ("lynx", "ollama", "qwen3:1.7b"),
    "mus": ("lynx", "ollama", "qwen3:4b-instruct"),
    "apodemus": ("lynx", "llama_cpp", "gemma-4-E2B-Q4_K_M.gguf"),
    "neotoma": ("lynx", "llama_cpp", "gemma-4-E4B-Q4_K_M.gguf"),
    "unnamed-experimental-agent": (
        "lynx",
        "llama_cpp",
        "Qwen3.5-4B-Q4_K_M.gguf",
    ),
}


def get_model_profile(model_id: str) -> ModelProfile | None:
    return ALL_MODEL_PROFILES.get(model_id)


def cloud_models_for_provider(
    provider: CloudProvider,
    *,
    dev_mode: bool = False,
) -> tuple[ModelProfile, ...]:
    return tuple(
        profile
        for profile in CLOUD_MODEL_PROFILES.values()
        if profile.provider == provider and (not profile.dev_only or dev_mode)
    )


def local_models_for_runtime(
    runtime: LocalRuntime,
    *,
    dev_mode: bool = False,
) -> tuple[ModelProfile, ...]:
    return tuple(
        profile
        for profile in LOCAL_MODEL_PROFILES.values()
        if profile.provider == runtime and (not profile.dev_only or dev_mode)
    )


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


def reconcile_panthera_provider_model(
    provider: CloudProvider,
    model: str,
    *,
    dev_mode: bool = False,
) -> tuple[CloudProvider, str]:
    """Return a provider/model pair that agree on the same cloud route."""
    profile = get_model_profile(model)
    models_for_provider = cloud_models_for_provider(provider, dev_mode=dev_mode)
    if (
        profile is not None
        and profile.provider == provider
        and (not profile.dev_only or dev_mode)
    ):
        return provider, model
    if models_for_provider:
        return provider, models_for_provider[0].model_id
    default_profile = get_model_profile(DEFAULT_PANTHERA_MODEL)
    assert default_profile is not None
    return default_profile.provider, default_profile.model_id


def reconcile_lynx_runtime_model(
    runtime: LocalRuntime,
    model: str,
    *,
    dev_mode: bool = False,
) -> tuple[LocalRuntime, str]:
    """Return a runtime/model pair that agree on the same local route."""
    profile = get_model_profile(model)
    models_for_runtime = local_models_for_runtime(runtime, dev_mode=dev_mode)
    if (
        profile is not None
        and profile.provider == runtime
        and (not profile.dev_only or dev_mode)
    ):
        return runtime, model
    if models_for_runtime:
        return runtime, models_for_runtime[0].model_id
    default_profile = get_model_profile(DEFAULT_LYNX_MODEL)
    assert default_profile is not None
    return default_profile.provider, default_profile.model_id


def visible_cloud_providers(*, dev_mode: bool = False) -> tuple[CloudProvider, ...]:
    providers: list[CloudProvider] = []
    seen: set[str] = set()
    for profile in visible_cloud_models(dev_mode=dev_mode):
        if profile.provider in seen:
            continue
        seen.add(profile.provider)
        providers.append(profile.provider)
    return tuple(providers)


def reconcile_lynx_context_window(
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


def reconcile_lynx_reasoning_mode(
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


def reconcile_panthera_reasoning(
    model: str,
    reasoning: str | None,
) -> str | None:
    """Keep the reasoning level when supported by the model; otherwise use model default."""
    profile = get_model_profile(model)
    if profile is None or not profile.reasoning_options:
        return None
    if reasoning in profile.reasoning_options:
        return reasoning
    legacy_map = {"light": "low", "focused": "medium", "extended": "high"}
    mapped = legacy_map.get(reasoning or "")
    if mapped in profile.reasoning_options:
        return mapped
    return profile.default_reasoning


reconcile_panthera_effort = reconcile_panthera_reasoning


def visible_local_runtimes(*, dev_mode: bool = False) -> tuple[LocalRuntime, ...]:
    runtimes: list[LocalRuntime] = []
    seen: set[str] = set()
    for profile in visible_local_models(dev_mode=dev_mode):
        if profile.provider in seen:
            continue
        seen.add(profile.provider)
        runtimes.append(profile.provider)
    return tuple(runtimes)
