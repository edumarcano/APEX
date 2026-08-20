from __future__ import annotations

import html
import json
import re
import unicodedata
from typing import Any

from core.synthesis.models import BriefingFacts, BriefingMode

_SPEECH = "===SPEECH==="
_INSIGHTS = "===INSIGHTS==="
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKUP_RE = re.compile(r"<[^>]+>|[`*_>#\[\]{}]+")
_BULLET_RE = re.compile(r"^[\s\-•*>]+")
_WORD_RE = re.compile(r"\S+")
_UNTRUSTED_OPEN = "<untrusted_connector_data>"
_UNTRUSTED_CLOSE = "</untrusted_connector_data>"
_DEFAULT_MAX_CHARS = 2000


def sanitize_fact(value: object, limit: int = 240) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = html.unescape(text).replace(_SPEECH, " ").replace(_INSIGHTS, " ")
    text = text.replace(_UNTRUSTED_OPEN, " ").replace(_UNTRUSTED_CLOSE, " ")
    text = _CONTROL_RE.sub(" ", text)
    text = _MARKUP_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    prefix = text[: limit + 1]
    if " " in prefix:
        shortened = prefix.rsplit(" ", 1)[0].strip()
        if shortened:
            return shortened
    return text[:limit].strip()


def _shrink_candidates(data: dict[str, Any]) -> list[tuple[Any, Any, str]]:
    """Return mutable (container, key_or_index, kind) shrink targets."""
    candidates: list[tuple[Any, Any, str]] = []
    if isinstance(data.get("first_pending_reminder"), str):
        candidates.append((data, "first_pending_reminder", "str"))
    if isinstance(data.get("weather"), str):
        candidates.append((data, "weather", "str"))
    calendar = data.get("next_calendar_event")
    if isinstance(calendar, dict):
        candidates.append((calendar, "title", "str"))
    subjects = data.get("email_recent_subjects")
    if isinstance(subjects, list):
        for index, value in enumerate(subjects):
            if isinstance(value, str):
                candidates.append((subjects, index, "list"))
    headlines = data.get("news_headlines")
    if isinstance(headlines, list):
        for headline in headlines:
            if isinstance(headline, dict):
                candidates.append((headline, "headline", "str"))
    football = data.get("football_next_fixture")
    if isinstance(football, dict) and isinstance(football.get("summary"), str):
        candidates.append((football, "summary", "str"))
    return candidates


def _candidate_length(entry: tuple[Any, Any, str]) -> int:
    container, key, _kind = entry
    return len(str(container[key]))


def _drop_optional_payload_item(
    data: dict[str, Any], *, minimums: dict[str, int]
) -> str | None:
    """Remove one optional value so payload reduction always makes progress."""
    for key in (
        "sports_events",
        "emails",
        "reminders",
        "calendar_events",
        "weather_hourly",
        "weather_daily",
        "email_recent_subjects",
        "news_headlines",
        "connector_health",
        "failed_connectors",
    ):
        values = data.get(key)
        if isinstance(values, list) and len(values) > minimums.get(key, 0):
            values.pop()
            return key

    for key in (
        "first_pending_reminder",
        "weather",
        "weather_apparent_temp_f",
        "weather_temp_max_f",
        "weather_temp_min_f",
        "weather_precip_probability",
        "weather_condition",
        "next_calendar_event",
        "f1_upcoming",
        "football_next_fixture",
    ):
        if data.get(key) not in (None, ""):
            data[key] = None
            return key
    return None


