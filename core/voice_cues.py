"""Deterministic contextual voice cue copy and formatting."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

VoiceCueName = Literal[
    "activation_ready",
    "activation_loading",
    "activation_refresh_failed",
    "activation_no_fresh_telemetry",
    "briefing_generating",
    "briefing_ready",
    "briefing_failed",
    "highlights_ready",
    "highlights_failed",
]

_PROFILE_LABELS = {"daily": "Daily", "catch_up": "Catch Up", "deep": "Deep"}


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
    briefing_profile: str | None = None,
) -> str:
    """Format one public cue from local time, saved designation, and mode."""
    local_now = now or datetime.now()
    salutation = _salutation(local_now)
    vocative = _vocative(user_designation)

    if cue == "activation_ready":
        return "Your Overview is ready."
    if cue == "activation_loading":
        return f"{salutation}{vocative}. I’m collecting telemetry for your Overview."
    if cue == "activation_refresh_failed":
        return "I couldn’t refresh your Overview telemetry just now. Please try again."
    if cue == "activation_no_fresh_telemetry":
        return "I couldn’t find an available telemetry source for your Overview. Please try again."

    if cue == "briefing_generating":
        label = _PROFILE_LABELS.get(briefing_profile or "")
        return f"I’m preparing your {label} briefing." if label else "I’m preparing your briefing."
    if cue == "briefing_ready":
        return "Your briefing is ready."
    if cue == "briefing_failed":
        return "I couldn’t finish your briefing. Please try again."
    if cue == "highlights_ready":
        return "Your spoken highlights are ready."
    if cue == "highlights_failed":
        return "I couldn’t prepare your spoken highlights. Please try again."

    raise ValueError(f"Unsupported voice cue: {cue!r}")
