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
    DEFAULT_APEX_MODEL,
    DEFAULT_LOCAL_MODEL,
    get_model_profile,
)
from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS
from core.agent.types import LocalReasoningMode

AgentKey = Literal["apex"]
CloudProvider = Literal["openai", "openrouter", "gemini", "xai"]
LocalRuntime = Literal["ollama", "llama_cpp"]
AgentRuntime = Literal["cloud", "local"]
CloudEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
BriefingMode = Literal["flash", "focused", "structured"]
VoiceEngine = Literal["google", "pyttsx3", "kokoro"]
VoiceGender = Literal["male", "female"]
VoiceMode = Literal["off", "manual", "automatic"]

VALID_AGENT_KEYS: frozenset[str] = frozenset({"apex"})
VALID_CLOUD_PROVIDERS: frozenset[str] = frozenset({"openai", "openrouter", "gemini", "xai"})
VALID_LOCAL_RUNTIMES: frozenset[str] = frozenset({"ollama", "llama_cpp"})
VALID_LOCAL_REASONING_MODES: frozenset[str] = frozenset({"none", "focused"})
VALID_CLOUD_EFFORTS: frozenset[str] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"flash", "focused", "structured"}
)
VALID_VOICE_ENGINES: frozenset[str] = frozenset({"google", "pyttsx3", "kokoro"})
VALID_VOICE_GENDERS: frozenset[str] = frozenset({"male", "female"})
VALID_VOICE_MODES: frozenset[str] = frozenset({"off", "manual", "automatic"})

SETTINGS_SCHEMA_VERSION: int = 19
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


def _default_local_context_window() -> int:
    return LLAMA_CPP_RUNTIME_CONFIGS[DEFAULT_LOCAL_MODEL].default_context_window


def _validate_local_context_window(value: int, model: str) -> int:
    profile = get_model_profile(model)
    llama_runtime = LLAMA_CPP_RUNTIME_CONFIGS.get(model)
    if profile is None or profile.provider != "llama_cpp":
        return value
    if llama_runtime is None or value not in llama_runtime.allowed_context_windows:
        raise ValueError(
            f"Unsupported local context preset for model {model!r}: {value!r}"
        )
    return value


def _validate_local_reasoning_mode(
    value: LocalReasoningMode, model: str
) -> LocalReasoningMode:
    from core.agent.catalog import local_reasoning_modes_for_model

    supported = local_reasoning_modes_for_model(model)
    if value not in supported:
        raise ValueError(
            f"Unsupported local reasoning mode for model {model!r}: {value!r}"
        )
    return value


class CloudHostedToolsSettings(BaseModel):
    """Provider-hosted grounding toggles for the selected cloud model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    google_search: bool = True
    google_maps: bool = True
    x_search: bool = True


class CloudSettings(BaseModel):
    """Cloud model, effort, and hosted-tool preferences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    last_model: str = DEFAULT_APEX_MODEL
    effort: CloudEffort = "low"
    personal_context_enabled: bool = False
    hosted_tools: CloudHostedToolsSettings = Field(
        default_factory=CloudHostedToolsSettings
    )

    @field_validator("last_model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        profile = get_model_profile(value)
        if profile is None or profile.runtime != "cloud":
            raise ValueError(f"Unsupported cloud model: {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_cloud_model(self) -> CloudSettings:
        profile = get_model_profile(self.last_model)
        if profile is None or profile.runtime != "cloud":
            raise ValueError(f"Unsupported cloud model: {self.last_model!r}")
        return self


class LocalSettings(BaseModel):
    """Local model, context, and reasoning preferences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    last_model: str = DEFAULT_LOCAL_MODEL
    context_window: StrictInt = Field(default_factory=_default_local_context_window)
    reasoning_mode: LocalReasoningMode = "none"
    personal_context_enabled: bool = False

    @field_validator("last_model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        profile = get_model_profile(value)
        if profile is None or profile.runtime != "local":
            raise ValueError(f"Unsupported local model: {value!r}")
        return value

    @field_validator("context_window")
    @classmethod
    def _validate_context(cls, value: int, info) -> int:
        data = info.data
        model = data.get("last_model", DEFAULT_LOCAL_MODEL)
        return _validate_local_context_window(value, model)

    @field_validator("reasoning_mode")
    @classmethod
    def _validate_reasoning(cls, value: LocalReasoningMode, info) -> LocalReasoningMode:
        data = info.data
        model = data.get("last_model", DEFAULT_LOCAL_MODEL)
        return _validate_local_reasoning_mode(value, model)

    @model_validator(mode="after")
    def _validate_local_model(self) -> LocalSettings:
        profile = get_model_profile(self.last_model)
        if profile is None or profile.runtime != "local":
            raise ValueError(f"Unsupported local model: {self.last_model!r}")
        return self


class AgentSettings(BaseModel):
    """Apex Agent query enablement, selected model, and runtime preferences."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    selected_model: str = DEFAULT_APEX_MODEL
    sandbox_mode: bool = False
    cloud: CloudSettings = Field(default_factory=CloudSettings)
    local: LocalSettings = Field(default_factory=LocalSettings)

    @field_validator("selected_model")
    @classmethod
    def _validate_agent(cls, value: str) -> str:
        if get_model_profile(value) is None:
            raise ValueError(f"Unsupported model: {value!r}")
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
    """Backend-persisted custom profiles and per-runtime defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    custom_profiles: tuple[ToolProfile, ...] = ()
    default_profile_by_runtime: dict[str, str] = Field(default_factory=dict)


class BriefingSettings(BaseModel):
    """Default briefing synthesis mode for generate and trigger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_mode: BriefingMode = "flash"


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


class CloudHostedToolsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    google_search: bool | None = None
    google_maps: bool | None = None
    x_search: bool | None = None


class CloudSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_model: str | None = None
    effort: CloudEffort | None = None
    personal_context_enabled: bool | None = None
    hosted_tools: CloudHostedToolsPatch | None = None

    @field_validator("last_model")
    @classmethod
    def _validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        profile = get_model_profile(value)
        if profile is None or profile.runtime != "cloud":
            raise ValueError(f"Unsupported cloud model: {value!r}")
        return value


class LocalSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_model: str | None = None
    context_window: StrictInt | None = None
    reasoning_mode: LocalReasoningMode | None = None
    personal_context_enabled: bool | None = None

    @field_validator("last_model")
    @classmethod
    def _validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return value
        profile = get_model_profile(value)
        if profile is None or profile.runtime != "local":
            raise ValueError(f"Unsupported local model: {value!r}")
        return value


class AgentSettingsPatch(BaseModel):
    """Partial Agent query settings patch; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    selected_model: str | None = None
    sandbox_mode: bool | None = None
    cloud: CloudSettingsPatch | None = None
    local: LocalSettingsPatch | None = None

    @field_validator("selected_model")
    @classmethod
    def _validate_model(cls, value: str | None) -> str | None:
        if value is not None and get_model_profile(value) is None:
            raise ValueError(f"Unsupported model: {value!r}")
        return value


class ToolProfilesPatch(BaseModel):
    """Replaceable persisted tool-profile collections."""

    model_config = ConfigDict(extra="forbid")

    custom_profiles: list[ToolProfile] | None = None
    default_profile_by_runtime: dict[str, str] | None = None


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
