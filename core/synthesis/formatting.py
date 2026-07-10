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


def sanitize_fact(value: object, limit: int = 240) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = html.unescape(text).replace(_SPEECH, " ").replace(_INSIGHTS, " ")
    text = _CONTROL_RE.sub(" ", text)
    text = _MARKUP_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    shortened = text[: limit + 1].rsplit(" ", 1)[0].strip()
    return shortened or text[:limit].strip()


def compact_payload(source: SynthesisInput, max_chars: int = 2000) -> str:
    data: dict[str, Any] = {
        "generated_at": sanitize_fact(source.generated_at, 64),
        "timezone": sanitize_fact(source.timezone, 64),
        "weather": sanitize_fact(source.weather_summary),
        "calendar_event_count": source.calendar_event_count,
        "next_calendar_event": None,
        "pending_reminder_count": source.pending_reminder_count,
        "first_pending_reminder": sanitize_fact(source.first_pending_reminder),
        "f1_this_week": None,
        "failed_connectors": [sanitize_fact(item, 48) for item in source.failed_connectors[:8]],
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

    # Shrink the longest user-authored fields until the complete JSON fits.
    while True:
        rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if len(rendered) <= max_chars:
            return rendered
        candidates: list[tuple[dict[str, Any], str]] = []
        if isinstance(data.get("first_pending_reminder"), str):
            candidates.append((data, "first_pending_reminder"))
        calendar = data.get("next_calendar_event")
        if isinstance(calendar, dict):
            candidates.append((calendar, "title"))
        if isinstance(data.get("weather"), str):
            candidates.append((data, "weather"))
        target, key = max(candidates, key=lambda entry: len(str(entry[0].get(entry[1], ""))))
        current = str(target.get(key, ""))
        if len(current) <= 32:
            data["failed_connectors"] = []
            rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            if len(rendered) <= max_chars:
                return rendered
            raise ValueError("Compact synthesis payload could not be bounded safely.")
        target[key] = sanitize_fact(current, max(32, len(current) - 64))


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
    failures = [sanitize_fact(item, 48) for item in source.failed_connectors if sanitize_fact(item, 48)]
    if failures:
        parts.append(f"Unavailable telemetry: {', '.join(failures)}.")
    weather = sanitize_fact(source.weather_summary, 160)
    if weather:
        parts.append(weather.rstrip(".") + ".")
    if source.next_calendar_event:
        event = source.next_calendar_event
        when = "All day " + sanitize_fact(event.start, 72) if event.all_day else sanitize_fact(event.start, 72)
        parts.append(
            f"Calendar: {source.calendar_event_count} event{'s' if source.calendar_event_count != 1 else ''}; "
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
    briefing = _clamp_words(" ".join(parts), 75)
    insights = ["Deterministic privacy-safe briefing fallback active."]
    return briefing or "No briefing telemetry is currently available.", insights
