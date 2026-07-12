"""Typed models for editable runtime settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssistantProfile = Literal[
    "comet", "nova", "pulsar", "lynx", "acinonyx", "neofelis"
]
VoiceEngine = Literal["google", "pyttsx3", "kokoro"]
VoiceGender = Literal["male", "female"]

VALID_ASSISTANT_PROFILES: frozenset[str] = frozenset(
    {"comet", "nova", "pulsar", "lynx", "acinonyx", "neofelis"}
)
VALID_VOICE_ENGINES: frozenset[str] = frozenset({"google", "pyttsx3", "kokoro"})
VALID_VOICE_GENDERS: frozenset[str] = frozenset({"male", "female"})

SETTINGS_SCHEMA_VERSION: int = 1


class FeaturesSettings(BaseModel):
    """Connector feature toggles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weather: bool = False
    sports: bool = False
    news: bool = False
    email: bool = False
    calendar: bool = False


class ModulesSettings(BaseModel):
    """Sports sub-module toggles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    football: bool = False
    f1: bool = False


class AssistantSettings(BaseModel):
    """Ask-APEX assistant enablement and default profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    default_profile: AssistantProfile = "comet"


class VoiceSettings(BaseModel):
    """TTS engine and voice gender."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: VoiceEngine = "pyttsx3"
    gender: VoiceGender = "female"


class RuntimeSettingsSnapshot(BaseModel):
    """Immutable published view of resolved editable settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    features: FeaturesSettings = Field(default_factory=FeaturesSettings)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    assistant: AssistantSettings = Field(default_factory=AssistantSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)


class FeaturesPatch(BaseModel):
    """Partial features patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    weather: bool | None = None
    sports: bool | None = None
    news: bool | None = None
    email: bool | None = None
    calendar: bool | None = None


class ModulesPatch(BaseModel):
    """Partial modules patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    football: bool | None = None
    f1: bool | None = None


class AssistantPatch(BaseModel):
    """Partial assistant patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    default_profile: AssistantProfile | None = None


class VoicePatch(BaseModel):
    """Partial voice patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    engine: VoiceEngine | None = None
    gender: VoiceGender | None = None


class SettingsPatch(BaseModel):
    """Strict dirty-field patch for transactional settings updates."""

    model_config = ConfigDict(extra="forbid")

    features: FeaturesPatch | None = None
    modules: ModulesPatch | None = None
    assistant: AssistantPatch | None = None
    voice: VoicePatch | None = None


class SettingsResponse(BaseModel):
    """Public settings API envelope for GET and successful PATCH."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = SETTINGS_SCHEMA_VERSION
    settings: RuntimeSettingsSnapshot
    local_file_present: bool
    local_override_active: bool
    load_warning: str | None = None
    dev_mode_active: bool
    demo_mode_active: bool
