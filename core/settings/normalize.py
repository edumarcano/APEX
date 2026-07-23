"""Legacy-key normalization, overlay merge, and on-disk mapping helpers."""

from __future__ import annotations

import copy
import logging
from typing import Any

from core.settings.models import (
    VALID_ASSISTANT_PROFILES,
    VALID_BRIEFING_MODES,
    VALID_VOICE_ENGINES,
    VALID_VOICE_GENDERS,
    VALID_VOICE_MODES,
    AssistantSettings,
    BriefingSettings,
    FeaturesSettings,
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
    {"features", "modules", "ask_apex", "briefing", "tts_settings"}
)


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
    validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    """
    Normalize a single config layer for editable settings.

    - Prefer ``ask_apex.default_profile``; fall back to ``default_cloud_profile``.
    - Map legacy TTS engine ``piper`` to ``pyttsx3``.
    - Warn and drop unknown keys under editable sections.
    """
    if not isinstance(raw, dict):
        _LOGGER.warning("%s root must be a JSON object; ignoring layer.", layer_name)
        return {}

    normalized: dict[str, Any] = {}

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
                value, layer_name, validation_errors
            )
        elif key == "modules":
            normalized["modules"] = _normalize_modules(
                value, layer_name, validation_errors
            )
        elif key == "ask_apex":
            ask_apex = _normalize_ask_apex(value, layer_name, validation_errors)
            if ask_apex:
                normalized["ask_apex"] = ask_apex
        elif key == "briefing":
            briefing = _normalize_briefing(value, layer_name, validation_errors)
            if briefing:
                normalized["briefing"] = briefing
        elif key == "tts_settings":
            tts = _normalize_tts_settings(value, layer_name, validation_errors)
            if tts:
                normalized["tts_settings"] = tts

    return normalized


def _record_error(errors: list[str] | None, message: str) -> None:
    if errors is not None:
        errors.append(message)


