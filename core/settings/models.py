"""Typed models for editable runtime settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CloudSettingsAgent = Literal["panthera", "neofelis", "delphinus", "orcinus"]
LocalSettingsAgent = Literal["sorex", "mus", "apodemus"]
ApodemusContextWindow = Literal[4096, 8192, 16384, 32768]
AgentRuntime = Literal["cloud", "local"]
CloudEffort = Literal["light", "focused", "extended"]
BriefingMode = Literal["panthera", "mus", "sorex", "structured_digest"]
VoiceEngine = Literal["google", "pyttsx3", "kokoro"]
VoiceGender = Literal["male", "female"]
VoiceMode = Literal["off", "manual", "automatic"]

VALID_CLOUD_SETTINGS_AGENTS: frozenset[str] = frozenset(
    {"panthera", "neofelis", "delphinus", "orcinus"}
)
VALID_LOCAL_SETTINGS_AGENTS: frozenset[str] = frozenset({"sorex", "mus", "apodemus"})
VALID_APODEMUS_CONTEXT_WINDOWS: frozenset[int] = frozenset(
    {4096, 8192, 16384, 32768}
)
VALID_CLOUD_EFFORTS: frozenset[str] = frozenset({"light", "focused", "extended"})
VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"panthera", "mus", "sorex", "structured_digest"}
)
VALID_VOICE_ENGINES: frozenset[str] = frozenset({"google", "pyttsx3", "kokoro"})
VALID_VOICE_GENDERS: frozenset[str] = frozenset({"male", "female"})
VALID_VOICE_MODES: frozenset[str] = frozenset({"off", "manual", "automatic"})

SETTINGS_SCHEMA_VERSION: int = 10
MCP_PROVIDER_IDS: tuple[str, ...] = ("github", "brave", "alphavantage")

LlamaCppServerState = Literal[
    "disabled",
    "external_connected",
    "managed_running",
    "starting",
    "managed_stopped",
    "startup_failed",
]
LlamaCppServerOwnership = Literal["none", "external", "apex"]


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


class FootballTeamSettings(BaseModel):
    """One followed football-data.org team, configured outside Runtime Settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)


class FootballSettings(BaseModel):
    """Read-only football connector preferences from the configuration files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    teams: tuple[FootballTeamSettings, ...] = ()


class AskApexSettings(BaseModel):
    """Ask APEX enablement, runtime, Agent, and grounding preferences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    runtime: AgentRuntime = "cloud"
    cloud_agent: CloudSettingsAgent = "panthera"
    effort: CloudEffort = "focused"
    local_agent: LocalSettingsAgent = "mus"
    apodemus_context_window: ApodemusContextWindow = 8192
    neofelis_google_search_enabled: bool = True
    neofelis_google_maps_enabled: bool = True
    delphinus_x_search_enabled: bool = True
    orcinus_x_search_enabled: bool = True


class BriefingSettings(BaseModel):
    """Default briefing synthesis mode for generate and trigger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_mode: BriefingMode = "panthera"


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


class LlamaCppSettings(BaseModel):
    """Editable llama.cpp router enablement, host, and optional managed server."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    managed: bool = False
    host: str = "http://127.0.0.1:8080"
    executable_path: str = ""
    preset_path: str = ""


class RuntimeSettingsSnapshot(BaseModel):
    """Immutable published view of resolved editable settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_designation: str = Field(
        default="",
        max_length=80,
        description="Optional local designation used when addressing the user.",
    )
    features: FeaturesSettings = Field(default_factory=FeaturesSettings)
    modules: ModulesSettings = Field(default_factory=ModulesSettings)
    football: FootballSettings = Field(default_factory=FootballSettings)
    ask_apex: AskApexSettings = Field(default_factory=AskApexSettings)
    briefing: BriefingSettings = Field(default_factory=BriefingSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    llama_cpp: LlamaCppSettings = Field(default_factory=LlamaCppSettings)


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


class AskApexPatch(BaseModel):
    """Partial Ask APEX patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    runtime: AgentRuntime | None = None
    cloud_agent: CloudSettingsAgent | None = None
    effort: CloudEffort | None = None
    local_agent: LocalSettingsAgent | None = None
    apodemus_context_window: ApodemusContextWindow | None = None
    neofelis_google_search_enabled: bool | None = None
    neofelis_google_maps_enabled: bool | None = None
    delphinus_x_search_enabled: bool | None = None
    orcinus_x_search_enabled: bool | None = None


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


class LlamaCppPatch(BaseModel):
    """Partial llama.cpp runtime patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    managed: bool | None = None
    host: str | None = None
    executable_path: str | None = None
    preset_path: str | None = None


class LlamaCppServerStatusResponse(BaseModel):
    """Sanitized llama.cpp server ownership status for the Settings UI."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    managed: bool
    ownership: LlamaCppServerOwnership
    state: LlamaCppServerState
    last_error: str | None = None


class SettingsPatch(BaseModel):
    """Strict dirty-field patch for transactional settings updates."""

    model_config = ConfigDict(extra="forbid")

    user_designation: str | None = Field(default=None, max_length=80)
    features: FeaturesPatch | None = None
    modules: ModulesPatch | None = None
    ask_apex: AskApexPatch | None = None
    briefing: BriefingPatch | None = None
    voice: VoicePatch | None = None
    mcp: McpPatch | None = None
    llama_cpp: LlamaCppPatch | None = None


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
