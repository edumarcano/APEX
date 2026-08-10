"""Legacy-key normalization, overlay merge, and on-disk mapping helpers."""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from core.agent.catalog import migrate_schema5_briefing, migrate_schema7_ask_apex
from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS
from core.settings.models import (
    VALID_BRIEFING_MODES,
    VALID_CLOUD_EFFORTS,
    VALID_CLOUD_SETTINGS_AGENTS,
    VALID_LOCAL_SETTINGS_AGENTS,
    VALID_VOICE_ENGINES,
    VALID_VOICE_GENDERS,
    VALID_VOICE_MODES,
    AskApexSettings,
    BriefingSettings,
    FeaturesSettings,
    FootballSettings,
    FootballTeamSettings,
    LlamaCppSettings,
    MarketSettings,
    McpServerEnablementSettings,
    McpServersSettings,
    McpSettings,
    MCP_PROVIDER_IDS,
    ModulesSettings,
    RuntimeSettingsSnapshot,
    SettingsPatch,
    ToolProfile,
    ToolProfilesSettings,
    VoiceSettings,
)

_LOGGER = logging.getLogger(__name__)

_FEATURE_KEYS: frozenset[str] = frozenset(
    {"weather", "sports", "news", "email", "calendar", "market"}
)
_MODULE_KEYS: frozenset[str] = frozenset({"football", "f1"})
EDITABLE_ROOT_KEYS: frozenset[str] = frozenset(
    {
        "user_designation",
        "features",
        "modules",
        "football",
        "market",
        "ask_apex",
        "tool_profiles",
        "briefing",
        "tts_settings",
        "mcp",
        "llama_cpp",
    }
)
_DEFAULT_LLAMA_CPP_HOST = "http://127.0.0.1:8080"
_LLAMA_CPP_FILE_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "idle_unload_timeout_minutes",
        "manual_unload_enabled",
        "request_timeout_seconds",
        "resource_gates",
    }
)
_LOOPBACK_HOSTNAMES: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
_TOOL_PROFILE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$", re.IGNORECASE)


