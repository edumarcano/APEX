"""Deterministic contextual voice cue copy and formatting."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

VoiceCueName = Literal[
    "activation_ready",
    "activation_loading",
    "activation_refresh_failed",
    "activation_no_fresh_telemetry",
    "telemetry_refresh_failed",
]


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
    user_designation: str | None = None,
    now: datetime | None = None,
) -> str:
    """Format one public cue from local time, saved designation, and mode."""
    local_now = now or datetime.now()
    salutation = _salutation(local_now)
    vocative = _vocative(user_designation)

    if cue == "activation_ready":
        return f"{salutation}{vocative}. I have your telemetry at hand. I’m standing by to brief you."
    if cue == "activation_loading":
        return f"{salutation}{vocative}. I’m gathering your telemetry and standing by for a briefing."
    if cue == "activation_refresh_failed":
        return "I couldn’t refresh your telemetry just now. I’m still standing by."
    if cue == "activation_no_fresh_telemetry":
        return "I’m standing by without fresh telemetry."

    if cue == "telemetry_refresh_failed":
        return "I couldn’t refresh your telemetry just now. Please try again."

    raise ValueError(f"Unsupported voice cue: {cue!r}")
