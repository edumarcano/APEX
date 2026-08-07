"""Typed models for editable runtime settings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from core.agent.types import LocalReasoningMode

CloudSettingsAgent = Literal["panthera", "neofelis", "delphinus", "orcinus"]
LocalSettingsAgent = Literal["sorex", "mus", "apodemus", "neotoma"]
AgentRuntime = Literal["cloud", "local"]
CloudEffort = Literal["light", "focused", "extended"]
BriefingMode = Literal["panthera", "mus", "sorex", "structured_digest"]
VoiceEngine = Literal["google", "pyttsx3", "kokoro"]
VoiceGender = Literal["male", "female"]
VoiceMode = Literal["off", "manual", "automatic"]

VALID_CLOUD_SETTINGS_AGENTS: frozenset[str] = frozenset(
    {"panthera", "neofelis", "delphinus", "orcinus"}
)
VALID_LOCAL_SETTINGS_AGENTS: frozenset[str] = frozenset(
    {"sorex", "mus", "apodemus", "neotoma"}
)
VALID_LOCAL_REASONING_MODES: frozenset[str] = frozenset({"none", "focused"})
VALID_CLOUD_EFFORTS: frozenset[str] = frozenset({"light", "focused", "extended"})
VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"panthera", "mus", "sorex", "structured_digest"}
)
VALID_VOICE_ENGINES: frozenset[str] = frozenset({"google", "pyttsx3", "kokoro"})
VALID_VOICE_GENDERS: frozenset[str] = frozenset({"male", "female"})
VALID_VOICE_MODES: frozenset[str] = frozenset({"off", "manual", "automatic"})

SETTINGS_SCHEMA_VERSION: int = 13
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


def _default_local_context_windows() -> dict[str, int]:
    """Resolve defaults from registered provider capabilities."""
    from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS

    return {
        agent_key: runtime.default_context_window
        for agent_key, runtime in LLAMA_CPP_RUNTIME_CONFIGS.items()
    }


def _validate_local_context_windows(
    value: dict[str, StrictInt],
) -> dict[str, StrictInt]:
    """Validate context preferences against the registered provider data."""
    from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS

    for agent_key, context_window in value.items():
        runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(agent_key)
        if runtime is None or context_window not in runtime.allowed_context_windows:
            raise ValueError(
                f"Unsupported local context preset for Agent {agent_key!r}: "
                f"{context_window!r}"
            )
    return value


def _default_local_reasoning_modes() -> dict[str, LocalReasoningMode]:
    """Keep every registered local Agent explicitly in the safe default mode."""
    return {agent_key: "none" for agent_key in VALID_LOCAL_SETTINGS_AGENTS}


def _validate_local_reasoning_modes(
    value: dict[str, LocalReasoningMode],
) -> dict[str, LocalReasoningMode]:
    """Validate reasoning preferences against provider-declared capabilities."""
    from core.agent.catalog import local_reasoning_modes_for_agent

    for agent_key, reasoning_mode in value.items():
        supported = local_reasoning_modes_for_agent(agent_key)
        if reasoning_mode not in supported:
            raise ValueError(
                f"Unsupported local reasoning mode for Agent {agent_key!r}: "
                f"{reasoning_mode!r}"
            )
    return value


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
    """One followed football-data.org team."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)


class FootballSettings(BaseModel):
    """Football connector preferences (up to three followed teams)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    teams: tuple[FootballTeamSettings, ...] = ()


class MarketSettings(BaseModel):
    """Market ticker symbols for the HUD monitor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbols: tuple[str, ...] = ()


class AskApexSettings(BaseModel):
    """Ask APEX enablement, runtime, Agent, and grounding preferences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    runtime: AgentRuntime = "cloud"
    cloud_agent: CloudSettingsAgent = "panthera"
    effort: CloudEffort = "focused"
    local_agent: LocalSettingsAgent = "mus"
    local_context_windows: dict[str, StrictInt] = Field(
        default_factory=_default_local_context_windows
    )
    local_reasoning_modes: dict[str, LocalReasoningMode] = Field(
        default_factory=_default_local_reasoning_modes
    )
    neofelis_google_search_enabled: bool = True
    neofelis_google_maps_enabled: bool = True
    delphinus_x_search_enabled: bool = True
    orcinus_x_search_enabled: bool = True

    _validate_context_windows = field_validator("local_context_windows")(
        _validate_local_context_windows
    )
    _validate_reasoning_modes = field_validator("local_reasoning_modes")(
        _validate_local_reasoning_modes
    )


class ToolProfile(BaseModel):
    """One persisted or built-in stable tool selection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    tool_names: tuple[str, ...] = ()
    built_in: bool = False
    dynamic: bool = False


class ToolProfilesSettings(BaseModel):
    """Backend-persisted custom profiles and per-Agent defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    custom_profiles: tuple[ToolProfile, ...] = ()
    default_profile_by_agent: dict[str, str] = Field(default_factory=dict)


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
    market: MarketSettings = Field(default_factory=MarketSettings)
    ask_apex: AskApexSettings = Field(default_factory=AskApexSettings)
    tool_profiles: ToolProfilesSettings = Field(default_factory=ToolProfilesSettings)
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


class FootballTeamPatch(BaseModel):
    """One followed team in a replaceable football teams patch."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=100)


class FootballPatch(BaseModel):
    """Partial football patch; teams replaces the full followed-team list."""

    model_config = ConfigDict(extra="forbid")

    teams: list[FootballTeamPatch] | None = None


class MarketPatch(BaseModel):
    """Partial market patch; symbols replaces the full ticker list."""

    model_config = ConfigDict(extra="forbid")

    symbols: list[str] | None = None


class AskApexPatch(BaseModel):
    """Partial Ask APEX patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    runtime: AgentRuntime | None = None
    cloud_agent: CloudSettingsAgent | None = None
    effort: CloudEffort | None = None
    local_agent: LocalSettingsAgent | None = None
    local_context_windows: dict[str, StrictInt] | None = None
    local_reasoning_modes: dict[str, LocalReasoningMode] | None = None
    neofelis_google_search_enabled: bool | None = None
    neofelis_google_maps_enabled: bool | None = None
    delphinus_x_search_enabled: bool | None = None
    orcinus_x_search_enabled: bool | None = None

    _validate_context_windows = field_validator("local_context_windows")(
        _validate_local_context_windows
    )
    _validate_reasoning_modes = field_validator("local_reasoning_modes")(
        _validate_local_reasoning_modes
    )


class ToolProfilesPatch(BaseModel):
    """Replaceable persisted tool-profile collections."""

    model_config = ConfigDict(extra="forbid")

    custom_profiles: list[ToolProfile] | None = None
    default_profile_by_agent: dict[str, str] | None = None


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
    football: FootballPatch | None = None
    market: MarketPatch | None = None
    ask_apex: AskApexPatch | None = None
    tool_profiles: ToolProfilesPatch | None = None
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
