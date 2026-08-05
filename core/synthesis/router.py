from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from core.agent.pricing import estimate_inference_cost
from core.agent.local_runtime import (
    end_local_execution,
    get_active_loaded_model,
    get_status_snapshot,
    is_local_model_loaded,
    switch_local_model,
    try_begin_local_execution,
)
from core.agent.catalog import (
    AGENT_SPECS,
    build_concrete_agent,
    compose_agent_system_instruction,
)
from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.ollama_lifecycle import (
    check_resource_gate,
)
from core.agent.providers.openai_provider import OpenAIProvider
from core.agent.types import AgentMessage
from core.config import (
    LOCAL_FALLBACK_GRACE_SECONDS,
    LOCAL_PRIMARY_GRACE_SECONDS,
    OLLAMA_ENABLED,
    OLLAMA_SYNTHESIS_PROMPT,
    PRIMARY_SYNTHESIS_PROMPT,
)
from core.synthesis.formatting import (
    deterministic_fallback,
    parse_model_output,
    wrap_untrusted_payload,
)
from core.synthesis.models import (
    LOCAL_BRIEFING_AGENTS,
    BriefingMode,
    SynthesisInput,
    SynthesisResult,
    strategy_to_briefing_mode,
)
from core.settings import get_settings_store

_LOGGER = logging.getLogger(__name__)


StateCallback = Callable[[str, str | None, str | None, str | None], None]


@dataclass
class WarmupHandle:
    agent_key: str = "mus"
    event: threading.Event = field(default_factory=threading.Event)
    success: bool = False
    reason: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None

    @property
    def elapsed_ms(self) -> int | None:
        end = self.finished_at
        return int(((end or time.monotonic()) - self.started_at) * 1000)


def _agent_key_for_model(model_name: str | None) -> str | None:
    for key, spec in AGENT_SPECS.items():
        if spec.runtime == "local" and spec.api_model == model_name:
            return key
    return None


def resident_agent_key() -> str | None:
    tracked = _agent_key_for_model(get_active_loaded_model())
    if tracked:
        return tracked
    if not OLLAMA_ENABLED:
        return None
    snapshot = get_status_snapshot()
    for model in snapshot["loaded_models"]:
        for value in (model["model"], model["name"]):
            key = _agent_key_for_model(value)
            if key:
                return key
    return None


def _has_unrecognized_resident_model() -> bool:
    if not OLLAMA_ENABLED:
        return False
    snapshot = get_status_snapshot()
    return bool(snapshot["loaded_models"]) and resident_agent_key() is None


def _system_prompt_for_agent(agent_key: str) -> str:
    """Sorex keeps its local prompt; Mus uses the primary briefing contract."""
    if agent_key == "sorex":
        return OLLAMA_SYNTHESIS_PROMPT
    return PRIMARY_SYNTHESIS_PROMPT


