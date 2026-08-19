from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from core.agent.pricing import estimate_inference_cost
from core.agent.catalog import (
    AGENT_SPECS,
    agent_key_for_local_model_ref,
    build_concrete_agent,
    compose_agent_system_instruction,
    local_model_refs_for_model,
    resolve_selected_model_profile,
)
from core.agent.model_catalog import (
    DEFAULT_FELIS_MODEL,
    PANTHERA_BRIEFING_MODEL,
    get_model_profile,
)
from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.openrouter import OpenRouterProvider
from core.agent.local_runtime.contract import LocalModelRef
from core.agent.local_runtime.coordinator import (
    check_resource_gate,
    end_local_execution,
    get_active_local_model,
    get_provider_snapshot,
    is_local_model_ready,
    switch_local_model,
    try_begin_local_execution,
)
from core.agent.local_runtime.registry import (
    get_local_runtime_backend,
    iter_local_runtime_backends,
)
from core.agent.providers.llama_cpp import LlamaCppProvider
from core.agent.providers.llama_cpp_models import (
    llama_cpp_context_window_for_runtime_model_id,
)
from core.agent.types import AgentMessage, LocalReasoningMode
from core.config import (
    LOCAL_FALLBACK_GRACE_SECONDS,
    LOCAL_PRIMARY_GRACE_SECONDS,
    PRIMARY_SYNTHESIS_PROMPT,
)
from core.synthesis.formatting import (
    deterministic_fallback,
    parse_model_output,
    wrap_untrusted_payload,
)
from core.synthesis.models import (
    FELIS_BRIEFING_CONTEXT_WINDOW,
    LOCAL_BRIEFING_AGENTS,
    BriefingMode,
    SynthesisInput,
    SynthesisResult,
    strategy_to_briefing_mode,
)
from core.settings import get_settings_store

_LOGGER = logging.getLogger(__name__)

_LOCAL_SYNTHESIS_FINAL_ANSWER_MAX_TOKENS = 512
_FELIS_BRIEFING_MODEL = DEFAULT_FELIS_MODEL
_PANTHERA_BRIEFING_MODEL = PANTHERA_BRIEFING_MODEL


StateCallback = Callable[[str, str | None, str | None, str | None], None]


@dataclass
class WarmupHandle:
    agent_key: str = "felis"
    model_ref: LocalModelRef | None = None
    event: threading.Event = field(default_factory=threading.Event)
    success: bool = False
    reason: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None

    @property
    def elapsed_ms(self) -> int | None:
        end = self.finished_at
        return int(((end or time.monotonic()) - self.started_at) * 1000)


def resident_local_model_ref() -> LocalModelRef | None:
    """Return the provider-qualified resident APEX model, when one is known."""
    return get_active_local_model()


def resident_agent_key() -> str | None:
    tracked = resident_local_model_ref()
    return agent_key_for_local_model_ref(tracked) if tracked is not None else None


def _resident_felis_briefing_model() -> LocalModelRef | None:
    """Return the resident fixed Felis briefing model, when it is loaded."""
    resident = resident_local_model_ref()
    if resident is None:
        return None
    return (
        resident
        if resident in local_model_refs_for_model(_FELIS_BRIEFING_MODEL)
        else None
    )


def _felis_briefing_provider() -> str:
    """Return the provider for Felis's fixed briefing model."""
    profile = get_model_profile(_FELIS_BRIEFING_MODEL)
    if profile is None:
        raise RuntimeError("felis_briefing_model_invalid")
    return profile.provider


def _briefing_provider_for_agent(agent_key: str) -> str:
    if agent_key == "felis":
        return _felis_briefing_provider()
    return resolve_selected_model_profile(agent_key).provider


