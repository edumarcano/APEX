"""Typed connector collection and briefing pipeline orchestration."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status

from core import brain, database, speaker
from core.agent.sandbox_context import publish_masked_briefing
from core.api.demo import build_demo_briefing, load_mock_telemetry
from core.api.models import (
    BriefingResponse,
    BriefingTargetStatus,
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
    BriefingFacts,
    BriefingMode,
    CalendarFact,
    ConnectorHealthFact,
    F1Fact,
    FootballFact,
    NewsFact,
    ReminderFact,
    EmailFact,
    SportEventFact,
    WeatherDayFact,
    WeatherHourFact,
    SynthesisInput,
    SynthesisRouter,
    strategy_to_briefing_mode,
)
from core.telemetry.models import TelemetrySnapshot
from core.telemetry.service import RefreshInProgressError, get_telemetry_service

_DEMO_STAGE_DELAY_SECONDS = 1.5
_LOGGER = logging.getLogger(__name__)
_WINDOWS_TIME_ZONES = {"Eastern Standard Time": "America/New_York", "UTC": "UTC"}


def _reminder_due_timestamp(
    value: object, fallback_zone: ZoneInfo
) -> tuple[str | None, str | None]:
    """Normalize Microsoft To Do's local due value without losing its timezone."""
    if not isinstance(value, dict) or not isinstance(value.get("date_time"), str):
        return None, None
    time_zone = value.get("time_zone") if isinstance(value.get("time_zone"), str) else None
    zone_name = _WINDOWS_TIME_ZONES.get(time_zone or "", time_zone)
    try:
        due_at = datetime.fromisoformat(value["date_time"].replace("Z", "+00:00"))
    except ValueError:
        return None, time_zone
    if due_at.tzinfo is None:
        try:
            due_at = due_at.replace(tzinfo=ZoneInfo(zone_name)) if zone_name else due_at.replace(tzinfo=fallback_zone)
        except Exception:
            due_at = due_at.replace(tzinfo=fallback_zone)
    return due_at.isoformat(), time_zone


