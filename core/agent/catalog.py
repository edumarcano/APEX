"""Apex Agent catalog, effort resolution, and provider model factories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from core.agent.model_catalog import (
    DEFAULT_LOCAL_MODEL,
    DEFAULT_LOCAL_RUNTIME,
    DEFAULT_APEX_MODEL,
    LOCAL_MODEL_PROFILES,
    ModelProfile,
    get_model_profile,
    model_has_credentials,
)
from core.agent.providers.contract import InferenceProvider, is_local_inference_provider
from core.agent.local_runtime.contract import LocalModelRef
from core.agent.providers.gemini_models import GeminiModelProfile, GeminiThinkingLevel
from core.agent.providers.llama_cpp_models import (
    LLAMA_CPP_RUNTIME_CONFIGS,
    LlamaCppModelProfile,
    build_llama_cpp_profile,
    llama_cpp_runtime_config,
    model_id_for_llama_cpp_alias,
)
from core.agent.providers.ollama_models import (
    OLLAMA_HIGH_RESOURCE_MODELS,
    OLLAMA_RUNTIME_CONFIGS,
    OllamaModelProfile,
)
from core.agent.providers.responses_api import ResponsesModelProfile
from core.agent.providers.openrouter import OpenRouterModelProfile
from core.agent.tool_policies import hosted_tools_for_model
from core.agent.types import LocalReasoningMode
from core.config import (
    AGENT_SYSTEM_PROMPT,
    LOCAL_AGENT_SYSTEM_PROMPT,
    is_dev_mode,
)

AgentKey: TypeAlias = Literal["apex"]
AgentRuntime: TypeAlias = Literal["cloud", "local"]
NativeEffort: TypeAlias = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
CloudProvider: TypeAlias = Literal["openai", "openrouter", "gemini"]
LocalRuntime: TypeAlias = Literal["ollama", "llama_cpp"]

VALID_AGENT_KEYS: frozenset[str] = frozenset({"apex"})

_PROVIDER_DISPLAY_NAMES: dict[InferenceProvider, str] = {
    "gemini": "Google",
    "ollama": "Ollama",
    "llama_cpp": "llama.cpp",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
}

AgentModelProfile = (
    GeminiModelProfile
    | OllamaModelProfile
    | LlamaCppModelProfile
    | ResponsesModelProfile
    | OpenRouterModelProfile
)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Static metadata for one durable Apex Agent identity."""

    key: AgentKey
    display_name: str
    description: str
    identity_instruction: str
    capability_tags: tuple[str, ...]


AGENT_SPECS: dict[str, AgentSpec] = {
    "apex": AgentSpec(
        key="apex",
        display_name="Apex Agent",
        description="APEX's built-in personal operations assistant for briefings, trusted context, connected services, and APEX actions.",
        identity_instruction="You are Apex Agent, APEX's built-in personal operations assistant.",
        capability_tags=("APEX", "Personal operations"),
    ),
}

_RUNTIME_PROFILE_ORDER: tuple[str, ...] = ("apex",)


def runtime_agent_order() -> tuple[str, ...]:
    """Return HUD-visible Agent keys in display order."""
    return _RUNTIME_PROFILE_ORDER


def is_agent_visible(key: str) -> bool:
    return key in AGENT_SPECS


def resolve_effort_for_model(
    model_id: str,
    requested: str | None,
) -> str | None:
    """Resolve effort for a selected model."""
    profile = get_model_profile(model_id)
    if profile is None:
        raise ValueError(f"Unknown model {model_id!r}")
    return resolve_effort(profile, requested)


def resolve_effort(
    model_profile: ModelProfile,
    requested: str | None,
) -> str | None:
    """Resolve model-native reasoning effort for a model."""
    if not model_profile.reasoning_options:
        return None
    if requested:
        cleaned = requested.strip().lower()
        if cleaned in model_profile.reasoning_options:
            return cleaned
    return model_profile.default_reasoning