def _has_unrecognized_resident_model() -> bool:
    """Return whether an enabled local backend reports an unknown resident model."""
    for backend in iter_local_runtime_backends(enabled_only=True):
        snapshot = get_provider_snapshot(backend.provider)
        if not snapshot["reachable"]:
            continue
        for model in snapshot["loaded_models"]:
            if model["state"] != "loaded":
                continue
            recognized = any(
                agent_key_for_local_model_ref(
                    LocalModelRef(provider=backend.provider, model=value)
                )
                is not None
                for value in (model["model"], model["name"])
            )
            if not recognized:
                return True
    return False


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

    def start_agent_warmup(
        self,
        agent_key: str,
        *,
        context_window: int | None = None,
        reasoning_mode: LocalReasoningMode | None = None,
    ) -> WarmupHandle:
        handle = WarmupHandle(agent_key=agent_key)
        if agent_key not in LOCAL_BRIEFING_AGENTS:
            handle.reason = "local_agent_invalid"
            handle.finished_at = time.monotonic()
            handle.event.set()
            return handle
        if agent_key == "felis":
            context_window = context_window or FELIS_BRIEFING_CONTEXT_WINDOW
            reasoning_mode = reasoning_mode or "none"
        try:
            agent = build_concrete_agent(
                agent_key,
                native_effort=None,
                local_context_window=context_window,
                local_reasoning_mode=reasoning_mode,
                model_id=_FELIS_BRIEFING_MODEL if agent_key == "felis" else None,
            )
            backend = get_local_runtime_backend(agent.provider)
        except Exception:
            handle.reason = "local_warmup_failed"
            handle.finished_at = time.monotonic()
            handle.event.set()
            return handle
        if not backend.enabled:
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

        self._state("loading", agent.provider, agent_key, None)

        def worker() -> None:
            try:
                snapshot = get_provider_snapshot(agent.provider)
                if not snapshot["reachable"]:
                    handle.reason = "local_unreachable"
                    return
                if agent.runtime_model_id not in snapshot["installed_models"]:
                    handle.reason = "local_model_missing"
                    return
                model_ref = LocalModelRef(
                    provider=agent.provider, model=agent.runtime_model_id
                )
                handle.model_ref = model_ref
                if not is_local_model_ready(model_ref):
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

    def prepare(self, strategy: str) -> WarmupHandle | None:
        mode = strategy_to_briefing_mode(strategy)
        return self.prepare_mode(mode)

    def prepare_mode(self, mode: BriefingMode) -> WarmupHandle | None:
        if mode == "structured_digest" or mode == "panthera":
            return None
        if mode not in LOCAL_BRIEFING_AGENTS:
            return None
        resident_ref = _resident_felis_briefing_model() if mode == "felis" else None
        if resident_ref is not None:
            self._state(
                "ready",
                _felis_briefing_provider(),
                mode,
                None,
            )
            return None
        # Explicit local selection warms the selected Agent.
        if mode == "felis":
            return self.start_agent_warmup(
                mode,
                context_window=FELIS_BRIEFING_CONTEXT_WINDOW,
                reasoning_mode="none",
            )
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

    def _structured_digest_fallback(
        self,
        source: SynthesisInput,
        reason: str,
        warmup_ms: int | None = None,
    ) -> SynthesisResult:
        result = self._raw(source, reason, warmup_ms)
        result.fallback_steps = ["structured_digest:resolved"]
        return result

    def _panthera(self, source: SynthesisInput) -> SynthesisResult:
        """Synthesize with the fixed-None Panthera briefing agent."""
        import os

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("openrouter_unavailable")
        agent = build_concrete_agent(
            "panthera",
            native_effort="none",
            model_id=_PANTHERA_BRIEFING_MODEL,
        )
        self._state("generating", "openrouter", "panthera", None)
        turn = OpenRouterProvider(api_key).generate_turn(
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
            provider="openrouter",
            agent="panthera",
            generation_ms=round(turn.provider_ms) if turn.provider_ms is not None else None,
            provider_ms=turn.provider_ms,
            resolved_model=turn.resolved_model or agent.api_model,
            usage=turn.usage,
            cost_estimate=estimate_inference_cost(
                model=turn.resolved_model,
                configured_model=agent.api_model,
                provider="openrouter",
                usage=turn.usage,
                hosted_tool_events=turn.provider_tool_events,
            ),
        )

    def _local_profile_for_synthesis(
        self,
        agent_key: str,
        *,
        resident_ref: LocalModelRef | None = None,
    ):
        """Build the provider profile for a local briefing Agent."""
        context_window: int | None = None
        if AGENT_SPECS[agent_key].runtime == "local":
            context_window = FELIS_BRIEFING_CONTEXT_WINDOW
            if resident_ref is not None and resident_ref.provider == "llama_cpp":
                model_id = (
                    _FELIS_BRIEFING_MODEL
                    if agent_key == "felis"
                    else resolve_selected_model_profile(agent_key).model_id
                )
                context_window = (
                    llama_cpp_context_window_for_runtime_model_id(
                        model_id, resident_ref.model
                    )
                    or context_window
                )
        user_designation = get_settings_store().get_snapshot().user_designation
        system_instruction = compose_agent_system_instruction(
            agent_key,
            PRIMARY_SYNTHESIS_PROMPT,
            user_designation=user_designation,
        )
        return build_concrete_agent(
            agent_key,
            native_effort=None,
            local_context_window=context_window,
            local_reasoning_mode="none",
            model_id=_FELIS_BRIEFING_MODEL if agent_key == "felis" else None,
        ).model_copy(
            update={
                "final_answer_max_tokens": _LOCAL_SYNTHESIS_FINAL_ANSWER_MAX_TOKENS,
                "system_instruction": system_instruction,
            }
        )

    def _local(
        self,
        source: SynthesisInput,
        agent_key: str,
        warmup_ms: int | None,
        *,
        resident_ref: LocalModelRef | None = None,
    ) -> SynthesisResult:
        if not try_begin_local_execution():
            raise RuntimeError("local_busy")
        started = time.monotonic()
        try:
            effective_ref = resident_ref or resident_local_model_ref()
            agent = self._local_profile_for_synthesis(
                agent_key, resident_ref=effective_ref
            )
            if agent.provider == "ollama":
                provider = OllamaProvider()
            elif agent.provider == "llama_cpp":
                provider = LlamaCppProvider()
            else:
                raise RuntimeError("local_provider_invalid")
            self._state("generating", agent.provider, agent_key, None)
            turn = provider.generate_turn(
                [AgentMessage(role="user", content=wrap_untrusted_payload(source))],
                [],
                agent,
            )
            briefing, insights = parse_model_output(turn.message.content or "")
            return SynthesisResult(
                briefing=briefing,
                insights=insights,
                provider=agent.provider,  # type: ignore[arg-type]
                agent=agent_key,  # type: ignore[arg-type]
                warmup_ms=warmup_ms,
                generation_ms=int((time.monotonic() - started) * 1000),
                provider_ms=turn.provider_ms,
                resolved_model=turn.resolved_model or agent.api_model,
                usage=turn.usage,
                cost_estimate=estimate_inference_cost(
                    model=turn.resolved_model,
                    configured_model=agent.api_model,
                    provider=agent.provider,
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
        resident_ref = (
            _resident_felis_briefing_model() if agent_key == "felis" else None
        )
        if resident_ref is not None:
            try:
                result = self._local(
                    source,
                    agent_key,
                    None,
                    resident_ref=resident_ref,
                )
                self._state("complete", result.provider, result.agent, None)
                return result
            except Exception as exc:
                reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
                return self._structured_digest_fallback(source, reason)

        if warmup is None:
            warmup = self.start_agent_warmup(agent_key)
        elif warmup.agent_key != agent_key:
            # Caller prepared a different agent; switch to the selected one.
            warmup = self.start_agent_warmup(agent_key)

        if not warmup.event.wait(LOCAL_PRIMARY_GRACE_SECONDS):
            return self._structured_digest_fallback(
                source, "local_warmup_timeout", warmup.elapsed_ms
            )
        if not warmup.success:
            return self._structured_digest_fallback(
                source, warmup.reason or "local_warmup_failed", warmup.elapsed_ms
            )
        self._state(
            "ready",
            _briefing_provider_for_agent(agent_key),
            agent_key,
            None,
        )
        try:
            result = self._local(
                source,
                agent_key,
                warmup.elapsed_ms,
                resident_ref=warmup.model_ref,
            )
            self._state("complete", result.provider, result.agent, None)
            return result
        except Exception as exc:
            reason = str(exc) if str(exc).startswith("local_") else "local_generation_failed"
            return self._structured_digest_fallback(source, reason, warmup.elapsed_ms)

    def _synthesize_panthera(self, source: SynthesisInput) -> SynthesisResult:
        """Route Panthera failure through Felis, then Structured Digest."""
        fallback_steps: list[str] = []
        try:
            result = self._panthera(source)
            self._state("complete", result.provider, result.agent, None)
            return result
        except Exception as exc:
            _LOGGER.error(
                "Panthera briefing synthesis failed; falling back to Felis/Structured Digest. "
                "error_type=%s",
                type(exc).__name__,
            )
            reason = (
                str(exc)
                if str(exc).startswith("openrouter_")
                else "openrouter_error"
            )
            fallback_steps.append(f"panthera:{reason}")

        for agent_key in ("felis",):
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
        resident_ref = (
            _resident_felis_briefing_model() if agent_key == "felis" else None
        )
        if resident_ref is not None:
            try:
                return (
                    self._local(
                        source,
                        agent_key,
                        None,
                        resident_ref=resident_ref,
                    ),
                    "",
                )
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
        self._state(
            "ready",
            _briefing_provider_for_agent(agent_key),
            agent_key,
            None,
        )
        try:
            return (
                self._local(
                    source,
                    agent_key,
                    warmup.elapsed_ms,
                    resident_ref=warmup.model_ref,
                ),
                "",
            )
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
