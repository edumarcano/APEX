"""Process-current masked briefing context for sandboxed Apex Agent turns."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MaskedBriefingContext:
    snapshot_id: str
    briefing: str
    insights: tuple[str, ...]


_LOCK = threading.Lock()
_CURRENT: MaskedBriefingContext | None = None


def publish_masked_briefing(
    *, snapshot_id: str, briefing: str, insights: list[str]
) -> None:
    """Replace the process-current context after masked DEV synthesis."""
    global _CURRENT
    with _LOCK:
        _CURRENT = MaskedBriefingContext(
            snapshot_id=snapshot_id,
            briefing=briefing,
            insights=tuple(insights),
        )


def get_masked_briefing(snapshot_id: str) -> MaskedBriefingContext | None:
    with _LOCK:
        if _CURRENT is None or _CURRENT.snapshot_id != snapshot_id:
            return None
        return _CURRENT


def clear_masked_briefing_for_tests() -> None:
    global _CURRENT
    with _LOCK:
        _CURRENT = None