def model_has_available_credentials(
    model_id: str, profile: ModelProfile | None = None
) -> bool:
    """Return whether a model has credentials."""
    resolved_profile = profile or get_model_profile(model_id)
    if resolved_profile is None:
        return False
    return model_has_credentials(resolved_profile)


def compose_agent_system_instruction(
    agent_key: str,
    base_instruction: str,
    *,
    model_profile: ModelProfile | None = None,
    user_designation: str = "",
) -> str:
    """Compose identity, behavior, and optional user-addressing instructions."""
    if agent_key != "apex":
        raise ValueError(f"Unknown Agent key: {agent_key!r}")
    identity = AGENT_SPECS["apex"].identity_instruction
    if model_profile is not None:
        identity = (
            f"{identity} You are currently powered by {model_profile.display_name}."
        )
    normalized_base = base_instruction.strip()
    normalized_designation = " ".join(user_designation.split())[:80]
    designation_instruction = (
        f'Address the user as "{normalized_designation}" when natural.'
        if normalized_designation
        else ""
    )
    body = "\n\n".join(
        part for part in (normalized_base, designation_instruction) if part
    )
    return f"{identity}\n\n{body}" if body else identity


def credential_missing_message(
    model_id: str, profile: ModelProfile | None = None
) -> str:
    if profile is None:
        profile = get_model_profile(model_id)
    if profile is None:
        raise ValueError(f"Unknown model {model_id!r}")
    env_key = profile.credential_env or "API_KEY"
    provider_label = _PROVIDER_DISPLAY_NAMES[profile.provider]
    return (
        f"APEX is currently unavailable because the {provider_label} "
        f"API key is not configured. Please set {env_key} in your "
        "environment and restart the API server."
    )


def credential_missing_error(
    model_id: str, profile: ModelProfile | None = None
) -> str:
    if profile is None:
        profile = get_model_profile(model_id)
    if profile is None:
        raise ValueError(f"Unknown model {model_id!r}")
    return f"{profile.credential_env} is missing from environment variables."


def resolve_selected_model_profile() -> ModelProfile:
    """Return the authoritative selected model profile."""
    from core.settings import get_settings_store

    settings = get_settings_store().get_snapshot().ask_apex
    model_id = settings.selected_model
    profile = get_model_profile(model_id)
    if profile is None:
        raise ValueError(f"Unknown selected model {model_id!r}")
    return profile


def resolve_cloud_provider() -> CloudProvider:
    profile = resolve_selected_model_profile()
    return profile.provider  # type: ignore[return-value]


def resolve_local_runtime() -> LocalRuntime:
    profile = resolve_selected_model_profile()
    return profile.provider  # type: ignore[return-value]



