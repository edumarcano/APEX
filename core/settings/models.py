"""Typed models for editable runtime settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AssistantProfile = Literal[
    "comet", "nova", "pulsar", "lynx", "acinonyx", "neofelis"
]
BriefingMode = Literal[
    "comet", "lynx", "acinonyx", "neofelis", "structured_digest"
]
VoiceEngine = Literal["google", "pyttsx3", "kokoro"]
VoiceGender = Literal["male", "female"]
VoiceMode = Literal["off", "manual", "automatic"]

VALID_ASSISTANT_PROFILES: frozenset[str] = frozenset(
    {"comet", "nova", "pulsar", "lynx", "acinonyx", "neofelis"}
)
VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"comet", "lynx", "acinonyx", "neofelis", "structured_digest"}
)
VALID_VOICE_ENGINES: frozenset[str] = frozenset({"google", "pyttsx3", "kokoro"})
VALID_VOICE_GENDERS: frozenset[str] = frozenset({"male", "female"})
VALID_VOICE_MODES: frozenset[str] = frozenset({"off", "manual", "automatic"})

SETTINGS_SCHEMA_VERSION: int = 4
MCP_PROVIDER_IDS: tuple[str, ...] = ("github", "brave", "alphavantage")


class FeaturesSettings(BaseModel):
    """Connector feature toggles."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    weather: bool = False
    sports: bool = False
    news: bool = False
    email: bool = False
    calendar: bool = False
    market: bool = False


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


class BriefingSettings(BaseModel):
    """Default briefing synthesis mode for generate and trigger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_mode: BriefingMode = "comet"


class VoiceSettings(BaseModel):
    """TTS engine, voice gender, and delivery mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: VoiceEngine = "pyttsx3"
    gender: VoiceGender = "female"
    mode: VoiceMode = "automatic"


class McpServerEnablementSettings(BaseModel):
    """Editable enablement for one tracked MCP provider preset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False


class McpServersSettings(BaseModel):
    """Fixed MCP provider presets exposed through Runtime Settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    github: McpServerEnablementSettings = Field(
        default_factory=McpServerEnablementSettings
    )
    brave: McpServerEnablementSettings = Field(
        default_factory=McpServerEnablementSettings
    )
    alphavantage: McpServerEnablementSettings = Field(
        default_factory=McpServerEnablementSettings
    )


class McpSettings(BaseModel):
    """Editable MCP client and tracked-provider enablement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    servers: McpServersSettings = Field(default_factory=McpServersSettings)


class RuntimeSettingsSnapshot(BaseModel):
    """Immutable published view of resolved editable settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    features: FeaturesSettings = Field(default_factory=FeaturesSettings)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    assistant: AssistantSettings = Field(default_factory=AssistantSettings)
    briefing: BriefingSettings = Field(default_factory=BriefingSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)


class FeaturesPatch(BaseModel):
    """Partial features patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    weather: bool | None = None
    sports: bool | None = None
    news: bool | None = None
    email: bool | None = None
    calendar: bool | None = None
    market: bool | None = None


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


class BriefingPatch(BaseModel):
    """Partial briefing patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    default_mode: BriefingMode | None = None


class VoicePatch(BaseModel):
    """Partial voice patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    engine: VoiceEngine | None = None
    gender: VoiceGender | None = None
    mode: VoiceMode | None = None


class McpServerEnablementPatch(BaseModel):
    """Partial enablement update for one tracked MCP provider."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None


class McpServersPatch(BaseModel):
    """Partial updates for the fixed MCP provider presets."""

    model_config = ConfigDict(extra="forbid")

    github: McpServerEnablementPatch | None = None
    brave: McpServerEnablementPatch | None = None
    alphavantage: McpServerEnablementPatch | None = None


class McpPatch(BaseModel):
    """Partial MCP runtime enablement update."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    servers: McpServersPatch | None = None


class SettingsPatch(BaseModel):
    """Strict dirty-field patch for transactional settings updates."""

    model_config = ConfigDict(extra="forbid")

    features: FeaturesPatch | None = None
    modules: ModulesPatch | None = None
    assistant: AssistantPatch | None = None
    briefing: BriefingPatch | None = None
    voice: VoicePatch | None = None
    mcp: McpPatch | None = None


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
