"""Apex Agent catalog, effort resolution, and provider model factories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from core.agent.providers.contract import InferenceProvider, is_local_inference_provider
from core.agent.local_runtime.contract import LocalModelRef
from core.agent.providers.gemini_models import GeminiModelProfile, GeminiThinkingLevel
from core.agent.providers.llama_cpp_models import (
    LLAMA_CPP_RUNTIME_CONFIGS,
    LlamaCppModelProfile,
    build_llama_cpp_profile,
)
from core.agent.providers.ollama_models import (
    OLLAMA_HIGH_RESOURCE_AGENTS,
    OLLAMA_RUNTIME_CONFIGS,
    OllamaModelProfile,
)
from core.agent.providers.responses_api import ResponsesModelProfile
from core.agent.tool_policies import hosted_tools_for_agent
from core.agent.types import LocalReasoningMode
from core.config import (
    AGENT_SYSTEM_PROMPT,
    GEMINI_AGENT_MAX_TOOL_CALLS,
    GEMINI_AGENT_MAX_TURNS,
    LOCAL_AGENT_SYSTEM_PROMPT,
    MUS_CPU_LIMIT,
    MUS_RAM_LIMIT,
    SOREX_CPU_LIMIT,
    SOREX_RAM_LIMIT,
    is_dev_mode,
)

AgentKey: TypeAlias = Literal[
    "acinonyx",
    "panthera",
    "neofelis",
    "delphinus",
    "orcinus",
    "sorex",
    "mus",
    "apodemus",
    "neotoma",
    "unnamed-experimental-agent",
]
CloudAgentKey: TypeAlias = Literal[
    "acinonyx", "panthera", "neofelis", "delphinus", "orcinus"
]
CloudSettingsAgentKey: TypeAlias = Literal[
    "panthera", "neofelis", "delphinus", "orcinus"
]
LocalAgentKey: TypeAlias = Literal[
    "sorex",
    "mus",
    "apodemus",
    "neotoma",
    "unnamed-experimental-agent",
]
AgentRuntime: TypeAlias = Literal["cloud", "local"]
ApexEffort: TypeAlias = Literal["light", "focused", "extended"]
NativeEffort: TypeAlias = Literal["low", "medium", "high"]

VALID_AGENT_KEYS: frozenset[str] = frozenset(
    {
        "acinonyx",
        "panthera",
        "neofelis",
        "delphinus",
        "orcinus",
        "sorex",
        "mus",
        "apodemus",
        "neotoma",
        "unnamed-experimental-agent",
    }
)
VALID_CLOUD_SETTINGS_AGENTS: frozenset[str] = frozenset(
    {"panthera", "neofelis", "delphinus", "orcinus"}
)
VALID_LOCAL_SETTINGS_AGENTS: frozenset[str] = frozenset(
    {"sorex", "mus", "apodemus", "neotoma", "unnamed-experimental-agent"}
)
VALID_APEX_EFFORTS: frozenset[str] = frozenset({"light", "focused", "extended"})
VALID_NATIVE_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high"})

_PROVIDER_DISPLAY_NAMES: dict[InferenceProvider, str] = {
    "gemini": "Google",
    "ollama": "Ollama",
    "llama_cpp": "llama.cpp",
    "openai": "OpenAI",
    "xai": "SpaceXAI",
}

_SCHEMA5_CLOUD_PROFILES: frozenset[str] = frozenset({"comet", "nova", "pulsar"})
_SCHEMA5_LOCAL_PROFILES: frozenset[str] = frozenset({"lynx", "acinonyx", "neofelis"})
_SCHEMA5_ALL_PROFILES: frozenset[str] = _SCHEMA5_CLOUD_PROFILES | _SCHEMA5_LOCAL_PROFILES

_APEX_TO_NATIVE_EFFORT: dict[str, NativeEffort] = {
    "light": "low",
    "focused": "medium",
    "extended": "high",
}

AgentModelProfile = (
    GeminiModelProfile
    | OllamaModelProfile
    | LlamaCppModelProfile
    | ResponsesModelProfile
)


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Static metadata for one Apex Agent."""

    key: AgentKey
    display_name: str
    description: str
    identity_instruction: str
    agent_version: str
    provider: InferenceProvider
    runtime: AgentRuntime
    api_model: str
    default_effort: ApexEffort | None
    credential_env: str | None
    max_tool_turns: int
    max_tool_calls: int
    tier: str
    stability: Literal["stable", "preview", "experimental"]
    capability_tags: tuple[str, ...]
    dev_only: bool = False
    supports_effort: bool = True
    supports_encrypted_reasoning: bool = True


