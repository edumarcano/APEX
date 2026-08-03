"""Legacy-key normalization, overlay merge, and on-disk mapping helpers."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from core.agent.catalog import migrate_schema5_briefing, migrate_schema7_ask_apex
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
    McpServerEnablementSettings,
    McpServersSettings,
    McpSettings,
    MCP_PROVIDER_IDS,
    ModulesSettings,
    RuntimeSettingsSnapshot,
    SettingsPatch,
    VoiceSettings,
)

_LOGGER = logging.getLogger(__name__)

_FEATURE_KEYS: frozenset[str] = frozenset(
    {"weather", "sports", "news", "email", "calendar", "market"}
)
_MODULE_KEYS: frozenset[str] = frozenset({"football", "f1"})
_EDITABLE_ROOT_KEYS: frozenset[str] = frozenset(
    {"features", "modules", "football", "ask_apex", "briefing", "tts_settings", "mcp"}
)


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
        if key not in _EDITABLE_ROOT_KEYS:
            if key not in (
                "system_prompt",
                "synthesis",
                "agent_system_prompt",
                "local_agent_system_prompt",
                "gemini",
                "ollama",
            ):
                _LOGGER.warning(
                    "Ignoring unknown config key %r in %s.",
                    key,
                    layer_name,
                )
            continue

        if key == "features":
            normalized["features"] = _normalize_features(
                value, layer_name, issues
            )
        elif key == "modules":
            normalized["modules"] = _normalize_modules(
                value, layer_name, issues
            )
        elif key == "football":
            football = _normalize_football(value, layer_name, issues)
            if football:
                normalized["football"] = football
        elif key == "ask_apex":
            ask_apex = _normalize_ask_apex(value, layer_name, issues)
            if ask_apex:
                normalized["ask_apex"] = ask_apex
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

    return normalized


def _normalize_football(
    value: Any, layer_name: str, issues: NormalizationIssues | None
) -> dict[str, Any]:
    """Validate the file-configured followed-team list as one replaceable value."""
    if not isinstance(value, dict):
        _record_error(issues, "football must be a JSON object")
        return {}
    teams = value.get("teams")
    if not isinstance(teams, list) or not 1 <= len(teams) <= 3:
        _record_error(issues, "football.teams must contain one to three teams")
        return {}
    normalized_teams: list[dict[str, Any]] = []
    team_ids: set[int] = set()
    for team in teams:
        if not isinstance(team, dict):
            _record_error(issues, "football.teams entries must be objects")
            return {}
        team_id = team.get("id")
        name = team.get("name")
        if isinstance(team_id, bool) or not isinstance(team_id, int) or team_id <= 0:
            _record_error(issues, "football team id must be a positive integer")
            return {}
        if team_id in team_ids:
            _record_error(issues, "football team ids must be unique")
            return {}
        if not isinstance(name, str) or not (clean_name := name.strip()) or len(clean_name) > 100:
            _record_error(issues, "football team name must be a non-empty string up to 100 characters")
            return {}
        team_ids.add(team_id)
        normalized_teams.append({"id": team_id, "name": clean_name})
    return {"teams": normalized_teams}


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
    ask_apex_raw = merged.get("ask_apex") if isinstance(merged.get("ask_apex"), dict) else {}
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
    runtime = ask_apex.get("runtime", "cloud")
    if runtime not in {"cloud", "local"}:
        runtime = "cloud"
    cloud_agent = ask_apex.get("cloud_agent", "panthera")
    if cloud_agent not in VALID_CLOUD_SETTINGS_AGENTS:
        cloud_agent = "panthera"
    effort = ask_apex.get("effort", "focused")
    if effort not in VALID_CLOUD_EFFORTS:
        effort = "focused"
    local_agent = ask_apex.get("local_agent", "mus")
    if local_agent not in VALID_LOCAL_SETTINGS_AGENTS:
        local_agent = "mus"
    ask_apex_settings = AskApexSettings(
        enabled=bool(ask_apex.get("enabled", True))
        if "enabled" in ask_apex
        else True,
        runtime=runtime,  # type: ignore[arg-type]
        cloud_agent=cloud_agent,  # type: ignore[arg-type]
        effort=effort,  # type: ignore[arg-type]
        local_agent=local_agent,  # type: ignore[arg-type]
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
    return RuntimeSettingsSnapshot(
        features=features,
        modules=modules,
        football=football,
        ask_apex=ask_apex_settings,
        briefing=briefing,
        voice=voice,
        mcp=mcp,
    )


def snapshot_to_ondisk(snapshot: RuntimeSettingsSnapshot) -> dict[str, Any]:
    """Serialize a snapshot to on-disk editable section keys."""
    return {
        "features": snapshot.features.model_dump(),
        "modules": snapshot.modules.model_dump(),
        "ask_apex": {
            "enabled": snapshot.ask_apex.enabled,
            "runtime": snapshot.ask_apex.runtime,
            "cloud_agent": snapshot.ask_apex.cloud_agent,
            "effort": snapshot.ask_apex.effort,
            "local_agent": snapshot.ask_apex.local_agent,
            "neofelis_google_search_enabled": (
                snapshot.ask_apex.neofelis_google_search_enabled
            ),
            "neofelis_google_maps_enabled": (
                snapshot.ask_apex.neofelis_google_maps_enabled
            ),
            "delphinus_x_search_enabled": snapshot.ask_apex.delphinus_x_search_enabled,
            "orcinus_x_search_enabled": snapshot.ask_apex.orcinus_x_search_enabled,
        },
        "briefing": {
            "default_mode": snapshot.briefing.default_mode,
        },
        "tts_settings": {
            "primary_tts": snapshot.voice.engine,
            "voice_gender": snapshot.voice.gender,
            "voice_mode": snapshot.voice.mode,
        },
        "mcp": snapshot.mcp.model_dump(),
    }


def apply_patch_to_snapshot(
    snapshot: RuntimeSettingsSnapshot,
    patch: SettingsPatch,
) -> RuntimeSettingsSnapshot:
    """Merge a strict dirty-field patch onto a snapshot and return a new snapshot."""
    data = snapshot.model_dump()
    patch_data = patch.model_dump(exclude_none=True)
    return RuntimeSettingsSnapshot.model_validate(recursive_overlay(data, patch_data))


def patch_to_ondisk(patch: SettingsPatch) -> dict[str, Any]:
    """Map a logical SettingsPatch onto on-disk key structure (dirty fields only)."""
    ondisk: dict[str, Any] = {}
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
    if patch.ask_apex is not None:
        ask_apex: dict[str, Any] = {}
        ask_apex_patch = patch.ask_apex.model_dump(exclude_none=True)
        ask_apex.update(ask_apex_patch)
        if ask_apex:
            ondisk["ask_apex"] = ask_apex
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
    return ondisk