def build_concrete_agent(
    agent_key: str = "apex",
    *,
    native_effort: NativeEffort | None,
    local_context_window: int | None = None,
    local_reasoning_mode: LocalReasoningMode | None = None,
    google_search_enabled: bool = True,
    google_maps_enabled: bool = True,
    model_id: str | None = None,
) -> AgentModelProfile:
    """Materialize a provider-specific model configuration for an Agent."""
    if agent_key != "apex":
        raise ValueError(f"Unknown Agent key: {agent_key!r}")
    spec = AGENT_SPECS["apex"]
    if model_id is None:
        model_profile = resolve_selected_model_profile()
    else:
        resolved = get_model_profile(model_id)
        if resolved is None:
            raise ValueError(f"Unknown model {model_id!r}")
        model_profile = resolved

    system_instruction = compose_agent_system_instruction(
        "apex",
        AGENT_SYSTEM_PROMPT if model_profile.runtime == "cloud" else LOCAL_AGENT_SYSTEM_PROMPT,
        model_profile=model_profile,
    )

    if model_profile.provider == "gemini":
        thinking: GeminiThinkingLevel = (
            native_effort
            or model_profile.default_reasoning
            or "medium"  # type: ignore[assignment]
        )
        return GeminiModelProfile(
            display_name=spec.display_name,
            api_model=model_profile.model_id,
            stability=model_profile.stability,
            thinking_level=thinking,
            max_tool_turns=model_profile.max_tool_turns,
            max_tool_calls=model_profile.max_tool_calls,
            system_instruction=system_instruction,
            hosted_tools=hosted_tools_for_model(
                model_profile,
                google_search_enabled=google_search_enabled,
                google_maps_enabled=google_maps_enabled,
            ),
        )
    if model_profile.provider == "ollama":
        runtime = OLLAMA_RUNTIME_CONFIGS[model_profile.model_id]
        resolved_reasoning_mode = _resolve_local_reasoning_mode(
            model_profile.model_id, local_reasoning_mode
        )
        return OllamaModelProfile(
            display_name=spec.display_name,
            api_model=model_profile.model_id,
            stability=model_profile.stability,
            default_temperature=runtime.default_temperature,
            max_tool_turns=model_profile.max_tool_turns,
            max_tool_calls=model_profile.max_tool_calls,
            context_window=runtime.context_window,
            tool_select_max_tokens=runtime.tool_select_max_tokens,
            final_answer_max_tokens=runtime.final_answer_max_tokens,
            num_thread=runtime.num_thread,
            generation_timeout=runtime.generation_timeout,
            think=runtime.think,
            supported_reasoning_modes=runtime.supported_reasoning_modes,
            default_reasoning_mode=runtime.default_reasoning_mode,
            reasoning_mode=resolved_reasoning_mode,
            ram_limit=runtime.ram_limit,
            cpu_limit=runtime.cpu_limit,
            high_resource=model_profile.model_id in OLLAMA_HIGH_RESOURCE_MODELS,
            system_instruction=system_instruction,
        )
    if model_profile.provider == "llama_cpp":
        resolved_reasoning_mode = _resolve_local_reasoning_mode(
            model_profile.model_id, local_reasoning_mode
        )
        return build_llama_cpp_profile(
            model_profile.model_id,
            display_name=spec.display_name,
            api_model=model_profile.model_id,
            stability=model_profile.stability,
            max_tool_turns=model_profile.max_tool_turns,
            max_tool_calls=model_profile.max_tool_calls,
            system_instruction=system_instruction,
            context_window=local_context_window,
            reasoning_mode=resolved_reasoning_mode,
        )
    if model_profile.provider == "openrouter":
        effective_effort = (
            native_effort
            if native_effort is not None
            else model_profile.default_reasoning
        )
        return OpenRouterModelProfile(
            display_name=spec.display_name,
            api_model=model_profile.model_id,
            max_tool_turns=model_profile.max_tool_turns,
            max_tool_calls=model_profile.max_tool_calls,
            system_instruction=system_instruction,
            reasoning_effort=effective_effort,
        )
    effective_effort = (
        native_effort
        if native_effort is not None
        else (
            model_profile.default_reasoning
            if model_profile.reasoning_options
            else None
        )
    )
    return ResponsesModelProfile(
        provider=model_profile.provider,  # type: ignore[arg-type]
        display_name=spec.display_name,
        api_model=model_profile.model_id,
        max_tool_turns=model_profile.max_tool_turns,
        max_tool_calls=model_profile.max_tool_calls,
        system_instruction=system_instruction,
        reasoning_effort=effective_effort,
        hosted_tools=hosted_tools_for_model(
            model_profile,
            google_search_enabled=google_search_enabled,
            google_maps_enabled=google_maps_enabled,
        ),
        supports_encrypted_reasoning=model_profile.supports_encrypted_reasoning,
    )


