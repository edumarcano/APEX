"""Thread-safe pipeline runtime state and trigger locking."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from core import speaker


class PipelineState:
    """
    Thread-safe pipeline progress for diagnostics and lifecycle checkpoints.

    Internal fields track step index, phase label, last UTC timestamp ISO string,
    and whether a run currently holds active status for `/api/v1/status` probing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_active = False
        self._run_id: str | None = None
        self._step = 0
        self._label = "IDLE"
        self._timestamp = datetime.now(timezone.utc).isoformat()
        self._active_tts_engine = "google"
        self._system_load_throttled = False
        self._synthesis: dict[str, Any] = {
            "phase": "idle",
            "provider": None,
            "profile": None,
            "loading": False,
            "fallback_reason": None,
        }

    def begin_run(self, run_id: str) -> None:
        """Mark a briefing run active and bind its correlation ID."""
        with self._lock:
            self._is_active = True
            self._run_id = run_id
            self._step = 0
            self._label = "START"
            self._timestamp = datetime.now(timezone.utc).isoformat()

    def update(
        self,
        step: int,
        label: str,
        *,
        active_tts_engine: str | None = None,
        system_load_throttled: bool | None = None,
    ) -> None:
        """
        Advance the conceptual pipeline stage.

        Args:
            step: Monotonic pipeline step index supplied by orchestration logic.
            label: Stable short label naming the stage for dashboards and probes.
            active_tts_engine: Resolved TTS engine for the active run, when known.
            system_load_throttled: Whether hardware throttle thresholds are active.
        """
        with self._lock:
            self._is_active = True
            self._step = step
            self._label = label
            self._timestamp = datetime.now(timezone.utc).isoformat()
            if active_tts_engine is not None:
                self._active_tts_engine = active_tts_engine
            if system_load_throttled is not None:
                self._system_load_throttled = system_load_throttled

    def update_synthesis(
        self,
        phase: str,
        provider: str | None,
        profile: str | None,
        fallback_reason: str | None,
    ) -> None:
        """Update live synthesis routing state without changing the pipeline step."""
        with self._lock:
            self._synthesis = {
                "phase": phase,
                "provider": provider,
                "profile": profile,
                "loading": phase == "loading",
                "fallback_reason": fallback_reason,
            }

    def reset(self) -> None:
        """Restore the tracker to idle or pre-run defaults."""
        with self._lock:
            self._is_active = False
            self._run_id = None
            self._step = 0
            self._label = "IDLE"
            self._timestamp = datetime.now(timezone.utc).isoformat()
            self._active_tts_engine = "google"
            self._system_load_throttled = False
            self._synthesis = {
                "phase": "idle",
                "provider": None,
                "profile": None,
                "loading": False,
                "fallback_reason": None,
            }

    def get_state(self) -> dict[str, Any] | None:
        """
        Produce a shallow snapshot suitable for `/api/v1/status` responses.

        Returns:
            Mapping for JSON serialization, or None when no active run is recorded.
        """
        with self._lock:
            if not self._is_active:
                return None
            return {
                "run_id": self._run_id,
                "step": self._step,
                "label": self._label,
                "timestamp": self._timestamp,
                "is_speaking": speaker.is_speaking(),
                "active_tts_engine": self._active_tts_engine,
                "system_load_throttled": self._system_load_throttled,
                "synthesis": dict(self._synthesis),
            }


global_pipeline_state = PipelineState()
_TRIGGER_LOCK = threading.Lock()


def _speak_and_cleanup(
    text: str,
    *,
    tts_override: str | None = None,
    voice_gender: str | None = None,
    lock: threading.Lock | None = None,
) -> None:
    """Play briefing audio on a worker thread and reset pipeline state when playback ends."""
    try:
        speaker.speak(text, tts_override=tts_override, voice_gender=voice_gender)
    finally:
        global_pipeline_state.reset()
        if lock is not None:
            lock.release()
