"""Runtime settings foundation: models, normalize, and process-wide store."""

from __future__ import annotations

from core.settings.models import (
    AssistantPatch,
    AssistantSettings,
    FeaturesPatch,
    FeaturesSettings,
    ModulesPatch,
    ModulesSettings,
    RuntimeSettingsSnapshot,
    SettingsPatch,
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
    "AssistantPatch",
    "AssistantSettings",
    "FeaturesPatch",
    "FeaturesSettings",
    "ModulesPatch",
    "ModulesSettings",
    "RuntimeSettingsSnapshot",
    "RuntimeSettingsStore",
    "SettingsPatch",
    "SettingsPersistenceError",
    "VoicePatch",
    "VoiceSettings",
    "get_settings_store",
    "reset_settings_store_for_tests",
]
