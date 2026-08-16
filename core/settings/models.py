"""Typed models for editable runtime settings."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from core.agent.model_catalog import (
    DEFAULT_FELIS_MODEL,
    DEFAULT_PANTHERA_MODEL,
    get_model_profile,
)
from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS
from core.agent.types import LocalReasoningMode

AgentKey = Literal["panthera", "felis"]
CloudProvider = Literal["openai", "gemini", "xai"]
LocalRuntime = Literal["ollama", "llama_cpp"]
AgentRuntime = Literal["cloud", "local"]
CloudEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
BriefingMode = Literal["panthera", "felis", "structured_digest"]
VoiceEngine = Literal["google", "pyttsx3", "kokoro"]
VoiceGender = Literal["male", "female"]
VoiceMode = Literal["off", "manual", "automatic"]

VALID_AGENT_KEYS: frozenset[str] = frozenset({"panthera", "felis"})
VALID_CLOUD_PROVIDERS: frozenset[str] = frozenset({"openai", "gemini", "xai"})
VALID_LOCAL_RUNTIMES: frozenset[str] = frozenset({"ollama", "llama_cpp"})
VALID_LOCAL_REASONING_MODES: frozenset[str] = frozenset({"none", "focused"})
VALID_CLOUD_EFFORTS: frozenset[str] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh"}
)
VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"panthera", "felis", "structured_digest"}
)
VALID_VOICE_ENGINES: frozenset[str] = frozenset({"google", "pyttsx3", "kokoro"})
VALID_VOICE_GENDERS: frozenset[str] = frozenset({"male", "female"})
VALID_VOICE_MODES: frozenset[str] = frozenset({"off", "manual", "automatic"})

SETTINGS_SCHEMA_VERSION: int = 16
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


def _default_felis_context_window() -> int:
    return LLAMA_CPP_RUNTIME_CONFIGS[DEFAULT_FELIS_MODEL].default_context_window


def _validate_felis_context_window(value: int, model: str) -> int:
    profile = get_model_profile(model)
    llama_runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(model)
    if profile is None or profile.provider != "llama_cpp":
        return value
    if llama_runtime is None or value not in llama_runtime.allowed_context_windows:
        raise ValueError(
            f"Unsupported local context preset for model {model!r}: {value!r}"
        )
    return value


def _validate_felis_reasoning_mode(
    value: LocalReasoningMode, model: str
) -> LocalReasoningMode:
    from core.agent.catalog import local_reasoning_modes_for_model

    supported = local_reasoning_modes_for_model(model)
    if value not in supported:
        raise ValueError(
            f"Unsupported local reasoning mode for model {model!r}: {value!r}"
        )
    return value


class PantheraHostedToolsSettings(BaseModel):
    """Provider-hosted grounding toggles for Panthera's selected model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    google_search: bool = True
    google_maps: bool = True
    x_search: bool = True


class PantheraSettings(BaseModel):
    """Cloud model, effort, and hosted-tool preferences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = DEFAULT_PANTHERA_MODEL
    effort: CloudEffort = "medium"
    hosted_tools: PantheraHostedToolsSettings = Field(
        default_factory=PantheraHostedToolsSettings
    )

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        profile = get_model_profile(value)
        if profile is None or profile.runtime != "cloud":
            raise ValueError(f"Unsupported Panthera model: {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_cloud_model(self) -> PantheraSettings:
        profile = get_model_profile(self.model)
        if profile is None or profile.runtime != "cloud":
            raise ValueError(f"Unsupported Panthera model: {self.model!r}")
        return self


class FelisSettings(BaseModel):
    """Local model, context, and reasoning preferences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = DEFAULT_FELIS_MODEL
    context_window: StrictInt = Field(default_factory=_default_felis_context_window)
    reasoning_mode: LocalReasoningMode = "none"

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        profile = get_model_profile(value)
        if profile is None or profile.runtime != "local":
            raise ValueError(f"Unsupported Felis model: {value!r}")
        return value

    @field_validator("context_window")
    @classmethod
    def _validate_context(cls, value: int, info) -> int:
        data = info.data
        model = data.get("model", DEFAULT_FELIS_MODEL)
        return _validate_felis_context_window(value, model)

    @field_validator("reasoning_mode")
    @classmethod
    def _validate_reasoning(cls, value: LocalReasoningMode, info) -> LocalReasoningMode:
        data = info.data
        model = data.get("model", DEFAULT_FELIS_MODEL)
        return _validate_felis_reasoning_mode(value, model)

    @model_validator(mode="after")
    def _validate_local_model(self) -> FelisSettings:
        profile = get_model_profile(self.model)
        if profile is None or profile.runtime != "local":
            raise ValueError(f"Unsupported Felis model: {self.model!r}")
        return self


class AgentSettings(BaseModel):
    """Agent query enablement, identity, sandbox, and nested Agent configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    agent: AgentKey = "panthera"
    sandbox_mode: bool = False
    panthera: PantheraSettings = Field(default_factory=PantheraSettings)
    felis: FelisSettings = Field(default_factory=FelisSettings)

    @field_validator("agent")
    @classmethod
    def _validate_agent(cls, value: str) -> str:
        if value not in VALID_AGENT_KEYS:
            raise ValueError(f"Unsupported Agent key: {value!r}")
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


class MicrosoftTodoSettings(BaseModel):
    """One explicitly selected Microsoft To Do list for APEX reminders."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reminder_list_id: str = Field(default="", max_length=512)

    @field_validator("reminder_list_id")
    @classmethod
    def _validate_reminder_list_id(cls, value: str) -> str:
        if value and value != value.strip():
            raise ValueError("reminder_list_id must be an opaque trimmed identifier")
        return value


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
    ask_apex: AgentSettings = Field(default_factory=AgentSettings)
    tool_profiles: ToolProfilesSettings = Field(default_factory=ToolProfilesSettings)
    briefing: BriefingSettings = Field(default_factory=BriefingSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    llama_cpp: LlamaCppSettings = Field(default_factory=LlamaCppSettings)
    microsoft_todo: MicrosoftTodoSettings = Field(default_factory=MicrosoftTodoSettings)


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


class PantheraHostedToolsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    google_search: bool | None = None
    google_maps: bool | None = None
    x_search: bool | None = None


class PantheraSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    effort: CloudEffort | None = None
    hosted_tools: PantheraHostedToolsPatch | None = None


class FelisSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    context_window: StrictInt | None = None
    reasoning_mode: LocalReasoningMode | None = None


class AgentSettingsPatch(BaseModel):
    """Partial Agent query settings patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    agent: AgentKey | None = None
    sandbox_mode: bool | None = None
    panthera: PantheraSettingsPatch | None = None
    felis: FelisSettingsPatch | None = None


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


class MicrosoftTodoPatch(BaseModel):
    """Partial selected-list update for the Microsoft To Do reminder source."""

    model_config = ConfigDict(extra="forbid")

    reminder_list_id: str | None = Field(default=None, max_length=512)

    @field_validator("reminder_list_id")
    @classmethod
    def _validate_reminder_list_id(cls, value: str | None) -> str | None:
        if value is not None and value and value != value.strip():
            raise ValueError("reminder_list_id must be an opaque trimmed identifier")
        return value


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
    ask_apex: AgentSettingsPatch | None = None
    tool_profiles: ToolProfilesPatch | None = None
    briefing: BriefingPatch | None = None
    voice: VoicePatch | None = None
    mcp: McpPatch | None = None
    llama_cpp: LlamaCppPatch | None = None
    microsoft_todo: MicrosoftTodoPatch | None = None


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
