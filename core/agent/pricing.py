"""Versioned inference pricing registry and cost estimator.

Estimates cover provider token usage and successful billable provider-hosted
tool invocations only. MCP connectors (Brave, Alpha Vantage, etc.) and other
third-party service charges are intentionally excluded.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.providers.contract import ProviderToolEvent
from core.agent.types import CostCompleteness, CostEstimate, TokenUsage

PRICING_VERSION = "2026.08.01"
_CURRENCY = "USD"


@dataclass(frozen=True, slots=True)
class ModelTokenRates:
    """USD per 1M tokens for a configured or resolved model id."""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float = 0.0
    reasoning_per_million: float | None = None


@dataclass(frozen=True, slots=True)
class HostedToolRate:
    """USD per successful billable hosted-tool invocation."""

    usd_per_invocation: float


# Rates are estimates for planning/observability. Keep keys lowercase.
_MODEL_RATES: dict[str, ModelTokenRates] = {
    # Gemini (v1.18 roster + future sandbox)
    "gemini-3.5-flash-lite": ModelTokenRates(0.10, 0.40, cached_input_per_million=0.025),
    "gemini-3.5-flash": ModelTokenRates(0.30, 2.50, cached_input_per_million=0.075),
    "gemini-3.6-flash": ModelTokenRates(0.50, 3.00, cached_input_per_million=0.125),
    # OpenAI placeholders for unexposed adapters / future Panthera
    "gpt-5.6": ModelTokenRates(1.25, 10.00, cached_input_per_million=0.125),
    "gpt-5.4": ModelTokenRates(1.25, 10.00, cached_input_per_million=0.125),
    "gpt-4.1": ModelTokenRates(2.00, 8.00, cached_input_per_million=0.50),
    "gpt-4.1-mini": ModelTokenRates(0.40, 1.60, cached_input_per_million=0.10),
    "gpt-4o": ModelTokenRates(2.50, 10.00, cached_input_per_million=1.25),
    "gpt-4o-mini": ModelTokenRates(0.15, 0.60, cached_input_per_million=0.075),
    # xAI placeholders for unexposed adapters / future Delphinus & Orcinus
    "grok-4.3": ModelTokenRates(3.00, 15.00),
    "grok-4.5": ModelTokenRates(3.00, 15.00),
    "grok-4": ModelTokenRates(3.00, 15.00),
    "grok-3": ModelTokenRates(3.00, 15.00),
    "grok-3-mini": ModelTokenRates(0.30, 0.50),
}

# Local Ollama inference is treated as zero provider cost.
_LOCAL_ZERO = ModelTokenRates(0.0, 0.0, cached_input_per_million=0.0)

_HOSTED_TOOL_RATES: dict[str, HostedToolRate] = {
    "google_search": HostedToolRate(0.035),
    "google_maps": HostedToolRate(0.025),
    "x_search": HostedToolRate(0.005),
    "web_search": HostedToolRate(0.025),
}


def lookup_model_rates(model: str | None) -> ModelTokenRates | None:
    """Return token rates for a model id, including Ollama local zero-cost."""
    if not model:
        return None
    normalized = model.strip().lower()
    if normalized in _MODEL_RATES:
        return _MODEL_RATES[normalized]
    # Ollama tags (qwen3:1.7b, etc.) and unknown local identifiers.
    if ":" in normalized or normalized.startswith("qwen"):
        return _LOCAL_ZERO
    return None


def lookup_hosted_tool_rate(tool_name: str) -> HostedToolRate | None:
    """Return the per-invocation rate for a provider-hosted tool name."""
    return _HOSTED_TOOL_RATES.get(tool_name.strip().lower())


def estimate_inference_cost(
    *,
    model: str | None,
    usage: TokenUsage | None,
    hosted_tool_events: list[ProviderToolEvent] | None = None,
    configured_model: str | None = None,
) -> CostEstimate:
    """Estimate token + hosted-tool cost for a completed query."""
    rates = lookup_model_rates(model) or lookup_model_rates(configured_model)
    token_cost: float | None = None
    token_complete = False

    if rates is not None and usage is not None:
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        if input_tokens is not None or output_tokens is not None:
            token_cost = 0.0
            token_complete = True
            if input_tokens is not None:
                token_cost += (input_tokens / 1_000_000.0) * rates.input_per_million
            else:
                token_complete = False
            if usage.cached_input_tokens is not None:
                token_cost += (
                    usage.cached_input_tokens / 1_000_000.0
                ) * rates.cached_input_per_million
            if usage.reasoning_tokens is not None:
                reasoning_rate = (
                    rates.reasoning_per_million
                    if rates.reasoning_per_million is not None
                    else rates.output_per_million
                )
                token_cost += (usage.reasoning_tokens / 1_000_000.0) * reasoning_rate
            if output_tokens is not None:
                token_cost += (output_tokens / 1_000_000.0) * rates.output_per_million
            else:
                token_complete = False

    hosted_cost = 0.0
    hosted_complete = True
    saw_hosted = False
    for event in hosted_tool_events or []:
        if event.origin != "provider":
            continue
        rate = lookup_hosted_tool_rate(event.name)
        if rate is None:
            hosted_complete = False
            continue
        saw_hosted = True
        if event.status != "ok":
            continue
        units = event.billable_units if event.billable_units is not None else 1
        hosted_cost += units * rate.usd_per_invocation

    if not saw_hosted:
        hosted_cost_value: float | None = 0.0 if token_cost is not None else None
        hosted_complete = True
    else:
        hosted_cost_value = hosted_cost

    completeness = _resolve_completeness(
        rates_found=rates is not None,
        token_cost=token_cost,
        token_complete=token_complete,
        hosted_cost=hosted_cost_value,
        hosted_complete=hosted_complete,
        saw_hosted=saw_hosted,
    )

    total: float | None = None
    if token_cost is not None or hosted_cost_value is not None:
        total = (token_cost or 0.0) + (hosted_cost_value or 0.0)

    return CostEstimate(
        token_cost=token_cost,
        hosted_tool_cost=hosted_cost_value,
        total_cost=total,
        currency=_CURRENCY,
        pricing_version=PRICING_VERSION,
        completeness=completeness,
    )


def _resolve_completeness(
    *,
    rates_found: bool,
    token_cost: float | None,
    token_complete: bool,
    hosted_cost: float | None,
    hosted_complete: bool,
    saw_hosted: bool,
) -> CostCompleteness:
    if token_cost is None and hosted_cost is None:
        return "unavailable"
    if not rates_found and not saw_hosted:
        return "unavailable"
    if token_cost is not None and token_complete and hosted_complete:
        return "complete"
    return "partial"