def _normalize_features(
    value: Any, layer_name: str, errors: list[str] | None
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
    value: Any, layer_name: str, errors: list[str] | None
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
    value: Any, layer_name: str, errors: list[str] | None
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if not isinstance(value, dict):
        if value is not None:
            _record_error(errors, "ask_apex must be a JSON object")
            _LOGGER.warning(
                'Config key "ask_apex" in %s must be a JSON object.', layer_name
            )
        return result

    known_keys = {
        "enabled",
        "default_profile",
        "default_cloud_profile",
        "max_session_messages",
    }
    for key in value:
        if key not in known_keys:
            _LOGGER.warning(
                "Ignoring unknown ask_apex key %r in %s.", key, layer_name
            )

    enabled_raw = value.get("enabled")
    if isinstance(enabled_raw, bool):
        result["enabled"] = enabled_raw
    elif enabled_raw is not None:
        _record_error(errors, "ask_apex.enabled must be a boolean")
        _LOGGER.warning(
            "ask_apex.enabled in %s must be a boolean; ignoring.",
            layer_name,
        )

    # Prefer default_profile; retain default_cloud_profile as read-time fallback.
    if "default_profile" in value:
        preferred = _coerce_profile(
            value.get("default_profile"),
            key="ask_apex.default_profile",
            layer_name=layer_name,
            errors=errors,
        )
        if preferred is not None:
            result["default_profile"] = preferred
        elif "default_cloud_profile" in value:
            legacy = _coerce_profile(
                value.get("default_cloud_profile"),
                key="ask_apex.default_cloud_profile",
                layer_name=layer_name,
                errors=errors,
            )
            if legacy is not None:
                result["default_profile"] = legacy
    elif "default_cloud_profile" in value:
        legacy = _coerce_profile(
            value.get("default_cloud_profile"),
            key="ask_apex.default_cloud_profile",
            layer_name=layer_name,
            errors=errors,
        )
        if legacy is not None:
            result["default_profile"] = legacy

    return result


def _coerce_profile(
    raw: Any, *, key: str, layer_name: str, errors: list[str] | None
) -> str | None:
    if not isinstance(raw, str):
        if raw is not None:
            _record_error(errors, f"{key} must be a string")
            _LOGGER.warning(
                "Config key %r in %s must be a string; ignoring.",
                key,
                layer_name,
            )
        return None
    normalized = raw.strip().lower()
    if normalized in VALID_ASSISTANT_PROFILES:
        return normalized
    _record_error(errors, f"{key} is not a valid profile")
    _LOGGER.warning(
        "Config key %r=%r in %s is not a valid profile; ignoring.",
        key,
        raw,
        layer_name,
    )
    return None


def _normalize_tts_settings(
    value: Any, layer_name: str, errors: list[str] | None
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
    value: Any, layer_name: str, errors: list[str] | None
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
            mode = _coerce_briefing_mode(raw, layer_name=layer_name, errors=errors)
            if mode is not None:
                result["default_mode"] = mode
        else:
            _LOGGER.warning(
                "Ignoring unknown briefing key %r in %s.", key, layer_name
            )
    return result


def _coerce_briefing_mode(
    raw: Any, *, layer_name: str, errors: list[str] | None
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
    raw: Any, *, layer_name: str, errors: list[str] | None
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
    raw: Any, *, layer_name: str, errors: list[str] | None
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
    raw: Any, *, layer_name: str, errors: list[str] | None
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
    ask_apex = merged.get("ask_apex") if isinstance(merged.get("ask_apex"), dict) else {}
    tts = merged.get("tts_settings") if isinstance(merged.get("tts_settings"), dict) else {}

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
    profile = ask_apex.get("default_profile", "comet")
    if profile not in VALID_ASSISTANT_PROFILES:
        profile = "comet"
    assistant = AssistantSettings(
        enabled=bool(ask_apex.get("enabled", True))
        if "enabled" in ask_apex
        else True,
        default_profile=profile,  # type: ignore[arg-type]
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
    default_mode = briefing_raw.get("default_mode", "comet")
    if default_mode not in VALID_BRIEFING_MODES:
        default_mode = "comet"
    briefing = BriefingSettings(
        default_mode=default_mode,  # type: ignore[arg-type]
    )
    return RuntimeSettingsSnapshot(
        features=features,
        modules=modules,
        assistant=assistant,
        briefing=briefing,
        voice=voice,
    )


def snapshot_to_ondisk(snapshot: RuntimeSettingsSnapshot) -> dict[str, Any]:
    """Serialize a snapshot to on-disk editable section keys."""
    return {
        "features": snapshot.features.model_dump(),
        "modules": snapshot.modules.model_dump(),
        "ask_apex": {
            "enabled": snapshot.assistant.enabled,
            "default_profile": snapshot.assistant.default_profile,
        },
        "briefing": {
            "default_mode": snapshot.briefing.default_mode,
        },
        "tts_settings": {
            "primary_tts": snapshot.voice.engine,
            "voice_gender": snapshot.voice.gender,
            "voice_mode": snapshot.voice.mode,
        },
    }


def apply_patch_to_snapshot(
    snapshot: RuntimeSettingsSnapshot,
    patch: SettingsPatch,
) -> RuntimeSettingsSnapshot:
    """Merge a strict dirty-field patch onto a snapshot and return a new snapshot."""
    data = snapshot.model_dump()
    patch_data = patch.model_dump(exclude_none=True)
    for section, values in patch_data.items():
        if not isinstance(values, dict):
            continue
        current = data.setdefault(section, {})
        for key, value in values.items():
            current[key] = value
    return RuntimeSettingsSnapshot.model_validate(data)


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
    if patch.assistant is not None:
        ask_apex: dict[str, Any] = {}
        if patch.assistant.enabled is not None:
            ask_apex["enabled"] = patch.assistant.enabled
        if patch.assistant.default_profile is not None:
            ask_apex["default_profile"] = patch.assistant.default_profile
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
    return ondisk
