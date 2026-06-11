"""
FastAPI application for APEX (Milestone Nexus).

Standalone HTTP surface; briefing trigger mirrors main.start_apex flow.
"""

from __future__ import annotations

import json
import os
import time
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

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
from core import brain, database, scanner, speaker
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
    is_dev_mode,
)

load_dotenv(dotenv_path=ENV_PATH)

WEATHER_FAILED_RE = re.compile(r"(offline|error|failed)", re.IGNORECASE)
SPORTS_F1_FAILED_RE = re.compile(r"(telemetry unavailable)", re.IGNORECASE)
SPORTS_FB_FAILED_RE = re.compile(r"(telemetry unavailable|throttled)", re.IGNORECASE)
NEWS_FAILED_RE = re.compile(r"(telemetry unavailable|offline)", re.IGNORECASE)
EMAIL_FAILED_RE = re.compile(r"(error|check connection)", re.IGNORECASE)
CALENDAR_FAILED_RE = re.compile(r"(error|check connection)", re.IGNORECASE)

_F1_CACHE_PATH = Path(__file__).resolve().parent.parent / "clients" / ".f1_cache.json"

app = FastAPI(title="APEX Nexus")


DEFAULT_ALLOWED_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
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

    def update(self, step: int, label: str) -> None:
        """
        Advance the conceptual pipeline stage.

        Args:
            step: Monotonic pipeline step index supplied by orchestration logic.
            label: Stable short label naming the stage for dashboards and probes.
        """
        with self._lock:
            self._is_active = True
            self._step = step
            self._label = label
            self._timestamp = datetime.now(timezone.utc).isoformat()

    def reset(self) -> None:
        """Restore the tracker to idle or pre-run defaults."""
        with self._lock:
            self._is_active = False
            self._step = 0
            self._label = "IDLE"
            self._timestamp = datetime.now(timezone.utc).isoformat()

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
            }


global_pipeline_state = PipelineState()
_TRIGGER_LOCK = threading.Lock()

_MOCK_TELEMETRY_PATH = Path(__file__).resolve().parent / "mock" / "telemetry.json"
_DEMO_STAGE_DELAY_SECONDS = 1.5


