"""Public FastAPI request and response models for the APEX API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.agent.providers.gemini_models import GeminiThinkingLevel
from core.connectors.models import ConnectorHealthEntry


DigestStatus = Literal[
    "valid",
    "legacy",
    "malformed",
    "unavailable",
    "zero_health",
]


class RuntimeMetadata(BaseModel):
    run_id: str | None = Field(
        default=None,
        description="Correlation ID for the briefing pipeline run.",
    )
    dev_mode_active: bool = Field(
        description="Whether unified DEV_MODE is active for this run.",
    )
    demo_mode_active: bool = Field(
        description="Whether DEMO_MODE simulation controls are active for this run.",
    )
    synthesis_strategy: str = Field(
        description="Active briefing synthesis backend (dev config or production default).",
    )
    synthesis_provider: Literal["gemini", "ollama", "raw", "demo"] | None = None
    synthesis_profile: Literal["comet", "lynx", "acinonyx", "neofelis"] | None = None
    synthesis_fallback_reason: str | None = None
    synthesis_warmup_ms: int | None = None
    synthesis_generation_ms: int | None = None
    tts_strategy: Literal["google", "kokoro", "pyttsx3"] = Field(
        description="Active text-to-speech backend (google, kokoro, or pyttsx3).",
    )
    active_tts_engine: Literal["google", "kokoro", "pyttsx3"] = Field(
        description="Resolved TTS engine for this run (google, kokoro, or pyttsx3).",
    )
    system_load_throttled: bool = Field(
        description="True when CPU or RAM utilization triggered a local-engine fallback.",
    )


class TelemetryPayload(BaseModel):
    weather: str = Field(description="Weather module telemetry string.")
    sports: str = Field(description="Sports module telemetry string.")
    news: str = Field(description="News module telemetry string.")
    email: str = Field(description="Email module telemetry string.")
    calendar: str = Field(description="Calendar module telemetry string.")
    reminders: str = Field(description="Reminders module telemetry string.")


class DigestPayload(BaseModel):
    weather_archetype: str | None = Field(
        default=None,
        description="Normalized weather condition label for HUD display.",
    )
    unread_emails_count: int = Field(
        default=0,
        description="Count of unread primary inbox messages.",
    )
    upcoming_events_count: int = Field(
        default=0,
        description="Count of calendar events within the briefing window.",
    )
    f1_sprint_active: bool = Field(
        default=False,
        description="Whether an F1 sprint session is scheduled this week.",
    )
    reminders_pending_count: int = Field(
        default=0,
        description="Count of unread reminders awaiting briefing inclusion.",
    )
    sync_health_score: float | None = Field(
        default=None,
        description=(
            "Equal-weight connector sync health score (0–100) derived from typed "
            "connector statuses."
        ),
    )
    connector_health: list[ConnectorHealthEntry] = Field(
        default_factory=list,
        description=(
            "Per-connector health rows with status, freshness, reason code, and "
            "observation time."
        ),
    )
    confidence_score: float = Field(
        description=(
            "Compatibility alias for sync_health_score. Legacy consumers should "
            "prefer sync_health_score when present."
        ),
    )
    failed_connectors: list[str] = Field(
        default_factory=list,
        description=(
            "Legacy unavailable-connector labels. F1 and football failures map to "
            "'sports'."
        ),
    )
    insights: list[str] = Field(
        default_factory=list,
        description="Cross-correlated action-oriented insight bullets for HUD display.",
    )

    @model_validator(mode="before")
    @classmethod
    def _alias_sync_health(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        sync_score = payload.get("sync_health_score")
        confidence = payload.get("confidence_score")
        if isinstance(sync_score, (int, float)) and not isinstance(sync_score, bool):
            canonical_score = float(sync_score)
            payload["sync_health_score"] = canonical_score
            payload["confidence_score"] = canonical_score
        elif isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
            canonical_score = float(confidence)
            payload["sync_health_score"] = canonical_score
            payload["confidence_score"] = canonical_score
        return payload


class BriefingResponse(BaseModel):
    status: str = Field(description="Run outcome label.")
    briefing: str = Field(description="Synthesized briefing text.")
    telemetry: TelemetryPayload = Field(
        description="Per-module raw telemetry captured before synthesis.",
    )
    digest: DigestPayload = Field(
        description="Structured telemetry data summaries and trust scoring metrics.",
    )
    metadata: RuntimeMetadata = Field(
        description="Runtime routing metadata for synthesis and TTS.",
    )


def classify_digest_payload(
    raw_digest: Any,
    *,
    digest_parse_error: str | None = None,
) -> tuple[DigestPayload, DigestStatus]:
    """
    Parse a digest and classify history quality.

    Distinguishes malformed rows from genuine zero-health and legacy
    confidence-only payloads. Safe HUD defaults are always returned.
    """
    if digest_parse_error:
        return DigestPayload(confidence_score=0.0), "malformed"

    if not isinstance(raw_digest, dict):
        return DigestPayload(confidence_score=0.0), "malformed"

    if not raw_digest:
        return DigestPayload(confidence_score=0.0), "malformed"

    has_sync = "sync_health_score" in raw_digest or "connector_health" in raw_digest
    has_confidence = "confidence_score" in raw_digest

    try:
        parsed = DigestPayload.model_validate(raw_digest)
    except Exception:
        return DigestPayload(confidence_score=0.0), "malformed"

    score = parsed.sync_health_score
    if score is None:
        score = parsed.confidence_score

    if has_sync and score == 0.0:
        return parsed, "zero_health"
    if has_sync:
        return parsed, "valid"
    if has_confidence:
        if score == 0.0:
            return parsed, "zero_health"
        return parsed, "legacy"
    return parsed, "legacy"


def parse_digest_payload(raw_digest: Any) -> DigestPayload:
    """Safely parse a digest sub-object with fallback defaults on validation failure."""
    digest, _status = classify_digest_payload(raw_digest)
    return digest


def parse_runtime_metadata(raw_metadata: Any) -> RuntimeMetadata | None:
    """Parse optional history metadata without breaking legacy rows."""
    if not isinstance(raw_metadata, dict):
        return None
    try:
        return RuntimeMetadata.model_validate(raw_metadata)
    except Exception:
        return None


# Compatibility aliases used by characterization tests during the package split.
_parse_digest_payload = parse_digest_payload
_parse_runtime_metadata = parse_runtime_metadata


class CreateReminderRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Raw reminder text; sanitized before persistence.",
    )


class CreateReminderResponse(BaseModel):
    id: int = Field(
        ...,
        ge=1,
        description="SQLite row ID of the persisted reminder.",
    )


class ReminderRecord(BaseModel):
    id: int = Field(..., ge=1, description="SQLite row ID of the reminder.")
    note: str = Field(..., description="Sanitized reminder text.")


class MarkReadRequest(BaseModel):
    ids: list[Annotated[int, Field(ge=1)]] = Field(
        ...,
        min_length=1,
        description="Reminder row IDs to mark as read.",
    )


class MarkReadResponse(BaseModel):
    status: str = Field(
        default="success",
        description="Outcome label for the mark-read operation.",
    )


ProfileAvailabilityStatus = Literal[
    "available",
    "disabled",
    "ollama_unreachable",
    "model_not_installed",
    "insufficient_ram",
    "cpu_overloaded",
]


class LocalLoadedModelStatus(BaseModel):
    name: str = Field(description="Loaded model tag reported by Ollama.")
    model: str = Field(description="Canonical loaded model name reported by Ollama.")
    size_bytes: int | None = Field(
        default=None,
        description="Total loaded model size in bytes, when reported by Ollama.",
    )
    size_vram_bytes: int | None = Field(
        default=None,
        description="Loaded model bytes resident in VRAM, when reported by Ollama.",
    )
    processor: str | None = Field(
        default=None,
        description="Processor/offload split reported by Ollama.",
    )
    context: str | None = Field(
        default=None,
        description="Runtime context length reported by Ollama.",
    )
    expires_at: str | None = Field(
        default=None,
        description="Ollama expiration timestamp for the loaded model.",
    )


class AgentProfileStatus(BaseModel):
    key: str = Field(description="Stable profile identifier used by the HUD.")
    display_name: str = Field(description="Human-readable profile label.")
    provider: Literal["ollama", "gemini"] = Field(
        description="Inference backend for this profile.",
    )
    tier: str = Field(description="Profile performance tier label.")
    stability: Literal["stable", "preview"] = Field(
        description="Release stage classification for this profile.",
    )
    thinking_level: GeminiThinkingLevel | None = Field(
        default=None,
        description=(
            "Gemini thinking level for this profile. Null for Ollama profiles."
        ),
    )
    status: ProfileAvailabilityStatus = Field(
        description="Current availability state for this profile.",
    )
    active: bool = Field(
        description="Whether this profile's model is currently loaded in memory.",
    )
    loading: bool = Field(
        default=False,
        description="Whether this profile's model is currently being warmed up.",
    )
    reason: str | None = Field(
        default=None,
        description="Human-readable explanation when status is not available.",
    )
    idle_unload_remaining_seconds: int | None = Field(
        default=None,
        description="Seconds until auto-unload when this profile is active.",
    )
    loaded_model: LocalLoadedModelStatus | None = Field(
        default=None,
        description="Runtime details reported by Ollama for the active loaded model.",
    )


class LocalUnloadResponse(BaseModel):
    status: str = Field(
        default="success",
        description="Outcome label for the manual unload operation.",
    )


class BriefingHistoryRecord(BaseModel):
    id: int
    timestamp: str
    briefing: str
    digest: DigestPayload
    metadata: RuntimeMetadata | None = None
    digest_status: DigestStatus = Field(
        default="valid",
        description=(
            "History quality classification: valid, legacy, malformed, "
            "unavailable, or zero_health."
        ),
    )


class PipelineSynthesisState(BaseModel):
    phase: Literal["idle", "loading", "ready", "generating", "fallback", "complete"] = "idle"
    provider: Literal["gemini", "ollama", "raw", "demo"] | None = None
    profile: Literal["comet", "lynx", "acinonyx", "neofelis"] | None = None
    loading: bool = False
    fallback_reason: str | None = None


class PipelineStatusSnapshot(BaseModel):
    run_id: str | None = Field(
        default=None,
        description="Correlation ID for the active briefing pipeline run.",
    )
    step: int = Field(description="Monotonic pipeline step index for the active run.")
    label: str = Field(description="Short stage label for dashboards and probes.")
    timestamp: str = Field(description="UTC ISO-8601 timestamp of the last stage update.")
    is_speaking: bool = Field(
        description="True when the speaker subsystem lock is held or audio playback is active.",
    )
    active_tts_engine: Literal["google", "kokoro", "pyttsx3"] = Field(
        description="Resolved TTS engine for the active run (google, kokoro, or pyttsx3).",
    )
    system_load_throttled: bool = Field(
        description="True when hardware throttle thresholds forced a local-engine fallback.",
    )
    synthesis: PipelineSynthesisState | None = None


MarketTickerStatus = Literal["live", "stale", "unavailable"]
MarketGlobalStatus = Literal[
    "live",
    "partial",
    "stale",
    "unavailable",
    "not_configured",
    "provider_unavailable",
]


class MarketTickerItem(BaseModel):
    symbol: str = Field(description="Configured ticker symbol.")
    price: float | None = Field(default=None, description="Latest available daily close price.")
    change: float | None = Field(
        default=None,
        description="Absolute close-to-close change versus the prior trading day.",
    )
    change_percent: float | None = Field(
        default=None,
        description="Percent close-to-close change without the trailing percent sign.",
    )
    status: MarketTickerStatus = Field(
        description="Per-symbol freshness state (live, stale, or unavailable).",
    )
    last_updated: str | None = Field(
        default=None,
        description="UTC ISO-8601 timestamp of the last successful market data fetch.",
    )
    sparkline: list[float] = Field(
        default_factory=list,
        description="Up to seven recent daily closing prices, newest first.",
    )


class MarketResponse(BaseModel):
    status: MarketGlobalStatus = Field(
        description="Aggregate market feed state for the configured symbol set.",
    )
    cooldown_active: bool = Field(
        description="True when outgoing Alpha Vantage requests are globally paused.",
    )
    cooldown_remaining_seconds: int = Field(
        ge=0,
        description="Seconds remaining in the active provider cooldown window.",
    )
    tickers: list[MarketTickerItem] = Field(
        default_factory=list,
        description="Ordered market ticker snapshots for configured symbols.",
    )
