"""Legacy-key normalization, overlay merge, and on-disk mapping helpers."""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from core.agent.model_catalog import (
    DEFAULT_FELIS_MODEL,
    DEFAULT_FELIS_RUNTIME,
    get_model_profile,
    reconcile_felis_context_window,
    reconcile_felis_model,
    reconcile_felis_reasoning_mode,
    reconcile_panthera_model,
    reconcile_panthera_reasoning,
)
from core.config import is_dev_mode
from core.settings.models import (
    VALID_AGENT_KEYS,
    VALID_BRIEFING_MODES,
    VALID_CLOUD_EFFORTS,
    VALID_VOICE_ENGINES,
    VALID_VOICE_GENDERS,
    VALID_VOICE_MODES,
    AgentSettings,
    BriefingSettings,
    FeaturesSettings,
    FelisSettings,
    FootballSettings,
    FootballTeamSettings,
    LlamaCppSettings,
    MicrosoftTodoSettings,
    MarketSettings,
    McpServerEnablementSettings,
    PantheraHostedToolsSettings,
    PantheraSettings,
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
        "microsoft_todo",
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
            agent_settings = _normalize_agent_settings(value, layer_name, issues)
            if agent_settings:
                normalized["ask_apex"] = agent_settings
        elif key == "tool_profiles":
            tool_profiles = _normalize_tool_profiles(value, layer_name, issues)
            if tool_profiles:
                normalized["tool_profiles"] = tool_profiles
        elif key == "briefing":
            briefing = _normalize_briefing(
                value, layer_name, issues
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
        elif key == "microsoft_todo":
            microsoft_todo = _normalize_microsoft_todo(value, layer_name, issues)
            if microsoft_todo is not None:
                normalized["microsoft_todo"] = microsoft_todo

    return normalized


def _normalize_microsoft_todo(
    value: Any, layer_name: str, issues: NormalizationIssues | None
) -> dict[str, Any] | None:
    """Normalize the intentionally small reminder-list selection setting."""
    if not isinstance(value, dict):
        _record_error(issues, "microsoft_todo must be an object")
        _LOGGER.warning("microsoft_todo in %s must be an object; ignoring.", layer_name)
        return None
    unknown = set(value) - {"reminder_list_id"}
    if unknown:
        _record_warning(issues, "microsoft_todo contains unknown fields")
        _LOGGER.warning("Ignoring unknown microsoft_todo fields in %s.", layer_name)
    if "reminder_list_id" not in value:
        return {}
    list_id = value["reminder_list_id"]
    if not isinstance(list_id, str) or len(list_id) > 512 or (
        list_id and list_id != list_id.strip()
    ):
        _record_error(issues, "microsoft_todo.reminder_list_id is invalid")
        _LOGGER.warning("microsoft_todo.reminder_list_id in %s is invalid; ignoring.", layer_name)
        return {}
    return {"reminder_list_id": list_id}


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


def _normalize_agent_settings(
    value: Any, layer_name: str, errors: NormalizationIssues | None
) -> dict[str, Any]:
    if not isinstance(value, dict):
        if value is not None:
            _record_error(errors, "ask_apex must be a JSON object")
            _LOGGER.warning(
                'Config key "ask_apex" in %s must be a JSON object.', layer_name
            )
        return {}

    _record_unsupported_agent_fields(
        value,
        allowed={
            "enabled",
            "agent",
            "sandbox_mode",
            "panthera",
            "felis",
            "max_session_messages",
            "apodemus_context_window",
        },
        path="ask_apex",
        layer_name=layer_name,
        errors=errors,
    )
    result: dict[str, Any] = {}

    if isinstance(value.get("enabled"), bool):
        result["enabled"] = value["enabled"]
    elif value.get("enabled") is not None:
        _record_error(errors, "ask_apex.enabled must be a boolean")

    agent = value.get("agent", "panthera")
    if agent in VALID_AGENT_KEYS:
        result["agent"] = agent
    elif agent is not None:
        _record_error(errors, "ask_apex.agent is not valid")

    if "sandbox_mode" in value:
        if isinstance(value["sandbox_mode"], bool):
            result["sandbox_mode"] = value["sandbox_mode"]
        elif value["sandbox_mode"] is not None:
            _record_error(errors, "ask_apex.sandbox_mode must be a boolean")

    panthera_raw = value.get("panthera")
    if isinstance(panthera_raw, dict):
        _record_unsupported_agent_fields(
            panthera_raw,
            allowed={"model", "effort", "hosted_tools"},
            path="ask_apex.panthera",
            layer_name=layer_name,
            errors=errors,
        )
        panthera: dict[str, Any] = {}
        model = panthera_raw.get("model")
        if isinstance(model, str) and get_model_profile(model.strip()) is not None:
            profile = get_model_profile(model.strip())
            if profile is not None and profile.runtime == "cloud":
                reconciled_model = reconcile_panthera_model(
                    model.strip(),
                    dev_mode=is_dev_mode(),
                )
                panthera["model"] = reconciled_model
            else:
                _record_error(errors, "ask_apex.panthera.model is not valid")
        elif model is not None:
            _record_error(errors, "ask_apex.panthera.model is not valid")
        effort = panthera_raw.get("effort")
        if isinstance(effort, str):
            effort_str = effort.strip().lower()
            if effort_str in VALID_CLOUD_EFFORTS:
                panthera["effort"] = effort_str
            else:
                _record_error(errors, "ask_apex.panthera.effort is not valid")
        elif effort is not None:
            _record_error(errors, "ask_apex.panthera.effort is not valid")
        if "model" in panthera:
            reconciled_effort = reconcile_panthera_reasoning(
                panthera["model"], panthera.get("effort")
            )
            if reconciled_effort is not None:
                panthera["effort"] = reconciled_effort
        hosted_raw = panthera_raw.get("hosted_tools")
        if isinstance(hosted_raw, dict):
            _record_unsupported_agent_fields(
                hosted_raw,
                allowed={"google_search", "google_maps", "x_search"},
                path="ask_apex.panthera.hosted_tools",
                layer_name=layer_name,
                errors=errors,
            )
            hosted: dict[str, bool] = {}
            for key in ("google_search", "google_maps", "x_search"):
                if isinstance(hosted_raw.get(key), bool):
                    hosted[key] = hosted_raw[key]
            if hosted:
                panthera["hosted_tools"] = hosted
        elif hosted_raw is not None:
            _record_error(errors, "ask_apex.panthera.hosted_tools must be an object")
        if panthera:
            result["panthera"] = panthera
    elif panthera_raw is not None:
        _record_error(errors, "ask_apex.panthera must be an object")

    felis_raw = value.get("felis")
    if isinstance(felis_raw, dict):
        _record_unsupported_agent_fields(
            felis_raw,
            allowed={"model", "context_window", "reasoning_mode"},
            path="ask_apex.felis",
            layer_name=layer_name,
            errors=errors,
        )
        felis: dict[str, Any] = {}
        model = felis_raw.get("model")
        if isinstance(model, str) and get_model_profile(model.strip()) is not None:
            profile = get_model_profile(model.strip())
            if profile is not None and profile.runtime == "local":
                reconciled_model = reconcile_felis_model(
                    model.strip(),
                    dev_mode=is_dev_mode(),
                )
                felis["model"] = reconciled_model
            else:
                _record_error(errors, "ask_apex.felis.model is not valid")
        elif model is not None:
            _record_error(errors, "ask_apex.felis.model is not valid")
        context_window = felis_raw.get("context_window")
        if isinstance(context_window, int) and not isinstance(context_window, bool):
            felis["context_window"] = context_window
        elif context_window is not None:
            _record_error(errors, "ask_apex.felis.context_window must be an integer")
        reasoning_mode = felis_raw.get("reasoning_mode")
        if isinstance(reasoning_mode, str) and reasoning_mode in {"none", "focused"}:
            felis["reasoning_mode"] = reasoning_mode
        elif reasoning_mode is not None:
            _record_error(errors, "ask_apex.felis.reasoning_mode is not valid")
        if felis:
            result["felis"] = felis
    elif felis_raw is not None:
        _record_error(errors, "ask_apex.felis must be an object")

    felis_result = result.get("felis")
    if isinstance(felis_result, dict):
        model = felis_result.get("model", DEFAULT_FELIS_MODEL)
        profile = get_model_profile(model) if isinstance(model, str) else None
        runtime = (
            profile.provider
            if profile is not None and profile.runtime == "local"
            else DEFAULT_FELIS_RUNTIME
        )
        if isinstance(model, str):
            context_window = felis_result.get("context_window")
            if isinstance(context_window, int) and not isinstance(context_window, bool):
                felis_result["context_window"] = reconcile_felis_context_window(
                    runtime,  # type: ignore[arg-type]
                    model,
                    context_window,
                )
            reasoning_mode = felis_result.get("reasoning_mode")
            if isinstance(reasoning_mode, str) and reasoning_mode in {"none", "focused"}:
                felis_result["reasoning_mode"] = reconcile_felis_reasoning_mode(
                    model,
                    reasoning_mode,  # type: ignore[arg-type]
                )

    return result


def _record_unsupported_agent_fields(
    value: dict[str, Any],
    *,
    allowed: set[str],
    path: str,
    layer_name: str,
    errors: NormalizationIssues | None,
) -> None:
    """Reject stale Agent/provider/runtime keys instead of silently dropping them."""
    local_override = layer_name == "config.local.json"
    for key in sorted(set(value) - allowed):
        if local_override:
            _record_error(
                errors,
                f"unsupported Agent settings format; reset local settings ({path}.{key})",
            )
            _LOGGER.warning(
                "Unsupported Agent settings field %r in %s; reset local settings.",
                f"{path}.{key}",
                layer_name,
            )


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
                    and agent.strip().lower() in VALID_AGENT_KEYS
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

    for key, raw in value.items():
        if key == "default_mode":
            mode = _coerce_briefing_mode(
                raw,
                layer_name=layer_name,
                errors=errors,
            )
            if mode is not None:
                result["default_mode"] = mode
        else:
            _LOGGER.warning(
                "Ignoring unknown briefing key %r in %s.", key, layer_name
            )
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
    agent_settings_raw = merged.get("ask_apex") if isinstance(merged.get("ask_apex"), dict) else {}
    tool_profiles_raw = (
        merged.get("tool_profiles")
        if isinstance(merged.get("tool_profiles"), dict)
        else {}
    )
    agent_settings = _normalize_agent_settings(agent_settings_raw, layer_name="snapshot", errors=None)
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
    agent_settings_snapshot = AgentSettings.model_validate(agent_settings)
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
            if str(agent).strip().lower() in VALID_AGENT_KEYS and str(profile_id).strip()
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
    default_mode = briefing_raw.get("default_mode", "panthera")
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
    microsoft_todo_raw = (
        merged.get("microsoft_todo")
        if isinstance(merged.get("microsoft_todo"), dict)
        else {}
    )
    reminder_list_id = microsoft_todo_raw.get("reminder_list_id", "")
    if (
        not isinstance(reminder_list_id, str)
        or len(reminder_list_id) > 512
        or (reminder_list_id and reminder_list_id != reminder_list_id.strip())
    ):
        reminder_list_id = ""
    microsoft_todo = MicrosoftTodoSettings(reminder_list_id=reminder_list_id)
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
        ask_apex=agent_settings_snapshot,
        tool_profiles=tool_profiles,
        briefing=briefing,
        voice=voice,
        mcp=mcp,
        llama_cpp=llama_cpp,
        microsoft_todo=microsoft_todo,
    )


def snapshot_to_ondisk(snapshot: RuntimeSettingsSnapshot) -> dict[str, Any]:
    """Serialize a snapshot to on-disk editable section keys."""
    return {
        "user_designation": snapshot.user_designation,
        "features": snapshot.features.model_dump(),
        "modules": snapshot.modules.model_dump(),
        "ask_apex": {
            "enabled": snapshot.ask_apex.enabled,
            "agent": snapshot.ask_apex.agent,
            "sandbox_mode": snapshot.ask_apex.sandbox_mode,
            "panthera": snapshot.ask_apex.panthera.model_dump(),
            "felis": snapshot.ask_apex.felis.model_dump(),
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
        "microsoft_todo": snapshot.microsoft_todo.model_dump(),
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
        agent_settings_payload: dict[str, Any] = {}
        agent_settings_patch = patch.ask_apex.model_dump(exclude_none=True)
        agent_settings_payload.update(agent_settings_patch)
        if agent_settings_payload:
            ondisk["ask_apex"] = agent_settings_payload
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
    if patch.microsoft_todo is not None and patch.microsoft_todo.reminder_list_id is not None:
        ondisk["microsoft_todo"] = {
            "reminder_list_id": patch.microsoft_todo.reminder_list_id,
        }
    return ondisk