def _speak_and_cleanup(
    text: str,
    *,
    tts_override: str | None = None,
    digest: DigestPayload | None = None,
    lock: threading.Lock | None = None,
) -> None:
    """Play briefing audio on a worker thread and reset pipeline state when playback ends."""
    if digest is not None and not is_dev_mode():
        try:
            print("[SYSTEM] Logging briefing run to persistent SQLite ledger.")
            digest_dict = (
                digest.model_dump()
                if hasattr(digest, "model_dump")
                else digest.dict()
            )
            database.save_briefing(text, digest_dict)
            database.prune_historical_ledger()
        except Exception as exc:
            print(f"[SYSTEM]: Briefing ledger persistence failed: ({exc})")

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
    tts_strategy: str = Field(
        description="Active text-to-speech backend (dev config or production default).",
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
    """Safely parse a digest sub-object with fallback defaults for missing keys."""
    if not isinstance(raw_digest, dict):
        return DigestPayload(confidence_score=0.0)

    failed_connectors = raw_digest.get("failed_connectors", [])
    if not isinstance(failed_connectors, list):
        failed_connectors = []

    raw_insights = raw_digest.get("insights", [])
    if not isinstance(raw_insights, list):
        raw_insights = []

    return DigestPayload(
        weather_archetype=raw_digest.get("weather_archetype"),
        unread_emails_count=int(raw_digest.get("unread_emails_count", 0)),
        upcoming_events_count=int(raw_digest.get("upcoming_events_count", 0)),
        f1_sprint_active=bool(raw_digest.get("f1_sprint_active", False)),
        reminders_pending_count=int(raw_digest.get("reminders_pending_count", 0)),
        confidence_score=float(raw_digest.get("confidence_score", 0.0)),
        failed_connectors=[str(name) for name in failed_connectors],
        insights=[str(line) for line in raw_insights],
    )


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
    earned_weight = 0.0
    total_weight = 0.0
    sports_failed = False

    if MODULE_F1 and MODULE_FOOTBALL:
        f1_part, fb_part = _split_sports_report(sports_report)
        total_weight = 1.0
        if not SPORTS_F1_FAILED_RE.search(f1_part):
            earned_weight += 0.5
        else:
            sports_failed = True
        if not SPORTS_FB_FAILED_RE.search(fb_part):
            earned_weight += 0.5
        else:
            sports_failed = True
    elif MODULE_F1:
        total_weight = 1.0
        if SPORTS_F1_FAILED_RE.search(sports_report):
            sports_failed = True
        else:
            earned_weight = 1.0
    elif MODULE_FOOTBALL:
        total_weight = 1.0
        if SPORTS_FB_FAILED_RE.search(sports_report):
            sports_failed = True
        else:
            earned_weight = 1.0
    else:
        total_weight = 1.0
        earned_weight = 1.0

    return earned_weight, total_weight, sports_failed


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
    combined_raw_data = (
        f"{telemetry.weather} | {telemetry.sports} | {telemetry.email} | "
        f"{telemetry.calendar} | {telemetry.news} | {telemetry.reminders}"
    )
    return (
        "Greetings Chief. APEX simulation controls are operational. "
        "Atmospheric sensors report seventy-two degrees with clear skies. "
        "The Monaco Grand Prix is scheduled for this week, with the main race running on Sunday. "
        "Your inbox has two unread primary messages, and your next calendar item, "
        "Demo Presentation, begins at three PM. All local databases are fully synchronized."
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

        global_pipeline_state.update(4, "DELIVERY")
        voice_thread = threading.Thread(
            target=_speak_and_cleanup,
            kwargs={
                "text": final_briefing,
                "tts_override": DEMO_TTS,
                "digest": digest,
                "lock": _TRIGGER_LOCK,
            },
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
    cleaned = _MARKDOWN_CODE_BLOCK_PATTERN.sub(" ", cleaned)
    cleaned = _MARKDOWN_IMAGE_PATTERN.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_INLINE_CODE_PATTERN.sub(r"\1", cleaned)
    cleaned = _MARKDOWN_HEADER_PATTERN.sub("", cleaned)
    cleaned = _MARKDOWN_BLOCKQUOTE_PATTERN.sub("", cleaned)
    cleaned = _MARKDOWN_HRULE_PATTERN.sub(" ", cleaned)
    cleaned = _MARKDOWN_LIST_MARKER_PATTERN.sub("", cleaned)
    cleaned = _MARKDOWN_ORDERED_LIST_PATTERN.sub("", cleaned)
    cleaned = _MARKDOWN_BOLD_PATTERN.sub(
        lambda match: match.group(1) or match.group(2) or "",
        cleaned,
    )
    cleaned = _MARKDOWN_ITALIC_PATTERN.sub(
        lambda match: match.group(1) or match.group(2) or "",
        cleaned,
    )
    cleaned = _MARKDOWN_STRIKE_PATTERN.sub(r"\1", cleaned)
    cleaned = _NON_ASCII_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


@app.get("/")
def health_check() -> dict[str, Any]:
    """
    Return a minimal health payload for monitoring and readiness probes.
    """
    return {"status": "online", "system": "APEX Nexus"}


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

    try:
        if DEMO_MODE:
            return _run_demo_briefing()

        voice_thread_started = False
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

            speaker.speak("System initialized. All modules online.")

            global_pipeline_state.update(2, "COLLECTION")
            print("[SYSTEM]: Fetching data...")
            if FEATURE_WEATHER:
                weather_report = weather_client.fetch_weather_data()
            else:
                print("[SYSTEM]: Weather module bypassed via user preference")
                weather_report = ""

            f1_cache_existed_before = False
            f1_mtime_before: float | None = None
            f1_mtime_after: float | None = None
            if FEATURE_SPORTS:
                f1_cache_existed_before = _F1_CACHE_PATH.exists()
                if f1_cache_existed_before:
                    f1_mtime_before = os.path.getmtime(_F1_CACHE_PATH)
                sports_report = sports_client.fetch_sports_data()
                if _F1_CACHE_PATH.exists():
                    f1_mtime_after = os.path.getmtime(_F1_CACHE_PATH)
            else:
                print("[SYSTEM]: Sports module bypassed via user preference")
                sports_report = ""

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
            )
            filler_thread.start()

            brain_output = brain.process_telemetry(combined_raw_data)
            final_briefing = brain_output["briefing"]
            briefing_insights = brain_output["insights"]

            filler_thread.join()

            f1_cache_penalty = False
            if FEATURE_SPORTS and MODULE_F1 and f1_cache_existed_before:
                f1_cache_penalty = (
                    f1_mtime_before is not None
                    and f1_mtime_after is not None
                    and f1_mtime_after == f1_mtime_before
                )

            confidence_score, failed_connectors = _compute_confidence_and_failures(
                weather_report=weather_report,
                sports_report=sports_report,
                news_report=news_report,
                email_report=email_report,
                calendar_report=calendar_report,
                f1_cache_penalty=f1_cache_penalty,
            )

            global_pipeline_state.update(4, "DELIVERY")
            digest_payload = DigestPayload(
                confidence_score=confidence_score,
                failed_connectors=failed_connectors,
                insights=briefing_insights,
            )
            voice_thread = threading.Thread(
                target=_speak_and_cleanup,
                kwargs={
                    "text": final_briefing,
                    "digest": digest_payload,
                    "lock": _TRIGGER_LOCK,
                },
            )
            voice_thread.start()
            voice_thread_started = True

            if dev_mode:
                synthesis_strategy = DEV_AI_SYNTHESIS
                tts_strategy = DEV_TTS_PLAYBACK
            else:
                synthesis_strategy = "llm"
                tts_strategy = "google"

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


def main() -> None:
    """Run the API server bound to localhost."""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
