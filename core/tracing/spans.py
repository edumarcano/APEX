"""OpenTelemetry GenAI span helpers with strict privacy boundaries and failure isolation."""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Generator
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode, Tracer

from core.tracing.service import get_tracing_service

_LOGGER = logging.getLogger(__name__)


class RunSpanContext:
    """Mutable handle for updating the root invoke_agent span."""

    def __init__(self, span: Span, trace_id: str | None) -> None:
        self.span = span
        self.trace_id = trace_id

    def record_progress(
        self,
        *,
        resolved_model: str | None = None,
        provider: str | None = None,
        runtime: str | None = None,
        turns_count: int | None = None,
        tool_calls_count: int | None = None,
        retries_count: int | None = None,
        total_tokens: int | None = None,
        usage_quality: str | None = None,
        status: str | None = None,
        stop_reason: str | None = None,
        error_code: str | None = None,
    ) -> None:
        try:
            if resolved_model:
                self.span.set_attribute("gen_ai.response.model", resolved_model)
            if provider:
                self.span.set_attribute("apex.provider", provider)
            if runtime:
                self.span.set_attribute("apex.runtime", runtime)
            if turns_count is not None:
                self.span.set_attribute("apex.turns_count", turns_count)
            if tool_calls_count is not None:
                self.span.set_attribute("apex.tool_calls_count", tool_calls_count)
            if retries_count is not None:
                self.span.set_attribute("apex.retries_count", retries_count)
            if total_tokens is not None:
                self.span.set_attribute("apex.total_tokens", total_tokens)
            if usage_quality is not None:
                self.span.set_attribute("apex.usage_quality", usage_quality)
            if status is not None:
                self.span.set_attribute("apex.status", status)
                if status == "completed":
                    self.span.set_status(StatusCode.OK)
                elif status in {"failed", "cancelled", "interrupted"}:
                    self.span.set_status(
                        StatusCode.ERROR,
                        description=error_code or stop_reason or status,
                    )
            if stop_reason is not None:
                self.span.set_attribute("apex.stop_reason", stop_reason)
            if error_code is not None:
                self.span.set_attribute("apex.error_code", error_code)
        except Exception as exc:
            _LOGGER.debug("Failed to record span progress: %s", exc)

    def record_terminal(
        self,
        record: Any,
        *,
        error_code: str | None = None,
    ) -> None:
        """Record final metrics, status, and outcome from a terminal RunRecord."""
        err_code = error_code
        if err_code is None and getattr(record, "error", None) is not None:
            err_code = getattr(record.error, "code", None)
        self.record_progress(
            resolved_model=getattr(record, "resolved_model", None),
            provider=getattr(record, "provider", None),
            runtime=getattr(record, "runtime", None),
            turns_count=getattr(record, "turns_count", None),
            tool_calls_count=getattr(record, "tool_calls_count", None),
            retries_count=getattr(record, "retries_count", None),
            total_tokens=getattr(record, "total_tokens", None),
            usage_quality=getattr(record, "usage_quality", None),
            status=getattr(record, "status", None),
            stop_reason=getattr(record, "stop_reason", None),
            error_code=err_code,
        )


@contextlib.contextmanager
def trace_run(
    *,
    run_id: UUID,
    conversation_id: UUID,
    user_message_id: UUID,
    agent_message_id: UUID,
    requested_model: str,
    provider: str | None = None,
    runtime: str | None = None,
    limit_snapshot: Any = None,
) -> Generator[RunSpanContext, None, None]:
    """
    Context manager for the root `invoke_agent` span covering one Cortex run.

    Follows GenAI semantic conventions:
    - Span name: `invoke_agent`
    - Preserves zero-content privacy guarantee: NO prompts, answers, or raw exceptions.
    - Captures the 32-hex `trace_id` for durable record linkage.
    """
    tracer: Tracer = get_tracing_service().get_tracer("apex.cortex")
    span_cm = tracer.start_as_current_span(
        "invoke_agent",
        attributes={
            "gen_ai.system": "apex",
            "gen_ai.request.model": requested_model,
            "apex.run_id": str(run_id),
            "apex.conversation_id": str(conversation_id),
            "apex.user_message_id": str(user_message_id),
            "apex.agent_message_id": str(agent_message_id),
            **({"apex.provider": provider} if provider else {}),
            **({"apex.runtime": runtime} if runtime else {}),
        },
    )

    try:
        with span_cm as span:
            # Extract 32-hex trace ID if present
            trace_id_str: str | None = None
            try:
                span_ctx = span.get_span_context()
                if span_ctx.is_valid and span_ctx.trace_id:
                    trace_id_str = format(span_ctx.trace_id, "032x")
            except Exception:
                trace_id_str = None

            if limit_snapshot is not None:
                try:
                    span.set_attribute(
                        "apex.limit.max_elapsed_seconds",
                        limit_snapshot.max_elapsed_seconds,
                    )
                    span.set_attribute(
                        "apex.limit.max_total_tokens",
                        limit_snapshot.max_total_tokens,
                    )
                    span.set_attribute(
                        "apex.limit.max_retries",
                        limit_snapshot.max_retries,
                    )
                    span.set_attribute(
                        "apex.limit.max_model_turns",
                        limit_snapshot.max_model_turns,
                    )
                    span.set_attribute(
                        "apex.limit.max_tool_calls",
                        limit_snapshot.max_tool_calls,
                    )
                except Exception:
                    pass

            handle = RunSpanContext(span, trace_id_str)
            yield handle
    except Exception as exc:
        _LOGGER.debug("Exception inside trace_run context: %s", exc)
        raise


