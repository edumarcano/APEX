from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from google import genai
from google.genai import types

from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.ollama_lifecycle import (
    check_resource_gate,
    end_local_execution,
    get_active_loaded_model,
    get_status_snapshot,
    is_local_model_loaded,
    switch_local_model,
    try_begin_local_execution,
)
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES
from core.agent.types import AgentMessage
from core.config import (
    GEMINI_SYNTHESIS_PROMPT,
    LOCAL_FALLBACK_GRACE_SECONDS,
    LOCAL_PRIMARY_GRACE_SECONDS,
    OLLAMA_ENABLED,
    OLLAMA_SYNTHESIS_PROMPT,
)
from core.synthesis.formatting import compact_payload, deterministic_fallback, parse_model_output
from core.synthesis.models import SynthesisInput, SynthesisResult

_LOGGER = logging.getLogger(__name__)


StateCallback = Callable[[str, str | None, str | None, str | None], None]


@dataclass
class WarmupHandle:
    profile_key: str = "lynx"
    event: threading.Event = field(default_factory=threading.Event)
    success: bool = False
    reason: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None

    @property
    def elapsed_ms(self) -> int | None:
        end = self.finished_at
        return int(((end or time.monotonic()) - self.started_at) * 1000)


def _profile_key_for_model(model_name: str | None) -> str | None:
    for key, profile in OLLAMA_MODEL_PROFILES.items():
        if profile.api_model == model_name:
            return key
    return None


def resident_profile_key() -> str | None:
    tracked = _profile_key_for_model(get_active_loaded_model())
    if tracked:
        return tracked
    if not OLLAMA_ENABLED:
        return None
    snapshot = get_status_snapshot()
    for model in snapshot["loaded_models"]:
        for value in (model["model"], model["name"]):
            key = _profile_key_for_model(value)
            if key:
                return key
    return None


def _has_unrecognized_resident_model() -> bool:
    if not OLLAMA_ENABLED:
        return False
    snapshot = get_status_snapshot()
    return bool(snapshot["loaded_models"]) and resident_profile_key() is None


