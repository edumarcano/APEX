"""Domain models and types for durable Cortex runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal[
    "queued",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]

RunStopReason = Literal[
    "end_turn",
    "operator_cancelled",
    "max_elapsed_seconds",
    "max_total_tokens",
    "max_retries",
    "max_model_turns",
    "max_tool_calls",
    "provider_error",
    "tool_error",
    "runtime_error",
    "resource_exhaustion",
    "interrupted_by_restart",
    "internal_error",
]

UsageQuality = Literal["reported", "estimated", "unavailable"]
RunPartition = Literal["production", "sandbox"]


class RunLimitSnapshot(BaseModel):
    """Immutable limit snapshot captured at run creation."""

    model_config = ConfigDict(extra="forbid")

    max_elapsed_seconds: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    max_retries: int = Field(ge=0)
    max_model_turns: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)


class RunCompletionEvidence(BaseModel):
    """Evidence of completion: message state, persistence flag, and opaque identifiers."""

    model_config = ConfigDict(extra="forbid")

    final_message_id: UUID | None = None
    final_message_status: str | None = None
    answer_persisted: bool = False
    tool_outcome_counts: dict[str, int] = Field(default_factory=dict)
    action_ids: list[str] = Field(default_factory=list)


class RunError(BaseModel):
    """Sanitized diagnostic error information."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class RunRecord(BaseModel):
    """Durable run record tracking execution metadata and completion evidence."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    partition: RunPartition
    user_message_id: UUID
    agent_message_id: UUID
    requested_model: str
    resolved_model: str | None = None
    provider: str | None = None
    runtime: str | None = None
    status: RunStatus
    stop_reason: RunStopReason | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime
    limit_snapshot: RunLimitSnapshot
    turns_count: int = Field(default=0, ge=0)
    tool_calls_count: int = Field(default=0, ge=0)
    retries_count: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    usage_quality: UsageQuality = "unavailable"
    runtime_measurements: dict[str, Any] = Field(default_factory=dict)
    evidence: RunCompletionEvidence = Field(default_factory=RunCompletionEvidence)
    trace_id: str | None = None
    error: RunError | None = None
