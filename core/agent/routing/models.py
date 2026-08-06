"""Immutable routing contracts for smart tool selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.agent.capabilities import CapabilityDescriptor
from core.agent.types import AgentMessage, LocalToolScope

ToolRoutingMode = Literal["disabled", "shadow", "enabled"]
RoutingRuntime = Literal["cloud", "local"]

RoutingDecisionKind = Literal[
    "disabled",
    "explicit",
    "explicit_none",
    "semantic",
    "semantic_none",
    "shadow",
    "fallback_full",
    "fallback_none",
    "model_unavailable",
    "model_error",
]


@dataclass(frozen=True, slots=True)
class CapabilityRoutingRequest:
    prompt: str
    history: tuple[AgentMessage, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    agent_key: str
    runtime: RoutingRuntime
    mode: ToolRoutingMode
    explicit_scope: LocalToolScope | None


@dataclass(frozen=True, slots=True)
class RankedCapabilityFamily:
    key: str
    score: float


@dataclass(frozen=True, slots=True)
class CapabilityRoutingDecision:
    kind: RoutingDecisionKind
    offered_capabilities: tuple[CapabilityDescriptor, ...]
    selected_families: tuple[str, ...]
    considered_tool_count: int
    offered_tool_count: int
    considered_schema_tokens: int
    offered_schema_tokens: int
    top_score: float | None
    score_margin: float | None
    latency_ms: float
    enforced: bool
    model_key: str | None
    fallback_reason: str | None
    truncated_families: tuple[str, ...] = ()
