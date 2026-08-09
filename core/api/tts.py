"""Compatibility helpers delegating speech policy to :mod:`core.speaker`."""

from __future__ import annotations

from core import speaker


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
    """Compatibility wrapper for callers not yet migrated to ``speaker.prepare_text``."""
    return speaker.prepare_text(text)


# Compatibility aliases for callers and tests that used private names.
_resolve_tts_diagnostics = resolve_tts_diagnostics
