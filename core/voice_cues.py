"""Deterministic contextual voice cue copy and formatting."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

BriefingMode = Literal["flash", "focused", "structured"]
VoiceCueName = Literal[
    "activation_ready",
    "activation_loading",
    "activation_refresh_failed",
    "activation_no_fresh_telemetry",
    "start_with_briefing",
    "briefing_refresh",
    "briefing_existing_snapshot",
    "briefing_collection_complete",
    "briefing_partial_sources",
    "briefing_sources_unavailable",
    "briefing_no_snapshot",
    "briefing_generation_failed",
]

BRIEFING_CUES = frozenset(
    {
        "start_with_briefing",
        "briefing_refresh",
        "briefing_existing_snapshot",
        "briefing_collection_complete",
        "briefing_partial_sources",
        "briefing_sources_unavailable",
        "briefing_generation_failed",
    }
)

_MODE_NAMES: dict[BriefingMode, str] = {
    "flash": "Flash",
    "focused": "Focused",
    "structured": "Structured",
}


def _salutation(now: datetime) -> str:
    if 5 <= now.hour < 12:
        return "Good morning"
    if 12 <= now.hour < 17:
        return "Good afternoon"
    return "Good evening"


def _vocative(designation: str | None) -> str:
    normalized = " ".join((designation or "").split()).strip(" ,.!?;:")
    return f", {normalized}" if normalized else ""


def format_voice_cue(
    cue: VoiceCueName,
    *,
    mode: BriefingMode | None = None,
    user_designation: str | None = None,
    now: datetime | None = None,
) -> str:
    """Format one public cue from local time, saved designation, and mode."""
    local_now = now or datetime.now()
    salutation = _salutation(local_now)
    vocative = _vocative(user_designation)
    mode_name = _MODE_NAMES[mode] if mode is not None else None

    if cue == "activation_ready":
        return f"{salutation}{vocative}. I have your telemetry at hand. I’m standing by to brief you."
    if cue == "activation_loading":
        return f"{salutation}{vocative}. I’m gathering your telemetry and standing by for a briefing."
    if cue == "activation_refresh_failed":
        return "I couldn’t refresh your telemetry just now. I’m still standing by."
    if cue == "activation_no_fresh_telemetry":
        return "I’m standing by without fresh telemetry."

    if cue == "briefing_no_snapshot":
        return "I couldn’t gather usable telemetry, so I can’t prepare your briefing yet."

    if mode_name is None:
        raise ValueError(f"Cue {cue!r} requires a briefing mode.")

    if cue == "start_with_briefing":
        return f"{salutation}{vocative}. I’m gathering your telemetry for your {mode_name} briefing."
    if cue == "briefing_refresh":
        return f"I’m refreshing your telemetry for your {mode_name} briefing."
    if cue == "briefing_existing_snapshot":
        return f"I’m preparing your {mode_name} briefing now."
    if cue == "briefing_collection_complete":
        return f"I’ve gathered what’s available. I’m preparing your {mode_name} briefing."
    if cue == "briefing_partial_sources":
        return f"Some sources didn’t respond. I’ll use what’s available while preparing your {mode_name} briefing."
    if cue == "briefing_sources_unavailable":
        return f"None of your telemetry sources responded. I’m preparing your {mode_name} briefing with that limitation."
    if cue == "briefing_generation_failed":
        return f"I couldn’t finish your {mode_name} briefing this time. You can try again when you’re ready."
    raise ValueError(f"Unsupported voice cue: {cue!r}")
