"""Versioned inference pricing registry and cost estimator.

Estimates cover provider token usage and successful billable provider-hosted
tool invocations only. MCP connectors (Brave, Alpha Vantage, and similar
services) remain outside APEX's provider-cost estimates.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.providers.contract import (
    InferenceProvider,
    ProviderToolEvent,
    is_local_inference_provider,
)
from core.agent.types import CostCompleteness, CostEstimate, TokenUsage

PRICING_VERSION = "2026.08.02"
_CURRENCY = "USD"


@dataclass(frozen=True, slots=True)
class ModelTokenRates:
    """USD per 1M tokens for a configured or resolved model id."""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float = 0.0
    reasoning_per_million: float | None = None
    long_context_threshold_tokens: int | None = None
    long_context_input_per_million: float | None = None
    long_context_output_per_million: float | None = None
    long_context_cached_input_per_million: float | None = None


@dataclass(frozen=True, slots=True)
class ProfilePricing:
    """Catalog pricing shown and estimated for one Apex Agent."""

    billing_basis: str
    rates: ModelTokenRates


@dataclass(frozen=True, slots=True)
class HostedToolRate:
    """USD per successful billable hosted-tool invocation."""

    usd_per_invocation: float


# Standard paid rates, reconciled against provider documentation on 2026-08-02.
_MODEL_RATES: dict[str, ModelTokenRates] = {
    "gemini-3.5-flash-lite": ModelTokenRates(0.30, 2.50, 0.03),
    "gemini-3.6-flash": ModelTokenRates(1.50, 7.50, 0.15),
    "gpt-5.6-luna": ModelTokenRates(
        0.20,
        1.20,
        0.02,
        long_context_threshold_tokens=272_000,
        long_context_input_per_million=0.40,
        long_context_output_per_million=1.80,
        long_context_cached_input_per_million=0.04,
    ),
    "grok-4.3": ModelTokenRates(
        1.25,
        2.50,
        0.20,
        long_context_threshold_tokens=200_000,
        long_context_input_per_million=2.50,
        long_context_output_per_million=5.00,
        long_context_cached_input_per_million=0.40,
    ),
    "grok-4.5": ModelTokenRates(
        2.00,
        6.00,
        0.30,
        long_context_threshold_tokens=200_000,
        long_context_input_per_million=4.00,
        long_context_output_per_million=12.00,
        long_context_cached_input_per_million=0.60,
    ),
}

_LOCAL_ZERO = ModelTokenRates(0.0, 0.0, 0.0)
_FREE_TIER_ZERO = ModelTokenRates(0.0, 0.0, 0.0)
_FREE_TIER_MODELS = frozenset({"gemini-3.5-flash-lite"})

_HOSTED_TOOL_RATES: dict[str, HostedToolRate] = {
    "google_search": HostedToolRate(0.014),
    "google_maps": HostedToolRate(0.025),
    "x_search": HostedToolRate(0.005),
}


def lookup_model_rates(
    model: str | None, *, provider: InferenceProvider | None = None
) -> ModelTokenRates | None:
    """Return standard model rates; local inference has no provider token cost."""
    if is_local_inference_provider(provider):
        return _LOCAL_ZERO
    if not model:
        return None
    return _MODEL_RATES.get(model.strip().lower())


def agent_pricing(
    agent_key: str,
    *,
    model: str,
    provider: InferenceProvider,
) -> ProfilePricing:
    """Return the authoritative billing basis for an Apex Agent."""
    if is_local_inference_provider(provider):
        return ProfilePricing("local", _LOCAL_ZERO)
    if model.strip().lower() in _FREE_TIER_MODELS:
        return ProfilePricing("free_tier", _FREE_TIER_ZERO)
    return ProfilePricing(
        "standard",
        lookup_model_rates(model, provider=provider) or ModelTokenRates(0.0, 0.0),
    )


def lookup_hosted_tool_rate(tool_name: str) -> HostedToolRate | None:
    """Return the per-invocation rate for a provider-hosted tool name."""
    return _HOSTED_TOOL_RATES.get(tool_name.strip().lower())


def estimate_inference_cost(
    *,
    model: str | None,
    usage: TokenUsage | None,
    hosted_tool_events: list[ProviderToolEvent] | None = None,
    configured_model: str | None = None,
    provider: InferenceProvider | None = None,
    agent_key: str | None = None,
) -> CostEstimate:
    """Estimate token and provider-hosted-tool cost for a completed query."""
    rates = lookup_model_rates(model, provider=provider) or lookup_model_rates(
        configured_model, provider=provider
    )
    if agent_key is not None and provider is not None:
        rates = agent_pricing(
            agent_key,
            model=configured_model or model or "",
            provider=provider,
        ).rates

    token_cost: float | None = None
    token_complete = False
    if rates is not None and usage is not None:
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
        if input_tokens is not None or output_tokens is not None:
            token_cost = 0.0
            token_complete = True
            use_long_context = bool(
                rates.long_context_threshold_tokens is not None
                and (input_tokens or 0) > rates.long_context_threshold_tokens
            )
            input_rate = (
                rates.long_context_input_per_million
                if use_long_context and rates.long_context_input_per_million is not None
                else rates.input_per_million
            )
            cached_rate = (
                rates.long_context_cached_input_per_million
                if use_long_context
                and rates.long_context_cached_input_per_million is not None
                else rates.cached_input_per_million
            )
            output_rate = (
                rates.long_context_output_per_million
                if use_long_context and rates.long_context_output_per_million is not None
                else rates.output_per_million
            )
            if input_tokens is not None:
                cached_tokens = min(usage.cached_input_tokens or 0, input_tokens)
                uncached_tokens = input_tokens - cached_tokens
                token_cost += (uncached_tokens / 1_000_000.0) * input_rate
                token_cost += (cached_tokens / 1_000_000.0) * cached_rate
            else:
                token_complete = False
            if usage.reasoning_tokens is not None:
                reasoning_rate = rates.reasoning_per_million or output_rate
                token_cost += (usage.reasoning_tokens / 1_000_000.0) * reasoning_rate
            if output_tokens is not None:
                token_cost += (output_tokens / 1_000_000.0) * output_rate
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
    total = (
        (token_cost or 0.0) + (hosted_cost_value or 0.0)
        if token_cost is not None or hosted_cost_value is not None
        else None
    )
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
