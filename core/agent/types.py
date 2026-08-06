from typing import Any, Dict, List, Literal, Optional, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


LocalToolScope: TypeAlias = Literal[
    "schedule",
    "weather",
    "f1",
    "mail",
    "search",
    "market",
    "briefings",
    "todo",
    "none",
]

AgentKey: TypeAlias = Literal[
    "acinonyx",
    "panthera",
    "neofelis",
    "delphinus",
    "orcinus",
    "sorex",
    "mus",
    "apodemus",
]
ApexEffort: TypeAlias = Literal["light", "focused", "extended"]

CostCompleteness = Literal["complete", "partial", "unavailable"]


class TokenUsage(BaseModel):
    """Normalized token accounting for one provider turn or aggregated query.

    Providers disagree on whether cached and reasoning tokens are nested inside
    the input and output counters, so every adapter must normalize to this
    convention before returning usage:

    - ``input_tokens`` counts all prompt tokens and includes ``cached_input_tokens``.
    - ``output_tokens`` counts visible completion tokens and excludes ``reasoning_tokens``.
    - ``total_tokens`` is ``input_tokens + reasoning_tokens + output_tokens``;
      cached tokens are never added again because they are already in the input.
    """

    input_tokens: int | None = Field(
        default=None,
        ge=0,
        description="All prompt tokens, including any cached prompt tokens.",
    )
    cached_input_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Subset of input_tokens served from cache, when reported.",
    )
    reasoning_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Hidden reasoning tokens, counted separately from output_tokens.",
    )
    output_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Visible completion tokens, excluding reasoning tokens.",
    )
    total_tokens: int | None = Field(
        default=None, ge=0, description="Provider-reported or derived total."
    )


class QueryTiming(BaseModel):
    """Wall-clock timing for a completed Agent query."""

    total_ms: float | None = Field(
        default=None, ge=0, description="End-to-end query duration."
    )
    provider_ms: float | None = Field(
        default=None, ge=0, description="Time spent in provider generate_turn calls."
    )
    apex_tool_ms: float | None = Field(
        default=None, ge=0, description="Time spent executing APEX-managed tools."
    )


class Citation(BaseModel):
    """Normalized citation or grounding reference from a provider-hosted tool."""

    title: str | None = None
    uri: str | None = None
    snippet: str | None = None
    source: str | None = Field(
        default=None,
        description="Provider-specific citation source label when available.",
    )


class CostEstimate(BaseModel):
    """Estimated inference cost derived from the versioned pricing registry."""

    token_cost: float | None = Field(default=None, ge=0)
    hosted_tool_cost: float | None = Field(default=None, ge=0)
    total_cost: float | None = Field(default=None, ge=0)
    currency: str = "USD"
    pricing_version: str
    completeness: CostCompleteness = "unavailable"


class LocalContextUsage(BaseModel):
    estimated_prompt_tokens: int = Field(
        ge=0, description="Conservative preflight prompt-token estimate."
    )
    peak_prompt_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Largest prompt_eval_count returned across local model turns.",
    )
    context_window: int = Field(
        ge=1, description="Configured local Agent context window."
    )
    history_messages_dropped: int = Field(
        default=0,
        ge=0,
        description="Prior session messages omitted to keep the local prompt bounded.",
    )


class LocalCommandStatus(BaseModel):
    key: LocalToolScope
    command: str = Field(description="Slash command shown in the Ask APEX console.")
    label: str
    description: str
    tool_count: int = Field(ge=0)
    estimated_schema_tokens: int = Field(ge=0)
    available: bool
    unavailable_reason: str | None = None


class ToolCall(BaseModel):
    id: str = Field(description="Unique call identifier provided by the model.")
    name: str = Field(description="The matching name of the tool to execute.")
    arguments: Dict[str, Any] = Field(
        description="Arguments mapping validated against the tool schema."
    )
    thought_signature: Optional[str] = Field(
        default=None,
        description="Opaque reasoning token required to maintain Gemini 3 loop state.",
    )