class SynthesisRouter:
    def __init__(self, state_callback: StateCallback | None = None) -> None:
        self._state_callback = state_callback or (lambda *_args: None)

    def _state(
        self,
        phase: str,
        provider: str | None = None,
        agent: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._state_callback(phase, provider, agent, reason)

    def start_agent_warmup(self, agent_key: str) -> WarmupHandle:
        handle = WarmupHandle(agent_key=agent_key)
        if agent_key not in LOCAL_BRIEFING_AGENTS:
            handle.reason = "local_agent_invalid"
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

        self._state("loading", "ollama", agent_key, None)

        def worker() -> None:
            try:
                agent = build_concrete_agent(agent_key, native_effort=None)
                snapshot = get_status_snapshot()
                if not snapshot["reachable"]:
                    handle.reason = "local_unreachable"
                    return
                if agent.api_model not in snapshot["installed_tags"]:
                    handle.reason = "local_model_missing"
                    return
                if not is_local_model_loaded(agent.api_model):
                    allowed, gate_reason = check_resource_gate(
                        agent.ram_limit, agent.cpu_limit
                    )
                    if not allowed:
                        handle.reason = f"local_{gate_reason or 'resource_gated'}"
                        return
                handle.success = switch_local_model(agent)
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

    def start_sorex_warmup(self) -> WarmupHandle:
        """Warm Sorex for cloud-fallback paths."""
        return self.start_agent_warmup("sorex")

    def start_lynx_warmup(self) -> WarmupHandle:
        """Compatibility alias for legacy callers."""
        return self.start_sorex_warmup()

    def prepare(self, strategy: str) -> WarmupHandle | None:
        mode = strategy_to_briefing_mode(strategy)
        return self.prepare_mode(mode)

    def prepare_mode(self, mode: BriefingMode) -> WarmupHandle | None:
        if mode == "structured_digest" or mode == "panthera":
            return None
        if mode not in LOCAL_BRIEFING_AGENTS:
            return None
        resident = resident_agent_key()
        if resident == mode:
            self._state("ready", "ollama", resident, None)
            return None
        # Explicit local selection (or legacy local→acinonyx) warms the selected agent.
        return self.start_agent_warmup(mode)

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

    def _panthera(self, source: SynthesisInput) -> SynthesisResult:
        """Synthesize with the fixed-Light Panthera briefing agent."""
        import os

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("openai_unavailable")
        agent = build_concrete_agent("panthera", native_effort="low")
        self._state("generating", "openai", "panthera", None)
        turn = OpenAIProvider(api_key).generate_turn(
            [AgentMessage(role="user", content=wrap_untrusted_payload(source))],
            [],
            agent,
            system_instruction_override=compose_agent_system_instruction(
                "panthera",
                PRIMARY_SYNTHESIS_PROMPT,
                user_designation=get_settings_store().get_snapshot().user_designation,
            ),
        )
        briefing, insights = parse_model_output(turn.message.content or "")
        return SynthesisResult(
            briefing=briefing,
            insights=insights,
            provider="openai",
            agent="panthera",
            generation_ms=round(turn.provider_ms) if turn.provider_ms is not None else None,
            provider_ms=turn.provider_ms,
            resolved_model=turn.resolved_model or agent.api_model,
            usage=turn.usage,
            cost_estimate=estimate_inference_cost(
                model=turn.resolved_model,
                configured_model=agent.api_model,
                provider="openai",
                usage=turn.usage,
                hosted_tool_events=turn.provider_tool_events,
            ),
        )

    def _ollama(
        self, source: SynthesisInput, agent_key: str, warmup_ms: int | None
    ) -> SynthesisResult:
        if not try_begin_local_execution():
            raise RuntimeError("local_busy")
        started = time.monotonic()
        try:
            user_designation = get_settings_store().get_snapshot().user_designation
            system_instruction = compose_agent_system_instruction(
                agent_key,
                _system_prompt_for_agent(agent_key),
                user_designation=user_designation,
            )
            if agent_key == "sorex" and user_designation:
                normalized_designation = " ".join(user_designation.split())[:80]
                system_instruction += (
                    "\n\nIn the ===SPEECH=== section, address the user as "
                    f'"{normalized_designation}" exactly once. Keep the address natural.'
                )
            agent = build_concrete_agent(agent_key, native_effort=None).model_copy(
                update={
                    "final_answer_max_tokens": 512,
                    "think": False,
                    "system_instruction": system_instruction,
                }
            )
            self._state("generating", "ollama", agent_key, None)
            turn = OllamaProvider().generate_turn(
                [AgentMessage(role="user", content=wrap_untrusted_payload(source))],
                [],
                agent,
            )
            briefing, insights = parse_model_output(turn.message.content or "")
            return SynthesisResult(
                briefing=briefing,
                insights=insights,
                provider="ollama",
                agent=agent_key,  # type: ignore[arg-type]
                warmup_ms=warmup_ms,
                generation_ms=int((time.monotonic() - started) * 1000),
                provider_ms=turn.provider_ms,
                resolved_model=turn.resolved_model or agent.api_model,
                usage=turn.usage,
                cost_estimate=estimate_inference_cost(
                    model=turn.resolved_model,
                    configured_model=agent.api_model,
                    provider="ollama",
                    usage=turn.usage,
                    hosted_tool_events=turn.provider_tool_events,
                ),
            )
        finally:
            end_local_execution()

    def _synthesize_explicit_local(
        self,
        source: SynthesisInput,
        agent_key: str,
        warmup: WarmupHandle | None,
    ) -> SynthesisResult:
        """Honor an explicitly selected local Agent; never silently substitute another."""
        resident = resident_agent_key()
        if resident == agent_key:
            try:
                result = self._ollama(source, agent_key, None)
                self._state("complete", result.provider, result.agent, None)
                return result
            except Exception as exc:
                reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
                return self._raw(source, reason)

        if warmup is None:
            warmup = self.start_agent_warmup(agent_key)
        elif warmup.agent_key != agent_key:
            # Caller prepared a different agent; switch to the selected one.
            warmup = self.start_agent_warmup(agent_key)

        if not warmup.event.wait(LOCAL_PRIMARY_GRACE_SECONDS):
            return self._raw(source, "local_warmup_timeout", warmup.elapsed_ms)
        if not warmup.success:
            return self._raw(
                source, warmup.reason or "local_warmup_failed", warmup.elapsed_ms
            )
        self._state("ready", "ollama", agent_key, None)
        try:
            result = self._ollama(source, agent_key, warmup.elapsed_ms)
            self._state("complete", result.provider, result.agent, None)
            return result
        except Exception as exc:
            reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
            return self._raw(source, reason, warmup.elapsed_ms)

    def _synthesize_panthera(self, source: SynthesisInput) -> SynthesisResult:
        """Route Panthera failure through Mus, Sorex, then Structured Digest."""
        fallback_steps: list[str] = []
        try:
            result = self._panthera(source)
            self._state("complete", result.provider, result.agent, None)
            return result
        except Exception as exc:
            _LOGGER.error(
                "Panthera briefing synthesis failed; falling back to local/raw. "
                "error_type=%s",
                type(exc).__name__,
            )
            reason = str(exc) if str(exc).startswith("openai_") else "openai_error"
            fallback_steps.append(f"panthera:{reason}")

        for agent_key in ("mus", "sorex"):
            result, local_reason = self._try_panthera_local_fallback(source, agent_key)
            if result is not None:
                fallback_steps.append(f"{agent_key}:resolved")
                result.fallback_reason = fallback_steps[0].split(":", 1)[1]
                result.fallback_steps = fallback_steps
                self._state(
                    "complete", result.provider, result.agent, result.fallback_reason
                )
                return result
            fallback_steps.append(f"{agent_key}:{local_reason}")
            reason = local_reason

        result = self._raw(source, reason)
        fallback_steps.append("structured_digest:resolved")
        result.fallback_steps = fallback_steps
        self._state("complete", result.provider, result.agent, reason)
        return result

    def _try_panthera_local_fallback(
        self, source: SynthesisInput, agent_key: str
    ) -> tuple[SynthesisResult | None, str]:
        """Attempt one ordered local fallback without substituting agents."""
        if resident_agent_key() == agent_key:
            try:
                return self._ollama(source, agent_key, None), ""
            except Exception as exc:
                return None, (
                    str(exc)
                    if str(exc).startswith("local_")
                    else "local_generation_failed"
                )

        warmup = self.start_agent_warmup(agent_key)
        if not warmup.event.wait(LOCAL_FALLBACK_GRACE_SECONDS):
            return None, "local_warmup_timeout"
        if not warmup.success:
            return None, warmup.reason or "local_warmup_failed"
        self._state("ready", "ollama", agent_key, None)
        try:
            return self._ollama(source, agent_key, warmup.elapsed_ms), ""
        except Exception as exc:
            return None, (
                str(exc)
                if str(exc).startswith("local_")
                else "local_generation_failed"
            )

    def synthesize_mode(
        self,
        source: SynthesisInput,
        mode: BriefingMode,
        warmup: WarmupHandle | None = None,
    ) -> SynthesisResult:
        if mode == "structured_digest":
            result = self._raw(source, "configured_raw")
            self._state("complete", result.provider, result.agent, result.fallback_reason)
            return result

        if mode == "panthera":
            return self._synthesize_panthera(source)

        if mode in LOCAL_BRIEFING_AGENTS:
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