def compact_payload(source: BriefingFacts, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    data: dict[str, Any] = {
        "generated_at": sanitize_fact(source.generated_at, 64),
        "timezone": sanitize_fact(source.timezone, 64),
        "weather": sanitize_fact(source.weather_summary),
        "weather_temp_f": source.weather_temp_f,
        "weather_apparent_temp_f": source.weather_apparent_temp_f,
        "weather_temp_max_f": source.weather_temp_max_f,
        "weather_temp_min_f": source.weather_temp_min_f,
        "weather_precip_probability": source.weather_precip_probability,
        "weather_condition": sanitize_fact(source.weather_condition, 96) or None,
        "email_unread_count": source.email_unread_count,
        "email_recent_subjects": [
            sanitize_fact(item, 120) for item in source.email_recent_subjects
        ],
        "news_headlines": [
            {
                "topic": sanitize_fact(item.topic, 64),
                "headline": sanitize_fact(item.headline, 160),
                "source": sanitize_fact(item.source, 96) or None,
                "published_at": sanitize_fact(item.published_at, 64) or None,
                "synopsis": sanitize_fact(item.synopsis, 360) or None,
            }
            for item in source.news_headlines
        ],
        "calendar_event_count": source.calendar_event_count,
        "next_calendar_event": None,
        "pending_reminder_count": source.pending_reminder_count,
        "first_pending_reminder": sanitize_fact(source.first_pending_reminder),
        "f1_upcoming": None,
        "football_next_fixture": None,
        "connector_health": [
            {
                "name": sanitize_fact(item.name, 32),
                "status": sanitize_fact(item.status, 24),
                "reason_code": sanitize_fact(item.reason_code, 48),
                "freshness": sanitize_fact(item.freshness, 24),
                "observed_at": sanitize_fact(item.observed_at, 64) or None,
            }
            for item in source.connector_health[:8]
        ],
        "failed_connectors": [
            sanitize_fact(item, 48) for item in source.failed_connectors[:8]
        ],
        "local_time": sanitize_fact(source.local_time, 64) or None,
        "snapshot_collected_at": sanitize_fact(source.snapshot_collected_at, 64) or None,
        "weather_daily": [
            {"date": sanitize_fact(item.date, 32), "condition": sanitize_fact(item.condition, 64) or None, "high_f": item.temp_max_f, "low_f": item.temp_min_f, "precip_probability": item.precip_probability, "wind_mph": item.wind_speed_mph}
            for item in source.weather_daily
        ],
        "weather_hourly": [
            {"time": sanitize_fact(item.time, 48), "condition": sanitize_fact(item.condition, 64) or None, "temp_f": item.temp_f, "precip_probability": item.precip_probability, "wind_mph": item.wind_speed_mph}
            for item in source.weather_hourly
        ],
        "calendar_events": [
            {"title": sanitize_fact(item.title, 160), "start": sanitize_fact(item.start, 64), "end": sanitize_fact(item.end, 64) or None, "all_day": item.all_day, "location": sanitize_fact(item.location, 120) or None}
            for item in source.calendar_events
        ],
        "reminders": [
            {"note": sanitize_fact(item.note, 160), "due": sanitize_fact(item.due, 64) or None, "due_time_zone": sanitize_fact(item.due_time_zone, 64) or None, "importance": sanitize_fact(item.importance, 24) or None, "source": sanitize_fact(item.source, 24) or None, "sync_state": sanitize_fact(item.sync_state, 24) or None}
            for item in source.reminders
        ],
        "overdue_reminder_count": source.overdue_reminder_count,
        "due_today_reminder_count": source.due_today_reminder_count,
        "emails": [
            {"sender": sanitize_fact(item.sender, 120) or None, "subject": sanitize_fact(item.subject, 160), "received_at": sanitize_fact(item.received_at, 64) or None, "snippet": sanitize_fact(item.snippet, 200) or None}
            for item in source.emails
        ],
        "sports_events": [
            {"kind": sanitize_fact(item.kind, 32), "title": sanitize_fact(item.title, 160), "start": sanitize_fact(item.start, 64), "detail": sanitize_fact(item.detail, 160) or None}
            for item in source.sports_events
        ],
        "truncated": {"calendar": source.calendar_truncated, "reminders": source.reminders_truncated, "sports": source.sports_truncated, "payload": []},
    }
    if source.next_calendar_event:
        data["next_calendar_event"] = {
            "title": sanitize_fact(source.next_calendar_event.title),
            "start": sanitize_fact(source.next_calendar_event.start, 96),
            "all_day": source.next_calendar_event.all_day,
        }
    if source.f1_upcoming:
        data["f1_upcoming"] = {
            "race_name": sanitize_fact(source.f1_upcoming.race_name),
            "start": sanitize_fact(source.f1_upcoming.start, 96),
            "sprint_scheduled": source.f1_upcoming.sprint_scheduled,
        }
    if source.football_next_fixture:
        data["football_next_fixture"] = {
            "team": sanitize_fact(source.football_next_fixture.team, 96),
            "opponent": sanitize_fact(source.football_next_fixture.opponent, 96),
            "home_or_away": source.football_next_fixture.home_or_away,
            "competition": sanitize_fact(source.football_next_fixture.competition, 96),
            "kickoff": sanitize_fact(source.football_next_fixture.kickoff, 96),
        }

    while True:
        rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(rendered) <= max_chars:
            return rendered

        candidates = [
            candidate
            for candidate in _shrink_candidates(data)
            if _candidate_length(candidate) > 32
        ]
        if candidates:
            container, key, _kind = max(candidates, key=_candidate_length)
            current = str(container[key])
            container[key] = sanitize_fact(current, max(32, len(current) - 64))
            continue

        minimums = (
            {
                "calendar_events": 3,
                "reminders": 2,
                "emails": 2,
                "sports_events": 1,
                "weather_daily": 1,
                "weather_hourly": 3,
                "news_headlines": 1,
                "connector_health": 1,
            }
            if max_chars >= 28_000
            else {}
        )
        dropped = _drop_optional_payload_item(data, minimums=minimums)
        if dropped is None:
            raise ValueError("Compact synthesis payload could not be bounded safely.")
        payload_truncation = data["truncated"]["payload"]
        if isinstance(payload_truncation, list) and dropped not in payload_truncation:
            payload_truncation.append(dropped)


def wrap_untrusted_payload(
    source: BriefingFacts,
    max_chars: int | None = None,
    *,
    mode: BriefingMode | None = None,
) -> str:
    """Serialize and mark connector facts as untrusted model evidence."""
    if max_chars is None:
        max_chars = 28_000 if mode == "focused" else 8_000 if mode == "flash" else _DEFAULT_MAX_CHARS
    compact = compact_payload(source, max_chars=max_chars)
    return f"{_UNTRUSTED_OPEN}\n{compact}\n{_UNTRUSTED_CLOSE}"


def _clamp_words(text: str, maximum: int) -> str:
    words = _WORD_RE.findall(text)
    return " ".join(words[:maximum]).strip()


def parse_model_output(
    text: str,
    *,
    max_words: int = 180,
    max_insights: int = 2,
    insight_max_words: int = 16,
) -> tuple[str, list[str]]:
    if text.count(_SPEECH) != 1 or text.count(_INSIGHTS) != 1:
        raise ValueError("Synthesis output must contain exactly one of each section marker.")
    speech_index = text.index(_SPEECH)
    insights_index = text.index(_INSIGHTS)
    if speech_index > insights_index:
        raise ValueError("Synthesis section markers are reversed.")
    # Preserve enough source text for the requested word ceiling before applying
    # the semantic word clamp. A fixed 1,200-character limit cut Focused output
    # short well before its 450-word contract.
    speech = sanitize_fact(
        text[speech_index + len(_SPEECH) : insights_index], max(1200, max_words * 8)
    )
    speech = _clamp_words(speech, max_words)
    if not speech:
        raise ValueError("Synthesis speech section is empty.")

    insights: list[str] = []
    for line in text[insights_index + len(_INSIGHTS) :].splitlines():
        cleaned = sanitize_fact(_BULLET_RE.sub("", line.strip()), 240)
        cleaned = _clamp_words(cleaned, insight_max_words)
        if cleaned:
            insights.append(cleaned)
        if len(insights) == max_insights:
            break
    return speech, insights


def render_structured_briefing(source: BriefingFacts) -> tuple[str, list[str]]:
    """Render the authoritative collected facts without model interpretation."""
    lines: list[str] = []
    insights: list[str] = []
    if source.local_time or source.generated_at:
        lines.append(f"TIME: {sanitize_fact(source.local_time or source.generated_at, 96)}")
    health = [
        item for item in source.connector_health
        if item.status not in {"healthy", "disabled"} or item.freshness == "stale"
    ]
    if health:
        labels = []
        for item in health:
            marker = "STALE" if item.freshness == "stale" else "DEGRADED"
            labels.append(f"{marker}: {sanitize_fact(item.name, 32)} ({sanitize_fact(item.reason_code, 48)})")
        lines.append("SOURCE HEALTH: " + "; ".join(labels))
        insights.extend(labels[:5])
    if source.weather_summary:
        lines.append("WEATHER: " + sanitize_fact(source.weather_summary, 320))
    if source.weather_daily:
        days = "; ".join(
            f"{sanitize_fact(day.date, 24)} {sanitize_fact(day.condition, 48)} high {day.temp_max_f if day.temp_max_f is not None else '?'} low {day.temp_min_f if day.temp_min_f is not None else '?'}"
            for day in source.weather_daily
        )
        lines.append("FORECAST: " + days)
    if source.calendar_events:
        entries = []
        for event in sorted(source.calendar_events, key=lambda item: item.start):
            location = f" @ {sanitize_fact(event.location, 80)}" if event.location else ""
            entries.append(f"{sanitize_fact(event.start, 64)} — {sanitize_fact(event.title, 160)}{location}")
        suffix = " [TRUNCATED]" if source.calendar_truncated else ""
        lines.append("CALENDAR" + suffix + ": " + " | ".join(entries))
    if source.reminders or source.pending_reminder_count:
        reminder_entries = [
            f"{sanitize_fact(item.note, 160)}{f' due {sanitize_fact(item.due, 48)}' if item.due else ''}"
            for item in source.reminders
        ]
        prefix = f"REMINDERS: {source.pending_reminder_count} pending"
        if source.overdue_reminder_count:
            prefix += f"; OVERDUE {source.overdue_reminder_count}"
            insights.append(f"OVERDUE: {source.overdue_reminder_count} reminders")
        if source.due_today_reminder_count:
            prefix += f"; due today {source.due_today_reminder_count}"
        suffix = " [TRUNCATED]" if source.reminders_truncated else ""
        lines.append(prefix + suffix + (" — " + " | ".join(reminder_entries) if reminder_entries else ""))
    if source.emails or source.email_unread_count:
        entries = [
            f"{sanitize_fact(item.sender, 80) + ': ' if item.sender else ''}{sanitize_fact(item.subject, 160)}"
            for item in source.emails
        ]
        lines.append(f"EMAIL: {source.email_unread_count} unread" + (" — " + " | ".join(entries) if entries else ""))
    if source.news_headlines:
        lines.append("NEWS: " + " | ".join(f"{sanitize_fact(item.topic, 48)} — {sanitize_fact(item.headline, 160)}" for item in source.news_headlines))
    if source.sports_events:
        suffix = " [TRUNCATED]" if source.sports_truncated else ""
        lines.append("SPORTS" + suffix + ": " + " | ".join(f"{sanitize_fact(item.start, 64)} — {sanitize_fact(item.title, 160)}" for item in sorted(source.sports_events, key=lambda item: item.start)))
    return "\n".join(lines) or "No briefing telemetry is currently available.", insights[:5]