@dataclass
class NormalizationIssues:
    """Structured validation diagnostics collected while normalizing a layer."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def recursive_overlay(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``overlay`` onto ``base``; overlay wins for non-dict values."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = recursive_overlay(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def normalize_layer(
    raw: dict[str, Any],
    *,
    layer_name: str,
    issues: NormalizationIssues | None = None,
) -> dict[str, Any]:
    """
    Normalize a single config layer for editable settings.

    - Migrate legacy schema-5 ask_apex keys to schema-6 shape.
    - Map legacy TTS engine ``piper`` to ``pyttsx3``.
    - Warn and drop unknown keys under editable sections.
    """
    if not isinstance(raw, dict):
        _LOGGER.warning("%s root must be a JSON object; ignoring layer.", layer_name)
        return {}

    normalized: dict[str, Any] = {}
    ask_apex_raw = raw.get("ask_apex")
    schema5_layer = raw.get("schema_version") == 5 or (
        isinstance(ask_apex_raw, dict)
        and bool({"default_profile", "default_cloud_profile"} & ask_apex_raw.keys())
    )

    for key, value in raw.items():
        if key == "schema_version":
            continue
        if key not in EDITABLE_ROOT_KEYS:
            if key not in (
                "synthesis",
                "agent_system_prompt",
                "local_agent_system_prompt",
                "gemini",
                "ollama",
                "llama_cpp",
            ):
                _LOGGER.warning(
                    "Ignoring unknown config key %r in %s.",
                    key,
                    layer_name,
                )
            continue

        if key == "user_designation":
            if layer_name == "config.json":
                _LOGGER.warning(
                    "Ignoring user_designation in tracked config.json; configure it in config.local.json."
                )
                continue
            designation = _normalize_user_designation(value, layer_name, issues)
            if designation is not None:
                normalized["user_designation"] = designation
        elif key == "features":
            normalized["features"] = _normalize_features(
                value, layer_name, issues
            )
        elif key == "modules":
            normalized["modules"] = _normalize_modules(
                value, layer_name, issues
            )
        elif key == "football":
            football = _normalize_football(value, layer_name, issues)
            if football is not None:
                normalized["football"] = football
        elif key == "market":
            market = _normalize_market(value, layer_name, issues)
            if market is not None:
                normalized["market"] = market
        elif key == "ask_apex":
            ask_apex = _normalize_ask_apex(value, layer_name, issues)
            if ask_apex:
                normalized["ask_apex"] = ask_apex
        elif key == "tool_profiles":
            tool_profiles = _normalize_tool_profiles(value, layer_name, issues)
            if tool_profiles:
                normalized["tool_profiles"] = tool_profiles
        elif key == "briefing":
            briefing = _normalize_briefing(
                value, layer_name, issues, schema5=schema5_layer
            )
            if briefing:
                normalized["briefing"] = briefing
        elif key == "tts_settings":
            tts = _normalize_tts_settings(value, layer_name, issues)
            if tts:
                normalized["tts_settings"] = tts
        elif key == "mcp":
            mcp = _normalize_mcp_settings(value, layer_name, issues)
            if mcp:
                normalized["mcp"] = mcp
        elif key == "llama_cpp":
            llama_cpp = _normalize_llama_cpp(value, layer_name, issues)
            if llama_cpp:
                normalized["llama_cpp"] = llama_cpp

    return normalized


def _normalize_user_designation(
    value: Any, layer_name: str, issues: NormalizationIssues | None
) -> str | None:
    """Normalize the optional local user designation without exposing its value."""
    if not isinstance(value, str):
        _record_error(issues, "user_designation must be a string")
        _LOGGER.warning(
            "user_designation in %s must be a string; ignoring.", layer_name
        )
        return None

    normalized = " ".join(value.split())
    if len(normalized) > 80:
        _record_error(issues, "user_designation must be at most 80 characters")
        _LOGGER.warning(
            "user_designation in %s exceeds the maximum length; ignoring.",
            layer_name,
        )
        return None
    return normalized


def _normalize_football(
    value: Any, layer_name: str, issues: NormalizationIssues | None
) -> dict[str, Any] | None:
    """Validate the followed-team list as one replaceable value (zero to three teams)."""
    if not isinstance(value, dict):
        _record_error(issues, "football must be a JSON object")
        return None
    teams = value.get("teams")
    if not isinstance(teams, list) or not 0 <= len(teams) <= 3:
        _record_error(issues, "football.teams must contain zero to three teams")
        return None
    if not teams:
        return {"teams": []}
    normalized_teams: list[dict[str, Any]] = []
    team_ids: set[int] = set()
    for team in teams:
        if not isinstance(team, dict):
            _record_error(issues, "football.teams entries must be objects")
            return None
        team_id = team.get("id")
        name = team.get("name")
        if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id <= 0:
            _record_error(issues, "football team id must be a positive integer")
            return None
        if team_id in team_ids:
            _record_error(issues, "football team ids must be unique")
            return None
        if not isinstance(name, str) or not (clean_name := name.strip()) or len(clean_name) > 100:
            _record_error(issues, "football team name must be a non-empty string up to 100 characters")
            return None
        team_ids.add(team_id)
        normalized_teams.append({"id": team_id, "name": clean_name})
    return {"teams": normalized_teams}


_TICKER_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")
_MAX_MARKET_SYMBOLS = 8


def _normalize_market(
    value: Any, layer_name: str, issues: NormalizationIssues | None
) -> dict[str, Any] | None:
    """Validate the market ticker list as one replaceable value (zero to eight symbols)."""
    if not isinstance(value, dict):
        _record_error(issues, "market must be a JSON object")
        return None
    symbols = value.get("symbols")
    if not isinstance(symbols, list) or not 0 <= len(symbols) <= _MAX_MARKET_SYMBOLS:
        _record_error(
            issues,
            f"market.symbols must contain zero to {_MAX_MARKET_SYMBOLS} symbols",
        )
        return None
    if not symbols:
        return {"symbols": []}
    normalized_symbols: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        if not isinstance(symbol, str):
            _record_error(issues, "market.symbols entries must be strings")
            return None
        candidate = symbol.strip().upper()
        if not candidate:
            _record_error(issues, "market symbol must be a non-empty string")
            return None
        if not _TICKER_SYMBOL_PATTERN.match(candidate):
            _record_error(issues, "market symbol contains invalid characters")
            return None
        if candidate in seen:
            _record_error(issues, "market symbols must be unique")
            return None
        seen.add(candidate)
        normalized_symbols.append(candidate)
    return {"symbols": normalized_symbols}


def _normalize_llama_cpp_host(
    value: Any,
    *,
    layer_name: str,
    issues: NormalizationIssues | None,
) -> str | None:
    """Validate and normalize a loopback llama.cpp router URL."""
    if not isinstance(value, str):
        _record_error(issues, "llama_cpp.host must be a string")
        _LOGGER.warning("llama_cpp.host in %s must be a string; ignoring.", layer_name)
        return None

    candidate = value.strip().rstrip("/")
    if not candidate:
        _record_error(issues, "llama_cpp.host must be a non-empty loopback HTTP URL")
        return None

    try:
        parsed = urlparse(candidate)
        if parsed.scheme != "http":
            _record_error(issues, "llama_cpp.host must use HTTP")
            return None
        if parsed.username or parsed.password:
            _record_error(issues, "llama_cpp.host must not include credentials")
            return None
        if parsed.query or parsed.fragment:
            _record_error(issues, "llama_cpp.host must not include query strings or fragments")
            return None
        if parsed.path not in {"", "/"}:
            _record_error(issues, "llama_cpp.host must not include a path")
            return None

        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        _record_error(issues, "llama_cpp.host must be a valid loopback HTTP URL")
        return None

    if hostname not in _LOOPBACK_HOSTNAMES:
        _record_error(
            issues,
            "llama_cpp.host must target a loopback address (127.0.0.1, localhost, or [::1])",
        )
        return None

    if port is None or port < 1 or port > 65535:
        _record_error(issues, "llama_cpp.host must include a valid port")
        return None

    if hostname == "::1":
        return f"http://[::1]:{port}"
    return f"http://{hostname}:{port}"


def _normalize_llama_cpp_path(
    value: Any,
    *,
    field_name: str,
    issues: NormalizationIssues | None,
) -> str | None:
    """Normalize a machine-local filesystem path string without existence checks."""
    if not isinstance(value, str):
        _record_error(issues, f"llama_cpp.{field_name} must be a string")
        return None
    candidate = value.strip()
    if "\x00" in candidate:
        _record_error(issues, f"llama_cpp.{field_name} must not contain null bytes")
        return None
    return candidate


def _normalize_llama_cpp(
    value: Any, layer_name: str, issues: NormalizationIssues | None
) -> dict[str, Any]:
    """Extract editable llama.cpp fields while leaving advanced config file-only."""
    result: dict[str, Any] = {}
    if not isinstance(value, dict):
        if value is not None:
            _record_error(issues, "llama_cpp must be a JSON object")
            _LOGGER.warning('Config key "llama_cpp" in %s must be a JSON object.', layer_name)
        return result

    editable_keys = {
        "enabled",
        "managed",
        "host",
        "executable_path",
        "preset_path",
    }
    for key in value:
        if key not in editable_keys and not (
            layer_name == "config.json" and key in _LLAMA_CPP_FILE_ONLY_KEYS
        ):
            _LOGGER.warning(
                "Ignoring non-editable llama_cpp key %r in %s.",
                key,
                layer_name,
            )

    enabled = value.get("enabled")
    if isinstance(enabled, bool):
        result["enabled"] = enabled
    elif enabled is not None:
        _record_error(issues, "llama_cpp.enabled must be a boolean")

    managed = value.get("managed")
    if isinstance(managed, bool):
        result["managed"] = managed
    elif managed is not None:
        _record_error(issues, "llama_cpp.managed must be a boolean")

    if "host" in value:
        host = _normalize_llama_cpp_host(
            value.get("host"),
            layer_name=layer_name,
            issues=issues,
        )
        if host is not None:
            result["host"] = host

    if "executable_path" in value:
        executable_path = _normalize_llama_cpp_path(
            value.get("executable_path"),
            field_name="executable_path",
            issues=issues,
        )
        if executable_path is not None:
            result["executable_path"] = executable_path

    if "preset_path" in value:
        preset_path = _normalize_llama_cpp_path(
            value.get("preset_path"),
            field_name="preset_path",
            issues=issues,
        )
        if preset_path is not None:
            result["preset_path"] = preset_path

    managed_effective = result.get("managed")
    if managed_effective is True:
        executable = result.get("executable_path")
        preset = result.get("preset_path")
        # When only toggling managed, require both path keys in this layer or
        # leave validation to the merged snapshot below.
        if "executable_path" in value and not (isinstance(executable, str) and executable):
            _record_error(
                issues,
                "llama_cpp.managed requires a non-empty executable_path",
            )
        if "preset_path" in value and not (isinstance(preset, str) and preset):
            _record_error(
                issues,
                "llama_cpp.managed requires a non-empty preset_path",
            )

    return result


def _normalize_mcp_settings(
    value: Any, layer_name: str, issues: NormalizationIssues | None
) -> dict[str, Any]:
    """Extract editable MCP booleans while leaving advanced config file-only."""
    result: dict[str, Any] = {}
    if not isinstance(value, dict):
        if value is not None:
            _record_warning(issues, "mcp must be a JSON object; disabling MCP")
            _LOGGER.warning('Config key "mcp" in %s must be a JSON object.', layer_name)
        return result

    enabled = value.get("enabled")
    if isinstance(enabled, bool):
        result["enabled"] = enabled
    elif enabled is not None:
        _record_warning(issues, "mcp.enabled must be a boolean; disabling MCP")
        _LOGGER.warning("mcp.enabled in %s must be a boolean; disabling.", layer_name)

    servers_raw = value.get("servers")
    if servers_raw is None:
        return result
    if not isinstance(servers_raw, dict):
        _record_warning(
            issues, "mcp.servers must be a JSON object; disabling providers"
        )
        _LOGGER.warning("mcp.servers in %s must be a JSON object.", layer_name)
        return result

    servers: dict[str, dict[str, bool]] = {}
    for provider in MCP_PROVIDER_IDS:
        provider_raw = servers_raw.get(provider)
        if provider_raw is None:
            continue
        if not isinstance(provider_raw, dict):
            _record_warning(
                issues, f"mcp.servers.{provider} must be a JSON object; disabling"
            )
            _LOGGER.warning(
                "mcp.servers.%s in %s must be a JSON object; disabling.",
                provider,
                layer_name,
            )
            continue
        provider_enabled = provider_raw.get("enabled")
        if isinstance(provider_enabled, bool):
            servers[provider] = {"enabled": provider_enabled}
        elif provider_enabled is not None:
            _record_warning(
                issues,
                f"mcp.servers.{provider}.enabled must be a boolean; disabling",
            )
            _LOGGER.warning(
                "mcp.servers.%s.enabled in %s must be a boolean; disabling.",
                provider,
                layer_name,
            )
    if servers:
        result["servers"] = servers
    return result


def _record_error(issues: NormalizationIssues | None, message: str) -> None:
    if issues is not None:
        issues.errors.append(message)


def _record_warning(issues: NormalizationIssues | None, message: str) -> None:
    if issues is not None:
        issues.warnings.append(message)


def _normalize_features(
    value: Any, layer_name: str, errors: NormalizationIssues | None
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    if not isinstance(value, dict):
        if value is not None:
            _record_error(errors, "features must be a JSON object")
            _LOGGER.warning(
                'Config key "features" in %s must be a JSON object.', layer_name
            )
        return result

    for key, raw in value.items():
        if key not in _FEATURE_KEYS:
            _LOGGER.warning(
                "Ignoring unknown feature key %r in %s.", key, layer_name
            )
            continue
        if isinstance(raw, bool):
            result[key] = raw
        elif raw is not None:
            _record_error(errors, f"features.{key} must be a boolean")
            _LOGGER.warning(
                "Feature %r in %s must be a boolean; ignoring invalid value.",
                key,
                layer_name,
            )
    return result


def _normalize_modules(
    value: Any, layer_name: str, errors: NormalizationIssues | None
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    if not isinstance(value, dict):
        if value is not None:
            _record_error(errors, "modules must be a JSON object")
            _LOGGER.warning(
                'Config key "modules" in %s must be a JSON object.', layer_name
            )
        return result

    for key, raw in value.items():
        if key not in _MODULE_KEYS:
            _LOGGER.warning(
                "Ignoring unknown module key %r in %s.", key, layer_name
            )
            continue
        if isinstance(raw, bool):
            result[key] = raw
        elif raw is not None:
            _record_error(errors, f"modules.{key} must be a boolean")
            _LOGGER.warning(
                "Module %r in %s must be a boolean; ignoring invalid value.",
                key,
                layer_name,
            )
    return result


def _normalize_ask_apex(
    value: Any, layer_name: str, errors: NormalizationIssues | None
) -> dict[str, Any]:
    if not isinstance(value, dict):
        if value is not None:
            _record_error(errors, "ask_apex must be a JSON object")
            _LOGGER.warning(
                'Config key "ask_apex" in %s must be a JSON object.', layer_name
            )
        return {}

    migrated = migrate_schema7_ask_apex(value)
    result: dict[str, Any] = {}

    known_keys = {
        "enabled",
        "runtime",
        "cloud_agent",
        "effort",
        "local_agent",
        "local_context_windows",
        "local_reasoning_modes",
        "apodemus_context_window",
        "neofelis_google_search_enabled",
        "neofelis_google_maps_enabled",
        "delphinus_x_search_enabled",
        "orcinus_x_search_enabled",
        "max_session_messages",
        # Historical schema-7 keys are accepted only so the one-way migration
        # can preserve existing local settings without spurious warnings.
        "mode",
        "cloud_profile",
        "cloud_effort",
        "local_profile",
        "default_profile",
        "default_cloud_profile",
    }
    for key in value:
        if key not in known_keys:
            _LOGGER.warning(
                "Ignoring unknown ask_apex key %r in %s.", key, layer_name
            )

    enabled_raw = migrated.get("enabled")
    if isinstance(enabled_raw, bool):
        result["enabled"] = enabled_raw
    elif enabled_raw is not None:
        _record_error(errors, "ask_apex.enabled must be a boolean")

    if "runtime" in migrated:
        runtime = migrated["runtime"]
        if runtime in {"cloud", "local"}:
            result["runtime"] = runtime
        else:
            _record_error(errors, "ask_apex.runtime must be cloud or local")

    if "cloud_agent" in migrated:
        cloud_agent = migrated["cloud_agent"]
        if isinstance(cloud_agent, str):
            normalized = cloud_agent.strip().lower()
            if normalized in VALID_CLOUD_SETTINGS_AGENTS:
                result["cloud_agent"] = normalized
            else:
                _record_error(errors, "ask_apex.cloud_agent is not valid")

    if "effort" in migrated:
        effort = migrated["effort"]
        if isinstance(effort, str):
            normalized = effort.strip().lower()
            if normalized in VALID_CLOUD_EFFORTS:
                result["effort"] = normalized
            else:
                _record_error(errors, "ask_apex.effort is not valid")

    if "local_agent" in migrated:
        local_agent = migrated["local_agent"]
        if isinstance(local_agent, str):
            normalized = local_agent.strip().lower()
            if normalized in VALID_LOCAL_SETTINGS_AGENTS:
                result["local_agent"] = normalized
            else:
                _record_error(errors, "ask_apex.local_agent is not valid")

    normalized_context_windows: dict[str, int] | None = None
    if "local_context_windows" in migrated:
        normalized_context_windows = _normalize_local_context_windows(
            migrated["local_context_windows"],
            layer_name,
            errors,
        )
        if normalized_context_windows is not None:
            result["local_context_windows"] = normalized_context_windows

    if "local_reasoning_modes" in migrated:
        normalized_reasoning_modes = _normalize_local_reasoning_modes(
            migrated["local_reasoning_modes"],
            layer_name,
            errors,
        )
        if normalized_reasoning_modes is not None:
            result["local_reasoning_modes"] = normalized_reasoning_modes

    if "apodemus_context_window" in migrated:
        context_window = _migrate_apodemus_context_window(
            migrated["apodemus_context_window"]
        )
        runtime = LLAMA_CPP_RUNTIME_CONFIGS["apodemus"]
        if isinstance(context_window, bool):
            _record_error(
                errors, "ask_apex.apodemus_context_window must be an integer"
            )
        elif (
            isinstance(context_window, int)
            and context_window in runtime.allowed_context_windows
        ):
            if normalized_context_windows is None:
                result["local_context_windows"] = {}
            result["local_context_windows"]["apodemus"] = context_window
        elif context_window is not None:
            _record_error(
                errors,
                "ask_apex.apodemus_context_window is not a supported preset",
            )

    if "neofelis_google_search_enabled" in migrated:
        google_search = migrated["neofelis_google_search_enabled"]
        if isinstance(google_search, bool):
            result["neofelis_google_search_enabled"] = google_search
        elif google_search is not None:
            _record_error(errors, "ask_apex.neofelis_google_search_enabled must be a boolean")

    for key in (
        "neofelis_google_maps_enabled",
        "delphinus_x_search_enabled",
        "orcinus_x_search_enabled",
    ):
        if key in migrated:
            enabled = migrated[key]
            if isinstance(enabled, bool):
                result[key] = enabled
            elif enabled is not None:
                _record_error(errors, f"ask_apex.{key} must be a boolean")

    return result


def _normalize_local_context_windows(
    value: Any,
    layer_name: str,
    errors: NormalizationIssues | None,
) -> dict[str, int] | None:
    """Normalize selectable context preferences for registered local runtimes."""
    if not isinstance(value, dict):
        _record_error(errors, "ask_apex.local_context_windows must be an object")
        _LOGGER.warning(
            "ask_apex.local_context_windows in %s must be an object; ignoring.",
            layer_name,
        )
        return None

    normalized: dict[str, int] = {}
    for agent_key, context_window in value.items():
        if not isinstance(agent_key, str):
            _record_error(
                errors,
                "ask_apex.local_context_windows keys must be Agent names",
            )
            continue
        runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(agent_key.strip().lower())
        if runtime is None:
            _record_error(
                errors,
                f"ask_apex.local_context_windows has unsupported Agent {agent_key!r}",
            )
            continue
        normalized_agent_key = agent_key.strip().lower()
        context_window = _migrate_apodemus_context_window(
            context_window,
            agent_key=normalized_agent_key,
        )
        if (
            isinstance(context_window, int)
            and not isinstance(context_window, bool)
            and context_window in runtime.allowed_context_windows
        ):
            normalized[normalized_agent_key] = context_window
            continue
        _record_error(
            errors,
            f"ask_apex.local_context_windows[{agent_key!r}] is not a supported preset",
        )
    return normalized


def _migrate_apodemus_context_window(
    context_window: Any,
    *,
    agent_key: str = "apodemus",
) -> Any:
    """Migrate the retired Apodemus 8K preference to the new 16K default."""
    if agent_key == "apodemus" and context_window == 8192:
        return 16384
    return context_window


def _normalize_local_reasoning_modes(
    value: Any,
    layer_name: str,
    errors: NormalizationIssues | None,
) -> dict[str, str] | None:
    """Normalize local reasoning preferences using provider capabilities."""
    if not isinstance(value, dict):
        _record_error(errors, "ask_apex.local_reasoning_modes must be an object")
        _LOGGER.warning(
            "ask_apex.local_reasoning_modes in %s must be an object; ignoring.",
            layer_name,
        )
        return None

    from core.agent.catalog import local_reasoning_modes_for_agent

    normalized: dict[str, str] = {}
    for agent_key, reasoning_mode in value.items():
        if not isinstance(agent_key, str):
            _record_error(
                errors,
                "ask_apex.local_reasoning_modes keys must be Agent names",
            )
            continue
        normalized_agent_key = agent_key.strip().lower()
        supported = local_reasoning_modes_for_agent(normalized_agent_key)
        if not supported:
            _record_error(
                errors,
                f"ask_apex.local_reasoning_modes has unsupported Agent {agent_key!r}",
            )
            continue
        if reasoning_mode in supported:
            normalized[normalized_agent_key] = reasoning_mode
            continue
        _record_error(
            errors,
            f"ask_apex.local_reasoning_modes[{agent_key!r}] is not supported",
        )
    return normalized


def _normalize_tool_profiles(
    value: Any, layer_name: str, errors: NormalizationIssues | None
) -> dict[str, Any]:
    """Normalize non-secret saved tool selections and Agent defaults."""
    if not isinstance(value, dict):
        _record_error(errors, "tool_profiles must be a JSON object")
        _LOGGER.warning(
            'Config key "tool_profiles" in %s must be a JSON object.',
            layer_name,
        )
        return {}

    result: dict[str, Any] = {}
    profiles_raw = value.get("custom_profiles", [])
    if profiles_raw is not None:
        if not isinstance(profiles_raw, list):
            _record_error(errors, "tool_profiles.custom_profiles must be a list")
        else:
            profiles: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for raw_profile in profiles_raw:
                if not isinstance(raw_profile, dict):
                    _record_error(errors, "tool profile entries must be objects")
                    continue
                profile_id = raw_profile.get("id")
                name = raw_profile.get("name")
                description = raw_profile.get("description", "")
                tool_names = raw_profile.get("tool_names", [])
                if (
                    not isinstance(profile_id, str)
                    or not profile_id.strip()
                    or len(profile_id.strip()) > 80
                    or not _TOOL_PROFILE_ID_PATTERN.fullmatch(profile_id.strip())
                    or not isinstance(name, str)
                    or not name.strip()
                    or len(name.strip()) > 80
                    or not isinstance(description, str)
                    or len(description) > 240
                    or not isinstance(tool_names, list)
                    or not all(isinstance(tool_name, str) for tool_name in tool_names)
                ):
                    _record_error(errors, "tool profile contains invalid fields")
                    continue
                normalized_id = profile_id.strip().lower()
                if normalized_id in seen_ids:
                    _record_error(errors, "tool profile ids must be unique")
                    continue
                seen_ids.add(normalized_id)
                deduped_names = list(
                    dict.fromkeys(
                        tool_name.strip()
                        for tool_name in tool_names
                        if tool_name.strip()
                    )
                )
                profiles.append(
                    ToolProfile(
                        id=normalized_id,
                        name=" ".join(name.split()),
                        description=description.strip(),
                        tool_names=tuple(deduped_names),
                        built_in=False,
                        dynamic=False,
                    ).model_dump()
                )
            result["custom_profiles"] = profiles

    defaults_raw = value.get("default_profile_by_agent", {})
    if defaults_raw is not None:
        if not isinstance(defaults_raw, dict):
            _record_error(
                errors, "tool_profiles.default_profile_by_agent must be an object"
            )
        else:
            defaults: dict[str, str] = {}
            for agent, profile_id in defaults_raw.items():
                if (
                    isinstance(agent, str)
                    and agent.strip()
                    and isinstance(profile_id, str)
                    and profile_id.strip()
                ):
                    defaults[agent.strip().lower()] = profile_id.strip().lower()
                else:
                    _record_error(
                        errors,
                        "tool profile defaults must map Agent names to profile IDs",
                    )
            result["default_profile_by_agent"] = defaults
    return result


def _normalize_tts_settings(
    value: Any, layer_name: str, errors: NormalizationIssues | None
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(value, dict):
        if value is not None:
            _record_error(errors, "tts_settings must be a JSON object")
            _LOGGER.warning(
                'Config key "tts_settings" in %s must be a JSON object.',
                layer_name,
            )
        return result

    for key, raw in value.items():
        if key == "primary_tts":
            engine = _coerce_engine(raw, layer_name=layer_name, errors=errors)
            if engine is not None:
                result["primary_tts"] = engine
        elif key == "voice_gender":
            gender = _coerce_gender(raw, layer_name=layer_name, errors=errors)
            if gender is not None:
                result["voice_gender"] = gender
        elif key == "voice_mode":
            mode = _coerce_voice_mode(raw, layer_name=layer_name, errors=errors)
            if mode is not None:
                result["voice_mode"] = mode
        else:
            _LOGGER.warning(
                "Ignoring unknown tts_settings key %r in %s.", key, layer_name
            )
    return result


def _normalize_briefing(
    value: Any,
    layer_name: str,
    errors: NormalizationIssues | None,
    *,
    schema5: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(value, dict):
        if value is not None:
            _record_error(errors, "briefing must be a JSON object")
            _LOGGER.warning(
                'Config key "briefing" in %s must be a JSON object.',
                layer_name,
            )
        return result

    migrated = migrate_schema5_briefing(value, schema5=schema5)
    for key, raw in value.items():
        if key == "default_mode":
            mode = _coerce_briefing_mode(
                migrated.get("default_mode", raw),
                layer_name=layer_name,
                errors=errors,
            )
            if mode is not None:
                result["default_mode"] = mode
        else:
            _LOGGER.warning(
                "Ignoring unknown briefing key %r in %s.", key, layer_name
            )
    if "default_mode" not in result and "default_mode" in migrated:
        mode = _coerce_briefing_mode(
            migrated["default_mode"], layer_name=layer_name, errors=errors
        )
        if mode is not None:
            result["default_mode"] = mode
    return result


def _coerce_briefing_mode(
    raw: Any, *, layer_name: str, errors: NormalizationIssues | None
) -> str | None:
    if not isinstance(raw, str):
        if raw is not None:
            _record_error(errors, "briefing.default_mode must be a string")
            _LOGGER.warning(
                "briefing.default_mode in %s must be a string; ignoring.",
                layer_name,
            )
        return None
    normalized = raw.strip().lower()
    if normalized in VALID_BRIEFING_MODES:
        return normalized
    _record_error(errors, "briefing.default_mode is not a valid mode")
    _LOGGER.warning(
        "briefing.default_mode=%r in %s is not a valid mode; ignoring.",
        raw,
        layer_name,
    )
    return None


def _coerce_voice_mode(
    raw: Any, *, layer_name: str, errors: NormalizationIssues | None
) -> str | None:
    if not isinstance(raw, str):
        if raw is not None:
            _record_error(errors, "tts_settings.voice_mode must be a string")
            _LOGGER.warning(
                "tts_settings.voice_mode in %s must be a string; ignoring.",
                layer_name,
            )
        return None
    normalized = raw.strip().lower()
    if normalized in VALID_VOICE_MODES:
        return normalized
    _record_error(errors, "tts_settings.voice_mode is not a valid mode")
    _LOGGER.warning(
        "tts_settings.voice_mode=%r in %s is not a valid mode; ignoring.",
        raw,
        layer_name,
    )
    return None


def _coerce_engine(
    raw: Any, *, layer_name: str, errors: NormalizationIssues | None
) -> str | None:
    if not isinstance(raw, str):
        if raw is not None:
            _record_error(errors, "tts_settings.primary_tts must be a string")
            _LOGGER.warning(
                "tts_settings.primary_tts in %s must be a string; ignoring.",
                layer_name,
            )
        return None
    normalized = raw.strip().lower()
    if normalized == "piper":
        _LOGGER.warning(
            "tts_settings.primary_tts='piper' in %s is deprecated; using 'pyttsx3'.",
            layer_name,
        )
        return "pyttsx3"
    if normalized in VALID_VOICE_ENGINES:
        return normalized
    _record_error(errors, "tts_settings.primary_tts is not a valid engine")
    _LOGGER.warning(
        "tts_settings.primary_tts=%r in %s is not a valid engine; ignoring.",
        raw,
        layer_name,
    )
    return None


def _coerce_gender(
    raw: Any, *, layer_name: str, errors: NormalizationIssues | None
) -> str | None:
    if not isinstance(raw, str):
        if raw is not None:
            _record_error(errors, "tts_settings.voice_gender must be a string")
            _LOGGER.warning(
                "tts_settings.voice_gender in %s must be a string; ignoring.",
                layer_name,
            )
        return None
    normalized = raw.strip().lower()
    if normalized in VALID_VOICE_GENDERS:
        return normalized
    _record_error(errors, "tts_settings.voice_gender is not valid")
    _LOGGER.warning(
        "tts_settings.voice_gender=%r in %s is not valid; ignoring.",
        raw,
        layer_name,
    )
    return None


def snapshot_from_merged(merged: dict[str, Any]) -> RuntimeSettingsSnapshot:
    """Build a validated immutable snapshot from a merged on-disk dict."""
    features_raw = merged.get("features") if isinstance(merged.get("features"), dict) else {}
    modules_raw = merged.get("modules") if isinstance(merged.get("modules"), dict) else {}
    football_raw = merged.get("football") if isinstance(merged.get("football"), dict) else {}
    market_raw = merged.get("market") if isinstance(merged.get("market"), dict) else {}
    ask_apex_raw = merged.get("ask_apex") if isinstance(merged.get("ask_apex"), dict) else {}
    tool_profiles_raw = (
        merged.get("tool_profiles")
        if isinstance(merged.get("tool_profiles"), dict)
        else {}
    )
    ask_apex = migrate_schema7_ask_apex(ask_apex_raw)
    tts = merged.get("tts_settings") if isinstance(merged.get("tts_settings"), dict) else {}
    mcp_raw = merged.get("mcp") if isinstance(merged.get("mcp"), dict) else {}
    mcp_servers_raw = (
        mcp_raw.get("servers") if isinstance(mcp_raw.get("servers"), dict) else {}
    )

    features = FeaturesSettings(
        weather=bool(features_raw.get("weather", False)),
        sports=bool(features_raw.get("sports", False)),
        news=bool(features_raw.get("news", False)),
        email=bool(features_raw.get("email", False)),
        calendar=bool(features_raw.get("calendar", False)),
        market=bool(features_raw.get("market", False)),
    )
    modules = ModulesSettings(
        football=bool(modules_raw.get("football", False)),
        f1=bool(modules_raw.get("f1", False)),
    )
    football = FootballSettings(
        teams=tuple(
            FootballTeamSettings.model_validate(team)
            for team in football_raw.get("teams", [])
            if isinstance(team, dict)
        )
    )
    market = MarketSettings(
        symbols=tuple(
            symbol.strip().upper()
            for symbol in market_raw.get("symbols", [])
            if isinstance(symbol, str) and symbol.strip()
        )
    )
    runtime = ask_apex.get("runtime", "cloud")
    if runtime not in {"cloud", "local"}:
        runtime = "cloud"
    cloud_agent = ask_apex.get("cloud_agent", "panthera")
    if cloud_agent not in VALID_CLOUD_SETTINGS_AGENTS:
        cloud_agent = "panthera"
    effort = ask_apex.get("effort", "focused")
    if effort not in VALID_CLOUD_EFFORTS:
        effort = "focused"
    local_agent = ask_apex.get("local_agent", "apodemus")
    if local_agent not in VALID_LOCAL_SETTINGS_AGENTS:
        local_agent = "apodemus"
    local_context_windows = {
        agent_key: runtime.default_context_window
        for agent_key, runtime in LLAMA_CPP_RUNTIME_CONFIGS.items()
    }
    configured_context_windows = ask_apex.get("local_context_windows", {})
    if isinstance(configured_context_windows, dict):
        for agent_key, context_window in configured_context_windows.items():
            runtime_config = LLAMA_CPP_RUNTIME_CONFIGS.get(agent_key)
            context_window = _migrate_apodemus_context_window(
                context_window,
                agent_key=agent_key,
            )
            if (
                runtime_config is not None
                and isinstance(context_window, int)
                and not isinstance(context_window, bool)
                and context_window in runtime_config.allowed_context_windows
            ):
                local_context_windows[agent_key] = context_window
    local_reasoning_modes = {
        agent_key: "none" for agent_key in VALID_LOCAL_SETTINGS_AGENTS
    }
    configured_reasoning_modes = ask_apex.get("local_reasoning_modes", {})
    if isinstance(configured_reasoning_modes, dict):
        for agent_key, reasoning_mode in configured_reasoning_modes.items():
            if (
                isinstance(agent_key, str)
                and reasoning_mode in {"none", "focused"}
            ):
                from core.agent.catalog import local_reasoning_modes_for_agent

                normalized_agent_key = agent_key.strip().lower()
                if reasoning_mode in local_reasoning_modes_for_agent(
                    normalized_agent_key
                ):
                    local_reasoning_modes[normalized_agent_key] = reasoning_mode
    ask_apex_settings = AskApexSettings(
        enabled=bool(ask_apex.get("enabled", True))
        if "enabled" in ask_apex
        else True,
        runtime=runtime,  # type: ignore[arg-type]
        cloud_agent=cloud_agent,  # type: ignore[arg-type]
        effort=effort,  # type: ignore[arg-type]
        local_agent=local_agent,  # type: ignore[arg-type]
        local_context_windows=local_context_windows,
        local_reasoning_modes=local_reasoning_modes,
        neofelis_google_search_enabled=bool(
            ask_apex.get("neofelis_google_search_enabled", True)
        ),
        neofelis_google_maps_enabled=bool(
            ask_apex.get("neofelis_google_maps_enabled", True)
        ),
        delphinus_x_search_enabled=bool(
            ask_apex.get("delphinus_x_search_enabled", True)
        ),
        orcinus_x_search_enabled=bool(
            ask_apex.get("orcinus_x_search_enabled", True)
        ),
    )
    custom_profiles: list[ToolProfile] = []
    for raw_profile in tool_profiles_raw.get("custom_profiles", []):
        if not isinstance(raw_profile, dict):
            continue
        try:
            profile = ToolProfile.model_validate(raw_profile)
        except Exception:
            continue
        if profile.built_in:
            profile = profile.model_copy(update={"built_in": False, "dynamic": False})
        custom_profiles.append(
            profile.model_copy(
                update={
                    "tool_names": tuple(
                        dict.fromkeys(
                            name.strip()
                            for name in profile.tool_names
                            if name.strip()
                        )
                    )
                }
            )
        )
    defaults_raw = tool_profiles_raw.get("default_profile_by_agent", {})
    default_profile_by_agent = (
        {
            str(agent).strip().lower(): str(profile_id).strip().lower()
            for agent, profile_id in defaults_raw.items()
            if str(agent).strip() and str(profile_id).strip()
        }
        if isinstance(defaults_raw, dict)
        else {}
    )
    tool_profiles = ToolProfilesSettings(
        custom_profiles=tuple(custom_profiles),
        default_profile_by_agent=default_profile_by_agent,
    )
    engine = tts.get("primary_tts", "pyttsx3")
    if engine not in VALID_VOICE_ENGINES:
        engine = "pyttsx3"
    gender = tts.get("voice_gender", "female")
    if gender not in VALID_VOICE_GENDERS:
        gender = "female"
    voice_mode = tts.get("voice_mode", "automatic")
    if voice_mode not in VALID_VOICE_MODES:
        voice_mode = "automatic"
    voice = VoiceSettings(
        engine=engine,  # type: ignore[arg-type]
        gender=gender,  # type: ignore[arg-type]
        mode=voice_mode,  # type: ignore[arg-type]
    )
    briefing_raw = (
        merged.get("briefing") if isinstance(merged.get("briefing"), dict) else {}
    )
    briefing_migrated = migrate_schema5_briefing(briefing_raw, schema5=False)
    default_mode = briefing_migrated.get("default_mode", "panthera")
    if default_mode not in VALID_BRIEFING_MODES:
        default_mode = "panthera"
    briefing = BriefingSettings(
        default_mode=default_mode,  # type: ignore[arg-type]
    )
    mcp = McpSettings(
        enabled=bool(mcp_raw.get("enabled", False)),
        servers=McpServersSettings(
            **{
                provider: McpServerEnablementSettings(
                    enabled=bool(
                        mcp_servers_raw.get(provider, {}).get("enabled", False)
                    )
                )
                for provider in MCP_PROVIDER_IDS
                if isinstance(mcp_servers_raw.get(provider, {}), dict)
            }
        ),
    )
    llama_cpp_raw = (
        merged.get("llama_cpp") if isinstance(merged.get("llama_cpp"), dict) else {}
    )
    llama_host = llama_cpp_raw.get("host", _DEFAULT_LLAMA_CPP_HOST)
    if not isinstance(llama_host, str) or not llama_host.strip():
        llama_host = _DEFAULT_LLAMA_CPP_HOST
    else:
        llama_host = llama_host.strip().rstrip("/")
    executable_path = llama_cpp_raw.get("executable_path", "")
    if not isinstance(executable_path, str):
        executable_path = ""
    else:
        executable_path = executable_path.strip()
    preset_path = llama_cpp_raw.get("preset_path", "")
    if not isinstance(preset_path, str):
        preset_path = ""
    else:
        preset_path = preset_path.strip()
    managed = bool(llama_cpp_raw.get("managed", False))
    if managed and (not executable_path or not preset_path):
        _LOGGER.warning(
            "llama_cpp.managed requires executable_path and preset_path; "
            "treating managed as false."
        )
        managed = False
    llama_cpp = LlamaCppSettings(
        enabled=bool(llama_cpp_raw.get("enabled", False)),
        managed=managed,
        host=llama_host,
        executable_path=executable_path,
        preset_path=preset_path,
    )
    return RuntimeSettingsSnapshot(
        user_designation=(
            merged.get("user_designation", "")
            if isinstance(merged.get("user_designation", ""), str)
            else ""
        ),
        features=features,
        modules=modules,
        football=football,
        market=market,
        ask_apex=ask_apex_settings,
        tool_profiles=tool_profiles,
        briefing=briefing,
        voice=voice,
        mcp=mcp,
        llama_cpp=llama_cpp,
    )


def snapshot_to_ondisk(snapshot: RuntimeSettingsSnapshot) -> dict[str, Any]:
    """Serialize a snapshot to on-disk editable section keys."""
    return {
        "user_designation": snapshot.user_designation,
        "features": snapshot.features.model_dump(),
        "modules": snapshot.modules.model_dump(),
        "ask_apex": {
            "enabled": snapshot.ask_apex.enabled,
            "runtime": snapshot.ask_apex.runtime,
            "cloud_agent": snapshot.ask_apex.cloud_agent,
            "effort": snapshot.ask_apex.effort,
            "local_agent": snapshot.ask_apex.local_agent,
            "local_context_windows": dict(
                snapshot.ask_apex.local_context_windows
            ),
            "local_reasoning_modes": dict(snapshot.ask_apex.local_reasoning_modes),
            "neofelis_google_search_enabled": (
                snapshot.ask_apex.neofelis_google_search_enabled
            ),
            "neofelis_google_maps_enabled": (
                snapshot.ask_apex.neofelis_google_maps_enabled
            ),
            "delphinus_x_search_enabled": snapshot.ask_apex.delphinus_x_search_enabled,
            "orcinus_x_search_enabled": snapshot.ask_apex.orcinus_x_search_enabled,
        },
        "tool_profiles": snapshot.tool_profiles.model_dump(),
        "briefing": {
            "default_mode": snapshot.briefing.default_mode,
        },
        "tts_settings": {
            "primary_tts": snapshot.voice.engine,
            "voice_gender": snapshot.voice.gender,
            "voice_mode": snapshot.voice.mode,
        },
        "mcp": snapshot.mcp.model_dump(),
        "llama_cpp": snapshot.llama_cpp.model_dump(),
    }


def apply_patch_to_snapshot(
    snapshot: RuntimeSettingsSnapshot,
    patch: SettingsPatch,
) -> RuntimeSettingsSnapshot:
    """Merge a strict dirty-field patch onto a snapshot and return a new snapshot."""
    data = snapshot.model_dump()
    patch_data = patch.model_dump(exclude_none=True)
    if "user_designation" in patch_data:
        patch_data["user_designation"] = " ".join(
            patch_data["user_designation"].split()
        )
    return RuntimeSettingsSnapshot.model_validate(recursive_overlay(data, patch_data))


def patch_to_ondisk(patch: SettingsPatch) -> dict[str, Any]:
    """Map a logical SettingsPatch onto on-disk key structure (dirty fields only)."""
    ondisk: dict[str, Any] = {}
    if patch.user_designation is not None:
        ondisk["user_designation"] = " ".join(patch.user_designation.split())
    if patch.features is not None:
        features = {
            key: value
            for key, value in patch.features.model_dump(exclude_none=True).items()
        }
        if features:
            ondisk["features"] = features
    if patch.modules is not None:
        modules = {
            key: value
            for key, value in patch.modules.model_dump(exclude_none=True).items()
        }
        if modules:
            ondisk["modules"] = modules
    if patch.football is not None and patch.football.teams is not None:
        ondisk["football"] = {
            "teams": [
                {"id": team.id, "name": team.name}
                for team in patch.football.teams
            ]
        }
    if patch.market is not None and patch.market.symbols is not None:
        ondisk["market"] = {
            "symbols": [symbol.strip().upper() for symbol in patch.market.symbols if symbol.strip()]
        }
    if patch.ask_apex is not None:
        ask_apex: dict[str, Any] = {}
        ask_apex_patch = patch.ask_apex.model_dump(exclude_none=True)
        ask_apex.update(ask_apex_patch)
        if ask_apex:
            ondisk["ask_apex"] = ask_apex
    if patch.tool_profiles is not None:
        tool_profiles: dict[str, Any] = {}
        if patch.tool_profiles.custom_profiles is not None:
            serialized_profiles: list[dict[str, Any]] = []
            for profile in patch.tool_profiles.custom_profiles:
                serialized = profile.model_dump()
                serialized["tool_names"] = list(profile.tool_names)
                serialized_profiles.append(serialized)
            tool_profiles["custom_profiles"] = serialized_profiles
        if patch.tool_profiles.default_profile_by_agent is not None:
            tool_profiles["default_profile_by_agent"] = {
                agent.strip().lower(): profile_id.strip().lower()
                for agent, profile_id in patch.tool_profiles.default_profile_by_agent.items()
            }
        if tool_profiles:
            ondisk["tool_profiles"] = tool_profiles
    if patch.briefing is not None:
        briefing: dict[str, Any] = {}
        if patch.briefing.default_mode is not None:
            briefing["default_mode"] = patch.briefing.default_mode
        if briefing:
            ondisk["briefing"] = briefing
    if patch.voice is not None:
        tts: dict[str, Any] = {}
        if patch.voice.engine is not None:
            tts["primary_tts"] = patch.voice.engine
        if patch.voice.gender is not None:
            tts["voice_gender"] = patch.voice.gender
        if patch.voice.mode is not None:
            tts["voice_mode"] = patch.voice.mode
        if tts:
            ondisk["tts_settings"] = tts
    if patch.mcp is not None:
        mcp: dict[str, Any] = {}
        if patch.mcp.enabled is not None:
            mcp["enabled"] = patch.mcp.enabled
        if patch.mcp.servers is not None:
            servers: dict[str, Any] = {}
            for provider, provider_patch in patch.mcp.servers:
                if provider_patch is not None and provider_patch.enabled is not None:
                    servers[provider] = {"enabled": provider_patch.enabled}
            if servers:
                mcp["servers"] = servers
        if mcp:
            ondisk["mcp"] = mcp
    if patch.llama_cpp is not None:
        llama_cpp: dict[str, Any] = {}
        if patch.llama_cpp.enabled is not None:
            llama_cpp["enabled"] = patch.llama_cpp.enabled
        if patch.llama_cpp.managed is not None:
            llama_cpp["managed"] = patch.llama_cpp.managed
        if patch.llama_cpp.host is not None:
            llama_cpp["host"] = patch.llama_cpp.host
        if patch.llama_cpp.executable_path is not None:
            llama_cpp["executable_path"] = patch.llama_cpp.executable_path
        if patch.llama_cpp.preset_path is not None:
            llama_cpp["preset_path"] = patch.llama_cpp.preset_path
        if llama_cpp:
            ondisk["llama_cpp"] = llama_cpp
    return ondisk