def build_agent_used_metadata(
    agent_key: str,
    *,
    provider: InferenceProvider,
    configured_model: str,
    resolved_model: str | None,
    requested_effort: NativeEffort | None,
    resolved_effort: NativeEffort | None,
    runtime: AgentRuntime,
    model_stability: str | None = None,
    hosted_tools: frozenset[str] | None = None,
) -> dict[str, Any]:
    if agent_key not in AGENT_SPECS:
        raise ValueError(f"Unknown Agent key: {agent_key!r}")
    metadata: dict[str, Any] = {
        "key": agent_key,
        "provider": provider,
        "configured_model": configured_model,
        "resolved_model": resolved_model or configured_model,
        "requested_effort": requested_effort,
        "resolved_effort": resolved_effort,
        "runtime": runtime,
    }
    if model_stability is not None:
        metadata["model_stability"] = model_stability
    if hosted_tools is not None:
        metadata["hosted_tools"] = sorted(hosted_tools)
    return metadata


def is_sandbox_query(*, sandbox_mode: bool, dev_mode: bool | None = None) -> bool:
    from core.agent.sandbox_policy import is_sandbox_active

    dev_active = is_dev_mode() if dev_mode is None else dev_mode
    return is_sandbox_active(sandbox_mode=sandbox_mode, dev_mode=dev_active)


def local_context_window_for_model(model_id: str) -> int | None:
    profile = get_model_profile(model_id)
    if profile is None or profile.provider != "llama_cpp":
        return None
    from core.settings import get_settings_store
    return get_settings_store().get_snapshot().ask_apex.local.context_window


def local_agent_keys() -> tuple[str, ...]:
    return ("apex",) if resolve_selected_model_profile().runtime == "local" else ()


def cloud_agent_keys() -> tuple[str, ...]:
    return ("apex",) if resolve_selected_model_profile().runtime == "cloud" else ()


def local_reasoning_modes_for_model(model_id: str) -> tuple[LocalReasoningMode, ...]:
    profile = get_model_profile(model_id)
    if profile is None:
        return ()
    if profile.provider == "llama_cpp":
        runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(model_id)
    elif profile.provider == "ollama":
        runtime = OLLAMA_RUNTIME_CONFIGS.get(model_id)
    else:
        return ()
    if runtime is None:
        return ()
    return runtime.supported_reasoning_modes


def local_reasoning_mode_for_model(model_id: str) -> LocalReasoningMode | None:
    supported = local_reasoning_modes_for_model(model_id)
    if not supported:
        return None
    from core.settings import get_settings_store

    value = get_settings_store().get_snapshot().ask_apex.local.reasoning_mode
    if value in supported:
        return value
    if "none" in supported:
        return "none"
    return supported[0]


def _resolve_local_reasoning_mode(
    model_id: str,
    requested: LocalReasoningMode | None,
) -> LocalReasoningMode:
    supported = local_reasoning_modes_for_model(model_id)
    if requested in supported:
        return requested  # type: ignore[return-value]
    from core.settings import get_settings_store

    settings = get_settings_store().get_snapshot().ask_apex
    if settings.local.last_model == model_id and settings.local.reasoning_mode in supported:
        return settings.local.reasoning_mode
    if "none" in supported:
        return "none"
    return supported[0] if supported else "none"


def local_model_ref_for_model(
    model_id: str,
    *,
    local_context_window: int | None = None,
) -> LocalModelRef:
    profile = build_concrete_agent(
        "apex",
        native_effort=None,
        local_context_window=local_context_window,
        model_id=model_id,
    )
    runtime_model_id = getattr(profile, "runtime_model_id", None)
    if not isinstance(runtime_model_id, str) or not runtime_model_id:
        raise ValueError(
            f"Model {model_id!r} concrete profile is missing runtime_model_id"
        )
    return LocalModelRef(
        provider=profile.provider,  # type: ignore[arg-type]
        model=runtime_model_id,
    )


def local_model_refs_for_model(model_id: str) -> frozenset[LocalModelRef]:
    profile = get_model_profile(model_id)
    if profile is None or profile.runtime != "local":
        return frozenset()
    if profile.provider == "llama_cpp":
        runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(model_id)
        if runtime is None:
            return frozenset()
        aliases = set(runtime.runtime_model_ids.values())
        return frozenset(
            LocalModelRef(provider="llama_cpp", model=alias) for alias in aliases
        )
    return frozenset(
        {LocalModelRef(provider=profile.provider, model=model_id)}  # type: ignore[arg-type]
    )


