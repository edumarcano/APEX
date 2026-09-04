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
from core.config import CORTEX_RUNS_EVENT_REPLAY_LIMIT
from core.runs.events import RunEventRegistry
from core.runs.models import (
    RunCompletionEvidence,
    RunError,
    RunErrorCode,
    RunRecord,
    RunRuntimeMeasurements,
    RunStopReason,
    UsageQuality,
)
from core.runs.service import RunHandle, RunService
from core.runs.store import RunConflictError
from core.tracing import trace_run

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


class RunHttpError(RuntimeError):
    """A request error that the synchronous route must re-raise."""

    def __init__(self, *, status_code: int, detail: Any) -> None:
        super().__init__(str(status_code))
        self.status_code = status_code
        self.detail = detail


@dataclass(slots=True)
class _ActiveRun:
    conversation_id: UUID
    cancel_event: threading.Event
    future: Future[Any] | None = None
    admitted_at: float | None = None


class RunExecutionControl:
    """Checkpoint-only cancellation and cumulative accounting for one run."""

    def __init__(
        self,
        handle: RunHandle,
        cancel_event: threading.Event,
        event_sink: Callable[[str, dict[str, Any], RunRecord | None], None] | None = None,
        *,
        queue_duration_ms: float | None = None,
    ) -> None:
        self.handle = handle
        self.cancel_event = cancel_event
        self.limits = handle.get_record().limit_snapshot
        self.started = time.monotonic()
        self.turns = 0
        self.tools = 0
        self.retries = 0
        self.tokens = 0
        self.usage_quality: UsageQuality = "unavailable"
        self.runtime_measurements = RunRuntimeMeasurements(
            queue_duration_ms=queue_duration_ms
        )
        self._turn_retry_count = 0
        self._event_sink = event_sink

    def publish_activity(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        record: RunRecord | None = None,
    ) -> None:
        """Forward a loop-owned safe activity event to the live run stream."""
        if self._event_sink is not None:
            self._event_sink(event_type, payload, record)

    def observe_provider_stream(self, event: Any) -> None:
        """Translate the intentionally small provider stream contract."""
        if event.kind == "text" and event.text:
            self.publish_activity("response.delta", {"text": event.text})
        elif event.kind == "reset":
            self.publish_activity("response.reset", {})

    def _elapsed(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def _check(self) -> None:
        if self.cancel_event.is_set():
            raise ExecutionCancelled()
        if self._elapsed() >= self.limits.max_elapsed_seconds:
            raise ExecutionLimitReached("max_elapsed_seconds")

    def remaining_seconds(self) -> float:
        """Return the run deadline remaining for provider timeout capping."""
        return max(0.0, self.limits.max_elapsed_seconds - (time.monotonic() - self.started))

    def before_provider_attempt(self) -> None:
        self._check()

    def before_retry(self, _retry_number: int = 0) -> None:
        self._check()
        self.retries += 1
        self._turn_retry_count += 1
        if self.retries > self.limits.max_retries:
            raise ExecutionLimitReached("max_retries")
        self._persist()

    def wait_retry(self, delay: float) -> None:
        """Wait cooperatively, converting deadline/cancel stops to run errors."""
        self._check()
        if delay >= self.remaining_seconds():
            raise ExecutionLimitReached("max_elapsed_seconds")
        self.cancel_event.wait(delay)
        self._check()

    def _persist(self, *, provider_ms: float | None = None) -> None:
        measurement_updates: dict[str, float] = {
            "total_duration_ms": round(self._elapsed() * 1000, 2),
        }
        if provider_ms is not None and self.runtime_measurements.eval_duration_ms is None:
            measurement_updates["eval_duration_ms"] = round(
                (self.runtime_measurements.eval_duration_ms or 0.0) + provider_ms,
                2,
            )
        self.runtime_measurements = self.runtime_measurements.model_copy(
            update=measurement_updates
        )
        record = self.handle.update_progress(
            turns_count=self.turns,
            tool_calls_count=self.tools,
            retries_count=self.retries,
            total_tokens=self.tokens,
            elapsed_seconds=self._elapsed(),
            usage_quality=self.usage_quality,
            runtime_measurements=self.runtime_measurements,
        )
        if record is not None:
            self.publish_activity(
                "usage.updated",
                {
                    "total_tokens": record.total_tokens,
                    "usage_quality": record.usage_quality,
                    "retries_count": record.retries_count,
                },
                record=record,
            )
            self.publish_activity(
                "runtime.updated",
                {"runtime_measurements": record.runtime_measurements.model_dump(mode="json")},
                record=record,
            )

    def before_model_turn(self) -> None:
        self._check()
        self._turn_retry_count = 0
        if self.turns >= self.limits.max_model_turns:
            raise ExecutionLimitReached("max_model_turns")

    def after_model_turn(self, result: ProviderTurnResult) -> None:
        self.turns += 1
        # Provider adapters that receive this control charge retries before
        # waiting.  Legacy adapters still report their count here.
        self.retries += max(0, result.retry_count - self._turn_retry_count)
        usage = result.usage
        if usage is not None and usage.total_tokens is not None:
            self.tokens += usage.total_tokens
            if self.usage_quality == "unavailable":
                self.usage_quality = "reported"
        elif result.estimated_prompt_tokens is not None:
            self.tokens += result.estimated_prompt_tokens
            self.usage_quality = "estimated"

        measurements = (
            result.runtime_measurements.model_dump(exclude_none=True)
            if result.runtime_measurements
            else {}
        )
        ttft_ms = measurements.get("ttft_ms")
        eval_ms = measurements.get("eval_duration_ms")
        provider_ms = result.provider_ms or 0.0
        if eval_ms is None and isinstance(ttft_ms, (int, float)) and provider_ms > ttft_ms:
            eval_ms = round(provider_ms - ttft_ms, 2)
        elif eval_ms is None and provider_ms > 0:
            eval_ms = round(provider_ms, 2)
        if eval_ms is not None and "eval_duration_ms" not in measurements:
            measurements["eval_duration_ms"] = eval_ms

        eval_count = measurements.get("eval_count")
        if eval_count is None and usage and usage.output_tokens is not None:
            eval_count = usage.output_tokens
            measurements["eval_count"] = eval_count

        if "tokens_per_second" not in measurements:
            if (
                isinstance(eval_count, (int, float))
                and eval_count > 0
                and isinstance(eval_ms, (int, float))
                and eval_ms > 0
            ):
                measurements["tokens_per_second"] = round(
                    float(eval_count) / (float(eval_ms) / 1000.0), 2
                )

        if "prompt_eval_count" not in measurements and usage and usage.input_tokens is not None:
            measurements["prompt_eval_count"] = usage.input_tokens
        if "prompt_eval_duration_ms" not in measurements and isinstance(ttft_ms, (int, float)) and ttft_ms > 0:
            measurements["prompt_eval_duration_ms"] = ttft_ms

        allowed = set(RunRuntimeMeasurements.model_fields)
        updates = {
            key: value
            for key, value in measurements.items()
            if key in allowed
            and key != "total_duration_ms"
            and isinstance(value, (int, float))
            and value >= 0
        }
        if updates:
            self.runtime_measurements = self.runtime_measurements.model_copy(update=updates)

        self._persist(provider_ms=result.provider_ms)
        self._check()
        if self.retries > self.limits.max_retries:
            raise ExecutionLimitReached("max_retries")
        if self.tokens > self.limits.max_total_tokens:
            raise ExecutionLimitReached("max_total_tokens")

    def before_tool(self) -> None:
        self._check()
        if self.tools >= self.limits.max_tool_calls:
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
        self.events = RunEventRegistry(replay_limit=CORTEX_RUNS_EVENT_REPLAY_LIMIT)

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
            self._active[agent_message_id] = _ActiveRun(
                conversation_id, threading.Event(), admitted_at=time.perf_counter()
            )
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
                self.events.start(handle.get_record())
                future = self._executor.submit(
                    self._run, handle, resolved_model, provider, runtime, active, execute, finalize_conversation
                )
            except Exception:
                self._active.pop(handle.run_id, None)
                self.events.discard(handle.run_id)
                self._slots.release()
                raise
            active.future = future
            return future

    def cancel(self, run_id: UUID) -> RunRecord:
        with self._lock:
            handle = self.service.get_handle(run_id)
            record = handle.set_cancelling()
            self.events.publish(
                run_id,
                "run.status",
                {"status": record.status},
                record=record,
            )
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
        initial_record = handle.get_record()
        with trace_run(
            run_id=handle.run_id,
            conversation_id=initial_record.conversation_id,
            user_message_id=initial_record.user_message_id,
            agent_message_id=initial_record.agent_message_id,
            requested_model=initial_record.requested_model,
            provider=provider,
            runtime=runtime,
            limit_snapshot=initial_record.limit_snapshot,
        ) as span_context:
            trace_id = span_context.trace_id
            queue_duration_ms = (
                round((time.perf_counter() - active.admitted_at) * 1000, 2)
                if active.admitted_at is not None
                else None
            )
            control = RunExecutionControl(
                handle,
                active.cancel_event,
                lambda event_type, payload, record=None: self.events.publish(
                    handle.run_id,
                    event_type,
                    payload,
                    record=record,
                ),
                queue_duration_ms=queue_duration_ms,
            )
            try:
                with self._lock:
                    if active.cancel_event.is_set() or handle.get_record().status == "cancelling":
                        raise ExecutionCancelled()
                    try:
                        record = handle.start(
                            resolved_model=resolved_model,
                            provider=provider,
                            runtime=runtime,
                            trace_id=trace_id,
                        )
                        if queue_duration_ms is not None:
                            record = handle.update_progress(
                                runtime_measurements=control.runtime_measurements,
                            ) or record
                        self.events.publish(
                            handle.run_id,
                            "run.status",
                            {"status": record.status},
                            record=record,
                        )
                        if queue_duration_ms is not None:
                            self.events.publish(
                                handle.run_id,
                                "runtime.updated",
                                {"runtime_measurements": record.runtime_measurements.model_dump(mode="json")},
                                record=record,
                            )
                    except RunConflictError:
                        if handle.get_record().status == "cancelling":
                            raise ExecutionCancelled() from None
                        raise
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
                record = handle.finalize(
                    status="completed" if conversation.status == "completed" else "failed",
                    stop_reason="end_turn" if conversation.status == "completed" else "provider_error",
                    evidence=evidence,
                    error=None if conversation.status == "completed" else RunError(code="provider_error"),
                )
                self._publish_terminal(record)
                span_context.record_terminal(record)
                return record
            except ExecutionCancelled:
                record = self._finalize_stopped(handle, control, finalize_conversation, "cancelled", "operator_cancelled", "operator_cancelled")
                span_context.record_terminal(record, error_code="operator_cancelled")
                return record
            except ExecutionLimitReached as exc:
                code = {"max_elapsed_seconds": "timeout", "max_total_tokens": "token_limit", "max_model_turns": "turn_limit", "max_tool_calls": "tool_limit", "max_retries": "retry_limit"}[exc.reason]
                record = self._finalize_stopped(handle, control, finalize_conversation, "failed", exc.reason, code)
                span_context.record_terminal(record, error_code=code)
                return record
            except RunHttpError as exc:
                stop_reason, error_code = _http_failure_mapping(exc.status_code)
                record = self._finalize_stopped(
                    handle,
                    control,
                    finalize_conversation,
                    "failed",
                    stop_reason,
                    error_code,
                )
                span_context.record_terminal(record, error_code=error_code)
                raise
            except Exception:
                record = self._finalize_stopped(handle, control, finalize_conversation, "failed", "internal_error", "internal_error")
                span_context.record_terminal(record, error_code="internal_error")
                return record
            finally:
                with self._lock:
                    self._active.pop(handle.run_id, None)
                    self._slots.release()

    def _finalize_stopped(self, handle: RunHandle, control: RunExecutionControl, finalize_conversation: FinalizeConversation, status: str, reason: RunStopReason, error_code: RunErrorCode) -> RunRecord:
        try:
            control.finish()
        except Exception:
            pass
        conversation = finalize_conversation(None, "interrupted" if status == "cancelled" else "failed", error_code)
        record = handle.finalize(
            status=status,  # type: ignore[arg-type]
            stop_reason=reason,  # type: ignore[arg-type]
            evidence=RunCompletionEvidence(final_message_status=conversation.status, answer_persisted=False),
            error=RunError(code=error_code),  # type: ignore[arg-type]
        )
        self._publish_terminal(record)
        return record

    def _publish_terminal(self, record: RunRecord) -> None:
        if record.status != "completed":
            # A stopped run never leaves provisional provider text presented as
            # a completed conversation answer.
            self.events.publish(record.id, "response.reset", {}, record=record)
        self.events.publish(
            record.id,
            "run.completed",
            {
                "status": record.status,
                "stop_reason": record.stop_reason,
                "error": record.error.model_dump(mode="json") if record.error else None,
            },
            record=record,
        )
        self.events.complete(record.id, record)


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


def _http_failure_mapping(status_code: int) -> tuple[RunStopReason, RunErrorCode]:
    """Map request/runtime HTTP failures without persisting their details."""
    if status_code == 429:
        return "resource_exhaustion", "resource_exhaustion"
    if status_code >= 500:
        return "provider_error", "provider_unavailable"
    return "internal_error", "internal_error"
