"""Compatibility helpers delegating speech policy to :mod:`core.speaker`."""

from __future__ import annotations

import re

from core import scanner, speaker

_MOJIBAKE_TOKEN_PATTERN = re.compile(r"\S*(?:Ãƒ|Ã‚|Ã…|â€|Ã°)\S*")


def resolve_tts_diagnostics(
    *,
    dev_mode: bool,
    configured_tts: str,
) -> tuple[str, bool]:
    """Return speaker-owned engine and load diagnostics."""
    return speaker.resolve_tts_diagnostics(
        dev_mode=dev_mode,
        configured_tts=configured_tts,
    )


def clean_for_tts(text: str) -> str:
    """Compatibility wrapper used by reminders until the v1.20 migration.

    Speech delivery itself uses ``speaker.prepare_text`` directly and preserves
    valid Unicode. This shim additionally drops obvious mojibake tokens so the
    pre-v1.20 reminder path retains its historical corruption cleanup without
    restoring the old ASCII-only policy.
    """
    cleaned = speaker.prepare_text(text)
    return re.sub(r"\s+", " ", _MOJIBAKE_TOKEN_PATTERN.sub(" ", cleaned)).strip()


# Compatibility aliases for callers and tests that used private names.
_resolve_tts_diagnostics = resolve_tts_diagnostics