class ToolResult(BaseModel):
    id: str = Field(description="The unique identifier corresponding to the ToolCall.")
    name: str = Field(description="The name of the tool executed.")
    output: Any = Field(
        description="Serializable raw outputs returned from the Python handler."
    )


class AgentMessage(BaseModel):
    role: Literal["user", "agent", "tool"] = Field(
        description="Message role in the chat history."
    )
    content: Optional[str] = Field(
        default=None, description="Raw text payload from user or Agent."
    )
    tool_calls: Optional[List[ToolCall]] = Field(
        default=None, description="Tool requests generated by the model."
    )
    tool_results: Optional[List[ToolResult]] = Field(
        default=None, description="Tool execution results returned to the model."
    )
    prompt_tokens: Optional[int] = Field(default=None, exclude=True)
    estimated_prompt_tokens: Optional[int] = Field(default=None, exclude=True)
    history_messages_dropped: int = Field(default=0, exclude=True)
    # Opaque provider continuation payload for Responses API adapters
    # (encrypted reasoning / output items). Never serialized to clients.
    provider_output_items: Optional[List[Dict[str, Any]]] = Field(
        default=None, exclude=True
    )


class AgentQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(description="The user's direct operations query.")
    agent: AgentKey = Field(
        default="panthera",
        description="The selected Apex Agent key (cloud or local).",
    )
    effort: ApexEffort | None = Field(
        default=None,
        description=(
            "Optional cloud effort override (light, focused, extended). "
            "Rejected for local Agents."
        ),
    )
    session_id: Optional[str] = Field(
        default=None, description="Optional temporary session grouping identifier."
    )
    history: List[AgentMessage] = Field(
        default_factory=list,
        description="Recent conversation history for the session.",
    )
    history_partition: Literal["production", "acinonyx"] = Field(
        default="production",
        description=(
            "Browser-owned history partition. Acinonyx history is accepted only "
            "when explicitly marked as sandbox history."
        ),
    )
    tool_scope: LocalToolScope | None = Field(
        default=None,
        description=(
            "Explicit local Agent command bundle. Omit for tool-free local turns; "
            "cloud Agents retain their normal automatic capability set."
        ),
    )
    snapshot_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional telemetry snapshot ID. When present and matching the "
            "current in-memory snapshot, module display text is injected as "
            "HUD context. Absent or mismatched IDs inject no snapshot context."
        ),
    )
    briefing_id: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Optional briefing history row ID. When present, that briefing's "
            "prose and insights are injected as HUD context. Absent IDs inject "
            "no briefing context."
        ),
    )


class AgentQueryResponse(BaseModel):
    answer: str = Field(description="The final synthesized response from the agent.")
    agent_used: Dict[str, Any] = Field(
        description="Display details of the configured Agent used."
    )
    tool_trace: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Audit trace of tools called during the loop.",
    )
    tool_outputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Structured outputs of whitelisted tools executed.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Active temporary session grouping identifier.",
    )
    error: Optional[str] = Field(
        default=None, description="Detailed error diagnostics, if any."
    )
    tool_scope_used: LocalToolScope | None = Field(
        default=None,
        description="Resolved local command bundle used for this response.",
    )
    local_context_usage: LocalContextUsage | None = Field(
        default=None,
        description="Local Agent prompt-window usage; null for cloud Agents.",
    )
    resolved_model: Optional[str] = Field(
        default=None,
        description="Model identifier resolved by the provider, when available.",
    )
    usage: TokenUsage | None = Field(
        default=None,
        description="Aggregated token usage across provider turns.",
    )
    timing: QueryTiming | None = Field(
        default=None,
        description="Query timing breakdown (total / provider / APEX tools).",
    )
    cost_estimate: CostEstimate | None = Field(
        default=None,
        description="Estimated provider token and hosted-tool cost.",
    )
    citations: List[Citation] = Field(
        default_factory=list,
        description="Normalized citations from provider-hosted grounding tools.",
    )