def _mode_to_strategy(mode: BriefingMode) -> str:
    if mode == "focused":
        return "cloud"
    if mode == "structured":
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
    snapshot: TelemetrySnapshot | None = None,
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
    timezone_name = (
        str(weather_data.get("timezone"))
        if isinstance(weather_data, dict) and isinstance(weather_data.get("timezone"), str)
        else "America/New_York"
    )
    try:
        local_zone = ZoneInfo(timezone_name)
    except Exception:
        timezone_name = "America/New_York"
        local_zone = ZoneInfo(timezone_name)

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
    now = datetime.now(timezone.utc)
    if isinstance(f1_map, dict) and isinstance(f1_map.get("raceStart"), str):
        try:
            race_start = datetime.fromisoformat(f1_map["raceStart"].replace("Z", "+00:00"))
            race_start = race_start.replace(tzinfo=timezone.utc) if race_start.tzinfo is None else race_start.astimezone(timezone.utc)
        except ValueError:
            race_start = None
        if race_start is not None and now <= race_start < now + timedelta(days=14):
            f1_fact = F1Fact(
                race_name=str(f1_map.get("raceName", "Unknown race")),
                start=race_start.isoformat(),
                sprint_scheduled=bool(f1_map.get("sprintScheduled")),
            )
    elif isinstance(f1_map, dict) and f1_map.get("relativeWeek") == "This week":
        # Older cache entries lack raceStart; retain their legacy display fact
        # until the next connector refresh replaces it with an ISO timestamp.
        f1_fact = F1Fact(
            race_name=str(f1_map.get("raceName", "Unknown race")),
            start=str(f1_map.get("raceDateTimeEST", "Unscheduled")),
            sprint_scheduled=bool(f1_map.get("sprintScheduled")),
        )

    football_fact: FootballFact | None = None
    fixtures = football_data.get("fixtures") if isinstance(football_data, dict) else None
    if football and football.status != "unavailable" and isinstance(fixtures, list):
        eligible: list[tuple[datetime, int, dict[str, object]]] = []
        for index, raw_fixture in enumerate(fixtures):
            if not isinstance(raw_fixture, dict):
                continue
            raw_kickoff = raw_fixture.get("kickoff_at")
            if not isinstance(raw_kickoff, str):
                continue
            try:
                kickoff = datetime.fromisoformat(raw_kickoff.replace("Z", "+00:00"))
            except ValueError:
                continue
            kickoff = kickoff.replace(tzinfo=timezone.utc) if kickoff.tzinfo is None else kickoff.astimezone(timezone.utc)
            if now <= kickoff <= now + timedelta(days=7):
                eligible.append((kickoff, index, raw_fixture))
        if eligible:
            kickoff, _index, fixture = min(eligible, key=lambda item: (item[0], item[1]))
            home_or_away = fixture.get("home_or_away")
            if home_or_away in {"home", "away"}:
                team = fixture.get("team")
                opponent = fixture.get("opponent")
                competition = fixture.get("competition")
                if all(isinstance(value, str) and value.strip() for value in (team, opponent, competition)):
                    football_fact = FootballFact(team=team, opponent=opponent, home_or_away=home_or_away, competition=competition, kickoff=kickoff.isoformat())

    news_headlines: list[NewsFact] = []
    if news and isinstance(news.data.get("headlines"), list):
        for item in news.data["headlines"][:5]:
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic", "")).strip()
            headline = str(item.get("headline", "")).strip()
            if topic and headline:
                news_headlines.append(NewsFact(
                    topic=topic,
                    headline=headline,
                    source=str(item["source"]) if isinstance(item.get("source"), str) else None,
                    published_at=str(item["published_at"]) if isinstance(item.get("published_at"), str) else None,
                    synopsis=str(item["synopsis"]) if isinstance(item.get("synopsis"), str) else None,
                ))

    email_subjects: list[str] = []
    emails = email_data.get("emails") if isinstance(email_data, dict) else None
    if isinstance(emails, list):
        for item in emails[:8]:
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
            freshness=result.freshness,
            observed_at=result.observed_at,
        )
        for result in results.values()
        if result is not None and result.status != "disabled"
    ]

    weather_summary = None
    if weather and weather.status != "unavailable":
        weather_summary = weather.display_text or None
        if weather_data.get("temp_f") is not None and weather_data.get("condition"):
            temp = weather_data["temp_f"]
            cond = weather_data["condition"]
            apparent = weather_data.get("apparent_temp_f")
            t_max = weather_data.get("temp_max_f")
            t_min = weather_data.get("temp_min_f")
            prob = weather_data.get("precip_probability_max")

            parts = [f"Current temperature is {temp} degrees"]
            if apparent is not None and apparent != temp:
                parts.append(f"(feels like {apparent})")
            parts.append(f"with {cond}.")
            if t_max is not None and t_min is not None:
                parts.append(f"High {t_max}, low {t_min}.")
            if isinstance(prob, (int, float)) and prob >= 30:
                parts.append(f"{int(prob)}% chance of rain.")
            weather_summary = " ".join(parts)

    calendar_facts: list[CalendarFact] = []
    if isinstance(events, list):
        for raw_event in events[:100]:
            if isinstance(raw_event, dict):
                calendar_facts.append(
                    CalendarFact(
                        title=str(raw_event.get("summary") or "Untitled event"),
                        start=str(raw_event.get("start") or "Time unavailable"),
                        end=str(raw_event["end"]) if isinstance(raw_event.get("end"), str) else None,
                        all_day=bool(raw_event.get("all_day")),
                        location=str(raw_event["location"]) if isinstance(raw_event.get("location"), str) else None,
                        time_zone=str(raw_event["time_zone"]) if isinstance(raw_event.get("time_zone"), str) else None,
                    )
                )

    reminder_facts: list[ReminderFact] = []
    reminder_records = reminder_data.get("records") if isinstance(reminder_data, dict) else None
    if isinstance(reminder_records, list):
        for raw_reminder in reminder_records[:50]:
            if not isinstance(raw_reminder, dict):
                continue
            note = raw_reminder.get("note")
            if not isinstance(note, str) or not note.strip():
                continue
            due, due_time_zone = _reminder_due_timestamp(
                raw_reminder.get("due"), local_zone
            )
            reminder_facts.append(
                ReminderFact(
                    note=note,
                    due=due,
                    due_time_zone=due_time_zone,
                    importance=str(raw_reminder["importance"]) if isinstance(raw_reminder.get("importance"), str) else None,
                    source=str(raw_reminder["source"]) if isinstance(raw_reminder.get("source"), str) else None,
                    sync_state=str(raw_reminder["sync_state"]) if isinstance(raw_reminder.get("sync_state"), str) else None,
                )
            )

    email_facts: list[EmailFact] = []
    if isinstance(emails, list):
        for raw_email in emails[:8]:
            if isinstance(raw_email, dict):
                subject = str(raw_email.get("subject") or "").strip()
                if subject:
                    email_facts.append(
                        EmailFact(
                            sender=str(raw_email["sender"]) if isinstance(raw_email.get("sender"), str) else None,
                            subject=subject,
                            received_at=str(raw_email["received_at"]) if isinstance(raw_email.get("received_at"), str) else str(raw_email["time"]) if isinstance(raw_email.get("time"), str) else None,
                            snippet=str(raw_email["snippet"]) if isinstance(raw_email.get("snippet"), str) else None,
                        )
                    )

    sports_events: list[SportEventFact] = []
    if f1_fact is not None:
        sports_events.append(SportEventFact(kind="f1", title=f1_fact.race_name, start=f1_fact.start, detail="Sprint scheduled" if f1_fact.sprint_scheduled else None))
    if isinstance(fixtures, list):
        for fixture in fixtures:
            if isinstance(fixture, dict) and isinstance(fixture.get("kickoff_at"), str):
                team, opponent = fixture.get("team"), fixture.get("opponent")
                if isinstance(team, str) and isinstance(opponent, str):
                    sports_events.append(SportEventFact(kind="football", title=f"{team} vs {opponent}", start=fixture["kickoff_at"], detail=str(fixture.get("competition") or "") or None))

    weather_daily: list[WeatherDayFact] = []
    for raw_day in weather_data.get("daily", []) if isinstance(weather_data, dict) and isinstance(weather_data.get("daily"), list) else []:
        if isinstance(raw_day, dict) and isinstance(raw_day.get("date"), str):
            weather_daily.append(WeatherDayFact(**raw_day))
    weather_hourly: list[WeatherHourFact] = []
    for raw_hour in weather_data.get("hourly", []) if isinstance(weather_data, dict) and isinstance(weather_data.get("hourly"), list) else []:
        if isinstance(raw_hour, dict) and isinstance(raw_hour.get("time"), str):
            weather_hourly.append(WeatherHourFact(**raw_hour))

    now_local = datetime.now(local_zone)
    overdue_count = 0
    due_today_count = 0
    for reminder in reminder_facts:
        if not reminder.due:
            continue
        try:
            due_at = datetime.fromisoformat(reminder.due.replace("Z", "+00:00")).astimezone(now_local.tzinfo)
        except ValueError:
            continue
        if due_at.date() < now_local.date():
            overdue_count += 1
        elif due_at.date() == now_local.date():
            due_today_count += 1

    importance_order = {"high": 0, "normal": 1, "low": 2}

    def reminder_sort_key(reminder: ReminderFact) -> tuple[int, int, datetime, str]:
        due_at: datetime | None = None
        if reminder.due:
            try:
                due_at = datetime.fromisoformat(reminder.due.replace("Z", "+00:00")).astimezone(local_zone)
            except ValueError:
                pass
        urgency = 3
        if due_at is not None:
            urgency = 0 if due_at.date() < now_local.date() else 1 if due_at.date() == now_local.date() else 2
        return (urgency, importance_order.get(reminder.importance or "normal", 1), due_at or datetime.max.replace(tzinfo=local_zone), reminder.note.casefold())

    reminder_facts.sort(key=reminder_sort_key)

    return BriefingFacts(
        weather_summary=weather_summary,
        weather_temp_f=(
            int(weather_data["temp_f"])
            if isinstance(weather_data, dict) and isinstance(weather_data.get("temp_f"), (int, float))
            else None
        ),
        weather_apparent_temp_f=(
            int(weather_data["apparent_temp_f"])
            if isinstance(weather_data, dict) and isinstance(weather_data.get("apparent_temp_f"), (int, float))
            else None
        ),
        weather_temp_max_f=(
            int(weather_data["temp_max_f"])
            if isinstance(weather_data, dict) and isinstance(weather_data.get("temp_max_f"), (int, float))
            else None
        ),
        weather_temp_min_f=(
            int(weather_data["temp_min_f"])
            if isinstance(weather_data, dict) and isinstance(weather_data.get("temp_min_f"), (int, float))
            else None
        ),
        weather_precip_probability=(
            int(weather_data["precip_probability_max"])
            if isinstance(weather_data, dict) and isinstance(weather_data.get("precip_probability_max"), (int, float))
            else None
        ),
        weather_condition=(
            str(weather_data.get("condition"))
            if isinstance(weather_data, dict) and weather_data.get("condition")
            else None
        ),
        email_unread_count=int(email_data.get("count", 0) or 0) if isinstance(email_data, dict) else 0,
        email_recent_subjects=email_subjects,
        emails=email_facts,
        news_headlines=news_headlines,
        calendar_event_count=int(
            calendar_data.get("total_count", calendar_data.get("count", 0)) or 0
        )
        if isinstance(calendar_data, dict)
        else 0,
        next_calendar_event=next_event,
        calendar_events=calendar_facts,
        calendar_truncated=bool(calendar_data.get("truncated", False)) if isinstance(calendar_data, dict) else False,
        pending_reminder_count=pending_count,
        first_pending_reminder=first_reminder,
        reminders=reminder_facts,
        overdue_reminder_count=overdue_count,
        due_today_reminder_count=due_today_count,
        reminders_truncated=bool(isinstance(reminder_records, list) and len(reminder_records) > 50),
        f1_upcoming=f1_fact,
        football_next_fixture=football_fact,
        sports_events=sports_events,
        sports_truncated=False,
        connector_health=connector_health,
        failed_connectors=failed_connectors,
        generated_at=datetime.now(timezone.utc).isoformat(),
        local_time=now_local.isoformat(),
        timezone=timezone_name,
        snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
        snapshot_collected_at=snapshot.collected_at if snapshot is not None else None,
    )