AGENT_SPECS: dict[str, AgentSpec] = {
    "acinonyx": AgentSpec(
        key="acinonyx",
        display_name="Apex Acinonyx",
        description="Development-only privacy sandbox for testing Apex with masked personal context.",
        identity_instruction=(
            "You are Apex Acinonyx, an Apex Agent powered by "
            "Gemini 3.5 Flash Lite. You are the development-only privacy sandbox."
        ),
        agent_version="1.0",
        provider="gemini",
        runtime="cloud",
        api_model="gemini-3.5-flash-lite",
        default_effort="focused",
        credential_env="GEMINI_SANDBOX_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="fast",
        stability="experimental",
        capability_tags=("Privacy sandbox", "Masked context"),
        dev_only=True,
    ),
    "panthera": AgentSpec(
        key="panthera",
        display_name="Apex Panthera",
        description="Default generalist for thoughtful answers, planning, and complex everyday work.",
        identity_instruction=(
            "You are Apex Panthera, an Apex Agent powered by "
            "GPT-5.6 Luna."
        ),
        agent_version="1.0",
        provider="openai",
        runtime="cloud",
        api_model="gpt-5.6-luna",
        default_effort="focused",
        credential_env="OPENAI_API_KEY",
        max_tool_turns=min(6, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(10, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="balanced",
        stability="stable",
        capability_tags=("Generalist", "Planning"),
    ),
    "neofelis": AgentSpec(
        key="neofelis",
        display_name="Apex Neofelis",
        description="Fast research specialist with optional Google Search and Maps grounding.",
        identity_instruction=(
            "You are Apex Neofelis, an Apex Agent powered by "
            "Gemini 3.6 Flash."
        ),
        agent_version="1.0",
        provider="gemini",
        runtime="cloud",
        api_model="gemini-3.6-flash",
        default_effort="focused",
        credential_env="GEMINI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="advanced",
        stability="stable",
        capability_tags=("Research", "Google Search", "Google Maps"),
        dev_only=True,
    ),
    "delphinus": AgentSpec(
        key="delphinus",
        display_name="Apex Delphinus",
        description="Balanced live-information Agent with optional X Search for current conversations and trends.",
        identity_instruction=(
            "You are Apex Delphinus, an Apex Agent powered by Grok 4.3."
        ),
        agent_version="1.0",
        provider="xai",
        runtime="cloud",
        api_model="grok-4.3",
        default_effort="focused",
        credential_env="XAI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="balanced",
        stability="stable",
        capability_tags=("Balanced", "X Search"),
        dev_only=True,
        supports_encrypted_reasoning=False,
    ),
    "orcinus": AgentSpec(
        key="orcinus",
        display_name="Apex Orcinus",
        description="Deep-reasoning Agent for difficult analysis, synthesis, and extended investigations.",
        identity_instruction=(
            "You are Apex Orcinus, an Apex Agent powered by Grok 4.5."
        ),
        agent_version="1.0",
        provider="xai",
        runtime="cloud",
        api_model="grok-4.5",
        default_effort="extended",
        credential_env="XAI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="advanced",
        stability="stable",
        capability_tags=("Deep reasoning", "Extended analysis", "X Search"),
        dev_only=True,
    ),
    "sorex": AgentSpec(
        key="sorex",
        display_name="Apex Sorex",
        description="Lightweight local development Agent for evaluating constrained-system workflows.",
        identity_instruction=(
            "You are Apex Sorex, an Apex Agent powered by "
            "Qwen3 1.7B through Ollama."
        ),
        agent_version="1.0",
        provider="ollama",
        runtime="local",
        api_model="qwen3:1.7b",
        default_effort=None,
        credential_env=None,
        max_tool_turns=2,
        max_tool_calls=3,
        tier="lightweight",
        stability="stable",
        capability_tags=("Lightweight", "Development", "Constrained local"),
        dev_only=True,
        supports_effort=False,
    ),
    "mus": AgentSpec(
        key="mus",
        display_name="Apex Mus",
        description="Local development generalist for evaluating capable offline work without cloud processing.",
        identity_instruction=(
            "You are Apex Mus, an Apex Agent powered by "
            "Qwen3 4B Instruct through Ollama."
        ),
        agent_version="1.0",
        provider="ollama",
        runtime="local",
        api_model="qwen3:4b-instruct",
        default_effort=None,
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        tier="balanced",
        stability="stable",
        capability_tags=("Larger model", "Development local"),
        dev_only=True,
        supports_effort=False,
    ),
    "apodemus": AgentSpec(
        key="apodemus",
        display_name="Apex Apodemus",
        description=(
            "Stable private local Agent for efficient tool-driven work through llama.cpp."
        ),
        identity_instruction=(
            "You are Apex Apodemus, an Apex Agent powered by "
            "Gemma 4 E2B through llama.cpp."
        ),
        agent_version="1.0",
        provider="llama_cpp",
        runtime="local",
        api_model="gemma-4-E2B-Q4_K_M.gguf",
        default_effort=None,
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        tier="balanced",
        stability="stable",
        capability_tags=("Efficient local", "Selectable context"),
        supports_effort=False,
    ),
    "neotoma": AgentSpec(
        key="neotoma",
        display_name="Apex Neotoma",
        description=(
            "Preview private local Agent for Gemma 4 E4B work through llama.cpp."
        ),
        identity_instruction=(
            "You are Apex Neotoma, an Apex Agent powered by "
            "Gemma 4 E4B through llama.cpp."
        ),
        agent_version="1.0",
        provider="llama_cpp",
        runtime="local",
        api_model="gemma-4-E4B-Q4_K_M.gguf",
        default_effort=None,
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        tier="balanced",
        stability="preview",
        capability_tags=("Generalist local", "Selectable context"),
        dev_only=False,
        supports_effort=False,
    ),
    "unnamed-experimental-agent": AgentSpec(
        key="unnamed-experimental-agent",
        display_name="Unnamed Experimental Agent",
        description=(
            "Development-only technical target for evaluating candidate local "
            "models through llama.cpp."
        ),
        identity_instruction=(
            "You are Unnamed Experimental Agent, a technical APEX development "
            "target powered by Qwen3.5 4B through llama.cpp."
        ),
        agent_version="1.0",
        provider="llama_cpp",
        runtime="local",
        api_model="Qwen3.5-4B-Q4_K_M.gguf",
        default_effort=None,
        credential_env=None,
        max_tool_turns=4,
        max_tool_calls=4,
        tier="balanced",
        stability="experimental",
        capability_tags=("Experimental local", "Selectable context"),
        dev_only=True,
        supports_effort=False,
    ),
}

_RUNTIME_PROFILE_ORDER: tuple[str, ...] = (
    "acinonyx",
    "panthera",
    "neofelis",
    "delphinus",
    "orcinus",
    "mus",
    "apodemus",
    "neotoma",
    "unnamed-experimental-agent",
    "sorex",
)


def runtime_agent_order(*, dev_mode: bool | None = None) -> tuple[str, ...]:
    """Return HUD-visible Agent keys in display order."""
    dev_active = is_dev_mode() if dev_mode is None else dev_mode
    return tuple(
        key
        for key in _RUNTIME_PROFILE_ORDER
        if not AGENT_SPECS[key].dev_only or dev_active
    )


def is_agent_visible(key: str, *, dev_mode: bool | None = None) -> bool:
    if key not in AGENT_SPECS:
        return False
    spec = AGENT_SPECS[key]
    if not spec.dev_only:
        return True
    dev_active = is_dev_mode() if dev_mode is None else dev_mode
    return dev_active


def apex_effort_to_native(effort: ApexEffort) -> NativeEffort:
    return _APEX_TO_NATIVE_EFFORT[effort]


def resolve_effort(
    agent_key: str,
    requested: ApexEffort | None,
) -> tuple[ApexEffort | None, NativeEffort | None]:
    """Resolve APEX and provider-native effort for an Agent."""
    spec = AGENT_SPECS[agent_key]
    if not spec.supports_effort:
        return None, None
    apex_effort = requested or spec.default_effort
    if apex_effort is None:
        return None, None
    return apex_effort, apex_effort_to_native(apex_effort)


def agent_has_credentials(agent_key: str) -> bool:
    spec = AGENT_SPECS[agent_key]
    if spec.credential_env is None:
        return True
    return bool(os.getenv(spec.credential_env))


def compose_agent_system_instruction(
    agent_key: str,
    base_instruction: str,
    *,
    user_designation: str = "",
) -> str:
    """Compose identity, behavior, and optional user-addressing instructions."""
    identity = AGENT_SPECS[agent_key].identity_instruction
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


def credential_missing_message(agent_key: str) -> str:
    spec = AGENT_SPECS[agent_key]
    env_key = spec.credential_env or "API_KEY"
    provider_label = _PROVIDER_DISPLAY_NAMES[spec.provider]
    return (
        f"APEX is currently unavailable because the {provider_label} "
        f"API key is not configured. Please set {env_key} in your "
        "environment and restart the API server."
    )


def credential_missing_error(agent_key: str) -> str:
    spec = AGENT_SPECS[agent_key]
    return f"{spec.credential_env} is missing from environment variables."


def build_concrete_agent(
    agent_key: str,
    *,
    native_effort: NativeEffort | None,
    local_context_window: int | None = None,
    local_reasoning_mode: LocalReasoningMode | None = None,
    neofelis_google_search_enabled: bool = True,
    neofelis_google_maps_enabled: bool = True,
    delphinus_x_search_enabled: bool = True,
    orcinus_x_search_enabled: bool = True,
) -> AgentModelProfile:
    """Materialize a provider-specific model configuration for an Agent."""
    spec = AGENT_SPECS[agent_key]
    if spec.provider == "gemini":
        thinking: GeminiThinkingLevel = native_effort or "medium"
        return GeminiModelProfile(
            display_name=spec.display_name,
            agent_version=spec.agent_version,
            api_model=spec.api_model,
            tier=spec.tier,  # type: ignore[arg-type]
            stability=spec.stability,
            thinking_level=thinking,
            max_tool_turns=spec.max_tool_turns,
            max_tool_calls=spec.max_tool_calls,
            system_instruction=compose_agent_system_instruction(
                agent_key, AGENT_SYSTEM_PROMPT
            ),
            hosted_tools=hosted_tools_for_agent(
                agent_key,
                neofelis_google_search_enabled=neofelis_google_search_enabled,
                neofelis_google_maps_enabled=neofelis_google_maps_enabled,
                delphinus_x_search_enabled=delphinus_x_search_enabled,
                orcinus_x_search_enabled=orcinus_x_search_enabled,
            ),
        )
    if spec.provider == "ollama":
        runtime = OLLAMA_RUNTIME_CONFIGS[agent_key]
        resolved_reasoning_mode = _resolve_local_reasoning_mode(
            agent_key, local_reasoning_mode
        )
        return OllamaModelProfile(
            display_name=spec.display_name,
            agent_version=spec.agent_version,
            api_model=spec.api_model,
            tier=spec.tier,  # type: ignore[arg-type]
            stability=spec.stability,
            default_temperature=runtime.default_temperature,
            max_tool_turns=spec.max_tool_turns,
            max_tool_calls=spec.max_tool_calls,
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
            high_resource=agent_key in OLLAMA_HIGH_RESOURCE_AGENTS,
            system_instruction=compose_agent_system_instruction(
                agent_key, runtime.system_instruction
            ),
        )
    if spec.provider == "llama_cpp":
        resolved_reasoning_mode = _resolve_local_reasoning_mode(
            agent_key, local_reasoning_mode
        )
        return build_llama_cpp_profile(
            agent_key,
            display_name=spec.display_name,
            agent_version=spec.agent_version,
            api_model=spec.api_model,
            tier=spec.tier,  # type: ignore[arg-type]
            stability=spec.stability,
            max_tool_turns=spec.max_tool_turns,
            max_tool_calls=spec.max_tool_calls,
            system_instruction=compose_agent_system_instruction(
                agent_key, LOCAL_AGENT_SYSTEM_PROMPT
            ),
            context_window=local_context_window,
            reasoning_mode=resolved_reasoning_mode,
        )
    return ResponsesModelProfile(
        provider=spec.provider,  # type: ignore[arg-type]
        display_name=spec.display_name,
        agent_version=spec.agent_version,
        api_model=spec.api_model,
        max_tool_turns=spec.max_tool_turns,
        max_tool_calls=spec.max_tool_calls,
        system_instruction=compose_agent_system_instruction(
            agent_key, AGENT_SYSTEM_PROMPT
        ),
        reasoning_effort=native_effort,
        hosted_tools=hosted_tools_for_agent(
            agent_key,
            neofelis_google_search_enabled=neofelis_google_search_enabled,
            neofelis_google_maps_enabled=neofelis_google_maps_enabled,
            delphinus_x_search_enabled=delphinus_x_search_enabled,
            orcinus_x_search_enabled=orcinus_x_search_enabled,
        ),
        supports_encrypted_reasoning=spec.supports_encrypted_reasoning,
    )


def build_agent_used_metadata(
    agent_key: str,
    *,
    configured_model: str,
    resolved_model: str | None,
    requested_effort: ApexEffort | None,
    resolved_apex_effort: ApexEffort | None,
    resolved_native_effort: NativeEffort | None,
) -> dict[str, Any]:
    spec = AGENT_SPECS[agent_key]
    return {
        "key": agent_key,
        "version": spec.agent_version,
        "provider": spec.provider,
        "configured_model": configured_model,
        "resolved_model": resolved_model or configured_model,
        "requested_effort": requested_effort,
        "resolved_effort": resolved_native_effort,
        "resolved_apex_effort": resolved_apex_effort,
        "runtime": spec.runtime,
    }


def is_acinonyx_agent(agent_key: str) -> bool:
    return agent_key == "acinonyx"


def local_agent_keys(*, dev_mode: bool | None = None) -> tuple[str, ...]:
    """Return visible Agent keys whose runtime is local, in HUD order."""
    return tuple(
        key
        for key in runtime_agent_order(dev_mode=dev_mode)
        if AGENT_SPECS[key].runtime == "local"
    )


def cloud_agent_keys(*, dev_mode: bool | None = None) -> tuple[str, ...]:
    """Return visible Agent keys whose runtime is cloud, in HUD order."""
    return tuple(
        key
        for key in runtime_agent_order(dev_mode=dev_mode)
        if AGENT_SPECS[key].runtime == "cloud"
    )


def is_local_agent_key(agent_key: str) -> bool:
    """Return whether ``agent_key`` is a catalogued local Agent."""
    spec = AGENT_SPECS.get(agent_key)
    return spec is not None and spec.runtime == "local"


def local_context_window_for_agent(agent_key: str) -> int | None:
    """Return the persisted selectable context for a local Agent, if present."""
    if not is_local_agent_key(agent_key):
        return None
    from core.settings import get_settings_store

    value = get_settings_store().get_snapshot().ask_apex.local_context_windows.get(
        agent_key
    )
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def local_reasoning_modes_for_agent(
    agent_key: str,
) -> tuple[LocalReasoningMode, ...]:
    """Return provider-declared reasoning modes for a local Agent."""
    spec = AGENT_SPECS.get(agent_key)
    if spec is None or spec.runtime != "local":
        return ()
    if spec.provider == "llama_cpp":
        runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(agent_key)
    elif spec.provider == "ollama":
        runtime = OLLAMA_RUNTIME_CONFIGS.get(agent_key)
    else:
        return ()
    if runtime is None:
        return ()
    return runtime.supported_reasoning_modes


def local_reasoning_mode_for_agent(agent_key: str) -> LocalReasoningMode | None:
    """Return the persisted reasoning mode, safely resolved to capabilities."""
    supported = local_reasoning_modes_for_agent(agent_key)
    if not supported:
        return None
    from core.settings import get_settings_store

    value = get_settings_store().get_snapshot().ask_apex.local_reasoning_modes.get(
        agent_key
    )
    if value in supported:
        return value
    if "none" in supported:
        return "none"
    return supported[0]


def _resolve_local_reasoning_mode(
    agent_key: str,
    requested: LocalReasoningMode | None,
) -> LocalReasoningMode:
    """Resolve an explicit or persisted mode against provider capabilities."""
    supported = local_reasoning_modes_for_agent(agent_key)
    if requested in supported:
        return requested  # type: ignore[return-value]
    persisted = local_reasoning_mode_for_agent(agent_key)
    if persisted is not None:
        return persisted
    return "none"


def is_cloud_agent_key(agent_key: str) -> bool:
    """Return whether ``agent_key`` is a catalogued cloud Agent."""
    spec = AGENT_SPECS.get(agent_key)
    return spec is not None and spec.runtime == "cloud"


def local_model_ref_for_agent(
    agent_key: str,
    *,
    local_context_window: int | None = None,
) -> LocalModelRef:
    """Return the currently selected runtime reference for a local Agent."""
    spec = AGENT_SPECS[agent_key]
    if spec.runtime != "local":
        raise ValueError(f"Agent {agent_key!r} is not a local Agent")
    if not is_local_inference_provider(spec.provider):
        raise ValueError(
            f"Agent {agent_key!r} uses unsupported local provider {spec.provider!r}"
        )
    profile = build_concrete_agent(
        agent_key,
        native_effort=None,
        local_context_window=local_context_window,
    )
    runtime_model_id = getattr(profile, "runtime_model_id", None)
    if not isinstance(runtime_model_id, str) or not runtime_model_id:
        raise ValueError(
            f"Agent {agent_key!r} concrete profile is missing runtime_model_id"
        )
    return LocalModelRef(
        provider=profile.provider,  # type: ignore[arg-type]
        model=runtime_model_id,
    )


def local_model_refs_for_agent(agent_key: str) -> frozenset[LocalModelRef]:
    """Return every recognized runtime reference belonging to a local Agent."""
    spec = AGENT_SPECS[agent_key]
    if spec.runtime != "local":
        return frozenset()
    if spec.provider == "llama_cpp":
        runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(agent_key)
        if runtime is None:
            return frozenset()
        return frozenset(
            LocalModelRef(provider="llama_cpp", model=alias)
            for alias in runtime.runtime_model_ids.values()
        )
    return frozenset({local_model_ref_for_agent(agent_key)})


def agent_key_for_local_model_ref(ref: LocalModelRef) -> str | None:
    """Return the Agent key for any recognized local runtime alias, if configured."""
    for key, spec in AGENT_SPECS.items():
        if spec.runtime != "local":
            continue
        if not is_local_inference_provider(spec.provider):
            continue
        if ref in local_model_refs_for_agent(key):
            return key
    return None


def known_local_model_refs() -> frozenset[LocalModelRef]:
    """Return every configured APEX local runtime model reference."""
    refs: set[LocalModelRef] = set()
    for key, spec in AGENT_SPECS.items():
        if spec.runtime != "local":
            continue
        refs.update(local_model_refs_for_agent(key))
    return frozenset(refs)


def migrate_schema5_ask_apex(raw: dict[str, Any]) -> dict[str, Any]:
    """One-way schema-5 → 6 migration for ask_apex on-disk shape."""
    if raw.get("mode") in {"cloud", "local"}:
        return raw
    if not ({"default_profile", "default_cloud_profile"} & raw.keys()):
        # Schema-6 local overrides are intentionally partial. Do not synthesize
        # defaults that would replace values from the base configuration layer.
        return raw

    migrated: dict[str, Any] = {
        "enabled": raw.get("enabled", True),
        "mode": "cloud",
        "cloud_profile": "panthera",
        "cloud_effort": "focused",
        "local_profile": "apodemus",
        "neofelis_google_search_enabled": bool(
            raw.get("neofelis_google_search_enabled", True)
        ),
    }

    legacy_profile = raw.get("default_profile") or raw.get("default_cloud_profile")
    if isinstance(legacy_profile, str):
        normalized = legacy_profile.strip().lower()
        if normalized in _SCHEMA5_CLOUD_PROFILES:
            migrated["mode"] = "cloud"
            migrated["cloud_profile"] = "panthera"
            migrated["cloud_effort"] = "focused"
            migrated["local_profile"] = "apodemus"
        elif normalized in _SCHEMA5_LOCAL_PROFILES:
            # Plan: every old local selection becomes Local/Apodemus while retaining
            # Panthera/Focused as the saved cloud choice.
            migrated["mode"] = "local"
            migrated["local_profile"] = "apodemus"
            migrated["cloud_profile"] = "panthera"
            migrated["cloud_effort"] = "focused"

    if isinstance(raw.get("enabled"), bool):
        migrated["enabled"] = raw["enabled"]
    if "neofelis_google_search_enabled" in raw and isinstance(
        raw["neofelis_google_search_enabled"], bool
    ):
        migrated["neofelis_google_search_enabled"] = raw[
            "neofelis_google_search_enabled"
        ]

    return migrated


def migrate_schema7_ask_apex(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert schema-7 historical ``ask_apex`` keys to schema-8 shape."""
    legacy = migrate_schema5_ask_apex(raw)
    if "runtime" in legacy:
        return legacy
    key_map = {
        "mode": "runtime",
        "cloud_profile": "cloud_agent",
        "cloud_effort": "effort",
        "local_profile": "local_agent",
    }
    return {key_map.get(key, key): value for key, value in legacy.items()}


def migrate_schema5_briefing(
    raw: dict[str, Any], *, schema5: bool = True
) -> dict[str, Any]:
    """Map every legacy briefing mode to panthera (schema-5 one-way migration)."""
    if not schema5:
        return raw
    return {"default_mode": "panthera"}


def resolve_agent_selection(
    agent_settings: Any,
    *,
    dev_mode: bool | None = None,
) -> tuple[AgentRuntime, str, ApexEffort | None]:
    """Resolve effective runtime, Agent, and effort from Agent settings."""
    dev_active = is_dev_mode() if dev_mode is None else dev_mode
    if dev_active:
        return "cloud", "acinonyx", getattr(agent_settings, "effort", "focused")

    runtime = getattr(agent_settings, "runtime", "cloud")
    if runtime == "local":
        agent = getattr(agent_settings, "local_agent", "apodemus")
        if not dev_active and not is_agent_visible(agent, dev_mode=False):
            agent = "apodemus"
        return "local", agent, None
    agent = getattr(agent_settings, "cloud_agent", "panthera")
    if not dev_active and not is_agent_visible(agent, dev_mode=False):
        agent = "panthera"
    effort = getattr(agent_settings, "effort", "focused")
    return "cloud", agent, effort
