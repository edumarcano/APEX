from __future__ import annotations

import html
import json
import re
import unicodedata
from typing import Any

from core.synthesis.models import SynthesisInput

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
    shortened = text[: limit + 1].rsplit(" ", 1)[0].strip()
    return shortened or text[:limit].strip()


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


def compact_payload(source: SynthesisInput, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    data: dict[str, Any] = {
        "generated_at": sanitize_fact(source.generated_at, 64),
        "timezone": sanitize_fact(source.timezone, 64),
        "weather": sanitize_fact(source.weather_summary),
        "weather_temp_f": source.weather_temp_f,
        "weather_condition": sanitize_fact(source.weather_condition, 96) or None,
        "email_unread_count": source.email_unread_count,
        "email_recent_subjects": [
            sanitize_fact(item, 120) for item in source.email_recent_subjects[:3]
        ],
        "news_headlines": [
            {
                "topic": sanitize_fact(item.topic, 64),
                "headline": sanitize_fact(item.headline, 160),
            }
            for item in source.news_headlines[:2]
        ],
        "calendar_event_count": source.calendar_event_count,
        "next_calendar_event": None,
        "pending_reminder_count": source.pending_reminder_count,
        "first_pending_reminder": sanitize_fact(source.first_pending_reminder),
        "f1_this_week": None,
        "football_next_fixture": None,
        "connector_health": [
            {
                "name": sanitize_fact(item.name, 32),
                "status": sanitize_fact(item.status, 24),
                "reason_code": sanitize_fact(item.reason_code, 48),
            }
            for item in source.connector_health[:8]
        ],
        "failed_connectors": [
            sanitize_fact(item, 48) for item in source.failed_connectors[:8]
        ],
    }
    if source.next_calendar_event:
        data["next_calendar_event"] = {
            "title": sanitize_fact(source.next_calendar_event.title),
            "start": sanitize_fact(source.next_calendar_event.start, 96),
            "all_day": source.next_calendar_event.all_day,
        }
    if source.f1_this_week:
        data["f1_this_week"] = {
            "race_name": sanitize_fact(source.f1_this_week.race_name),
            "start": sanitize_fact(source.f1_this_week.start, 96),
            "sprint_scheduled": source.f1_this_week.sprint_scheduled,
        }
    if source.football_next_fixture:
        data["football_next_fixture"] = {
            "opponent": sanitize_fact(source.football_next_fixture.opponent, 96),
            "fixture_date": sanitize_fact(source.football_next_fixture.fixture_date, 96),
            "summary": sanitize_fact(source.football_next_fixture.summary, 160) or None,
        }

    while True:
        rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(rendered) <= max_chars:
            return rendered

        candidates = _shrink_candidates(data)
        if not candidates:
            data["failed_connectors"] = []
            data["connector_health"] = []
            rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            if len(rendered) <= max_chars:
                return rendered
            raise ValueError("Compact synthesis payload could not be bounded safely.")

        container, key, kind = max(candidates, key=_candidate_length)
        current = str(container[key])
        if len(current) <= 32:
            if kind == "list":
                del container[key]
            else:
                data["failed_connectors"] = []
                data["connector_health"] = []
            continue
        container[key] = sanitize_fact(current, max(32, len(current) - 64))


def wrap_untrusted_payload(source: SynthesisInput, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    """Serialize and mark connector facts as untrusted model evidence."""
    compact = compact_payload(source, max_chars=max_chars)
    return f"{_UNTRUSTED_OPEN}\n{compact}\n{_UNTRUSTED_CLOSE}"


def _clamp_words(text: str, maximum: int) -> str:
    words = _WORD_RE.findall(text)
    return " ".join(words[:maximum]).strip()


def parse_model_output(text: str) -> tuple[str, list[str]]:
    if text.count(_SPEECH) != 1 or text.count(_INSIGHTS) != 1:
        raise ValueError("Synthesis output must contain exactly one of each section marker.")
    speech_index = text.index(_SPEECH)
    insights_index = text.index(_INSIGHTS)
    if speech_index > insights_index:
        raise ValueError("Synthesis section markers are reversed.")
    speech = sanitize_fact(text[speech_index + len(_SPEECH) : insights_index], 1200)
    speech = _clamp_words(speech, 75)
    if not speech:
        raise ValueError("Synthesis speech section is empty.")

    insights: list[str] = []
    for line in text[insights_index + len(_INSIGHTS) :].splitlines():
        cleaned = sanitize_fact(_BULLET_RE.sub("", line.strip()), 240)
        cleaned = _clamp_words(cleaned, 12)
        if cleaned:
            insights.append(cleaned)
        if len(insights) == 3:
            break
    return speech, insights


def deterministic_fallback(source: SynthesisInput) -> tuple[str, list[str]]:
    parts: list[str] = []
    failures = [
        sanitize_fact(item, 48) for item in source.failed_connectors if sanitize_fact(item, 48)
    ]
    if failures:
        parts.append(f"Unavailable telemetry: {', '.join(failures)}.")
    weather = sanitize_fact(source.weather_summary, 160)
    if weather:
        parts.append(weather.rstrip(".") + ".")
    if source.email_unread_count:
        parts.append(f"Email: {source.email_unread_count} unread.")
    if source.news_headlines:
        first = source.news_headlines[0]
        parts.append(
            f"News: {sanitize_fact(first.topic, 40)} — {sanitize_fact(first.headline, 80)}."
        )
    if source.next_calendar_event:
        event = source.next_calendar_event
        when = (
            "All day " + sanitize_fact(event.start, 72)
            if event.all_day
            else sanitize_fact(event.start, 72)
        )
        parts.append(
            f"Calendar: {source.calendar_event_count} event"
            f"{'s' if source.calendar_event_count != 1 else ''}; "
            f"next is {sanitize_fact(event.title, 100)} at {when}."
        )
    else:
        parts.append(f"Calendar: {source.calendar_event_count} upcoming events.")
    if source.first_pending_reminder:
        parts.append(
            f"Reminders: {source.pending_reminder_count} pending; first is "
            f"{sanitize_fact(source.first_pending_reminder, 120)}."
        )
    else:
        parts.append(f"Reminders: {source.pending_reminder_count} pending.")
    if source.f1_this_week:
        race = source.f1_this_week
        sprint = " with a sprint" if race.sprint_scheduled else ""
        parts.append(
            f"F1: {sanitize_fact(race.race_name, 100)} is this week at "
            f"{sanitize_fact(race.start, 72)}{sprint}."
        )
    if source.football_next_fixture:
        fixture = source.football_next_fixture
        parts.append(
            f"Football: Barcelona plays {sanitize_fact(fixture.opponent, 80)} on "
            f"{sanitize_fact(fixture.fixture_date, 72)}."
        )
    briefing = _clamp_words(" ".join(parts), 75)
    insights = ["Deterministic privacy-safe briefing fallback active."]
    return briefing or "No briefing telemetry is currently available.", insights