def _mask_dev_personal_results(
    results: dict[str, ConnectorResult | None],
) -> dict[str, ConnectorResult | None]:
    """Remove personal text before any DEV_MODE synthesis provider sees it."""
    masked = dict(results)
    email = results.get("email")
    if email is not None:
        count = int(email.data.get("count", 0) or 0)
        masked["email"] = email.model_copy(
            update={
                "display_text": f"Email Telemetry: {count} unread emails (details masked).",
                "data": {"count": count, "emails": []},
            }
        )
    calendar = results.get("calendar")
    if calendar is not None:
        count = int(
            calendar.data.get("total_count", calendar.data.get("count", 0)) or 0
        )
        masked["calendar"] = calendar.model_copy(
            update={
                "display_text": f"Calendar Telemetry: {count} upcoming events (details masked).",
                "data": {
                    "window_days": calendar.data.get("window_days", 7),
                    "events": [],
                    "total_count": count,
                },
            }
        )
    reminders = results.get("reminders")
    if reminders is not None:
        count = int(reminders.data.get("count", 0) or 0)
        masked["reminders"] = reminders.model_copy(
            update={
                "display_text": f"Pending Reminders: {count} (details masked).",
                "data": {"count": count, "notes": [], "records": []},
            }
        )
    return masked


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
        upcoming_events_count=int(
            (
                calendar.data.get(
                    "total_count",
                    calendar.data.get("count", 0),
                )
                if calendar
                else 0
            )
            or 0
        ),
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
        if dev_mode:
            results = _mask_dev_personal_results(results)
        health = compute_sync_health(results)
        synthesis_input = _build_synthesis_input(
            results=results,
            failed_connectors=health.failed_connectors,
            snapshot=snapshot,
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
            synthesis_agent=brain_output.get("agent"),
            synthesis_resolved_model=brain_output.get("resolved_model"),
            synthesis_fallback_reason=brain_output.get("fallback_reason"),
            synthesis_fallback_steps=brain_output.get("fallback_steps", []),
            synthesis_warmup_ms=brain_output.get("warmup_ms"),
            synthesis_generation_ms=brain_output.get("generation_ms"),
            synthesis_provider_ms=brain_output.get("provider_ms"),
            synthesis_usage=brain_output.get("usage"),
            synthesis_cost_estimate=brain_output.get("cost_estimate"),
            tts_strategy=tts_strategy,
            active_tts_engine=active_tts_engine,
            system_load_throttled=system_load_throttled,
            snapshot_id=snapshot.snapshot_id,
            spoken=spoken,
        )
        if dev_mode:
            publish_masked_briefing(
                snapshot_id=snapshot.snapshot_id,
                briefing=final_briefing,
                insights=briefing_insights,
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


def trigger_briefing(*, mode: BriefingMode | None = None) -> BriefingResponse:
    """
    Run a full APEX briefing pipeline.

    Force-refreshes telemetry, then synthesizes with an optional requested mode
    or the configured default. When ``DEMO_MODE`` is active, serves static mock
    telemetry through a staged simulation loop.

    Startup Wi-Fi/power/cooldown gating is no longer a hard blocker; callers
    should use ``POST /api/v1/preflight`` for advisory warnings.
    """
    _acquire_pipeline_lock()

    run_id = str(uuid.uuid4())
    with run_id_scope(run_id):
        try:
            if DEMO_MODE:
                return _run_demo_briefing(run_id=run_id, mode=mode)

            global_pipeline_state.begin_run(run_id)
            global_pipeline_state.update(1, "GATE")

            get_settings_store().get_snapshot()
            dev_mode = is_dev_mode()
            resolved_mode = mode or _resolve_default_mode(dev_mode=dev_mode)

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
                mode=resolved_mode,
                run_id=run_id,
                speak_fillers=True,
            )
        except Exception:
            if _TRIGGER_LOCK.locked():
                _TRIGGER_LOCK.release()
            global_pipeline_state.reset()
            raise


