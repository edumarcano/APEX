"""Load, validate, and normalize the DEMO_MODE telemetry fixture."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from core.api.models import DigestPayload, TelemetryPayload
from core.connectors.models import CONNECTOR_NAMES, ConnectorHealthEntry, utc_now_iso
from core.connectors.scoring import compute_sync_health
from core.telemetry.models import TelemetryModuleEntry

_FIXTURE_PATH = Path(__file__).resolve().parent / "telemetry.json"
_OFFSET_PATTERN = re.compile(
    r"^(?P<base>now|next[_-]sunday)(?P<offset>.*)?$",
    re.IGNORECASE,
)
_OFFSET_PART_PATTERN = re.compile(r"([+-]?)(\d+)([smhd])", re.IGNORECASE)
_VALID_STATUSES = frozenset({"healthy", "degraded", "unavailable", "disabled"})
_VALID_FRESHNESS = frozenset({"live", "fresh_cache", "stale", "none"})
try:
    _EASTERN_TZ = ZoneInfo("America/New_York")
except Exception:
    _EASTERN_TZ = timezone.utc


class DemoFixtureError(ValueError):
    """Raised when the demo fixture fails validation."""


@dataclass(frozen=True)
class DemoBundle:
    """Normalized DEMO_MODE telemetry derived from a single fixture."""

    telemetry: TelemetryPayload
    digest: DigestPayload
    modules: dict[str, TelemetryModuleEntry]
    collected_at: str


def _resolve_now(now: datetime | None) -> datetime:
    resolved = now or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def resolve_relative_time(token: str, *, now: datetime) -> datetime:
    """Resolve relative demo time tokens against an injectable clock.

    Supported bases are ``now`` and the strictly future ``next_sunday``.
    Either base may be followed by compound offsets such as ``+1d2h``.
    Supported units are seconds, minutes, hours, and days.
    """
    normalized = token.strip()
    if not normalized:
        raise DemoFixtureError("Relative time token must not be empty.")
    if normalized.lower() == "now":
        return now

    match = _OFFSET_PATTERN.match(normalized)
    if not match:
        raise DemoFixtureError(f"Unsupported relative time token: {token!r}")

    base = match.group("base").lower()
    if base == "next_sunday":
        resolved = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_until_sunday = (6 - now.weekday()) % 7 or 7
        resolved += timedelta(days=days_until_sunday)
    else:
        resolved = now

    offset_blob = match.group("offset")
    if not offset_blob:
        return resolved

    offset_parts = list(_OFFSET_PART_PATTERN.finditer(offset_blob))
    if not offset_parts or "".join(part.group(0) for part in offset_parts) != offset_blob:
        raise DemoFixtureError(f"Unsupported relative time token: {token!r}")

    current_sign = "+"
    for part in offset_parts:
        sign, amount_text, unit = part.groups()
        if sign:
            current_sign = sign
        amount = int(amount_text)
        unit_key = unit.lower()
        delta = {
            "s": timedelta(seconds=amount),
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit_key]
        resolved = resolved + (delta if current_sign == "+" else -delta)
    return resolved


def _require_dict(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DemoFixtureError(f"{path} must be a JSON object.")
    return value


def _require_str(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DemoFixtureError(f"{path} must be a non-empty string.")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _format_est_edt(dt_utc: datetime) -> str:
    dt_est = dt_utc.astimezone(_EASTERN_TZ)
    time_label = dt_est.strftime("%I:%M %p").lstrip("0")
    return f"{dt_est.strftime('%A, %B')} {dt_est.day} at {time_label} {dt_est.strftime('%Z')}"


def _relative_week_label(dt_utc: datetime, *, now: datetime) -> str:
    now_local = now.astimezone(_EASTERN_TZ)
    race_local = dt_utc.astimezone(_EASTERN_TZ)
    current_week_start = now_local.date() - timedelta(days=now_local.weekday())
    race_week_start = race_local.date() - timedelta(days=race_local.weekday())
    week_offset = max(0, (race_week_start - current_week_start).days // 7)
    if week_offset == 0:
        return "This week"
    if week_offset == 1:
        return "Next week"
    return f"In {week_offset} weeks"


def _load_raw_fixture() -> dict[str, Any]:
    try:
        with open(_FIXTURE_PATH, encoding="utf-8") as fixture_file:
            payload = json.load(fixture_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise DemoFixtureError("Demo telemetry payload unavailable.") from exc
    return _require_dict(payload, path="fixture root")


def _module_observed_at(module: dict[str, Any], *, now: datetime) -> str:
    if isinstance(module.get("observed_at"), str):
        return module["observed_at"]
    offset = module.get("observed_at_offset")
    if isinstance(offset, str):
        return resolve_relative_time(offset, now=now).isoformat()
    return now.isoformat()


def _build_weather_module(module: dict[str, Any], *, now: datetime) -> tuple[TelemetryModuleEntry, dict[str, Any]]:
    data = _require_dict(module.get("data"), path="weather.data")
    temp_f = data.get("temp_f")
    condition = _optional_str(data.get("condition")) or "clear sky"
    archetype = _optional_str(data.get("archetype")) or "clear_day"
    location = _optional_str(data.get("location"))
    if not isinstance(temp_f, (int, float)):
        raise DemoFixtureError("weather.data.temp_f must be numeric.")

    resolved_data = {
        "temp_f": int(round(float(temp_f))),
        "condition": condition,
        "archetype": archetype,
    }
    if location:
        resolved_data["location"] = location

    display = (
        f"Current temperature is {resolved_data['temp_f']} degrees with {condition}."
    )
    return (
        TelemetryModuleEntry(
            name="weather",
            status=module["status"],
            freshness=module["freshness"],
            reason_code=module["reason_code"],
            observed_at=_module_observed_at(module, now=now),
            display_text=display,
            data=resolved_data,
        ),
        resolved_data,
    )


def _build_news_module(module: dict[str, Any], *, now: datetime) -> tuple[TelemetryModuleEntry, dict[str, Any]]:
    data = _require_dict(module.get("data"), path="news.data")
    headlines_raw = data.get("headlines")
    if not isinstance(headlines_raw, list) or not headlines_raw:
        raise DemoFixtureError("news.data.headlines must be a non-empty list.")

    headlines: list[dict[str, str]] = []
    formatted: list[str] = []
    for index, item in enumerate(headlines_raw):
        row = _require_dict(item, path=f"news.data.headlines[{index}]")
        topic = _require_str(row.get("topic"), path=f"news.data.headlines[{index}].topic")
        headline = _require_str(
            row.get("headline"),
            path=f"news.data.headlines[{index}].headline",
        )
        headlines.append({"topic": topic, "headline": headline})
        formatted.append(f"[{topic}] {headline}")

    resolved_data = {"headlines": headlines, "topic_count": len(headlines)}
    display = "[NEWS TELEMETRY]\n" + " | ".join(formatted)
    return (
        TelemetryModuleEntry(
            name="news",
            status=module["status"],
            freshness=module["freshness"],
            reason_code=module["reason_code"],
            observed_at=_module_observed_at(module, now=now),
            display_text=display,
            data=resolved_data,
        ),
        resolved_data,
    )


def _build_email_module(module: dict[str, Any], *, now: datetime) -> tuple[TelemetryModuleEntry, dict[str, Any]]:
    data = _require_dict(module.get("data"), path="email.data")
    count = data.get("count")
    if not isinstance(count, int) or count < 0:
        raise DemoFixtureError("email.data.count must be a non-negative integer.")

    emails_raw = data.get("emails")
    if emails_raw is None:
        emails_raw = []
    if not isinstance(emails_raw, list):
        raise DemoFixtureError("email.data.emails must be a list.")

    emails: list[dict[str, str]] = []
    for index, item in enumerate(emails_raw):
        row = _require_dict(item, path=f"email.data.emails[{index}]")
        subject = _require_str(row.get("subject"), path=f"email.data.emails[{index}].subject")
        received = row.get("received_at")
        if isinstance(received, str) and received.strip():
            received_at = received.strip()
        elif isinstance(row.get("received_offset"), str):
            received_at = resolve_relative_time(row["received_offset"], now=now).strftime(
                "%I:%M %p"
            ).lstrip("0")
        else:
            received_at = "Earlier"
        emails.append({"subject": subject, "time": received_at})

    if emails:
        recent = ", ".join(f"'{item['subject']}' at {item['time']}" for item in emails[:3])
    else:
        recent = "Email Telemetry (24h): No unread emails"
    display = f"Email Telemetry: {count} unread primary emails. Most recent: {recent}"
    resolved_data = {"count": count, "emails": emails}
    return (
        TelemetryModuleEntry(
            name="email",
            status=module["status"],
            freshness=module["freshness"],
            reason_code=module["reason_code"],
            observed_at=_module_observed_at(module, now=now),
            display_text=display,
            data=resolved_data,
        ),
        resolved_data,
    )


def _build_calendar_module(module: dict[str, Any], *, now: datetime) -> tuple[TelemetryModuleEntry, dict[str, Any]]:
    data = _require_dict(module.get("data"), path="calendar.data")
    window_days = data.get("window_days", 7)
    if not isinstance(window_days, int) or window_days < 1:
        raise DemoFixtureError("calendar.data.window_days must be a positive integer.")

    events_raw = data.get("events")
    if events_raw is None:
        events_raw = []
    if not isinstance(events_raw, list):
        raise DemoFixtureError("calendar.data.events must be a list.")

    events: list[dict[str, Any]] = []
    for index, item in enumerate(events_raw):
        row = _require_dict(item, path=f"calendar.data.events[{index}]")
        summary = _require_str(row.get("summary"), path=f"calendar.data.events[{index}].summary")
        all_day = row.get("all_day") is True
        start_token = row.get("start")
        if isinstance(start_token, str) and start_token.strip():
            start_value = start_token.strip()
        elif isinstance(row.get("start_offset"), str):
            start_dt = resolve_relative_time(row["start_offset"], now=now)
            start_value = (
                start_dt.date().isoformat()
                if all_day
                else start_dt.isoformat()
            )
        else:
            raise DemoFixtureError(
                f"calendar.data.events[{index}] requires start or start_offset."
            )

        end_value: str | None = None
        end_token = row.get("end")
        if isinstance(end_token, str) and end_token.strip():
            end_value = end_token.strip()
        elif isinstance(row.get("end_offset"), str):
            end_dt = resolve_relative_time(row["end_offset"], now=now)
            end_value = end_dt.date().isoformat() if all_day else end_dt.isoformat()

        events.append(
            {
                "summary": summary,
                "start": start_value,
                "end": end_value,
                "all_day": all_day,
                "time_zone": _optional_str(row.get("time_zone")) or "UTC",
            }
        )

    events.sort(key=lambda event: event["start"])
    resolved_data = {
        "window_days": window_days,
        "events": events,
        "total_count": len(events),
    }
    if events:
        display_entries = [f"'{event['summary']}' at {event['start']}" for event in events]
        display = "Calendar Telemetry (7d): " + " | ".join(display_entries)
    else:
        display = "Calendar Telemetry (7d): No upcoming events"
    return (
        TelemetryModuleEntry(
            name="calendar",
            status=module["status"],
            freshness=module["freshness"],
            reason_code=module["reason_code"],
            observed_at=_module_observed_at(module, now=now),
            display_text=display,
            data=resolved_data,
        ),
        resolved_data,
    )


def _build_reminders_module(module: dict[str, Any], *, now: datetime) -> tuple[TelemetryModuleEntry, dict[str, Any]]:
    data = _require_dict(module.get("data"), path="reminders.data")
    notes_raw = data.get("notes")
    if notes_raw is None:
        notes_raw = []
    if not isinstance(notes_raw, list):
        raise DemoFixtureError("reminders.data.notes must be a list.")
    notes = [str(note).strip() for note in notes_raw if str(note).strip()]
    display = (
        f"Pending Reminders: {', '.join(notes)}"
        if notes
        else "No pending reminders."
    )
    resolved_data = {
        "count": len(notes),
        "notes": notes,
        "records": [{"id": index + 1, "note": note} for index, note in enumerate(notes)],
    }
    return (
        TelemetryModuleEntry(
            name="reminders",
            status=module["status"],
            freshness=module["freshness"],
            reason_code=module["reason_code"],
            observed_at=_module_observed_at(module, now=now),
            display_text=display,
            data=resolved_data,
        ),
        resolved_data,
    )


def _build_f1_module(module: dict[str, Any], *, now: datetime) -> tuple[TelemetryModuleEntry, dict[str, Any]]:
    data = _require_dict(module.get("data"), path="f1.data")
    f1_map_raw = _require_dict(data.get("f1_map"), path="f1.data.f1_map")
    race_name = _require_str(f1_map_raw.get("raceName"), path="f1.data.f1_map.raceName")
    round_value = _optional_str(f1_map_raw.get("round")) or "TBD"
    country = _optional_str(f1_map_raw.get("country")) or "Unknown"
    sprint_scheduled = f1_map_raw.get("sprintScheduled") is True

    if isinstance(f1_map_raw.get("race_start"), str):
        race_dt = datetime.fromisoformat(f1_map_raw["race_start"].replace("Z", "+00:00"))
        if race_dt.tzinfo is None:
            race_dt = race_dt.replace(tzinfo=timezone.utc)
    elif isinstance(f1_map_raw.get("race_start_offset"), str):
        race_dt = resolve_relative_time(f1_map_raw["race_start_offset"], now=now)
    else:
        raise DemoFixtureError("f1.data.f1_map requires race_start or race_start_offset.")

    sprint_dt: datetime | None = None
    if sprint_scheduled:
        if isinstance(f1_map_raw.get("sprint_start"), str):
            sprint_dt = datetime.fromisoformat(
                f1_map_raw["sprint_start"].replace("Z", "+00:00")
            )
            if sprint_dt.tzinfo is None:
                sprint_dt = sprint_dt.replace(tzinfo=timezone.utc)
        elif isinstance(f1_map_raw.get("sprint_start_offset"), str):
            sprint_dt = resolve_relative_time(f1_map_raw["sprint_start_offset"], now=now)

    f1_map = {
        "raceName": race_name,
        "round": round_value,
        "country": country,
        "raceDateTimeEST": _format_est_edt(race_dt),
        "relativeWeek": _relative_week_label(race_dt, now=now),
        "sprintScheduled": sprint_scheduled,
        "sprintDateTimeEST": (
            _format_est_edt(sprint_dt) if sprint_dt is not None else "Unscheduled"
        ),
    }
    resolved_data = {"f1_map": f1_map, "cache_refreshed": data.get("cache_refreshed", True)}
    display = f"F1_DATA:{json.dumps(f1_map, separators=(',', ':'))}"
    return (
        TelemetryModuleEntry(
            name="f1",
            status=module["status"],
            freshness=module["freshness"],
            reason_code=module["reason_code"],
            observed_at=_module_observed_at(module, now=now),
            display_text=display,
            data=resolved_data,
        ),
        resolved_data,
    )


def _build_football_module(module: dict[str, Any], *, now: datetime) -> tuple[TelemetryModuleEntry, dict[str, Any]]:
    data = module.get("data")
    if data is None:
        data = {}
    data = _require_dict(data, path="football.data")
    fixtures_raw = data.get("fixtures")
    if fixtures_raw is None:
        fixtures_raw = []
    if not isinstance(fixtures_raw, list):
        raise DemoFixtureError("football.data.fixtures must be a list.")

    fixtures: list[dict[str, Any]] = []
    for index, item in enumerate(fixtures_raw):
        row = _require_dict(item, path=f"football.data.fixtures[{index}]")
        fixture_id = _require_str(row.get("fixture_id"), path=f"football.data.fixtures[{index}].fixture_id")
        team = _require_str(row.get("team"), path=f"football.data.fixtures[{index}].team")
        opponent = _require_str(row.get("opponent"), path=f"football.data.fixtures[{index}].opponent")
        competition = _require_str(
            row.get("competition"),
            path=f"football.data.fixtures[{index}].competition",
        )
        home_or_away = row.get("home_or_away")
        if home_or_away not in {"home", "away"}:
            raise DemoFixtureError(
                f"football.data.fixtures[{index}].home_or_away must be 'home' or 'away'."
            )
        if isinstance(row.get("kickoff_at"), str):
            kickoff_at = row["kickoff_at"]
        elif isinstance(row.get("kickoff_offset"), str):
            kickoff_at = resolve_relative_time(row["kickoff_offset"], now=now).isoformat()
        else:
            raise DemoFixtureError(
                f"football.data.fixtures[{index}] requires kickoff_at or kickoff_offset."
            )
        fixtures.append(
            {
                "fixture_id": fixture_id,
                "team_id": int(row.get("team_id", 0) or 0),
                "team": team,
                "opponent": opponent,
                "home_or_away": home_or_away,
                "competition_id": int(row.get("competition_id", 0) or 0),
                "competition": competition,
                "kickoff_at": kickoff_at,
            }
        )

    fixtures.sort(key=lambda fixture: fixture["kickoff_at"])
    configured_team_count = data.get("configured_team_count", len(fixtures))
    if not isinstance(configured_team_count, int) or configured_team_count < 0:
        configured_team_count = len(fixtures)
    resolved_data = {
        "fixtures": fixtures,
        "configured_team_count": configured_team_count,
    }
    if fixtures:
        display = " ".join(
            (
                f"{fixture['team']}: "
                f"{'Home' if fixture['home_or_away'] == 'home' else 'Away'} "
                f"vs {fixture['opponent']} ({fixture['competition']})."
            )
            for fixture in fixtures
        )
    else:
        display = "No upcoming football fixtures."
    return (
        TelemetryModuleEntry(
            name="football",
            status=module["status"],
            freshness=module["freshness"],
            reason_code=module["reason_code"],
            observed_at=_module_observed_at(module, now=now),
            display_text=display,
            data=resolved_data,
        ),
        resolved_data,
    )


def _parse_module_shell(name: str, module: Any) -> dict[str, Any]:
    row = _require_dict(module, path=f"modules.{name}")
    status = row.get("status")
    freshness = row.get("freshness", "none")
    reason_code = row.get("reason_code", "ok")
    if status not in _VALID_STATUSES:
        raise DemoFixtureError(f"modules.{name}.status is invalid.")
    if freshness not in _VALID_FRESHNESS:
        raise DemoFixtureError(f"modules.{name}.freshness is invalid.")
    if not isinstance(reason_code, str) or not reason_code.strip():
        raise DemoFixtureError(f"modules.{name}.reason_code must be a string.")
    return {
        **row,
        "status": status,
        "freshness": freshness,
        "reason_code": reason_code.strip(),
    }


def _build_module(
    name: str,
    module: dict[str, Any],
    *,
    now: datetime,
) -> TelemetryModuleEntry:
    if name == "weather":
        entry, _ = _build_weather_module(module, now=now)
        return entry
    if name == "news":
        entry, _ = _build_news_module(module, now=now)
        return entry
    if name == "email":
        entry, _ = _build_email_module(module, now=now)
        return entry
    if name == "calendar":
        entry, _ = _build_calendar_module(module, now=now)
        return entry
    if name == "reminders":
        entry, _ = _build_reminders_module(module, now=now)
        return entry
    if name == "f1":
        entry, _ = _build_f1_module(module, now=now)
        return entry
    if name == "football":
        entry, _ = _build_football_module(module, now=now)
        return entry
    raise DemoFixtureError(f"Unsupported demo module: {name!r}")


def _derive_insights(
    *,
    weather_data: dict[str, Any],
    email_data: dict[str, Any],
    calendar_data: dict[str, Any],
    f1_data: dict[str, Any],
    reminders_data: dict[str, Any],
    fixture_insights: list[str],
) -> list[str]:
    insights = list(fixture_insights)
    events = calendar_data.get("events") if isinstance(calendar_data.get("events"), list) else []
    if events and len(insights) < 3:
        first = events[0]
        if isinstance(first, dict):
            summary = str(first.get("summary", "Upcoming event"))
            insights.append(f"Calendar: {summary} is next on the schedule.")
    f1_map = f1_data.get("f1_map") if isinstance(f1_data.get("f1_map"), dict) else {}
    if f1_map.get("relativeWeek") == "This week" and len(insights) < 3:
        race_name = str(f1_map.get("raceName", "Grand Prix"))
        insights.append(f"Sports: {race_name} is scheduled this week.")
    if reminders_data.get("count", 0) and len(insights) < 3:
        insights.append("Reminders: Pending follow-ups require attention.")
    if email_data.get("count", 0) and len(insights) < 3:
        insights.append("Email: Unread primary messages are waiting.")
    if weather_data.get("temp_f") is not None and len(insights) < 3:
        insights.append(
            f"Weather: {weather_data['temp_f']}°F with {weather_data.get('condition', 'current conditions')}."
        )
    return insights[:3]


def load_demo_bundle(*, now: datetime | None = None) -> DemoBundle:
    """Load and normalize the single-source DEMO_MODE fixture."""
    payload = _load_raw_fixture()
    modules_raw = _require_dict(payload.get("modules"), path="modules")
    now_utc = _resolve_now(now)
    collected_at = now_utc.isoformat()

    modules: dict[str, TelemetryModuleEntry] = {}
    structured: dict[str, dict[str, Any]] = {}
    for name in CONNECTOR_NAMES:
        if name not in modules_raw:
            raise DemoFixtureError(f"modules.{name} is required.")
        shell = _parse_module_shell(name, modules_raw[name])
        modules[name] = _build_module(name, shell, now=now_utc)
        structured[name] = dict(modules[name].data)

    report = compute_sync_health(
        {
            name: (
                None
                if entry.status == "disabled"
                else entry.to_connector_result()
            )
            for name, entry in modules.items()
        }
    )
    connector_health = [
        ConnectorHealthEntry(
            name=entry.name,
            status=entry.status,
            freshness=entry.freshness,
            reason_code=entry.reason_code,
            observed_at=entry.observed_at,
        )
        for entry in modules.values()
        if entry.status != "disabled"
    ]

    fixture_insights = payload.get("insights")
    insights: list[str] = []
    if isinstance(fixture_insights, list):
        insights = [str(item).strip() for item in fixture_insights if str(item).strip()]

    digest = DigestPayload(
        weather_archetype=str(structured["weather"].get("archetype") or "clear_day"),
        unread_emails_count=int(structured["email"].get("count", 0) or 0),
        upcoming_events_count=int(structured["calendar"].get("total_count", 0) or 0),
        f1_sprint_active=bool(
            isinstance(structured["f1"].get("f1_map"), dict)
            and structured["f1"]["f1_map"].get("sprintScheduled")
        ),
        reminders_pending_count=int(structured["reminders"].get("count", 0) or 0),
        sync_health_score=report.sync_health_score,
        connector_health=connector_health,
        confidence_score=report.sync_health_score,
        failed_connectors=list(report.failed_connectors),
        insights=_derive_insights(
            weather_data=structured["weather"],
            email_data=structured["email"],
            calendar_data=structured["calendar"],
            f1_data=structured["f1"],
            reminders_data=structured["reminders"],
            fixture_insights=insights,
        ),
    )

    telemetry = TelemetryPayload(
        weather=modules["weather"].display_text,
        sports=modules["f1"].display_text,
        news=modules["news"].display_text,
        email=modules["email"].display_text,
        calendar=modules["calendar"].display_text,
        reminders=modules["reminders"].display_text,
    )
    return DemoBundle(
        telemetry=telemetry,
        digest=digest,
        modules=modules,
        collected_at=collected_at,
    )
