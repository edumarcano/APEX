"""Unified federated profile registry, effort resolution, and profile factories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from core.agent.providers.contract import InferenceProvider
from core.agent.providers.gemini_models import GeminiModelProfile, GeminiThinkingLevel
from core.agent.providers.ollama_models import OllamaModelProfile
from core.agent.providers.responses_api import ResponsesModelProfile
from core.config import (
    DEFAULT_AGENT_SYSTEM_PROMPT,
    DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT,
    GEMINI_AGENT_MAX_TOOL_CALLS,
    GEMINI_AGENT_MAX_TURNS,
    MUS_CPU_LIMIT,
    MUS_RAM_LIMIT,
    SOREX_CPU_LIMIT,
    SOREX_RAM_LIMIT,
    is_dev_mode,
)

ProfileKey: TypeAlias = Literal[
    "acinonyx", "panthera", "neofelis", "delphinus", "orcinus", "sorex", "mus"
]
CloudProfileKey: TypeAlias = Literal[
    "acinonyx", "panthera", "neofelis", "delphinus", "orcinus"
]
CloudSettingsProfileKey: TypeAlias = Literal[
    "panthera", "neofelis", "delphinus", "orcinus"
]
LocalProfileKey: TypeAlias = Literal["sorex", "mus"]
AssistantMode: TypeAlias = Literal["cloud", "local"]
ApexEffort: TypeAlias = Literal["light", "focused", "extended"]
NativeEffort: TypeAlias = Literal["low", "medium", "high"]

VALID_PROFILE_KEYS: frozenset[str] = frozenset(
    {"acinonyx", "panthera", "neofelis", "delphinus", "orcinus", "sorex", "mus"}
)
VALID_CLOUD_SETTINGS_PROFILES: frozenset[str] = frozenset(
    {"panthera", "neofelis", "delphinus", "orcinus"}
)
VALID_LOCAL_SETTINGS_PROFILES: frozenset[str] = frozenset({"sorex", "mus"})
VALID_APEX_EFFORTS: frozenset[str] = frozenset({"light", "focused", "extended"})
VALID_NATIVE_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high"})

_SCHEMA5_CLOUD_PROFILES: frozenset[str] = frozenset({"comet", "nova", "pulsar"})
_SCHEMA5_LOCAL_PROFILES: frozenset[str] = frozenset({"lynx", "acinonyx", "neofelis"})
_SCHEMA5_ALL_PROFILES: frozenset[str] = _SCHEMA5_CLOUD_PROFILES | _SCHEMA5_LOCAL_PROFILES

_APEX_TO_NATIVE_EFFORT: dict[str, NativeEffort] = {
    "light": "low",
    "focused": "medium",
    "extended": "high",
}

AgentModelProfile = (
    GeminiModelProfile | OllamaModelProfile | ResponsesModelProfile
)


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """Static metadata for one federated assistant profile."""

    key: ProfileKey
    display_name: str
    profile_version: str
    provider: InferenceProvider
    mode: AssistantMode
    api_model: str
    default_effort: ApexEffort | None
    credential_env: str | None
    max_tool_turns: int
    max_tool_calls: int
    tier: str
    stability: Literal["stable", "preview"]
    dev_only: bool = False
    supports_effort: bool = True


PROFILE_SPECS: dict[str, ProfileSpec] = {
    "acinonyx": ProfileSpec(
        key="acinonyx",
        display_name="Apex Acinonyx",
        profile_version="2.0",
        provider="gemini",
        mode="cloud",
        api_model="gemini-3.5-flash-lite",
        default_effort="focused",
        credential_env="GEMINI_SANDBOX_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="fast",
        stability="stable",
        dev_only=True,
    ),
    "panthera": ProfileSpec(
        key="panthera",
        display_name="Apex Panthera",
        profile_version="2.0",
        provider="openai",
        mode="cloud",
        api_model="gpt-5.6-luna",
        default_effort="focused",
        credential_env="OPENAI_API_KEY",
        max_tool_turns=min(6, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(10, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="balanced",
        stability="stable",
    ),
    "neofelis": ProfileSpec(
        key="neofelis",
        display_name="Apex Neofelis",
        profile_version="2.0",
        provider="gemini",
        mode="cloud",
        api_model="gemini-3.6-flash",
        default_effort="focused",
        credential_env="GEMINI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="advanced",
        stability="stable",
    ),
    "delphinus": ProfileSpec(
        key="delphinus",
        display_name="Apex Delphinus",
        profile_version="2.0",
        provider="xai",
        mode="cloud",
        api_model="grok-4.3",
        default_effort="focused",
        credential_env="XAI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="balanced",
        stability="stable",
    ),
    "orcinus": ProfileSpec(
        key="orcinus",
        display_name="Apex Orcinus",
        profile_version="2.0",
        provider="xai",
        mode="cloud",
        api_model="grok-4.5",
        default_effort="extended",
        credential_env="XAI_API_KEY",
        max_tool_turns=min(4, GEMINI_AGENT_MAX_TURNS),
        max_tool_calls=min(6, GEMINI_AGENT_MAX_TOOL_CALLS),
        tier="advanced",
        stability="stable",
    ),
    "sorex": ProfileSpec(
        key="sorex",
        display_name="Apex Sorex",
        profile_version="2.0",
        provider="ollama",
        mode="local",
        api_model="qwen3:1.7b",
        default_effort=None,
        credential_env=None,
        max_tool_turns=2,
        max_tool_calls=3,
        tier="lightweight",
        stability="stable",
        supports_effort=False,
    ),
    "mus": ProfileSpec(
        key="mus",
        display_name="Apex Mus",
        profile_version="2.0",
        provider="ollama",
        mode="local",
        api_model="qwen3:4b-instruct",
        default_effort=None,
        credential_env=None,
        max_tool_turns=3,
        max_tool_calls=4,
        tier="balanced",
        stability="stable",
        supports_effort=False,
    ),
}

_RUNTIME_PROFILE_ORDER: tuple[str, ...] = (
    "sorex",
    "mus",
    "panthera",
    "neofelis",
    "delphinus",
    "orcinus",
    "acinonyx",
)


def runtime_profile_order(*, dev_mode: bool | None = None) -> tuple[str, ...]:
    """Return HUD-visible profile keys in display order."""
    dev_active = is_dev_mode() if dev_mode is None else dev_mode
    return tuple(
        key
        for key in _RUNTIME_PROFILE_ORDER
        if not PROFILE_SPECS[key].dev_only or dev_active
    )


def is_profile_visible(key: str, *, dev_mode: bool | None = None) -> bool:
    if key not in PROFILE_SPECS:
        return False
    spec = PROFILE_SPECS[key]
    if not spec.dev_only:
        return True
    dev_active = is_dev_mode() if dev_mode is None else dev_mode
    return dev_active


def apex_effort_to_native(effort: ApexEffort) -> NativeEffort:
    return _APEX_TO_NATIVE_EFFORT[effort]


def resolve_effort(
    profile_key: str,
    requested: ApexEffort | None,
) -> tuple[ApexEffort | None, NativeEffort | None]:
    """Resolve APEX and provider-native effort for a profile."""
    spec = PROFILE_SPECS[profile_key]
    if not spec.supports_effort:
        return None, None
    apex_effort = requested or spec.default_effort
    if apex_effort is None:
        return None, None
    return apex_effort, apex_effort_to_native(apex_effort)


def profile_has_credentials(profile_key: str) -> bool:
    spec = PROFILE_SPECS[profile_key]
    if spec.credential_env is None:
        return True
    return bool(os.getenv(spec.credential_env))


def credential_missing_message(profile_key: str) -> str:
    spec = PROFILE_SPECS[profile_key]
    env_key = spec.credential_env or "API_KEY"
    provider_label = spec.provider.upper()
    return (
        f"APEX is currently unavailable because the {provider_label} "
        f"API key is not configured. Please set {env_key} in your "
        "environment and restart the API server."
    )


def credential_missing_error(profile_key: str) -> str:
    spec = PROFILE_SPECS[profile_key]
    return f"{spec.credential_env} is missing from environment variables."


def build_concrete_profile(
    profile_key: str,
    *,
    native_effort: NativeEffort | None,
) -> AgentModelProfile:
    """Materialize a provider-specific profile with effort applied."""
    spec = PROFILE_SPECS[profile_key]
    if spec.provider == "gemini":
        thinking: GeminiThinkingLevel = native_effort or "medium"
        return GeminiModelProfile(
            display_name=spec.display_name,
            profile_version=spec.profile_version,
            api_model=spec.api_model,
            tier=spec.tier,  # type: ignore[arg-type]
            stability=spec.stability,
            thinking_level=thinking,
            max_tool_turns=spec.max_tool_turns,
            max_tool_calls=spec.max_tool_calls,
            system_instruction=DEFAULT_AGENT_SYSTEM_PROMPT,
        )
    if spec.provider == "ollama":
        ram_limit = SOREX_RAM_LIMIT if profile_key == "sorex" else MUS_RAM_LIMIT
        cpu_limit = SOREX_CPU_LIMIT if profile_key == "sorex" else MUS_CPU_LIMIT
        context_window = 4096
        if profile_key == "sorex":
            tool_select_max_tokens = 128
            final_answer_max_tokens = 512
            num_thread = 4
            generation_timeout = 120
        else:
            tool_select_max_tokens = 128
            final_answer_max_tokens = 768
            num_thread = 6
            generation_timeout = 150
        return OllamaModelProfile(
            display_name=spec.display_name,
            profile_version=spec.profile_version,
            api_model=spec.api_model,
            tier=spec.tier,  # type: ignore[arg-type]
            stability=spec.stability,
            max_tool_turns=spec.max_tool_turns,
            max_tool_calls=spec.max_tool_calls,
            context_window=context_window,
            tool_select_max_tokens=tool_select_max_tokens,
            final_answer_max_tokens=final_answer_max_tokens,
            num_thread=num_thread,
            generation_timeout=generation_timeout,
            ram_limit=ram_limit,
            cpu_limit=cpu_limit,
            system_instruction=DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT,
        )
    return ResponsesModelProfile(
        provider=spec.provider,  # type: ignore[arg-type]
        display_name=spec.display_name,
        profile_version=spec.profile_version,
        api_model=spec.api_model,
        max_tool_turns=spec.max_tool_turns,
        max_tool_calls=spec.max_tool_calls,
        system_instruction=DEFAULT_AGENT_SYSTEM_PROMPT,
        reasoning_effort=native_effort,
    )


def build_profile_used_metadata(
    profile_key: str,
    *,
    configured_model: str,
    resolved_model: str | None,
    requested_effort: ApexEffort | None,
    resolved_apex_effort: ApexEffort | None,
    resolved_native_effort: NativeEffort | None,
) -> dict[str, Any]:
    spec = PROFILE_SPECS[profile_key]
    return {
        "key": profile_key,
        "version": spec.profile_version,
        "provider": spec.provider,
        "configured_model": configured_model,
        "resolved_model": resolved_model or configured_model,
        "requested_effort": requested_effort,
        "resolved_effort": resolved_native_effort,
        "resolved_apex_effort": resolved_apex_effort,
        "mode": spec.mode,
    }


def is_acinonyx_fail_closed(profile_key: str) -> bool:
    return profile_key == "acinonyx"


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
        "local_profile": "mus",
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
            migrated["local_profile"] = "mus"
        elif normalized in _SCHEMA5_LOCAL_PROFILES:
            # Plan: every old local selection becomes Local/Mus while retaining
            # Panthera/Focused as the saved cloud choice.
            migrated["mode"] = "local"
            migrated["local_profile"] = "mus"
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


def migrate_schema5_briefing(
    raw: dict[str, Any], *, schema5: bool = True
) -> dict[str, Any]:
    """Map every legacy briefing mode to panthera (schema-5 one-way migration)."""
    if not schema5:
        return raw
    return {"default_mode": "panthera"}


def resolve_assistant_selection(
    assistant: Any,
    *,
    dev_mode: bool | None = None,
) -> tuple[AssistantMode, str, ApexEffort | None]:
    """Resolve effective assistant mode/profile/effort from saved settings."""
    dev_active = is_dev_mode() if dev_mode is None else dev_mode
    if dev_active:
        return "cloud", "acinonyx", "focused"

    mode = getattr(assistant, "mode", "cloud")
    if mode == "local":
        profile = getattr(assistant, "local_profile", "mus")
        return "local", profile, None
    profile = getattr(assistant, "cloud_profile", "panthera")
    effort = getattr(assistant, "cloud_effort", "focused")
    return "cloud", profile, effort
