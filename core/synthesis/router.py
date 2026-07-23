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
from core.synthesis.formatting import (
    deterministic_fallback,
    parse_model_output,
    wrap_untrusted_payload,
)
from core.synthesis.models import (
    LOCAL_BRIEFING_PROFILES,
    BriefingMode,
    SynthesisInput,
    SynthesisResult,
    strategy_to_briefing_mode,
)

_LOGGER = logging.getLogger(__name__)


StateCallback = Callable[[str, str | None, str | None, str | None], None]


@dataclass
class WarmupHandle:
    profile_key: str = "acinonyx"
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


def _system_prompt_for_profile(profile_key: str) -> str:
    """Lynx keeps its local prompt; Acinonyx/Neofelis use the Comet contract."""
    if profile_key == "lynx":
        return OLLAMA_SYNTHESIS_PROMPT
    return GEMINI_SYNTHESIS_PROMPT


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

    def start_profile_warmup(self, profile_key: str) -> WarmupHandle:
        handle = WarmupHandle(profile_key=profile_key)
        if profile_key not in LOCAL_BRIEFING_PROFILES:
            handle.reason = "local_profile_invalid"
            handle.finished_at = time.monotonic()
            handle.event.set()
            return handle
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

        self._state("loading", "ollama", profile_key, None)

        def worker() -> None:
            try:
                profile = OLLAMA_MODEL_PROFILES[profile_key]
                snapshot = get_status_snapshot()
                if not snapshot["reachable"]:
                    handle.reason = "local_unreachable"
                    return
                if profile.api_model not in snapshot["installed_tags"]:
                    handle.reason = "local_model_missing"
                    return
                if not is_local_model_loaded(profile.api_model):
                    allowed, gate_reason = check_resource_gate(
                        profile.ram_limit, profile.cpu_limit
                    )
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

    def start_lynx_warmup(self) -> WarmupHandle:
        """Warm Lynx for cloud-fallback paths."""
        return self.start_profile_warmup("lynx")

    def prepare(self, strategy: str) -> WarmupHandle | None:
        mode = strategy_to_briefing_mode(strategy)
        return self.prepare_mode(mode)

    def prepare_mode(self, mode: BriefingMode) -> WarmupHandle | None:
        if mode == "structured_digest" or mode == "comet":
            return None
        if mode not in LOCAL_BRIEFING_PROFILES:
            return None
        resident = resident_profile_key()
        if resident == mode:
            self._state("ready", "ollama", resident, None)
            return None
        # Explicit local selection (or legacy local→acinonyx) warms the selected profile.
        return self.start_profile_warmup(mode)

    def _raw(
        self, source: SynthesisInput, reason: str | None, warmup_ms: int | None = None
    ) -> SynthesisResult:
        self._state("fallback", "raw", None, reason)
        briefing, insights = deterministic_fallback(source)
        return SynthesisResult(
            briefing=briefing,
            insights=insights,
            provider="raw",
            fallback_reason=reason,
            warmup_ms=warmup_ms,
        )

    def _gemini(self, source: SynthesisInput) -> SynthesisResult:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("gemini_unavailable")
        self._state("generating", "gemini", "comet", None)
        started = time.monotonic()
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=[wrap_untrusted_payload(source)],
            config=types.GenerateContentConfig(
                system_instruction=GEMINI_SYNTHESIS_PROMPT,
                max_output_tokens=512,
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

    def _ollama(
        self, source: SynthesisInput, profile_key: str, warmup_ms: int | None
    ) -> SynthesisResult:
        if not try_begin_local_execution():
            raise RuntimeError("local_busy")
        started = time.monotonic()
        try:
            profile = OLLAMA_MODEL_PROFILES[profile_key].model_copy(
                update={
                    "final_answer_max_tokens": 512,
                    "think": False,
                    "system_instruction": _system_prompt_for_profile(profile_key),
                }
            )
            self._state("generating", "ollama", profile_key, None)
            message = OllamaProvider().generate_turn(
                [AgentMessage(role="user", content=wrap_untrusted_payload(source))],
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

    def _synthesize_explicit_local(
        self,
        source: SynthesisInput,
        profile_key: str,
        warmup: WarmupHandle | None,
    ) -> SynthesisResult:
        """Honor an explicitly selected local profile; never silently substitute another."""
        resident = resident_profile_key()
        if resident == profile_key:
            try:
                result = self._ollama(source, profile_key, None)
                self._state("complete", result.provider, result.profile, None)
                return result
            except Exception as exc:
                reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
                return self._raw(source, reason)

        if warmup is None:
            warmup = self.start_profile_warmup(profile_key)
        elif warmup.profile_key != profile_key:
            # Caller prepared a different profile; switch to the selected one.
            warmup = self.start_profile_warmup(profile_key)

        if not warmup.event.wait(LOCAL_PRIMARY_GRACE_SECONDS):
            return self._raw(source, "local_warmup_timeout", warmup.elapsed_ms)
        if not warmup.success:
            return self._raw(
                source, warmup.reason or "local_warmup_failed", warmup.elapsed_ms
            )
        self._state("ready", "ollama", profile_key, None)
        try:
            result = self._ollama(source, profile_key, warmup.elapsed_ms)
            self._state("complete", result.provider, result.profile, None)
            return result
        except Exception as exc:
            reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
            return self._raw(source, reason, warmup.elapsed_ms)

    def _synthesize_comet(
        self, source: SynthesisInput, warmup: WarmupHandle | None
    ) -> SynthesisResult:
        gemini_reason: str | None = None
        try:
            result = self._gemini(source)
            self._state("complete", result.provider, result.profile, None)
            return result
        except Exception as exc:
            _LOGGER.error(
                "Gemini briefing synthesis failed; falling back to local/raw. "
                "error_type=%s",
                type(exc).__name__,
            )
            gemini_reason = str(exc) if str(exc).startswith("gemini_") else "gemini_error"

        resident = resident_profile_key()
        if resident:
            try:
                result = self._ollama(source, resident, None)
                result.fallback_reason = gemini_reason
                self._state(
                    "complete", result.provider, result.profile, result.fallback_reason
                )
                return result
            except Exception as exc:
                reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
                return self._raw(source, reason)

        if warmup is None:
            warmup = self.start_lynx_warmup()
        if not warmup.event.wait(LOCAL_FALLBACK_GRACE_SECONDS):
            return self._raw(source, "local_warmup_timeout", warmup.elapsed_ms)
        if not warmup.success:
            return self._raw(
                source,
                warmup.reason or gemini_reason or "local_warmup_failed",
                warmup.elapsed_ms,
            )
        self._state("ready", "ollama", warmup.profile_key, gemini_reason)
        try:
            result = self._ollama(source, warmup.profile_key, warmup.elapsed_ms)
            result.fallback_reason = gemini_reason
            self._state(
                "complete", result.provider, result.profile, result.fallback_reason
            )
            return result
        except Exception as exc:
            reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
            return self._raw(source, reason, warmup.elapsed_ms)

    def synthesize_mode(
        self,
        source: SynthesisInput,
        mode: BriefingMode,
        warmup: WarmupHandle | None = None,
    ) -> SynthesisResult:
        if mode == "structured_digest":
            result = self._raw(source, "configured_raw")
            self._state("complete", result.provider, result.profile, result.fallback_reason)
            return result

        if mode == "comet":
            return self._synthesize_comet(source, warmup)

        if mode in LOCAL_BRIEFING_PROFILES:
            return self._synthesize_explicit_local(source, mode, warmup)

        return self._raw(source, "invalid_briefing_mode")

    def synthesize(
        self,
        source: SynthesisInput,
        strategy: str,
        warmup: WarmupHandle | None = None,
        *,
        full_telemetry: str | None = None,
    ) -> SynthesisResult:
        # full_telemetry is retained only as an unused compatibility keyword.
        _ = full_telemetry
        mode = strategy_to_briefing_mode(strategy)
        return self.synthesize_mode(source, mode, warmup)