def model_id_for_local_model_ref(ref: LocalModelRef) -> str | None:
    if ref.provider == "llama_cpp":
        if model_id_for_llama_cpp_alias(ref.model) is not None:
            return model_id_for_llama_cpp_alias(ref.model)
    for model_id, profile in LOCAL_MODEL_PROFILES.items():
        if profile.provider != ref.provider:
            continue
        if ref in local_model_refs_for_model(model_id):
            return model_id
    return None


def known_local_model_refs() -> frozenset[LocalModelRef]:
    refs: set[LocalModelRef] = set()
    for model_id in LOCAL_MODEL_PROFILES:
        refs.update(local_model_refs_for_model(model_id))
    return frozenset(refs)


def resolve_model_selection(
    agent_settings: Any,
) -> tuple[AgentRuntime, str, NativeEffort | None]:
    """Resolve effective runtime, model, and saved cloud effort."""
    model_id = getattr(agent_settings, "selected_model", DEFAULT_APEX_MODEL)
    profile = get_model_profile(model_id) or get_model_profile(DEFAULT_APEX_MODEL)
    assert profile is not None
    return profile.runtime, profile.model_id, (getattr(agent_settings.cloud, "effort", "low") if profile.runtime == "cloud" else None)


def default_cloud_settings() -> dict[str, Any]:
    return {
        "last_model": DEFAULT_APEX_MODEL,
        "effort": "low",
        "hosted_tools": {
            "google_search": True,
            "google_maps": True,
        },
    }


def default_local_settings() -> dict[str, Any]:
    return {
        "last_model": DEFAULT_LOCAL_MODEL,
        "context_window": llama_cpp_runtime_config(DEFAULT_LOCAL_MODEL).default_context_window,
        "reasoning_mode": "none",
    }


# Transitional internal adapters keep provider modules importable while their
# callers move to model-based routing. They are not accepted as public Agent
# identities or API inputs.
def agent_has_credentials(agent_key: str, profile: ModelProfile | None = None) -> bool:
    return model_has_available_credentials(
        profile.model_id if profile is not None else resolve_selected_model_profile().model_id,
        profile,
    )


def resolve_effort_for_agent(agent_key: str, requested: str | None) -> str | None:
    return resolve_effort_for_model(resolve_selected_model_profile().model_id, requested)


def is_local_agent_key(agent_key: str) -> bool:
    return agent_key == "apex" and resolve_selected_model_profile().runtime == "local"


def is_cloud_agent_key(agent_key: str) -> bool:
    return agent_key == "apex" and resolve_selected_model_profile().runtime == "cloud"


def local_context_window_for_agent(agent_key: str) -> int | None:
    return local_context_window_for_model(resolve_selected_model_profile().model_id)


def local_reasoning_modes_for_agent(agent_key: str) -> tuple[LocalReasoningMode, ...]:
    return local_reasoning_modes_for_model(resolve_selected_model_profile().model_id)


def local_reasoning_mode_for_agent(agent_key: str) -> LocalReasoningMode | None:
    return local_reasoning_mode_for_model(resolve_selected_model_profile().model_id)


def local_model_ref_for_agent(agent_key: str, *, local_context_window: int | None = None) -> LocalModelRef:
    return local_model_ref_for_model(resolve_selected_model_profile().model_id, local_context_window=local_context_window)


def local_model_refs_for_agent(agent_key: str) -> frozenset[LocalModelRef]:
    return local_model_refs_for_model(resolve_selected_model_profile().model_id)


def agent_key_for_local_model_ref(ref: LocalModelRef) -> str | None:
    return "apex" if model_id_for_local_model_ref(ref) is not None else None


def resolve_agent_selection(agent_settings: Any) -> tuple[AgentRuntime, str, NativeEffort | None]:
    return resolve_model_selection(agent_settings)