def build_briefing_target_statuses() -> list[BriefingTargetStatus]:
    """Return status and pricing for fixed Flash, Focused, and Structured modes."""
    import os
    from core.agent.model_catalog import (
        DEFAULT_FELIS_MODEL,
        PANTHERA_BRIEFING_MODEL,
        get_model_profile,
    )
    from core.agent.catalog import local_model_refs_for_model
    import core.agent.local_runtime.coordinator as coordinator
    from core.agent.local_runtime.registry import get_local_runtime_backend
    from core.agent.providers.llama_cpp_models import LLAMA_CPP_RUNTIME_CONFIGS
    from core.api.cortex import _PROFILE_STATUS_REASONS, _model_pricing_metadata

    panthera_profile = get_model_profile(PANTHERA_BRIEFING_MODEL)
    openrouter_configured = bool(os.getenv("OPENROUTER_API_KEY"))
    panthera_status = "configured" if openrouter_configured else "disabled"
    panthera_reason = (
        None
        if openrouter_configured
        else "OpenRouter API key is not configured (OPENROUTER_API_KEY)"
    )
    panthera_pricing = (
        _model_pricing_metadata(panthera_profile) if panthera_profile else None
    )

    felis_profile = get_model_profile(DEFAULT_FELIS_MODEL)
    llama_backend = get_local_runtime_backend("llama_cpp")
    felis_status = "available"
    felis_reason = None
    if not llama_backend.enabled:
        felis_status = "disabled"
        felis_reason = "llama.cpp runtime is disabled in settings"
    else:
        snapshot = llama_backend.get_status_snapshot()
        if not snapshot.get("reachable"):
            felis_status = "provider_unreachable"
            felis_reason = "llama.cpp is unreachable"
        elif felis_profile:
            installed_models = set(snapshot.get("installed_models", []))
            known_aliases = {
                ref.model for ref in local_model_refs_for_model(felis_profile.model_id)
            } | {felis_profile.model_id}
            if not (installed_models & known_aliases):
                felis_status = "model_not_installed"
                felis_reason = f"Model {felis_profile.model_id} is not installed"
            else:
                loaded_models = snapshot.get("loaded_models", [])
                is_resident = any(
                    (m.get("name") in known_aliases or m.get("model") in known_aliases)
                    and m.get("state") == "loaded"
                    for m in loaded_models
                )
                if not is_resident:
                    runtime_config = LLAMA_CPP_RUNTIME_CONFIGS.get(felis_profile.model_id)
                    ram_limit = runtime_config.ram_limit if runtime_config else 0.85
                    cpu_limit = runtime_config.cpu_limit if runtime_config else 0.90
                    gate_open, gate_reason = coordinator.check_resource_gate(
                        ram_limit, cpu_limit, vitals=coordinator.get_system_vitals()
                    )
                    if not gate_open and gate_reason is not None:
                        felis_status = gate_reason
                        felis_reason = _PROFILE_STATUS_REASONS.get(
                            gate_reason, f"Current {gate_reason} exceeds threshold"
                        )

    felis_pricing = (
        _model_pricing_metadata(felis_profile) if felis_profile else None
    )

    return [
        BriefingTargetStatus(
            mode="flash",
            label="Flash",
            description="Felis · local model",
            model_id=felis_profile.model_id if felis_profile else DEFAULT_FELIS_MODEL,
            model_display_name=felis_profile.display_name if felis_profile else "Gemma 4 E2B",
            provider="llama_cpp",
            runtime="local",
            status=felis_status,
            reason=felis_reason,
            pricing=felis_pricing,
        ),
        BriefingTargetStatus(
            mode="focused",
            label="Focused",
            description=f"Panthera · {panthera_profile.display_name if panthera_profile else 'DeepSeek V4 Flash 0731'}",
            model_id=panthera_profile.model_id if panthera_profile else PANTHERA_BRIEFING_MODEL,
            model_display_name=panthera_profile.display_name if panthera_profile else "DeepSeek V4 Flash 0731",
            provider="openrouter",
            runtime="cloud",
            status=panthera_status,
            reason=panthera_reason,
            pricing=panthera_pricing,
        ),
        BriefingTargetStatus(
            mode="structured",
            label="Structured",
            description="Deterministic · no model",
            model_id=None,
            model_display_name=None,
            provider=None,
            runtime="none",
            status="available",
            reason=None,
            pricing=None,
        ),
    ]