class ProviderTurnSpanContext:
    """Handle for updating the provider chat span."""

    def __init__(self, span: Span) -> None:
        self.span = span

    def record_result(self, result: Any) -> None:
        try:
            if getattr(result, "resolved_model", None):
                self.span.set_attribute("gen_ai.response.model", result.resolved_model)
            usage = getattr(result, "usage", None)
            if usage is not None:
                if usage.input_tokens is not None:
                    self.span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
                if usage.output_tokens is not None:
                    self.span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
            if getattr(result, "provider_ms", None) is not None:
                self.span.set_attribute("apex.provider_ms", result.provider_ms)
            measurements = getattr(result, "runtime_measurements", None)
            if measurements is not None:
                for attr in ("ttft_ms", "tokens_per_second", "eval_duration_ms"):
                    val = getattr(measurements, attr, None)
                    if val is not None:
                        self.span.set_attribute(f"apex.{attr}", val)
            self.span.set_status(StatusCode.OK)
        except Exception as exc:
            _LOGGER.debug("Failed to record provider turn result: %s", exc)


@contextlib.contextmanager
def trace_provider_turn(
    *,
    model: str,
    provider: str,
    turn: int,
) -> Generator[ProviderTurnSpanContext, None, None]:
    """Context manager for child provider chat span."""
    tracer: Tracer = get_tracing_service().get_tracer("apex.cortex.provider")
    span_cm = tracer.start_as_current_span(
        f"chat {model}",
        attributes={
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "apex.turn": turn,
        },
    )
    with span_cm as span:
        handle = ProviderTurnSpanContext(span)
        try:
            yield handle
        except Exception as exc:
            try:
                span.set_status(StatusCode.ERROR, description=type(exc).__name__)
            except Exception:
                pass
            raise


class ToolExecutionSpanContext:
    """Handle for updating the tool execution span."""

    def __init__(self, span: Span) -> None:
        self.span = span

    def record_completion(
        self,
        *,
        duration_ms: float,
        status: str,
        error_category: str | None = None,
        action_id: str | None = None,
        action_risk: str | None = None,
    ) -> None:
        try:
            self.span.set_attribute("apex.tool.duration_ms", duration_ms)
            self.span.set_attribute("apex.tool.status", status)
            if status == "ok":
                self.span.set_status(StatusCode.OK)
            else:
                self.span.set_status(
                    StatusCode.ERROR,
                    description=error_category or "tool_error",
                )
                if error_category:
                    self.span.set_attribute("apex.tool.error_category", error_category)
            if action_id:
                self.span.set_attribute("apex.action.id", action_id)
            if action_risk:
                self.span.set_attribute("apex.action.risk", action_risk)
        except Exception as exc:
            _LOGGER.debug("Failed to record tool execution span completion: %s", exc)


@contextlib.contextmanager
def trace_tool_execution(
    *,
    tool_name: str,
    origin: str = "apex",
) -> Generator[ToolExecutionSpanContext, None, None]:
    """
    Context manager for child tool execution span.

    Preserves privacy: NEVER records tool input arguments, target, or output content.
    """
    tracer: Tracer = get_tracing_service().get_tracer("apex.cortex.tools")
    span_cm = tracer.start_as_current_span(
        f"execute_tool {tool_name}",
        attributes={
            "gen_ai.tool.name": tool_name,
            "apex.tool.origin": origin,
        },
    )
    with span_cm as span:
        handle = ToolExecutionSpanContext(span)
        try:
            yield handle
        except Exception as exc:
            try:
                span.set_status(StatusCode.ERROR, description=type(exc).__name__)
            except Exception:
                pass
            raise
