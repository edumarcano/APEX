"""Partition-aware application service for Cortex runs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from core.config import is_dev_mode
from core.runs.models import (
    RunCompletionEvidence,
    RunError,
    RunLimitSnapshot,
    RunPartition,
    RunRecord,
    RunStatus,
    RunStopReason,
    UsageQuality,
)
from core.runs.store import RunStore
from core.settings import get_settings_store

_service: RunService | None = None


def set_run_service(service: RunService | None) -> None:
    """Register the global RunService instance."""
    global _service
    _service = service


def get_run_service() -> RunService:
    """Retrieve the global RunService instance."""
    if _service is None:
        raise RuntimeError("Run service is unavailable.")
    return _service


class RunService:
    """Partition-aware application service wrapping RunStore."""

    def __init__(self, store: RunStore) -> None:
        self.store = store

    @staticmethod
    def partition() -> RunPartition:
        """Resolve current partition ('production' vs 'sandbox') based on settings."""
        sandbox = (
            is_dev_mode()
            and get_settings_store().get_snapshot().ask_apex.sandbox_mode
        )
        return "sandbox" if sandbox else "production"

    def create_run(
        self,
        *,
        run_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID,
        agent_message_id: UUID,
        requested_model: str,
        limit_snapshot: RunLimitSnapshot,
        trace_id: str | None = None,
    ) -> tuple[RunRecord, bool]:
        """Create a run or return existing idempotent run record."""
        return self.store.create_run(
            run_id=run_id,
            conversation_id=conversation_id,
            partition=self.partition(),
            user_message_id=user_message_id,
            agent_message_id=agent_message_id,
            requested_model=requested_model,
            limit_snapshot=limit_snapshot,
            trace_id=trace_id,
        )

    def get_run(self, run_id: UUID) -> RunRecord:
        """Fetch run record in the active partition."""
        return self.store.get_run(run_id, self.partition())

    def get_run_by_agent_message_id(
        self, agent_message_id: UUID
    ) -> RunRecord | None:
        """Fetch run by agent_message_id in the active partition."""
        return self.store.get_run_by_agent_message_id(
            agent_message_id, self.partition()
        )

    def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        conversation_id: UUID | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[RunRecord]:
        """List runs in the active partition."""
        return self.store.list_runs(
            self.partition(),
            status=status,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )

    def start_run(
        self,
        run_id: UUID,
        *,
        resolved_model: str,
        provider: str,
        runtime: str,
    ) -> RunRecord:
        """Mark run as running in the active partition."""
        return self.store.start_run(
            run_id,
            partition=self.partition(),
            resolved_model=resolved_model,
            provider=provider,
            runtime=runtime,
        )

    def update_progress(
        self,
        run_id: UUID,
        *,
        turns_count: int | None = None,
        tool_calls_count: int | None = None,
        retries_count: int | None = None,
        total_tokens: int | None = None,
        elapsed_seconds: float | None = None,
        usage_quality: UsageQuality | None = None,
        runtime_measurements: dict[str, Any] | None = None,
    ) -> RunRecord:
        """Update metrics in the active partition."""
        return self.store.update_progress(
            run_id,
            partition=self.partition(),
            turns_count=turns_count,
            tool_calls_count=tool_calls_count,
            retries_count=retries_count,
            total_tokens=total_tokens,
            elapsed_seconds=elapsed_seconds,
            usage_quality=usage_quality,
            runtime_measurements=runtime_measurements,
        )

    def set_cancelling(self, run_id: UUID) -> RunRecord:
        """Mark run as cancelling in the active partition."""
        return self.store.set_cancelling(run_id, partition=self.partition())

    def finalize_run(
        self,
        run_id: UUID,
        *,
        status: RunStatus,
        stop_reason: RunStopReason,
        evidence: RunCompletionEvidence,
        error: RunError | None = None,
    ) -> RunRecord:
        """Finalize run in the active partition."""
        return self.store.finalize_run(
            run_id,
            partition=self.partition(),
            status=status,
            stop_reason=stop_reason,
            evidence=evidence,
            error=error,
        )

    def recover_interrupted(self) -> int:
        """Recover all unfinished runs across partitions on startup."""
        return self.store.recover_interrupted()

    def has_active_runs(self, conversation_id: UUID) -> bool:
        """Check whether a conversation has active runs."""
        return self.store.has_active_runs(conversation_id)
