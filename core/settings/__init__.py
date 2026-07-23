"""Runtime settings foundation: models, normalize, and process-wide store."""

from __future__ import annotations

from core.settings.models import (
    SETTINGS_SCHEMA_VERSION,
    AssistantPatch,
    AssistantSettings,
    BriefingPatch,
    BriefingSettings,
    FeaturesPatch,
    FeaturesSettings,
    ModulesPatch,
    ModulesSettings,
    RuntimeSettingsSnapshot,
    SettingsPatch,
    SettingsResponse,
    VoicePatch,
    VoiceSettings,
)
from core.settings.store import (
    RuntimeSettingsStore,
    SettingsPersistenceError,
    get_settings_store,
    reset_settings_store_for_tests,
)

__all__ = [
    "SETTINGS_SCHEMA_VERSION",
    "AssistantPatch",
    "AssistantSettings",
    "BriefingPatch",
    "BriefingSettings",
    "FeaturesPatch",
    "FeaturesSettings",
    "ModulesPatch",
    "ModulesSettings",
    "RuntimeSettingsSnapshot",
    "RuntimeSettingsStore",
    "SettingsPatch",
    "SettingsPersistenceError",
    "SettingsResponse",
    "VoicePatch",
    "VoiceSettings",
    "get_settings_store",
    "reset_settings_store_for_tests",
]
