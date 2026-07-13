"""Connector trust scoring and briefing pipeline orchestration."""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from clients import (
    calendar_client,
    gmail_client,
    google_auth,
    news_client,
    sports_client,
    weather_client,
)
from core import brain, database, scanner, speaker
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
from core.settings import FeaturesSettings, ModulesSettings, get_settings_store
from core.synthesis import CalendarFact, F1Fact, SynthesisInput, SynthesisRouter

WEATHER_FAILED_RE = re.compile(r"(offline|error|failed)", re.IGNORECASE)
SPORTS_F1_FAILED_RE = re.compile(r"(telemetry unavailable)", re.IGNORECASE)
SPORTS_FB_FAILED_RE = re.compile(r"(telemetry unavailable|throttled)", re.IGNORECASE)
NEWS_FAILED_RE = re.compile(r"(telemetry unavailable|offline)", re.IGNORECASE)
EMAIL_FAILED_RE = re.compile(r"(error|check connection)", re.IGNORECASE)
CALENDAR_FAILED_RE = re.compile(r"(error|check connection)", re.IGNORECASE)

_DEMO_STAGE_DELAY_SECONDS = 1.5


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
    *,
    modules: ModulesSettings,
) -> tuple[float, float, bool]:
    """
    Return earned weight, total weight, and whether any sports subdivision failed.

    Sports weight is 1.0 when a single sub-module is active, or 0.5 per sub-module
    when both F1 and football are enabled.
    """
    active_modules: list[tuple[re.Pattern[str], str]] = []
    if modules.f1 and modules.football:
        f1_part, fb_part = _split_sports_report(sports_report)
    else:
        f1_part, fb_part = sports_report, sports_report

    if modules.f1:
        active_modules.append((SPORTS_F1_FAILED_RE, f1_part))
    if modules.football:
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
    features: FeaturesSettings,
    modules: ModulesSettings,
) -> tuple[float, list[str]]:
    """Evaluate active connector telemetry and derive trust score plus failures."""
    failed_connectors: list[str] = []
    earned_weight = 0.0
    total_weight = 0.0

    connector_checks: list[tuple[str, bool, str, re.Pattern[str]]] = [
        ("weather", features.weather, weather_report, WEATHER_FAILED_RE),
        ("news", features.news, news_report, NEWS_FAILED_RE),
        ("email", features.email, email_report, EMAIL_FAILED_RE),
        ("calendar", features.calendar, calendar_report, CALENDAR_FAILED_RE),
    ]

    for connector_name, enabled, report, failure_pattern in connector_checks:
        if not enabled:
            continue
        total_weight += 1.0
        if failure_pattern.search(report):
            failed_connectors.append(connector_name)
        else:
            earned_weight += 1.0

    if features.sports:
        sports_earned, sports_total, sports_failed = _evaluate_sports_trust(
            sports_report,
            modules=modules,
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


def _run_demo_briefing() -> BriefingResponse:
    """Execute the staged simulation path when ``DEMO_MODE`` is active."""
    voice_thread_started = False

    try:
        global_pipeline_state.update(1, "GATE")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        global_pipeline_state.update(2, "COLLECTION")
        time.sleep(_DEMO_STAGE_DELAY_SECONDS)

        telemetry, digest = load_mock_telemetry()

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

        voice_thread = threading.Thread(
            target=_speak_and_cleanup,
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

        return BriefingResponse(
            status="success",
            briefing=final_briefing,
            telemetry=telemetry,
            digest=digest,
            metadata=RuntimeMetadata(
                dev_mode_active=True,
                demo_mode_active=True,
                synthesis_strategy="demo",
                synthesis_provider="demo",
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


def trigger_briefing() -> BriefingResponse:
    """
    Run a full APEX briefing pipeline.

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
            briefing_settings = get_settings_store().get_snapshot()
            features = briefing_settings.features
            modules = briefing_settings.modules

            dev_mode = is_dev_mode()
            synthesis_strategy = DEV_AI_SYNTHESIS if dev_mode else "cloud"
            synthesis_router = SynthesisRouter(global_pipeline_state.update_synthesis)
            warmup = synthesis_router.prepare(synthesis_strategy)

            if not dev_mode:
                database.log_run()

            speaker.speak("APEX online. Preparing situational overview.")

            global_pipeline_state.update(2, "COLLECTION")
            print("[SYSTEM]: Fetching data...")
            if features.weather:
                weather_report = weather_client.fetch_weather_data()
            else:
                print("[SYSTEM]: Weather module bypassed via user preference")
                weather_report = ""

            if features.sports:
                sports_report, f1_cache_refreshed, f1_map = sports_client.fetch_sports_snapshot(
                    f1=modules.f1,
                    football=modules.football,
                )
            else:
                print("[SYSTEM]: Sports module bypassed via user preference")
                sports_report = ""
                f1_cache_refreshed = True
                f1_map = None

            if features.news:
                news_report = news_client.fetch_news_data()
            else:
                print("[SYSTEM]: News module bypassed via user preference")
                news_report = ""

            if not features.email:
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

            if not features.calendar:
                print("[SYSTEM]: Calendar module bypassed via user preference")
                calendar_report = ""
                calendar_data: list[dict[str, Any]] = []
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
                    calendar_data = []

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

            f1_cache_penalty = (
                features.sports and modules.f1 and not f1_cache_refreshed
            )
            confidence_score, failed_connectors = _compute_confidence_and_failures(
                weather_report=weather_report,
                sports_report=sports_report,
                news_report=news_report,
                email_report=email_report,
                calendar_report=calendar_report,
                f1_cache_penalty=f1_cache_penalty,
                features=features,
                modules=modules,
            )

            next_event: CalendarFact | None = None
            if calendar_data:
                raw_event = calendar_data[0]
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
            synthesis_input = SynthesisInput(
                weather_summary=weather_report or None,
                calendar_event_count=len(calendar_data),
                next_calendar_event=next_event,
                pending_reminder_count=len(unread_records),
                first_pending_reminder=(str(unread_records[0][1]) if unread_records else None),
                f1_this_week=f1_fact,
                failed_connectors=failed_connectors,
                generated_at=datetime.now(timezone.utc).isoformat(),
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

            brain_output = brain.process_telemetry(
                combined_raw_data,
                synthesis_input=synthesis_input,
                strategy=synthesis_strategy,
                warmup=warmup,
                router=synthesis_router,
            )
            final_briefing = brain_output["briefing"]
            briefing_insights = brain_output["insights"]

            filler_thread.join()

            delivery_voice = get_settings_store().get_snapshot().voice
            if dev_mode:
                tts_strategy = DEV_TTS_PLAYBACK
            else:
                synthesis_strategy = "cloud"
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
            digest_payload = DigestPayload(
                confidence_score=confidence_score,
                failed_connectors=failed_connectors,
                insights=briefing_insights,
            )
            runtime_metadata = RuntimeMetadata(
                dev_mode_active=dev_mode,
                demo_mode_active=False,
                synthesis_strategy=synthesis_strategy,
                synthesis_provider=brain_output.get("provider"),
                synthesis_profile=brain_output.get("profile"),
                synthesis_fallback_reason=brain_output.get("fallback_reason"),
                synthesis_warmup_ms=brain_output.get("warmup_ms"),
                synthesis_generation_ms=brain_output.get("generation_ms"),
                tts_strategy=tts_strategy,
                active_tts_engine=active_tts_engine,
                system_load_throttled=system_load_throttled,
            )
            if not dev_mode:
                try:
                    print("[SYSTEM] Logging briefing run to persistent SQLite ledger.")
                    database.save_briefing(
                        final_briefing,
                        digest_payload.model_dump(),
                        runtime_metadata.model_dump(),
                    )
                    database.prune_historical_ledger()
                except Exception as exc:
                    print(f"[SYSTEM]: Briefing ledger persistence failed: ({exc})")

            voice_thread = threading.Thread(
                target=_speak_and_cleanup,
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
                metadata=runtime_metadata,
            )
        finally:
            if not voice_thread_started:
                global_pipeline_state.reset()
    finally:
        if not voice_thread_started:
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()
