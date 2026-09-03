"""Bounded in-process orchestration for durable Cortex runs."""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from core.agent.loop import ExecutionCancelled, ExecutionLimitReached
from core.agent.providers.contract import ProviderTurnResult
from core.runs.models import (
    RunCompletionEvidence,
    RunError,
    RunRecord,
    RunRuntimeMeasurements,
)
from core.runs.service import RunHandle, RunService

_coordinator: CortexRunCoordinator | None = None


def set_run_coordinator(coordinator: CortexRunCoordinator | None) -> None:
    global _coordinator
    _coordinator = coordinator


def get_run_coordinator() -> CortexRunCoordinator:
    if _coordinator is None:
        raise RuntimeError("Run coordinator is unavailable.")
    return _coordinator


class RunCapacityError(RuntimeError):
    """No worker slot is available for a new run."""


class ActiveConversationRunError(RuntimeError):
    """A different active run owns the requested conversation."""


@dataclass(slots=True)
class _ActiveRun:
    conversation_id: UUID
    cancel_event: threading.Event
    future: Future[Any] | None = None


class RunExecutionControl:
    """Checkpoint-only cancellation and cumulative accounting for one run."""

    def __init__(self, handle: RunHandle, cancel_event: threading.Event) -> None:
        self.handle = handle
        self.cancel_event = cancel_event
        self.started = time.monotonic()
        self.turns = 0
        self.tools = 0
        self.retries = 0
        self.tokens = 0
        self.usage_quality = "unavailable"

    def _elapsed(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def _check(self) -> None:
        if self.cancel_event.is_set():
            raise ExecutionCancelled()
        if self._elapsed() >= self.handle.get_record().limit_snapshot.max_elapsed_seconds:
            raise ExecutionLimitReached("max_elapsed_seconds")

    def _persist(self, *, provider_ms: float | None = None) -> None:
        measurements = RunRuntimeMeasurements(
            total_duration_ms=round(self._elapsed() * 1000, 2),
            eval_duration_ms=provider_ms,
        )
        self.handle.update_progress(
            turns_count=self.turns,
            tool_calls_count=self.tools,
            retries_count=self.retries,
            total_tokens=self.tokens,
            elapsed_seconds=self._elapsed(),
            usage_quality=self.usage_quality,  # type: ignore[arg-type]
            runtime_measurements=measurements,
        )

    def before_model_turn(self) -> None:
        self._check()
        if self.turns >= self.handle.get_record().limit_snapshot.max_model_turns:
            raise ExecutionLimitReached("max_model_turns")

    def after_model_turn(self, result: ProviderTurnResult) -> None:
        self.turns += 1
        self.retries += result.retry_count
        usage = result.usage
        if usage is not None and usage.total_tokens is not None:
            self.tokens += usage.total_tokens
            self.usage_quality = "reported"
        elif result.estimated_prompt_tokens is not None:
            self.tokens += result.estimated_prompt_tokens
            self.usage_quality = "estimated"
        self._persist(provider_ms=result.provider_ms)
        self._check()
        if self.retries > self.handle.get_record().limit_snapshot.max_retries:
            raise ExecutionLimitReached("max_retries")
        if self.tokens > self.handle.get_record().limit_snapshot.max_total_tokens:
            raise ExecutionLimitReached("max_total_tokens")

    def before_tool(self) -> None:
        self._check()
        if self.tools >= self.handle.get_record().limit_snapshot.max_tool_calls:
            raise ExecutionLimitReached("max_tool_calls")

    def after_tool(self) -> None:
        self.tools += 1
        self._persist()

    def finish(self) -> None:
        self._persist()


FinalizeConversation = Callable[[Any | None, str, str | None], Any]
ExecuteRun = Callable[[RunExecutionControl], Any]


class CortexRunCoordinator:
    """Own bounded worker admission and run lifecycle without an internal queue."""

    def __init__(self, service: RunService, *, max_workers: int) -> None:
        self.service = service
        self._slots = threading.BoundedSemaphore(max_workers)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="apex-run")
        self._lock = threading.RLock()
        self._active: dict[UUID, _ActiveRun] = {}

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def admit(self, *, conversation_id: UUID, agent_message_id: UUID) -> RunRecord | None:
        """Reserve capacity before durable conversation mutation, or return a replay."""
        with self._lock:
            existing = self.service.get_run_by_agent_message_id(agent_message_id)
            if existing is not None:
                return existing
            if conversation_id in (active.conversation_id for active in self._active.values()):
                raise ActiveConversationRunError()
            if self.service.has_active_runs(conversation_id):
                raise ActiveConversationRunError()
            if not self._slots.acquire(blocking=False):
                raise RunCapacityError()
            self._active[agent_message_id] = _ActiveRun(conversation_id, threading.Event())
            return None

    def abandon_admission(self, agent_message_id: UUID) -> None:
        with self._lock:
            if self._active.pop(agent_message_id, None) is not None:
                self._slots.release()

    def submit(
        self,
        *,
        handle: RunHandle,
        resolved_model: str,
        provider: str,
        runtime: str,
        execute: ExecuteRun,
        finalize_conversation: FinalizeConversation,
    ) -> Future[Any]:
        """Submit a previously admitted run; submission failure releases its slot."""
        with self._lock:
            active = self._active.get(handle.run_id)
            if active is None:
                # Admission uses the agent message id until the durable handle exists.
                active = self._active.pop(handle.get_record().agent_message_id, None)
                if active is None:
                    raise RuntimeError("Run was not admitted.")
                self._active[handle.run_id] = active
            try:
                future = self._executor.submit(
                    self._run, handle, resolved_model, provider, runtime, active, execute, finalize_conversation
                )
            except Exception:
                self._active.pop(handle.run_id, None)
                self._slots.release()
                raise
            active.future = future
            return future

    def cancel(self, run_id: UUID) -> RunRecord:
        handle = self.service.get_handle(run_id)
        record = handle.set_cancelling()
        with self._lock:
            active = self._active.get(run_id)
            if active is not None:
                active.cancel_event.set()
        return record

    def future_for(self, run_id: UUID) -> Future[Any] | None:
        """Return the in-process future when this process owns the active run."""
        with self._lock:
            active = self._active.get(run_id)
            return active.future if active is not None else None

    def _run(
        self,
        handle: RunHandle,
        resolved_model: str,
        provider: str,
        runtime: str,
        active: _ActiveRun,
        execute: ExecuteRun,
        finalize_conversation: FinalizeConversation,
    ) -> Any:
        control = RunExecutionControl(handle, active.cancel_event)
        try:
            if active.cancel_event.is_set() or handle.get_record().status == "cancelling":
                raise ExecutionCancelled()
            handle.start(resolved_model=resolved_model, provider=provider, runtime=runtime)
            response = execute(control)
            control.finish()
            message_status = "failed" if getattr(response, "error", None) else "completed"
            conversation = finalize_conversation(response, message_status, None)
            evidence = RunCompletionEvidence(
                final_message_status=conversation.status,
                answer_persisted=conversation.status == "completed",
                tool_outcome_counts=_tool_outcomes(response),
                action_ids=_action_ids(response),
            )
            return handle.finalize(
                status="completed" if conversation.status == "completed" else "failed",
                stop_reason="end_turn" if conversation.status == "completed" else "provider_error",
                evidence=evidence,
                error=None if conversation.status == "completed" else RunError(code="provider_error"),
            )
        except ExecutionCancelled:
            return self._finalize_stopped(handle, control, finalize_conversation, "cancelled", "operator_cancelled", "operator_cancelled")
        except ExecutionLimitReached as exc:
            code = {"max_elapsed_seconds": "timeout", "max_total_tokens": "token_limit", "max_model_turns": "turn_limit", "max_tool_calls": "tool_limit", "max_retries": "retry_limit"}[exc.reason]
            return self._finalize_stopped(handle, control, finalize_conversation, "failed", exc.reason, code)
        except Exception:
            return self._finalize_stopped(handle, control, finalize_conversation, "failed", "internal_error", "internal_error")
        finally:
            with self._lock:
                self._active.pop(handle.run_id, None)
                self._slots.release()

    @staticmethod
    def _finalize_stopped(handle: RunHandle, control: RunExecutionControl, finalize_conversation: FinalizeConversation, status: str, reason: str, error_code: str) -> RunRecord:
        try:
            control.finish()
        except Exception:
            pass
        conversation = finalize_conversation(None, "interrupted" if status == "cancelled" else "failed", error_code)
        return handle.finalize(
            status=status,  # type: ignore[arg-type]
            stop_reason=reason,  # type: ignore[arg-type]
            evidence=RunCompletionEvidence(final_message_status=conversation.status, answer_persisted=False),
            error=RunError(code=error_code),  # type: ignore[arg-type]
        )


def _tool_outcomes(response: Any) -> dict[str, int]:
    outcomes: dict[str, int] = {}
    for item in getattr(response, "tool_trace", []):
        key = str(item.get("status", "unknown"))
        outcomes[key] = outcomes.get(key, 0) + 1
    return outcomes


def _action_ids(response: Any) -> list[str]:
    ids: list[str] = []
    for item in getattr(response, "tool_outputs", []):
        output = item.get("output") if isinstance(item, dict) else None
        if isinstance(output, dict) and isinstance(output.get("action_id"), str):
            ids.append(output["action_id"])
    return ids
