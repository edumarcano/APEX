"""Domain models and types for durable Cortex runs."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

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
FinalMessageStatus = Literal["completed", "failed", "interrupted"]
TraceId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]

RunErrorCode = Literal[
    "timeout",
    "token_limit",
    "turn_limit",
    "tool_limit",
    "retry_limit",
    "provider_unavailable",
    "provider_error",
    "tool_error",
    "runtime_error",
    "resource_exhaustion",
    "interrupted_by_restart",
    "operator_cancelled",
    "internal_error",
]

SAFE_ERROR_MESSAGES: dict[str, str] = {
    "timeout": "Run exceeded maximum elapsed time limit.",
    "token_limit": "Run exceeded maximum token budget.",
    "turn_limit": "Run reached maximum model turn limit.",
    "tool_limit": "Run reached maximum tool execution limit.",
    "retry_limit": "Run exhausted provider retry attempts.",
    "provider_unavailable": "Provider endpoint was unreachable or unavailable.",
    "provider_error": "Inference provider encountered an unrecoverable error.",
    "tool_error": "An attached tool failed execution.",
    "runtime_error": "Local runtime coordinator encountered an execution error.",
    "resource_exhaustion": "System resources exceeded configured safety gates.",
    "interrupted_by_restart": "Run was interrupted by an APEX restart.",
    "operator_cancelled": "Run was cancelled by operator.",
    "internal_error": "An internal execution error occurred.",
}

_OPAQUE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]{1,64}$")


class RunLimitSnapshot(BaseModel):
    """Immutable limit snapshot captured at run creation."""

    model_config = ConfigDict(extra="forbid")

    max_elapsed_seconds: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    max_retries: int = Field(ge=0)
    max_model_turns: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)


class RunRuntimeMeasurements(BaseModel):
    """Allowlisted runtime execution measurements and timings only (no text or payloads)."""

    model_config = ConfigDict(extra="forbid")

    queue_duration_ms: float | None = Field(default=None, ge=0.0)
    prompt_eval_duration_ms: float | None = Field(default=None, ge=0.0)
    eval_duration_ms: float | None = Field(default=None, ge=0.0)
    total_duration_ms: float | None = Field(default=None, ge=0.0)
    ttft_ms: float | None = Field(default=None, ge=0.0)
    prompt_eval_count: int | None = Field(default=None, ge=0)
    eval_count: int | None = Field(default=None, ge=0)
    tokens_per_second: float | None = Field(default=None, ge=0.0)


class RunCompletionEvidence(BaseModel):
    """Evidence of completion: message state, persistence flag, and opaque identifiers."""

    model_config = ConfigDict(extra="forbid")

    final_message_status: FinalMessageStatus | None = None
    answer_persisted: bool = False
    tool_outcome_counts: dict[str, int] = Field(default_factory=dict)
    action_ids: list[str] = Field(default_factory=list)

    @field_validator("tool_outcome_counts")
    @classmethod
    def _validate_outcome_counts(cls, v: dict[str, int]) -> dict[str, int]:
        for k, count in v.items():
            if not isinstance(count, int) or count < 0:
                raise ValueError("Tool outcome counts must be non-negative integers.")
            if not _OPAQUE_ID_PATTERN.match(k):
                raise ValueError(f"Invalid outcome name: {k!r}")
        return v

    @field_validator("action_ids")
    @classmethod
    def _validate_action_ids(cls, v: list[str]) -> list[str]:
        for action_id in v:
            if not isinstance(action_id, str) or not _OPAQUE_ID_PATTERN.match(action_id):
                raise ValueError(
                    f"Action ID must be an opaque identifier (1-64 chars, alphanumeric/dash/underscore): {action_id!r}"
                )
        return v


class RunError(BaseModel):
    """Sanitized diagnostic error information with predefined safe messages."""

    model_config = ConfigDict(extra="forbid")

    code: RunErrorCode
    message: str = ""

    @model_validator(mode="after")
    def _enforce_predefined_safe_message(self) -> RunError:
        safe_msg = SAFE_ERROR_MESSAGES.get(self.code, "An execution error occurred.")
        object.__setattr__(self, "message", safe_msg)
        return self


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
    runtime_measurements: RunRuntimeMeasurements = Field(
        default_factory=RunRuntimeMeasurements
    )
    evidence: RunCompletionEvidence = Field(default_factory=RunCompletionEvidence)
    trace_id: TraceId | None = None
    error: RunError | None = None