class SynthesisRouter:
    def __init__(self, state_callback: StateCallback | None = None) -> None:
        self._state_callback = state_callback or (lambda *_args: None)

    def _state(
        self,
        phase: str,
        provider: str | None = None,
        profile: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._state_callback(phase, provider, profile, reason)

    def start_lynx_warmup(self) -> WarmupHandle:
        handle = WarmupHandle()
        if not OLLAMA_ENABLED:
            handle.reason = "local_disabled"
            handle.finished_at = time.monotonic()
            handle.event.set()
            return handle
        if _has_unrecognized_resident_model():
            handle.reason = "external_model_resident"
            handle.finished_at = time.monotonic()
            handle.event.set()
            return handle
        if not try_begin_local_execution():
            handle.reason = "local_busy"
            handle.finished_at = time.monotonic()
            handle.event.set()
            return handle

        self._state("loading", "ollama", "lynx", None)

        def worker() -> None:
            try:
                profile = OLLAMA_MODEL_PROFILES["lynx"]
                snapshot = get_status_snapshot()
                if not snapshot["reachable"]:
                    handle.reason = "local_unreachable"
                    return
                if profile.api_model not in snapshot["installed_tags"]:
                    handle.reason = "local_model_missing"
                    return
                if not is_local_model_loaded(profile.api_model):
                    allowed, gate_reason = check_resource_gate(profile.ram_limit, profile.cpu_limit)
                    if not allowed:
                        handle.reason = f"local_{gate_reason or 'resource_gated'}"
                        return
                handle.success = switch_local_model(profile)
                if not handle.success:
                    handle.reason = "local_warmup_failed"
            except Exception:
                handle.reason = "local_warmup_failed"
            finally:
                handle.finished_at = time.monotonic()
                end_local_execution()
                handle.event.set()

        threading.Thread(target=worker, daemon=True, name="apex-synthesis-warmup").start()
        return handle

    def prepare(self, strategy: str) -> WarmupHandle | None:
        if strategy != "local":
            return None
        resident = resident_profile_key()
        if resident:
            self._state("ready", "ollama", resident, None)
            return None
        return self.start_lynx_warmup()

    def _raw(self, source: SynthesisInput, reason: str | None, warmup_ms: int | None = None) -> SynthesisResult:
        self._state("fallback", "raw", None, reason)
        briefing, insights = deterministic_fallback(source)
        return SynthesisResult(
            briefing=briefing,
            insights=insights,
            provider="raw",
            fallback_reason=reason,
            warmup_ms=warmup_ms,
        )

    def _gemini(self, full_telemetry: str) -> SynthesisResult:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("gemini_unavailable")
        self._state("generating", "gemini", "comet", None)
        started = time.monotonic()
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[full_telemetry],
            config=types.GenerateContentConfig(
                system_instruction=GEMINI_SYNTHESIS_PROMPT,
                thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            ),
        )
        briefing, insights = parse_model_output((response.text or "").strip())
        return SynthesisResult(
            briefing=briefing,
            insights=insights,
            provider="gemini",
            profile="comet",
            generation_ms=int((time.monotonic() - started) * 1000),
        )

    def _ollama(self, source: SynthesisInput, profile_key: str, warmup_ms: int | None) -> SynthesisResult:
        if not try_begin_local_execution():
            raise RuntimeError("local_busy")
        started = time.monotonic()
        try:
            profile = OLLAMA_MODEL_PROFILES[profile_key].model_copy(
                update={
                    "final_answer_max_tokens": 512,
                    "think": False,
                    "system_instruction": OLLAMA_SYNTHESIS_PROMPT,
                }
            )
            self._state("generating", "ollama", profile_key, None)
            message = OllamaProvider().generate_turn(
                [AgentMessage(role="user", content=compact_payload(source))],
                [],
                profile,
            )
            briefing, insights = parse_model_output(message.content or "")
            return SynthesisResult(
                briefing=briefing,
                insights=insights,
                provider="ollama",
                profile=profile_key,  # type: ignore[arg-type]
                warmup_ms=warmup_ms,
                generation_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            end_local_execution()

    def synthesize(
        self,
        source: SynthesisInput,
        full_telemetry: str,
        strategy: str,
        warmup: WarmupHandle | None = None,
    ) -> SynthesisResult:
        if strategy == "raw":
            result = self._raw(source, "configured_raw")
            self._state("complete", result.provider, result.profile, result.fallback_reason)
            return result

        gemini_reason: str | None = None
        if strategy == "cloud":
            try:
                result = self._gemini(full_telemetry)
                self._state("complete", result.provider, result.profile, None)
                return result
            except Exception as exc:
                _LOGGER.exception("Gemini briefing synthesis failed; falling back to local/raw.")
                gemini_reason = str(exc) if str(exc).startswith("gemini_") else "gemini_error"

        resident = resident_profile_key()
        if resident:
            try:
                result = self._ollama(source, resident, None)
                result.fallback_reason = gemini_reason
                self._state("complete", result.provider, result.profile, result.fallback_reason)
                return result
            except Exception as exc:
                reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
                return self._raw(source, reason)

        if warmup is None:
            warmup = self.start_lynx_warmup()
        grace = LOCAL_PRIMARY_GRACE_SECONDS if strategy == "local" else LOCAL_FALLBACK_GRACE_SECONDS
        if not warmup.event.wait(grace):
            return self._raw(source, "local_warmup_timeout", warmup.elapsed_ms)
        if not warmup.success:
            return self._raw(source, warmup.reason or gemini_reason or "local_warmup_failed", warmup.elapsed_ms)
        self._state("ready", "ollama", warmup.profile_key, gemini_reason)
        try:
            result = self._ollama(source, warmup.profile_key, warmup.elapsed_ms)
            result.fallback_reason = gemini_reason
            self._state("complete", result.provider, result.profile, result.fallback_reason)
            return result
        except Exception as exc:
            reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
            return self._raw(source, reason, warmup.elapsed_ms)
