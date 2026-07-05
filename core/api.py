"""
FastAPI application for APEX (Milestone Nexus).

Standalone HTTP surface; briefing trigger mirrors main.start_apex flow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from clients import (
    calendar_client,
    gmail_client,
    google_auth,
    news_client,
    sports_client,
    weather_client,
)
from core import brain, database, scanner, speaker, config
from core.agent.loop import default_tools_dispatcher, run_agent_loop
from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.gemini_models import GEMINI_MODEL_PROFILES, GeminiModelProfile
from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.ollama_lifecycle import (
    SystemVitals,
    check_idle_models_loop,
    check_resource_gate,
    end_local_execution,
    get_active_loaded_model,
    get_idle_unload_remaining_seconds,
    get_status_snapshot,
    is_local_execution_active,
    switch_local_model,
    try_begin_local_execution,
    unload_active_local_model,
)
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES, OllamaModelProfile
from core.agent.types import AgentMessage, AgentQueryRequest, AgentQueryResponse
from core.config import (
    DEMO_MODE,
    DEMO_TTS,
    DEV_AI_SYNTHESIS,
    DEV_TTS_PLAYBACK,
    ENV_PATH,
    FEATURE_CALENDAR,
    FEATURE_EMAIL,
    FEATURE_NEWS,
    FEATURE_SPORTS,
    FEATURE_WEATHER,
    MODULE_F1,
    MODULE_FOOTBALL,
    OLLAMA_ENABLED,
    OLLAMA_MANUAL_UNLOAD_ENABLED,
    is_dev_mode,
)

load_dotenv(dotenv_path=ENV_PATH)

WEATHER_FAILED_RE = re.compile(r"(offline|error|failed)", re.IGNORECASE)
SPORTS_F1_FAILED_RE = re.compile(r"(telemetry unavailable)", re.IGNORECASE)
SPORTS_FB_FAILED_RE = re.compile(r"(telemetry unavailable|throttled)", re.IGNORECASE)
NEWS_FAILED_RE = re.compile(r"(telemetry unavailable|offline)", re.IGNORECASE)
EMAIL_FAILED_RE = re.compile(r"(error|check connection)", re.IGNORECASE)
CALENDAR_FAILED_RE = re.compile(r"(error|check connection)", re.IGNORECASE)

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Start background workers on API boot and cancel them on shutdown."""
    idle_model_task: asyncio.Task[None] | None = None

    if OLLAMA_ENABLED:
        idle_model_task = asyncio.create_task(check_idle_models_loop())
        _LOGGER.info("Started Ollama idle model monitor")

    yield

    if idle_model_task is not None:
        idle_model_task.cancel()
        try:
            await idle_model_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="APEX Nexus", lifespan=_app_lifespan)


DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


