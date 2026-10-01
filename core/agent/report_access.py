"""Execution-scoped privacy and partition policy for report reads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

from core.agent.capabilities import CapabilityError, CapabilityErrorCategory
from core.settings import get_settings_store


@dataclass(frozen=True, slots=True)
class ReportReadExecutionContext:
    """Trusted inputs captured when one Cortex Agent turn is admitted."""

    partition: str
    model_id: str
    permitted: bool


_REPORT_READ_CONTEXT: ContextVar[ReportReadExecutionContext | None] = ContextVar(
    "apex_report_read_context", default=None
)


@contextmanager
def bind_report_read_context(
    context: ReportReadExecutionContext,
) -> Iterator[None]:
    """Bind report access to one Agent turn and always restore the caller state."""
    token: Token[ReportReadExecutionContext | None] = _REPORT_READ_CONTEXT.set(context)
    try:
        yield
    finally:
        _REPORT_READ_CONTEXT.reset(token)


def report_read_availability(
    *, model_id: str, partition: str
) -> tuple[bool, str | None]:
    """Return whether report reads are currently allowed without touching SQLite."""
    from core.config import DEMO_MODE, is_dev_mode

    if DEMO_MODE:
        return False, "Report access is unavailable in demo mode."
    if is_dev_mode():
        return False, "Report access is unavailable in development mode."
    if partition != "production":
        return False, "Report access is unavailable for this conversation."

    from core.agent.model_catalog import get_model_profile

    model = get_model_profile(model_id)
    if model is None:
        return False, "Report access is unavailable for this model."

    try:
        settings = get_settings_store().get_snapshot().ask_apex
        runtime_settings = (
            settings.local if model.runtime == "local" else settings.cloud
        )
        if not runtime_settings.personal_context_enabled:
            return False, "Enable personal context for this model to read reports."
    except Exception:
        return False, "Report access is unavailable while settings are unavailable."

    try:
        # The getter checks only whether the process singleton was installed; it
        # performs no report or database read.
        from core.activity.service import get_activity_service

        get_activity_service()
    except Exception:
        return False, "Report storage is unavailable."

    return True, None


def make_report_read_context(
    *, model_id: str, partition: str
) -> ReportReadExecutionContext:
    permitted, _reason = report_read_availability(
        model_id=model_id, partition=partition
    )
    return ReportReadExecutionContext(
        partition=partition,
        model_id=model_id,
        permitted=permitted,
    )


def require_report_read_context() -> ReportReadExecutionContext:
    """Return the admitted context after enforcing its frozen and live policy."""
    context = _REPORT_READ_CONTEXT.get()
    if context is None or not context.permitted:
        raise CapabilityError(
            CapabilityErrorCategory.UNAVAILABLE,
            "Report access is unavailable.",
        )

    permitted, _reason = report_read_availability(
        model_id=context.model_id,
        partition=context.partition,
    )
    if not permitted:
        raise CapabilityError(
            CapabilityErrorCategory.UNAVAILABLE,
            "Report access is unavailable.",
        )
    return context
