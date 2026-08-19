"""Conversation contracts shared by persistence, routes, and Cortex."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.agent.types import AgentKey, ApexEffort

ConversationPartition = Literal["production", "sandbox"]
ConversationOrigin = Literal["hud", "cli"]
ConversationRole = Literal["user", "agent"]
ConversationMessageStatus = Literal["pending", "completed", "failed", "interrupted"]


def normalize_title(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Conversation titles must contain non-whitespace text.")
    if len(normalized) > 120:
        raise ValueError("Conversation titles may contain at most 120 characters.")
    return normalized


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    origin: ConversationOrigin = "hud"
    agent: AgentKey | None = None
    selected_tool_names: list[str] | None = None
    tool_profile_id: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return normalize_title(value) if value is not None else None


class ConversationPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    archived: bool | None = None
    active_leaf_message_id: UUID | None = None
    agent: AgentKey | None = None
    selected_tool_names: list[str] | None = None
    tool_profile_id: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        return normalize_title(value) if value is not None else None


class ConversationTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message_id: UUID
    agent_message_id: UUID
    parent_message_id: UUID | None = None
    prompt: str = Field(min_length=1, max_length=10000)
    agent: AgentKey | None = None
    effort: ApexEffort | None = None
    selected_tool_names: list[str] | None = None
    tool_profile_id: str | None = None
    snapshot_id: str | None = None
    briefing_id: int | None = Field(default=None, ge=1)

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Prompt must contain non-whitespace text.")
        return normalized


class ConversationMessage(BaseModel):
    id: UUID
    conversation_id: UUID
    parent_message_id: UUID | None = None
    role: ConversationRole
    content: str
    status: ConversationMessageStatus
    agent: AgentKey | None = None
    request_metadata: dict[str, Any] | None = None
    response_metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    partition: ConversationPartition
    origin: ConversationOrigin
    agent: AgentKey
    selected_tool_names: list[str] | None = None
    tool_profile_id: str | None = None
    active_leaf_message_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessage] = Field(default_factory=list)


class ConversationTurnResult(BaseModel):
    """Flat current Agent response plus durable message identifiers."""

    conversation_id: UUID
    user_message_id: UUID
    agent_message_id: UUID
    active_leaf_message_id: UUID
    message_status: ConversationMessageStatus
    answer: str
    agent_used: dict[str, Any] = Field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    resolved_tool_selection: dict[str, Any] = Field(default_factory=dict)
    requested_tool_names: list[str] = Field(default_factory=list)
    offered_tool_names: list[str] = Field(default_factory=list)
    rejected_tool_names: list[str] = Field(default_factory=list)
    selected_schema_tokens: int = 0
    active_tool_profile_id: str | None = None
    active_tool_profile_name: str | None = None
    local_context_usage: dict[str, Any] | None = None
    resolved_model: str | None = None
    usage: dict[str, Any] | None = None
    timing: dict[str, Any] | None = None
    cost_estimate: dict[str, Any] | None = None
    context_usage: dict[str, Any] | None = None
    context_references: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