def get_allowed_origins() -> list[str]:
    """Return allowed CORS origins from env, or local defaults."""
    configured_origins = os.getenv("APEX_ALLOWED_ORIGINS", "").strip()
    if not configured_origins:
        return list(DEFAULT_ALLOWED_ORIGINS)

    parsed_origins = [
        origin.strip() for origin in configured_origins.split(",")
    ]
    filtered_origins = [origin for origin in parsed_origins if origin]
    return filtered_origins or list(DEFAULT_ALLOWED_ORIGINS)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PipelineState:
    """
    Thread-safe pipeline progress for diagnostics and lifecycle checkpoints.

    Internal fields track step index, phase label, last UTC timestamp ISO string,
    and whether a run currently holds active status for `/api/v1/status` probing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_active = False
        self._step = 0
        self._label = "IDLE"
        self._timestamp = datetime.now(timezone.utc).isoformat()
        self._active_tts_engine = "google"
        self._system_load_throttled = False

    def update(
        self,
        step: int,
        label: str,
        *,
        active_tts_engine: str | None = None,
        system_load_throttled: bool | None = None,
    ) -> None:
        """
        Advance the conceptual pipeline stage.

        Args:
            step: Monotonic pipeline step index supplied by orchestration logic.
            label: Stable short label naming the stage for dashboards and probes.
            active_tts_engine: Resolved TTS engine for the active run, when known.
            system_load_throttled: Whether hardware throttle thresholds are active.
        """
        with self._lock:
            self._is_active = True
            self._step = step
            self._label = label
            self._timestamp = datetime.now(timezone.utc).isoformat()
            if active_tts_engine is not None:
                self._active_tts_engine = active_tts_engine
            if system_load_throttled is not None:
                self._system_load_throttled = system_load_throttled

    def reset(self) -> None:
        """Restore the tracker to idle or pre-run defaults."""
        with self._lock:
            self._is_active = False
            self._step = 0
            self._label = "IDLE"
            self._timestamp = datetime.now(timezone.utc).isoformat()
            self._active_tts_engine = "google"
            self._system_load_throttled = False

    def get_state(self) -> dict[str, Any] | None:
        """
        Produce a shallow snapshot suitable for `/api/v1/status` responses.

        Returns:
            Mapping for JSON serialization, or None when no active run is recorded.
        """
        with self._lock:
            if not self._is_active:
                return None
            return {
                "step": self._step,
                "label": self._label,
                "timestamp": self._timestamp,
                "is_speaking": speaker.is_speaking(),
                "active_tts_engine": self._active_tts_engine,
                "system_load_throttled": self._system_load_throttled,
            }


global_pipeline_state = PipelineState()
_TRIGGER_LOCK = threading.Lock()

_MOCK_TELEMETRY_PATH = Path(__file__).resolve().parent / "mock" / "telemetry.json"
_DEMO_STAGE_DELAY_SECONDS = 1.5


def _speak_and_cleanup(
    text: str,
    *,
    tts_override: str | None = None,
    lock: threading.Lock | None = None,
) -> None:
    """Play briefing audio on a worker thread and reset pipeline state when playback ends."""
    try:
        speaker.speak(text, tts_override=tts_override)
    finally:
        global_pipeline_state.reset()
        if lock is not None:
            lock.release()



class RuntimeMetadata(BaseModel):
    dev_mode_active: bool = Field(
        description="Whether unified DEV_MODE is active for this run.",
    )
    demo_mode_active: bool = Field(
        description="Whether DEMO_MODE simulation controls are active for this run.",
    )
    synthesis_strategy: str = Field(
        description="Active briefing synthesis backend (dev config or production default).",
    )
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
    confidence_score: float = Field(
        description="Aggregate trust score for connector telemetry (0–100).",
    )
    failed_connectors: list[str] = Field(
        default_factory=list,
        description="Connector module names that failed during collection.",
    )
    insights: list[str] = Field(
        default_factory=list,
        description="Cross-correlated action-oriented insight bullets for HUD display.",
    )


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


def _parse_digest_payload(raw_digest: Any) -> DigestPayload:
    """Safely parse a digest sub-object with fallback defaults on validation failure."""
    try:
        return DigestPayload.model_validate(raw_digest)
    except Exception:
        return DigestPayload(confidence_score=0.0)


def _split_sports_report(sports_report: str) -> tuple[str, str]:
    """Split combined sports telemetry into F1 and football segments."""
    marker = " Barcelona "
    if marker in sports_report:
        f1_part, remainder = sports_report.split(marker, 1)
        return f1_part, f"Barcelona {remainder}"
    if sports_report.startswith("Barcelona "):
        return "", sports_report
    return sports_report, ""


def _evaluate_sports_trust(
    sports_report: str,
) -> tuple[float, float, bool]:
    """
    Return earned weight, total weight, and whether any sports subdivision failed.

    Sports weight is 1.0 when a single sub-module is active, or 0.5 per sub-module
    when both F1 and football are enabled.
    """
    active_modules: list[tuple[re.Pattern[str], str]] = []
    if MODULE_F1 and MODULE_FOOTBALL:
        f1_part, fb_part = _split_sports_report(sports_report)
    else:
        f1_part, fb_part = sports_report, sports_report

    if MODULE_F1:
        active_modules.append((SPORTS_F1_FAILED_RE, f1_part))
    if MODULE_FOOTBALL:
        active_modules.append((SPORTS_FB_FAILED_RE, fb_part))

    if not active_modules:
        return 1.0, 1.0, False

    module_weight = 1.0 / len(active_modules)
    earned_weight = 0.0
    sports_failed = False
    for failure_pattern, module_report in active_modules:
        if failure_pattern.search(module_report):
            sports_failed = True
        else:
            earned_weight += module_weight

    return earned_weight, 1.0, sports_failed


def _compute_confidence_and_failures(
    *,
    weather_report: str,
    sports_report: str,
    news_report: str,
    email_report: str,
    calendar_report: str,
    f1_cache_penalty: bool,
) -> tuple[float, list[str]]:
    """Evaluate active connector telemetry and derive trust score plus failures."""
    failed_connectors: list[str] = []
    earned_weight = 0.0
    total_weight = 0.0

    connector_checks: list[tuple[str, bool, str, re.Pattern[str]]] = [
        ("weather", FEATURE_WEATHER, weather_report, WEATHER_FAILED_RE),
        ("news", FEATURE_NEWS, news_report, NEWS_FAILED_RE),
        ("email", FEATURE_EMAIL, email_report, EMAIL_FAILED_RE),
        ("calendar", FEATURE_CALENDAR, calendar_report, CALENDAR_FAILED_RE),
    ]

    for connector_name, enabled, report, failure_pattern in connector_checks:
        if not enabled:
            continue
        total_weight += 1.0
        if failure_pattern.search(report):
            failed_connectors.append(connector_name)
        else:
            earned_weight += 1.0

    if FEATURE_SPORTS:
        sports_earned, sports_total, sports_failed = _evaluate_sports_trust(
            sports_report
        )
        total_weight += sports_total
        earned_weight += sports_earned
        if sports_failed:
            failed_connectors.append("sports")

    if total_weight == 0.0:
        confidence_score = 100.0
    else:
        confidence_score = (earned_weight / total_weight) * 100.0

    if f1_cache_penalty:
        confidence_score *= 0.90

    confidence_score = round(max(0.0, min(100.0, confidence_score)), 1)
    return confidence_score, failed_connectors


def _load_mock_telemetry() -> tuple[TelemetryPayload, DigestPayload]:
    """Load static demo telemetry and digest from ``core/mock/telemetry.json``."""
    try:
        with open(_MOCK_TELEMETRY_PATH, encoding="utf-8") as mock_file:
            payload = json.load(mock_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Demo telemetry payload unavailable: {exc}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Demo telemetry payload must be a JSON object.",
        )

    digest = _parse_digest_payload(payload.get("digest"))

    try:
        telemetry = TelemetryPayload(**payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Demo telemetry payload failed schema validation: {exc}",
        ) from exc

    return telemetry, digest


def _mock_briefing_history() -> list[dict[str, Any]]:
    """Static briefing ledger for DEMO_MODE history responses."""
    return [
        {
            "id": 3,
            "timestamp": "2026-06-08T08:15:00",
            "briefing": (
                "Greetings Chief. APEX simulation controls are operational. "
                "Atmospheric sensors report seventy-two degrees with clear skies. "
                "Your inbox has two unread primary messages, and your next calendar item, "
                "Demo Presentation, begins at three PM."
            ),
            "digest": {
                "weather_archetype": "clear_day",
                "unread_emails_count": 2,
                "upcoming_events_count": 1,
                "f1_sprint_active": False,
                "reminders_pending_count": 2,
                "confidence_score": 100.0,
                "failed_connectors": [],
            },
        },
        {
            "id": 2,
            "timestamp": "2026-06-07T07:30:00",
            "briefing": (
                "Morning briefing. Overnight precipitation cleared; current conditions are "
                "partly cloudy at sixty-eight degrees. Three unread emails require attention, "
                "including a budget review thread. Sprint qualifying for the Monaco Grand Prix "
                "is scheduled this afternoon."
            ),
            "digest": {
                "weather_archetype": "partly_cloudy",
                "unread_emails_count": 3,
                "upcoming_events_count": 2,
                "f1_sprint_active": True,
                "reminders_pending_count": 1,
                "confidence_score": 92.5,
                "failed_connectors": ["news"],
            },
        },
        {
            "id": 1,
            "timestamp": "2026-06-06T06:45:00",
            "briefing": (
                "System status nominal. Light rain expected through mid-morning with temperatures "
                "near sixty-one degrees. Calendar is clear until afternoon stand-up. One reminder "
                "pending: submit quarterly metrics before end of day."
            ),
            "digest": {
                "weather_archetype": "light_rain",
                "unread_emails_count": 0,
                "upcoming_events_count": 0,
                "f1_sprint_active": False,
                "reminders_pending_count": 1,
                "confidence_score": 78.0,
                "failed_connectors": ["email", "calendar"],
            },
        },
    ]


def _build_demo_briefing(telemetry: TelemetryPayload) -> str:
    """Compose a deterministic briefing string from mock telemetry fields."""
    return (
        "Greetings Chief. APEX simulation controls are operational. "
        "Atmospheric sensors report seventy-two degrees with clear skies. "
        "The Monaco Grand Prix is scheduled for this week, with the main race running on Sunday. "
        "Your inbox has two unread primary messages, and your next calendar item, "
        "Demo Presentation, begins at three PM. All local databases are fully synchronized."
    )


def _run_demo_agent_query(payload: AgentQueryRequest) -> AgentQueryResponse:
    """Return deterministic assistant responses when ``DEMO_MODE`` is active."""
    profile: GeminiModelProfile | OllamaModelProfile | None = None
    if payload.profile in GEMINI_MODEL_PROFILES:
        profile = GEMINI_MODEL_PROFILES[payload.profile]
    elif payload.profile in OLLAMA_MODEL_PROFILES:
        profile = OLLAMA_MODEL_PROFILES[payload.profile]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown agent profile: {payload.profile!r}",
        )

    prompt_lower = payload.prompt.lower()
    answer: str
    tool_trace: list[dict[str, Any]]

    if any(keyword in prompt_lower for keyword in ("weather", "forecast", "temp")):
        answer = (
            "Under APEX simulation, the 3-day weather forecast for Plantation, FL "
            "indicates consistent light rain with high temperatures in the low 90s:\n\n"
            "* July 1: High 91°F, Low 80°F. Light rain.\n"
            "* July 2: High 90°F, Low 77°F. Light rain.\n"
            "* July 3: High 94°F, Low 84°F. Light rain."
        )
        tool_trace = [
            {"name": "get_weather_forecast", "status": "ok", "duration_ms": 115.4},
        ]
    elif any(
        keyword in prompt_lower
        for keyword in ("f1", "standings", "championship", "calendar")
    ):
        answer = (
            "APEX simulation data shows Max Verstappen leading the driver "
            "standings with 110 points. The next scheduled race is the Monaco "
            "Simulation Grand Prix running this week."
        )
        tool_trace = [
            {"name": "get_f1_driver_standings", "status": "ok", "duration_ms": 142.1},
        ]
    elif any(keyword in prompt_lower for keyword in ("reminder", "task")):
        answer = (
            "You have 2 pending reminders in the active ledger:\n\n"
            "* Review APEX demo script\n"
            "* Charge backup operations hardware"
        )
        tool_trace = [
            {"name": "get_active_reminders", "status": "ok", "duration_ms": 94.2},
        ]
    else:
        answer = (
            "APEX simulation is fully operational, Chief. I have verified your "
            "local database registers and ambient HUD context. Let me know if you "
            "would like me to simulate a weather forecast or F1 standings query."
        )
        tool_trace = []

    return AgentQueryResponse(
        answer=answer,
        profile_used=profile.model_dump(),
        tool_trace=tool_trace,
        session_id=payload.session_id,
        error=None,
    )


def _run_demo_briefing() -> BriefingResponse:
    """Execute the staged simulation path when ``DEMO_MODE`` is active."""
    voice_thread_started = False

    try:
        global_pipeline_state.update(1, "GATE")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        global_pipeline_state.update(2, "COLLECTION")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        telemetry, digest = _load_mock_telemetry()

        global_pipeline_state.update(3, "SYNTHESIS")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        final_briefing = _build_demo_briefing(telemetry)

        active_tts_engine, system_load_throttled = _resolve_tts_diagnostics(
            dev_mode=True,
            configured_tts=DEMO_TTS,
        )
        global_pipeline_state.update(
            4,
            "DELIVERY",
            active_tts_engine=active_tts_engine,
            system_load_throttled=system_load_throttled,
        )
        if not is_dev_mode():
            try:
                print("[SYSTEM] Logging briefing run to persistent SQLite ledger.")
                database.save_briefing(final_briefing, digest.model_dump())
                database.prune_historical_ledger()
            except Exception as exc:
                print(f"[SYSTEM]: Briefing ledger persistence failed: ({exc})")

        voice_thread = threading.Thread(
            target=_speak_and_cleanup,
            kwargs={
                "text": final_briefing,
                "tts_override": active_tts_engine,
                "lock": _TRIGGER_LOCK,
            },
            daemon=True,
        )
        voice_thread.start()
        voice_thread_started = True

        return BriefingResponse(
            status="success",
            briefing=final_briefing,
            telemetry=telemetry,
            digest=digest,
            metadata=RuntimeMetadata(
                dev_mode_active=True,
                demo_mode_active=True,
                synthesis_strategy="slm",
                tts_strategy=DEMO_TTS,
                active_tts_engine=active_tts_engine,
                system_load_throttled=system_load_throttled,
            ),
        )
    finally:
        if not voice_thread_started:
            global_pipeline_state.reset()
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()


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

_AGENT_PROFILE_ORDER: tuple[str, ...] = (
    "lynx",
    "acinonyx",
    "neofelis",
    "comet",
    "nova",
    "pulsar",
)

_PROFILE_STATUS_REASONS: dict[ProfileAvailabilityStatus, str] = {
    "disabled": "Ollama local inference is disabled in system settings",
    "ollama_unreachable": "Ollama daemon is unreachable",
    "model_not_installed": "Model tag is not installed locally",
    "insufficient_ram": "Current memory pressure exceeds threshold",
    "cpu_overloaded": "Current CPU utilization exceeds threshold",
}


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
    status: ProfileAvailabilityStatus = Field(
        description="Current availability state for this profile.",
    )
    active: bool = Field(
        description="Whether this profile's model is currently loaded in memory.",
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


class PipelineStatusSnapshot(BaseModel):
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


def _resolve_tts_diagnostics(
    *,
    dev_mode: bool,
    configured_tts: str,
) -> tuple[str, bool]:
    """
    Resolve the active TTS engine and throttle flag for runtime diagnostics.

    When hardware throttle thresholds are met, Kokoro ONNX downgrades to pyttsx3.
    Google Cloud TTS bypasses throttling because cloud synthesis has negligible
    local CPU/RAM overhead.
    """
    system_load_throttled = scanner.is_system_throttled()
    normalized = configured_tts.strip().lower()

    if system_load_throttled and normalized == "kokoro":
        return "pyttsx3", True

    if dev_mode:
        return normalized if normalized in {"google", "kokoro", "pyttsx3"} else "pyttsx3", system_load_throttled

    if normalized in {"google", "kokoro", "pyttsx3"}:
        return normalized, system_load_throttled

    return "google", system_load_throttled


_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MARKDOWN_HEADER_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MARKDOWN_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_MARKDOWN_STRIKE_PATTERN = re.compile(r"~~(.+?)~~")
_MARKDOWN_CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
_MARKDOWN_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
_MARKDOWN_BLOCKQUOTE_PATTERN = re.compile(r"^>\s?", re.MULTILINE)
_MARKDOWN_HRULE_PATTERN = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_MARKDOWN_LIST_MARKER_PATTERN = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_MARKDOWN_ORDERED_LIST_PATTERN = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_NON_ASCII_PATTERN = re.compile(r"[^\x00-\x7F]+")


def clean_for_tts(text: str) -> str:
    """
    Strip markdown constructs and non-ASCII characters for TTS-safe output.

    Args:
        text: Source string that may contain markdown or emoji.

    Returns:
        ASCII-only plain text with collapsed whitespace.
    """
    cleaned = text
    replacements = (
        (_MARKDOWN_CODE_BLOCK_PATTERN, " "),
        (_MARKDOWN_IMAGE_PATTERN, r"\1"),
        (_MARKDOWN_LINK_PATTERN, r"\1"),
        (_MARKDOWN_INLINE_CODE_PATTERN, r"\1"),
        (_MARKDOWN_HEADER_PATTERN, ""),
        (_MARKDOWN_BLOCKQUOTE_PATTERN, ""),
        (_MARKDOWN_HRULE_PATTERN, " "),
        (_MARKDOWN_LIST_MARKER_PATTERN, ""),
        (_MARKDOWN_ORDERED_LIST_PATTERN, ""),
        (_MARKDOWN_BOLD_PATTERN, lambda match: match.group(1) or match.group(2) or ""),
        (_MARKDOWN_ITALIC_PATTERN, lambda match: match.group(1) or match.group(2) or ""),
        (_MARKDOWN_STRIKE_PATTERN, r"\1"),
    )
    for pattern, replacement in replacements:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = _NON_ASCII_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@app.get("/")
def health_check() -> dict[str, Any]:
    """
    Return a minimal health payload for monitoring and readiness probes.
    """
    return {"status": "online", "system": "APEX Nexus"}


@app.get("/api/v1/config")
def get_global_config() -> dict[str, Any]:
    """Expose global system configurations to the frontend HUD on boot."""
    return {
        "default_profile": config.DEFAULT_CLOUD_PROFILE,
        "ask_apex_enabled": config.ASK_APEX_ENABLED,
        "max_session_messages": config.MAX_SESSION_MESSAGES,
    }


@app.get("/api/v1/status", response_model=PipelineStatusSnapshot)
def get_pipeline_diagnostic_status() -> PipelineStatusSnapshot:
    """
    Diagnostic snapshot keyed off global_pipeline_state for operators and probes.
    """
    snapshot = global_pipeline_state.get_state()
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No active pipeline run. System is OFFLINE.",
        )
    return PipelineStatusSnapshot(**snapshot)


@app.get("/api/v1/diagnostics")
def get_system_diagnostics() -> dict[str, float]:
    """
    Hardware utilization snapshot for operators and HUD diagnostics panels.
    """
    return scanner.sample_system_vitals()


@app.post("/api/v1/trigger", response_model=BriefingResponse)
def trigger_briefing() -> BriefingResponse:
    """
    HTTP entry point for a full APEX run.

    Mirrors main.start_apex execution order. When ``DEMO_MODE`` is active,
    serves static mock telemetry through a staged simulation loop.
    """
    if _TRIGGER_LOCK.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline run already active.",
        )

    lock_acquired = _TRIGGER_LOCK.acquire(blocking=False)
    if not lock_acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline run already active.",
        )

    voice_thread_started = False
    try:
        if DEMO_MODE:
            demo_res = _run_demo_briefing()
            voice_thread_started = True  # Lock ownership transferred to demo thread
            return demo_res

        global_pipeline_state.update(1, "GATE")

        if not scanner.should_run():
            global_pipeline_state.reset()
            raise HTTPException(
                status_code=403,
                detail="System gate failed: scanner.should_run() is False.",
            )

        try:
            dev_mode = is_dev_mode()

            if not dev_mode:
                database.log_run()

            speaker.speak("APEX online. Preparing situational overview.")

            global_pipeline_state.update(2, "COLLECTION")
            print("[SYSTEM]: Fetching data...")
            if FEATURE_WEATHER:
                weather_report = weather_client.fetch_weather_data()
            else:
                print("[SYSTEM]: Weather module bypassed via user preference")
                weather_report = ""

            if FEATURE_SPORTS:
                sports_report, f1_cache_refreshed = sports_client.fetch_sports_data()
            else:
                print("[SYSTEM]: Sports module bypassed via user preference")
                sports_report = ""
                f1_cache_refreshed = True

            if FEATURE_NEWS:
                news_report = news_client.fetch_news_data()
            else:
                print("[SYSTEM]: News module bypassed via user preference")
                news_report = ""

            if not FEATURE_EMAIL:
                print("[SYSTEM]: Email module bypassed via user preference")
                email_report = ""
            else:
                try:
                    email_service = google_auth.get_service("gmail", "v1")
                    email_data = gmail_client.get_unread_gmail_data(email_service)

                    count = email_data.get("count", 0)
                    items = email_data.get("emails", [])

                    if items:
                        recent_emails = [
                            f"'{email['subject']}' at {email['time']}"
                            for email in items
                        ]
                        recent_emails_str = ", ".join(recent_emails)
                    else:
                        recent_emails_str = (
                            "Email Telemetry (24h): No unread emails"
                        )

                    email_report = (
                        f"Email Telemetry: {count} unread primary emails. "
                        f"Most recent: {recent_emails_str}"
                    )
                except Exception as exc:
                    print(f"[SYSTEM]: Email fetch failed: ({exc})")
                    email_report = "ERROR: Check connection"

            if not FEATURE_CALENDAR:
                print("[SYSTEM]: Calendar module bypassed via user preference")
                calendar_report = ""
            else:
                try:
                    calendar_service = google_auth.get_service("calendar", "v3")
                    calendar_data = calendar_client.get_upcoming_calendar_events(
                        calendar_service
                    )
                    if calendar_data:
                        calendar_entries = [
                            f"'{event['summary']}' at {event['start']}"
                            for event in calendar_data
                        ]
                        calendar_report = (
                            "Calendar Telemetry (48h): "
                            + " | ".join(calendar_entries)
                        )
                    else:
                        calendar_report = (
                            "Calendar Telemetry (48h): No upcoming events"
                        )
                except Exception as exc:
                    print(f"[SYSTEM]: Calendar fetch failed: ({exc})")
                    calendar_report = "ERROR: Check connection"

            unread_records = database.fetch_unread_reminders()
            if unread_records:
                notes = [note for _, note in unread_records]
                notes_str = ", ".join(notes)
                memory_report = f"Pending Reminders: {notes_str}"
            else:
                memory_report = "No pending reminders."

            combined_raw_data = (
                f"{weather_report} | {sports_report} | {email_report} | "
                f"{calendar_report} | {news_report} | {memory_report}"
            )

            global_pipeline_state.update(3, "SYNTHESIS")
            print("[SYSTEM]: Synthesizing briefing...")

            # Execute filler audio concurrently to hide the Gemini processing time
            filler_thread = threading.Thread(
                target=speaker.speak,
                args=("Generating briefing... Please wait...",),
                daemon=True,
            )
            filler_thread.start()

            brain_output = brain.process_telemetry(combined_raw_data)
            final_briefing = brain_output["briefing"]
            briefing_insights = brain_output["insights"]

            filler_thread.join()

            f1_cache_penalty = FEATURE_SPORTS and MODULE_F1 and not f1_cache_refreshed

            confidence_score, failed_connectors = _compute_confidence_and_failures(
                weather_report=weather_report,
                sports_report=sports_report,
                news_report=news_report,
                email_report=email_report,
                calendar_report=calendar_report,
                f1_cache_penalty=f1_cache_penalty,
            )

            if dev_mode:
                synthesis_strategy = DEV_AI_SYNTHESIS
                tts_strategy = DEV_TTS_PLAYBACK
            else:
                synthesis_strategy = "llm"
                tts_strategy = config.PRIMARY_TTS

            active_tts_engine, system_load_throttled = _resolve_tts_diagnostics(
                dev_mode=dev_mode,
                configured_tts=tts_strategy,
            )
            global_pipeline_state.update(
                4,
                "DELIVERY",
                active_tts_engine=active_tts_engine,
                system_load_throttled=system_load_throttled,
            )
            digest_payload = DigestPayload(
                confidence_score=confidence_score,
                failed_connectors=failed_connectors,
                insights=briefing_insights,
            )
            if not dev_mode:
                try:
                    print("[SYSTEM] Logging briefing run to persistent SQLite ledger.")
                    database.save_briefing(
                        final_briefing, digest_payload.model_dump()
                    )
                    database.prune_historical_ledger()
                except Exception as exc:
                    print(f"[SYSTEM]: Briefing ledger persistence failed: ({exc})")

            voice_thread = threading.Thread(
                target=_speak_and_cleanup,
                kwargs={
                    "text": final_briefing,
                    "tts_override": active_tts_engine,
                    "lock": _TRIGGER_LOCK,
                },
                daemon=True,
            )
            voice_thread.start()
            voice_thread_started = True

            return BriefingResponse(
                status="success",
                briefing=final_briefing,
                telemetry=TelemetryPayload(
                    weather=weather_report,
                    sports=sports_report,
                    news=news_report,
                    email=email_report,
                    calendar=calendar_report,
                    reminders=memory_report,
                ),
                digest=digest_payload,
                metadata=RuntimeMetadata(
                    dev_mode_active=dev_mode,
                    demo_mode_active=False,
                    synthesis_strategy=synthesis_strategy,
                    tts_strategy=tts_strategy,
                    active_tts_engine=active_tts_engine,
                    system_load_throttled=system_load_throttled,
                ),
            )
        finally:
            if not voice_thread_started:
                global_pipeline_state.reset()
    finally:
        if not voice_thread_started:
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()


@app.get("/api/v1/briefings/history", response_model=list[BriefingHistoryRecord])
def get_briefing_history() -> list[dict[str, Any]]:
    """
    Return recent briefing ledger entries for HUD history panels.

    When ``DEMO_MODE`` is active, serves a static mock ledger without querying SQLite.
    """
    if DEMO_MODE:
        return _mock_briefing_history()

    rows = database.fetch_briefing_history(limit=50)
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "briefing": row["briefing"],
            "digest": _parse_digest_payload(row["digest"]),
        }
        for row in rows
    ]


@app.get("/api/v1/reminders", response_model=list[ReminderRecord])
def list_unread_reminders() -> list[ReminderRecord]:
    """
    Return all unread reminders as structured records for HUD refresh.

    Returns:
        List of reminder row IDs paired with their note text.
    """
    if DEMO_MODE:
        return [
            ReminderRecord(id=991, note="Review APEX demo script"),
            ReminderRecord(id=992, note="Charge backup operations hardware"),
        ]

    records = database.fetch_unread_reminders()
    return [{"id": row_id, "note": note} for row_id, note in records]


@app.post(
    "/api/v1/reminders",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateReminderResponse,
)
def create_reminder(payload: CreateReminderRequest) -> CreateReminderResponse:
    """
    Persist a sanitized reminder for inclusion in future briefings.

    Args:
        payload: Request body containing the raw reminder text.

    Returns:
        The database row ID assigned to the new reminder.

    Raises:
        HTTPException: When sanitization yields empty text.
    """
    sanitized_text = clean_for_tts(payload.text)
    if not sanitized_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reminder text is empty after TTS sanitization.",
        )
    if DEMO_MODE:
        return CreateReminderResponse(id=999)
    row_id = database.save_reminder(sanitized_text)
    return CreateReminderResponse(id=row_id)


@app.post(
    "/api/v1/reminders/read",
    status_code=status.HTTP_200_OK,
    response_model=MarkReadResponse,
)
def mark_reminders_read(payload: MarkReadRequest) -> MarkReadResponse:
    """
    Mark one or more reminders as read by SQLite row ID.

    Args:
        payload: Request body listing reminder IDs to update.

    Returns:
        Success outcome label after the database write completes.
    """
    if DEMO_MODE:
        return MarkReadResponse()
    database.mark_reminders_read(payload.ids)
    return MarkReadResponse()


def _resolve_local_profile_status(
    profile: OllamaModelProfile,
    *,
    ollama_reachable: bool,
    installed_tags: list[str],
    vitals: SystemVitals | None,
) -> tuple[ProfileAvailabilityStatus, str | None]:
    """Evaluate a local Ollama profile using cached snapshot signals."""
    if not OLLAMA_ENABLED:
        return "disabled", _PROFILE_STATUS_REASONS["disabled"]

    if not ollama_reachable:
        return "ollama_unreachable", _PROFILE_STATUS_REASONS["ollama_unreachable"]

    if profile.api_model not in installed_tags:
        return "model_not_installed", _PROFILE_STATUS_REASONS["model_not_installed"]

    gate_open, gate_reason = check_resource_gate(
        profile.ram_limit, profile.cpu_limit, vitals=vitals
    )
    if not gate_open and gate_reason is not None:
        return gate_reason, _PROFILE_STATUS_REASONS[gate_reason]

    return "available", None


def _resolve_cloud_profile_status() -> tuple[ProfileAvailabilityStatus, str | None]:
    """Evaluate cloud profile availability based on Gemini credentials."""
    if os.getenv("GEMINI_API_KEY"):
        return "available", None
    return "disabled", "Gemini API key is not configured"


def _build_agent_profile_statuses() -> list[AgentProfileStatus]:
    """Build the full profile availability matrix for the HUD."""
    tracked_active_model = get_active_loaded_model()
    idle_remaining = get_idle_unload_remaining_seconds()

    ollama_reachable = False
    installed_tags: list[str] = []
    loaded_models: list[dict[str, Any]] = []
    vitals: SystemVitals | None = None
    if OLLAMA_ENABLED:
        snapshot = get_status_snapshot()
        ollama_reachable = snapshot["reachable"]
        installed_tags = snapshot["installed_tags"]
        loaded_models = snapshot["loaded_models"]
        vitals = snapshot["vitals"]

    cloud_status, cloud_reason = _resolve_cloud_profile_status()

    profiles: list[AgentProfileStatus] = []

    for key in _AGENT_PROFILE_ORDER:
        if key in OLLAMA_MODEL_PROFILES:
            profile = OLLAMA_MODEL_PROFILES[key]
            loaded_model = next(
                (
                    model
                    for model in loaded_models
                    if model["name"] == profile.api_model
                    or model["model"] == profile.api_model
                ),
                None,
            )
            status, reason = _resolve_local_profile_status(
                profile,
                ollama_reachable=ollama_reachable,
                installed_tags=installed_tags,
                vitals=vitals,
            )
            is_tracked_active = tracked_active_model == profile.api_model
            is_active = (
                loaded_model is not None
                or is_tracked_active
            )
            profiles.append(
                AgentProfileStatus(
                    key=key,
                    display_name=profile.display_name,
                    provider="ollama",
                    status=status,
                    active=is_active,
                    reason=reason,
                    idle_unload_remaining_seconds=(
                        idle_remaining if is_tracked_active else None
                    ),
                    loaded_model=(
                        LocalLoadedModelStatus(**loaded_model)
                        if loaded_model is not None
                        else None
                    ),
                )
            )
            continue

        gemini_profile = GEMINI_MODEL_PROFILES.get(key)
        if gemini_profile is None:
            continue

        profiles.append(
            AgentProfileStatus(
                key=key,
                display_name=gemini_profile.display_name,
                provider="gemini",
                status=cloud_status,
                active=False,
                reason=cloud_reason,
            )
        )

    return profiles


@app.get("/api/v1/agent/profiles", response_model=list[AgentProfileStatus])
def list_agent_profiles() -> list[AgentProfileStatus]:
    """
    Return profile availability for local and cloud assistant modes.

    Ollama reachability, installed tags, and host vitals come from a shared
    TTL snapshot (single /api/tags probe at most once per 10 seconds), so
    frequent HUD polling never floods the daemon while a model is generating.
    """
    return _build_agent_profile_statuses()


@app.post(
    "/api/v1/agent/local/unload",
    response_model=LocalUnloadResponse,
)
def unload_active_local_agent_model() -> LocalUnloadResponse:
    """
    Manually unload the currently active local Ollama model from memory.

    Returns success when no model is active or the unload completes cleanly.
    """
    if not OLLAMA_MANUAL_UNLOAD_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manual local model unload is disabled in system settings.",
        )

    if is_local_execution_active():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A local model generation is in progress. "
                "Wait for it to finish before unloading."
            ),
        )

    if not unload_active_local_model():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Active local model failed to unload from Ollama.",
        )
    return LocalUnloadResponse()


def _trim_agent_history(
    history: list[AgentMessage], max_messages: int
) -> list[AgentMessage]:
    """
    Bound session history so prompt evaluation cost stays flat over a session.

    After the cut, leading non-user messages are dropped so the model never
    sees orphaned tool output or an assistant reply without its prompt at the
    start of the window.
    """
    if len(history) <= max_messages:
        return list(history)

    trimmed = list(history[-max_messages:])
    while trimmed and trimmed[0].role != "user":
        trimmed.pop(0)
    return trimmed


def _execute_agent_turn(
    payload: AgentQueryRequest,
    profile: GeminiModelProfile | OllamaModelProfile,
    api_key: str | None,
) -> AgentQueryResponse:
    """Build HUD context, select the provider, and run the bounded agent loop."""
    try:
        latest_runs = database.fetch_briefing_history(limit=1)
        hud_context = ""
        if latest_runs:
            briefing_text = latest_runs[0]["briefing"]
            insights_list = latest_runs[0]["digest"].get("insights", [])
            hud_context = (
                "\n\nCURRENT HUD STATE:\n"
                "The user is actively looking at this compiled briefing on their HUD screen:\n"
                f'- Briefing Prose: "{briefing_text}"\n'
                f"- Active Summary Insights: "
                f"{', '.join(insights_list) if insights_list else 'None'}\n"
                "Use this context to resolve relative follow-up queries about the active briefing "
                "(e.g., 'explain that first insight', 'why did you mention the weather?', "
                "or 'summarize this')."
            )

        if isinstance(profile, OllamaModelProfile):
            provider: GeminiProvider | OllamaProvider = OllamaProvider()
            base_prompt = config.LOCAL_AGENT_SYSTEM_PROMPT
        else:
            provider = GeminiProvider(api_key=api_key)
            base_prompt = config.AGENT_SYSTEM_PROMPT

        local_system_instruction = base_prompt + hud_context

        return run_agent_loop(
            payload,
            provider,
            profile,
            system_instruction_override=local_system_instruction,
        )
    except Exception as exc:
        _LOGGER.exception(
            "Agent turn failed for profile %s",
            payload.profile,
        )
        if isinstance(profile, OllamaModelProfile):
            answer = (
                "The APEX assistant encountered an issue reaching the local Ollama "
                "provider or running the requested operations. Please verify that "
                "Ollama is running, the model is installed, and system resources "
                "are sufficient, then try again."
            )
            error_detail = f"Local provider error ({type(exc).__name__}): {exc}"
        else:
            answer = (
                "The APEX assistant encountered an issue reaching the cloud provider "
                "or running the requested operations. Please check your "
                "credentials, network status, or quota allocations, and try again."
            )
            error_detail = f"Cloud provider error ({type(exc).__name__}): {exc}"

        return AgentQueryResponse(
            answer=answer,
            profile_used=profile.model_dump(),
            session_id=payload.session_id,
            error=error_detail,
        )


@app.post("/api/v1/agent/query", response_model=AgentQueryResponse)
def query_agent(payload: AgentQueryRequest) -> AgentQueryResponse:
    """
    Execute an APEX assistant turn with optional tool calling.

    Runs synchronously so uvicorn can offload blocking provider I/O to a
    worker thread. Local (Ollama) queries pass an admission gate first:
    a non-blocking execution slot (429 when busy), a host resource gate
    (503 with the gate reason), and a coordinated model switch (503 on
    load failure).
    """
    if not config.ASK_APEX_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="APEX is currently disabled in system settings.",
        )

    if DEMO_MODE:
        return _run_demo_agent_query(payload)

    profile: GeminiModelProfile | OllamaModelProfile | None = None
    if payload.profile in OLLAMA_MODEL_PROFILES:
        profile = OLLAMA_MODEL_PROFILES[payload.profile]
    elif payload.profile in GEMINI_MODEL_PROFILES:
        profile = GEMINI_MODEL_PROFILES[payload.profile]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown agent profile: {payload.profile!r}",
        )

    api_key: str | None = None
    if payload.profile in GEMINI_MODEL_PROFILES:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return AgentQueryResponse(
                answer=(
                    "APEX is currently unavailable because the Gemini "
                    "API key is not configured. Please set GEMINI_API_KEY in your "
                    "environment and restart the API server."
                ),
                profile_used={},
                session_id=payload.session_id,
                error="GEMINI_API_KEY is missing from environment variables.",
            )

    payload.history = _trim_agent_history(
        payload.history, config.MAX_SESSION_MESSAGES
    )

    if isinstance(profile, OllamaModelProfile):
        if not OLLAMA_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Local Ollama inference is disabled in system settings.",
            )

        if not try_begin_local_execution():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "A local model generation is already in progress. "
                    "Wait for it to finish and try again."
                ),
            )

        try:
            gate_open, gate_reason = check_resource_gate(
                profile.ram_limit, profile.cpu_limit
            )
            if not gate_open and gate_reason is not None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"Local profile blocked: "
                        f"{_PROFILE_STATUS_REASONS[gate_reason]}."
                    ),
                )

            if not switch_local_model(profile):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"Local model {profile.api_model} failed to load. "
                        "Ensure Ollama is reachable and configured."
                    ),
                )

            return _execute_agent_turn(payload, profile, api_key=None)
        finally:
            end_local_execution()

    return _execute_agent_turn(payload, profile, api_key=api_key)


def main() -> None:
    """Run the API server bound to localhost."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
