"""Provider-neutral profile and turn-result contracts for inference adapters."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from core.agent.types import (
    AgentMessage,
    Citation,
    TokenUsage,
)

InferenceProvider = Literal["gemini", "ollama", "llama_cpp", "openai", "xai"]
LocalInferenceProvider = Literal["ollama", "llama_cpp"]
LOCAL_INFERENCE_PROVIDERS: frozenset[str] = frozenset({"ollama", "llama_cpp"})
ToolTraceOrigin = Literal["apex", "provider"]


def is_local_inference_provider(value: object) -> bool:
    """Return whether ``value`` identifies a local inference provider."""
    return value in LOCAL_INFERENCE_PROVIDERS



class ProviderToolEvent(BaseModel):
    """Provider-hosted tool activity observed during a generate_turn call."""

    name: str
    origin: Literal["provider"] = "provider"
    status: Literal["ok", "error", "unknown"] = "unknown"
    duration_ms: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Wall-clock duration attributed to this hosted call. Providers that "
            "do not report per-call timing share the measured turn duration."
        ),
    )
    billable_units: int | None = Field(
        default=None,
        ge=0,
        description="Billable invocation count for hosted search/maps tools.",
    )
    detail: str | None = Field(
        default=None,
        description="Sanitized status detail; never includes secrets or raw payloads.",
    )


class ProviderTurnResult(BaseModel):
    """Result of one synchronous provider generate_turn call.

    Fields are shaped so future streaming events can reuse the same semantics
    without renaming meanings (message chunks, usage deltas, tool events).
    """

    message: AgentMessage
    resolved_model: str | None = Field(
        default=None,
        description="Model identifier actually served by the provider, when known.",
    )
    usage: TokenUsage | None = None
    provider_ms: float | None = Field(default=None, ge=0)
    citations: list[Citation] = Field(default_factory=list)
    provider_tool_events: list[ProviderToolEvent] = Field(default_factory=list)
    retry_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Bounded re-attempts consumed inside this turn, covering transport "
            "retries and local recovery re-posts."
        ),
    )
    estimated_prompt_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Local preflight prompt estimate (Ollama).",
    )
    history_messages_dropped: int = Field(
        default=0,
        ge=0,
        description="Prior history messages omitted to fit a local context window.",
    )


class ProviderProfile(Protocol):
    """Shared profile surface required by the agent loop and providers."""

    display_name: str
    agent_version: str
    api_model: str
    max_tool_turns: int
    max_tool_calls: int
    system_instruction: str

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        ...


def merge_token_usage(
    left: TokenUsage | None, right: TokenUsage | None
) -> TokenUsage | None:
    """Sum nullable usage counters across turns; preserve None when both missing."""
    if left is None and right is None:
        return None
    left = left or TokenUsage()
    right = right or TokenUsage()

    def _sum(a: int | None, b: int | None) -> int | None:
        if a is None and b is None:
            return None
        return (a or 0) + (b or 0)

    merged = TokenUsage(
        input_tokens=_sum(left.input_tokens, right.input_tokens),
        cached_input_tokens=_sum(left.cached_input_tokens, right.cached_input_tokens),
        reasoning_tokens=_sum(left.reasoning_tokens, right.reasoning_tokens),
        output_tokens=_sum(left.output_tokens, right.output_tokens),
        total_tokens=_sum(left.total_tokens, right.total_tokens),
    )
    if merged.total_tokens is None and any(
        value is not None
        for value in (
            merged.input_tokens,
            merged.reasoning_tokens,
            merged.output_tokens,
        )
    ):
        # Cached tokens are a subset of input_tokens and must not be added again.
        merged.total_tokens = (
            (merged.input_tokens or 0)
            + (merged.reasoning_tokens or 0)
            + (merged.output_tokens or 0)
        )
    return merged


def resolve_inference_provider(profile: object) -> InferenceProvider:
    """Map a concrete profile instance to its inference provider kind."""
    provider_attr = getattr(profile, "provider", None)
    if provider_attr in {"gemini", "ollama", "llama_cpp", "openai", "xai"}:
        return provider_attr  # type: ignore[return-value]

    module = type(profile).__module__
    name = type(profile).__name__
    if "llama_cpp" in module or name.startswith("LlamaCpp"):
        return "llama_cpp"
    if "ollama" in module or name.startswith("Ollama"):
        return "ollama"
    if "gemini" in module or name.startswith("Gemini"):
        return "gemini"
    if "xai" in module or name.startswith("XAI") or name.startswith("Xai"):
        return "xai"
    if "openai" in module or name.startswith("OpenAI"):
        return "openai"
    raise TypeError(f"Unsupported provider profile type: {type(profile)!r}")
