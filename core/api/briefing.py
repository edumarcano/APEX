"""Typed connector collection and briefing pipeline orchestration."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status

from core import brain, database, speaker
from core.api.demo import build_demo_briefing, load_mock_telemetry
from core.api.models import (
    BriefingResponse,
    DigestPayload,
    RuntimeMetadata,
    TelemetryPayload,
)
from core.api.state import _TRIGGER_LOCK, _speak_and_cleanup, global_pipeline_state
from core.api.tts import resolve_tts_diagnostics
from core.config import (
    DEMO_MODE,
    DEMO_TTS,
    DEV_AI_SYNTHESIS,
    DEV_TTS_PLAYBACK,
    is_dev_mode,
)
from core.connectors.models import ConnectorResult
from core.connectors.scoring import compute_sync_health
from core.runtime_logging import bind_run_id_context, run_id_scope
from core.settings import get_settings_store
from core.synthesis import (
    BriefingMode,
    CalendarFact,
    ConnectorHealthFact,
    F1Fact,
    FootballFact,
    NewsFact,
    SynthesisInput,
    SynthesisRouter,
    strategy_to_briefing_mode,
)
from core.telemetry.models import TelemetrySnapshot
from core.telemetry.service import RefreshInProgressError, get_telemetry_service

_DEMO_STAGE_DELAY_SECONDS = 1.5
_LOGGER = logging.getLogger(__name__)


def _mode_to_strategy(mode: BriefingMode) -> str:
    if mode == "comet":
        return "cloud"
    if mode == "structured_digest":
        return "raw"
    return "local"


def _resolve_default_mode(*, dev_mode: bool) -> BriefingMode:
    if dev_mode:
        return strategy_to_briefing_mode(DEV_AI_SYNTHESIS)
    return get_settings_store().get_snapshot().briefing.default_mode


def _voice_is_automatic() -> bool:
    return get_settings_store().get_snapshot().voice.mode == "automatic"


def _maybe_speak(text: str, *, tts_override: str | None = None, voice_gender: str | None = None) -> None:
    """Speak only when voice mode is automatic (blocking filler path)."""
    if not _voice_is_automatic():
        return
    speaker.speak(text, tts_override=tts_override, voice_gender=voice_gender)


def _compute_confidence_and_failures(
    *,
    results: dict[str, ConnectorResult | None],
) -> tuple[float, list[str]]:
    """Compatibility wrapper returning sync health score and legacy failures."""
    report = compute_sync_health(results)
    return report.sync_health_score, report.failed_connectors


def _build_synthesis_input(
    *,
    results: dict[str, ConnectorResult | None],
    failed_connectors: list[str],
) -> SynthesisInput:
    weather = results.get("weather")
    news = results.get("news")
    email = results.get("email")
    calendar = results.get("calendar")
    f1 = results.get("f1")
    football = results.get("football")
    reminders = results.get("reminders")

    weather_data = weather.data if weather else {}
    email_data = email.data if email else {}
    calendar_data = calendar.data if calendar else {}
    reminder_data = reminders.data if reminders else {}
    f1_map = f1.data.get("f1_map") if f1 else None
    football_data = football.data if football else {}

    next_event: CalendarFact | None = None
    events = calendar_data.get("events") if isinstance(calendar_data, dict) else None
    if isinstance(events, list) and events:
        raw_event = events[0]
        if isinstance(raw_event, dict):
            raw_start = str(raw_event.get("start", "")).strip()
            next_event = CalendarFact(
                title=str(raw_event.get("summary", "Untitled event")),
                start=raw_start or "Time unavailable",
                all_day=bool(raw_start and "T" not in raw_start),
            )

    f1_fact: F1Fact | None = None
    if isinstance(f1_map, dict) and f1_map.get("relativeWeek") == "This week":
        f1_fact = F1Fact(
            race_name=str(f1_map.get("raceName", "Unknown race")),
            start=str(f1_map.get("raceDateTimeEST", "Unscheduled")),
            sprint_scheduled=bool(f1_map.get("sprintScheduled")),
        )

    football_fact: FootballFact | None = None
    if football and football.status != "unavailable" and football_data.get("opponent"):
        football_fact = FootballFact(
            opponent=str(football_data.get("opponent", "")),
            fixture_date=str(football_data.get("fixture_date", "")),
            summary=str(football_data.get("summary") or "") or None,
        )

    news_headlines: list[NewsFact] = []
    if news and isinstance(news.data.get("headlines"), list):
        for item in news.data["headlines"][:2]:
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic", "")).strip()
            headline = str(item.get("headline", "")).strip()
            if topic and headline:
                news_headlines.append(NewsFact(topic=topic, headline=headline))

    email_subjects: list[str] = []
    emails = email_data.get("emails") if isinstance(email_data, dict) else None
    if isinstance(emails, list):
        for item in emails[:3]:
            if isinstance(item, dict):
                subject = str(item.get("subject", "")).strip()
                if subject:
                    email_subjects.append(subject)

    reminder_notes = reminder_data.get("notes") if isinstance(reminder_data, dict) else None
    first_reminder = None
    pending_count = 0
    if isinstance(reminder_notes, list) and reminder_notes:
        pending_count = len(reminder_notes)
        first_reminder = str(reminder_notes[0])

    connector_health = [
        ConnectorHealthFact(
            name=result.name,
            status=result.status,
            reason_code=result.reason_code,
        )
        for result in results.values()
        if result is not None and result.status != "disabled"
    ]

    weather_summary = None
    if weather and weather.status != "unavailable":
        weather_summary = weather.display_text or None
        if weather_data.get("temp_f") is not None and weather_data.get("condition"):
            weather_summary = (
                f"Current temperature is {weather_data['temp_f']} degrees "
                f"with {weather_data['condition']}."
            )

    return SynthesisInput(
        weather_summary=weather_summary,
        weather_temp_f=(
            int(weather_data["temp_f"])
            if isinstance(weather_data, dict) and isinstance(weather_data.get("temp_f"), (int, float))
            else None
        ),
        weather_condition=(
            str(weather_data.get("condition"))
            if isinstance(weather_data, dict) and weather_data.get("condition")
            else None
        ),
        email_unread_count=int(email_data.get("count", 0) or 0) if isinstance(email_data, dict) else 0,
        email_recent_subjects=email_subjects,
        news_headlines=news_headlines,
        calendar_event_count=int(calendar_data.get("count", 0) or 0)
        if isinstance(calendar_data, dict)
        else 0,
        next_calendar_event=next_event,
        pending_reminder_count=pending_count,
        first_pending_reminder=first_reminder,
        f1_this_week=f1_fact,
        football_next_fixture=football_fact,
        connector_health=connector_health,
        failed_connectors=failed_connectors,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _display_text(result: ConnectorResult | None) -> str:
    return result.display_text if result is not None else ""


def _legacy_telemetry_payload(results: dict[str, ConnectorResult | None]) -> TelemetryPayload:
    return TelemetryPayload(
        weather=_display_text(results.get("weather")),
        sports=" ".join(
            part
            for part in (
                _display_text(results.get("f1")),
                _display_text(results.get("football")),
            )
            if part
        ),
        news=_display_text(results.get("news")),
        email=_display_text(results.get("email")),
        calendar=_display_text(results.get("calendar")),
        reminders=_display_text(results.get("reminders")),
    )


def _build_digest(
    *,
    results: dict[str, ConnectorResult | None],
    insights: list[str],
) -> DigestPayload:
    report = compute_sync_health(results)
    weather = results.get("weather")
    email = results.get("email")
    calendar = results.get("calendar")
    f1 = results.get("f1")
    reminders = results.get("reminders")

    weather_archetype = None
    if weather and isinstance(weather.data.get("archetype"), str):
        weather_archetype = weather.data["archetype"]

    f1_sprint_active = False
    f1_map = f1.data.get("f1_map") if f1 else None
    if isinstance(f1_map, dict):
        f1_sprint_active = bool(f1_map.get("sprintScheduled"))

    return DigestPayload(
        weather_archetype=weather_archetype,
        unread_emails_count=int((email.data.get("count", 0) if email else 0) or 0),
        upcoming_events_count=int((calendar.data.get("count", 0) if calendar else 0) or 0),
        f1_sprint_active=f1_sprint_active,
        reminders_pending_count=int((reminders.data.get("count", 0) if reminders else 0) or 0),
        sync_health_score=report.sync_health_score,
        connector_health=report.connector_health,
        confidence_score=report.confidence_score,
        failed_connectors=report.failed_connectors,
        insights=insights,
    )


def _require_current_snapshot(snapshot_id: str) -> TelemetrySnapshot:
    snapshot = get_telemetry_service().latest()
    if snapshot is None or snapshot.snapshot_id != snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Telemetry snapshot is missing or no longer current.",
        )
    return snapshot


def _acquire_pipeline_lock() -> None:
    if _TRIGGER_LOCK.locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline run already active.",
        )
    if not _TRIGGER_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pipeline run already active.",
        )


def _run_demo_briefing(
    *,
    run_id: str,
    snapshot: TelemetrySnapshot | None = None,
    mode: BriefingMode | None = None,
) -> BriefingResponse:
    """Execute the staged simulation path when ``DEMO_MODE`` is active."""
    voice_thread_started = False

    try:
        global_pipeline_state.begin_run(run_id)
        global_pipeline_state.update(1, "GATE")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        global_pipeline_state.update(2, "COLLECTION")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        telemetry, digest = load_mock_telemetry()
        # The compatibility trigger seeds demo telemetry. Direct generation
        # reuses the already validated process-current snapshot.
        active_snapshot = snapshot or get_telemetry_service().seed_demo_snapshot()

        global_pipeline_state.update(3, "SYNTHESIS")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        final_briefing = build_demo_briefing(telemetry)

        active_tts_engine, system_load_throttled = resolve_tts_diagnostics(
            dev_mode=True,
            configured_tts=DEMO_TTS,
        )
        global_pipeline_state.update(
            4,
            "DELIVERY",
            active_tts_engine=active_tts_engine,
            system_load_throttled=system_load_throttled,
        )

        spoken = False
        if _voice_is_automatic():
            voice_thread = threading.Thread(
                target=bind_run_id_context(_speak_and_cleanup),
                kwargs={
                    "text": final_briefing,
                    "tts_override": active_tts_engine,
                    "voice_gender": get_settings_store().get_snapshot().voice.gender,
                    "lock": _TRIGGER_LOCK,
                },
                daemon=True,
            )
            voice_thread.start()
            voice_thread_started = True
            spoken = True
        else:
            global_pipeline_state.reset()
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()

        return BriefingResponse(
            status="success",
            briefing=final_briefing,
            telemetry=telemetry,
            digest=digest,
            metadata=RuntimeMetadata(
                run_id=run_id,
                dev_mode_active=True,
                demo_mode_active=True,
                synthesis_strategy="demo",
                briefing_mode=mode,
                synthesis_provider="demo",
                tts_strategy=DEMO_TTS,
                active_tts_engine=active_tts_engine,
                system_load_throttled=system_load_throttled,
                snapshot_id=active_snapshot.snapshot_id,
                spoken=spoken,
            ),
        )
    finally:
        if not voice_thread_started:
            global_pipeline_state.reset()
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()


def _synthesize_from_snapshot(
    *,
    snapshot: TelemetrySnapshot,
    mode: BriefingMode,
    run_id: str,
    speak_fillers: bool,
) -> BriefingResponse:
    """
    Synthesize, persist, and optionally speak from an existing snapshot.

    Caller must hold ``_TRIGGER_LOCK`` and have begun the pipeline run.
    """
    voice_thread_started = False
    try:
        get_settings_store().get_snapshot()
        dev_mode = is_dev_mode()
        synthesis_router = SynthesisRouter(global_pipeline_state.update_synthesis)
        warmup = synthesis_router.prepare_mode(mode)

        results = snapshot.results_map()
        health = compute_sync_health(results)
        synthesis_input = _build_synthesis_input(
            results=results,
            failed_connectors=health.failed_connectors,
        )

        global_pipeline_state.update(3, "SYNTHESIS")
        _LOGGER.info("Synthesizing briefing mode=%s", mode)

        filler_thread: threading.Thread | None = None
        if speak_fillers and _voice_is_automatic():
            filler_thread = threading.Thread(
                target=bind_run_id_context(speaker.speak),
                args=("Generating briefing... Please wait...",),
                daemon=True,
            )
            filler_thread.start()

        brain_output = brain.process_telemetry(
            "",
            synthesis_input=synthesis_input,
            mode=mode,
            warmup=warmup,
            router=synthesis_router,
        )
        final_briefing = brain_output["briefing"]
        briefing_insights = brain_output["insights"]

        if filler_thread is not None:
            filler_thread.join()

        delivery_voice = get_settings_store().get_snapshot().voice
        if dev_mode:
            tts_strategy = DEV_TTS_PLAYBACK
            synthesis_strategy = _mode_to_strategy(mode)
        else:
            synthesis_strategy = _mode_to_strategy(mode)
            tts_strategy = delivery_voice.engine

        active_tts_engine, system_load_throttled = resolve_tts_diagnostics(
            dev_mode=dev_mode,
            configured_tts=tts_strategy,
        )
        global_pipeline_state.update(
            4,
            "DELIVERY",
            active_tts_engine=active_tts_engine,
            system_load_throttled=system_load_throttled,
        )
        digest_payload = _build_digest(results=results, insights=briefing_insights)
        spoken = _voice_is_automatic()
        runtime_metadata = RuntimeMetadata(
            run_id=run_id,
            dev_mode_active=dev_mode,
            demo_mode_active=False,
            synthesis_strategy=synthesis_strategy,
            briefing_mode=mode,
            synthesis_provider=brain_output.get("provider"),
            synthesis_profile=brain_output.get("profile"),
            synthesis_fallback_reason=brain_output.get("fallback_reason"),
            synthesis_warmup_ms=brain_output.get("warmup_ms"),
            synthesis_generation_ms=brain_output.get("generation_ms"),
            tts_strategy=tts_strategy,
            active_tts_engine=active_tts_engine,
            system_load_throttled=system_load_throttled,
            snapshot_id=snapshot.snapshot_id,
            spoken=spoken,
        )
        if not dev_mode:
            try:
                _LOGGER.info("Persisting briefing run to SQLite ledger")
                database.save_briefing(
                    final_briefing,
                    digest_payload.model_dump(),
                    runtime_metadata.model_dump(),
                )
                database.prune_historical_ledger()
            except (sqlite3.Error, OSError, TypeError, ValueError):
                _LOGGER.exception(
                    "Briefing ledger persistence failed: persistence_error"
                )

        if spoken:
            voice_thread = threading.Thread(
                target=bind_run_id_context(_speak_and_cleanup),
                kwargs={
                    "text": final_briefing,
                    "tts_override": active_tts_engine,
                    "voice_gender": delivery_voice.gender,
                    "lock": _TRIGGER_LOCK,
                },
                daemon=True,
            )
            voice_thread.start()
            voice_thread_started = True
        else:
            global_pipeline_state.reset()
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()

        return BriefingResponse(
            status="success",
            briefing=final_briefing,
            telemetry=_legacy_telemetry_payload(results),
            digest=digest_payload,
            metadata=runtime_metadata,
        )
    finally:
        if not voice_thread_started:
            global_pipeline_state.reset()
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()


def generate_briefing(*, snapshot_id: str, mode: BriefingMode) -> BriefingResponse:
    """
    Generate a briefing from an existing in-memory telemetry snapshot.

    Performs no connector calls. Returns ``409`` when the snapshot is missing
    or no longer current in this process.
    """
    snapshot = _require_current_snapshot(snapshot_id)
    _acquire_pipeline_lock()
    run_id = str(uuid.uuid4())
    with run_id_scope(run_id):
        if DEMO_MODE:
            return _run_demo_briefing(run_id=run_id, snapshot=snapshot, mode=mode)
        try:
            global_pipeline_state.begin_run(run_id)
            global_pipeline_state.update(1, "GATE")
            if not is_dev_mode():
                database.log_run()
            global_pipeline_state.update(2, "COLLECTION")
            return _synthesize_from_snapshot(
                snapshot=snapshot,
                mode=mode,
                run_id=run_id,
                speak_fillers=False,
            )
        except Exception:
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()
            global_pipeline_state.reset()
            raise


def trigger_briefing() -> BriefingResponse:
    """
    Run a full APEX briefing pipeline.

    Force-refreshes telemetry, then synthesizes with the configured default
    briefing mode. When ``DEMO_MODE`` is active, serves static mock telemetry
    through a staged simulation loop.

    Startup Wi-Fi/power/cooldown gating is no longer a hard blocker; callers
    should use ``POST /api/v1/preflight`` for advisory warnings.
    """
    _acquire_pipeline_lock()

    run_id = str(uuid.uuid4())
    with run_id_scope(run_id):
        try:
            if DEMO_MODE:
                return _run_demo_briefing(run_id=run_id)

            global_pipeline_state.begin_run(run_id)
            global_pipeline_state.update(1, "GATE")

            get_settings_store().get_snapshot()
            dev_mode = is_dev_mode()
            mode = _resolve_default_mode(dev_mode=dev_mode)

            if not dev_mode:
                database.log_run()

            _maybe_speak("APEX online. Preparing situational overview.")

            global_pipeline_state.update(2, "COLLECTION")
            _LOGGER.info("Fetching connector data")
            try:
                snapshot = get_telemetry_service().collect_for_briefing()
            except RefreshInProgressError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from None

            return _synthesize_from_snapshot(
                snapshot=snapshot,
                mode=mode,
                run_id=run_id,
                speak_fillers=True,
            )
        except Exception:
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()
            global_pipeline_state.reset()
            raise
