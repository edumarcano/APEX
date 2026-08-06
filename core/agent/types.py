from typing import Any, Dict, List, Literal, Optional, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


ToolSelectionFailureCode: TypeAlias = Literal[
    "invalid",
    "profile-invalid",
    "not-exposed",
    "policy",
    "risk-rejected",
    "configuration-required",
    "authentication-required",
    "mcp-disabled",
    "mcp-disconnected",
    "mcp-not-allowlisted",
    "runtime-unavailable",
    "unavailable",
]

ToolCatalogGroupKind: TypeAlias = Literal["apex_family", "mcp_server"]

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


class ToolSelectionFailure(BaseModel):
    """Structured reason why one requested tool could not be selected."""

    name: str
    code: ToolSelectionFailureCode
    reason: str


class ToolSelectionDiagnostics(BaseModel):
    """The exact tool selection used or rejected for one Agent turn."""

    requested_tool_names: list[str] = Field(default_factory=list)
    offered_tool_names: list[str] = Field(default_factory=list)
    rejected_tool_names: list[str] = Field(default_factory=list)
    rejected_tools: list[ToolSelectionFailure] = Field(default_factory=list)
    selected_schema_tokens: int = Field(default=0, ge=0)
    active_profile_id: str | None = None
    active_profile_name: str | None = None


class ToolCatalogTool(BaseModel):
    """Provider-neutral catalog metadata for one model-facing capability."""

    name: str
    label: str
    description: str
    origin: Literal["native", "mcp"]
    source_id: str
    apex_family: str | None = None
    risk: Literal["read", "write", "destructive"] = "read"
    available: bool
    unavailable_reason: str | None = None
    estimated_schema_tokens: int = Field(default=0, ge=0)
    allowed_for_agent: bool


class ToolCatalogGroup(BaseModel):
    """A curated APEX family or external MCP server group."""

    id: str
    label: str
    kind: ToolCatalogGroupKind
    tool_count: int = Field(ge=0)
    schema_token_subtotal: int = Field(default=0, ge=0)
    tools: list[ToolCatalogTool] = Field(default_factory=list)


class ToolProfileMetadata(BaseModel):
    """A built-in or persisted tool profile exposed to the picker."""

    id: str
    name: str
    description: str
    tool_names: list[str] = Field(default_factory=list)
    built_in: bool = False
    dynamic: bool = False


class ToolCatalogResponse(BaseModel):
    """Agent-specific tool catalog and current policy/availability metadata."""

    agent: AgentKey
    groups: list[ToolCatalogGroup] = Field(default_factory=list)
    tools: list[ToolCatalogTool] = Field(default_factory=list)
    profiles: list[ToolProfileMetadata] = Field(default_factory=list)
    default_profile_id: str
    default_profile_name: str
    default_selected_tool_names: list[str] = Field(default_factory=list)
    context_window: int | None = Field(default=None, ge=1)
    reserved_response_tokens: int | None = Field(default=None, ge=0)


class ToolTokenBreakdown(BaseModel):
    """Estimated input-token accounting for one next Agent request."""

    system_instructions: int = Field(default=0, ge=0)
    conversation_history: int = Field(default=0, ge=0)
    hud_context: int = Field(default=0, ge=0)
    selected_tool_schemas: int = Field(default=0, ge=0)
    current_prompt: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    configured_context_window: int | None = Field(default=None, ge=1)
    reserved_response_tokens: int | None = Field(default=None, ge=0)
    remaining_estimated_capacity: int | None = None
    is_estimate: bool = True


class ToolPreflightResponse(BaseModel):
    """Estimated request budget using the same selected descriptors as execution."""

    agent: AgentKey
    selection: ToolSelectionDiagnostics
    breakdown: ToolTokenBreakdown
    warning: str | None = None
    can_proceed: bool = True


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
    selected_tool_names: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit stable capability names to expose for this turn. An empty "
            "list means no tools. When omitted, the active Agent default profile "
            "is resolved."
        ),
    )
    tool_profile_id: str | None = Field(
        default=None,
        description="Optional saved or built-in tool profile used for diagnostics.",
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
    resolved_tool_selection: ToolSelectionDiagnostics = Field(
        default_factory=ToolSelectionDiagnostics,
        description="Exact requested, offered, rejected, and estimated tool selection.",
    )
    requested_tool_names: list[str] = Field(default_factory=list)
    offered_tool_names: list[str] = Field(default_factory=list)
    rejected_tool_names: list[str] = Field(default_factory=list)
    selected_schema_tokens: int = Field(default=0, ge=0)
    active_tool_profile_id: str | None = None
    active_tool_profile_name: str | None = None
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
