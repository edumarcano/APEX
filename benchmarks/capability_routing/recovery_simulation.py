"""Runtime-aligned recovery simulation for benchmarks."""

from __future__ import annotations

from collections.abc import Sequence

from core.agent.capabilities import CapabilityDescriptor, list_agent_capabilities
from core.agent.local_commands import estimate_schema_tokens
from core.agent.routing.service import (
    _apply_schema_budget,
    _is_routable,
    _schema_budget_for_agent,
    resolve_capabilities,
)
from core.agent.routing.models import CapabilityRoutingRequest
from core.agent.routing.thresholds import RoutingThresholds
from core.agent.routing.tool_search import (
    RecoverySimulationResult,
    build_searchable_catalog,
    simulate_oracle_catalog_recovery,
)
from core.agent.types import AgentMessage


def _history_messages(history: Sequence[dict]) -> tuple[AgentMessage, ...]:
    return tuple(
        AgentMessage(role=item["role"], content=item["content"])
        for item in history
    )


def _initial_offered_descriptors(
    selected_families: set[str],
    *,
    runtime: str,
    agent_key: str,
    thresholds: RoutingThresholds,
) -> list[CapabilityDescriptor]:
    routable = [
        descriptor
        for descriptor in list_agent_capabilities()
        if _is_routable(descriptor) and descriptor.routing_family in selected_families
    ]
    offered, _fully_truncated, _partially_truncated = _apply_schema_budget(
        sorted(selected_families),
        routable,
        _schema_budget_for_agent(agent_key, thresholds),
        local_runtime=runtime == "local",
    )
    return offered


def simulate_runtime_catalog_recovery(
    *,
    prompt: str,
    initial_selected: set[str],
    expected: set[str],
    runtime: str,
    agent_key: str,
    thresholds: RoutingThresholds,
    max_tool_turns: int,
    history: Sequence[dict] = (),
) -> RecoverySimulationResult:
    """Simulate one bounded recovery pass using runtime catalog construction."""
    offered = _initial_offered_descriptors(
        initial_selected,
        runtime=runtime,
        agent_key=agent_key,
        thresholds=thresholds,
    )
    offered_names = {descriptor.name for descriptor in offered}
    offered_families = frozenset(
        descriptor.routing_family
        for descriptor in offered
        if descriptor.routing_family is not None
    )
    offered_tokens = estimate_schema_tokens(offered)
    agent_budget = _schema_budget_for_agent(agent_key, thresholds)
    expansion_allowance = min(
        thresholds.tool_search_max_expansion_schema_tokens,
        max(0, agent_budget - offered_tokens),
    )
    searchable_catalog = build_searchable_catalog(
        list_agent_capabilities(),
        runtime=runtime,
        agent_key=agent_key,
        offered_names=sorted(offered_names),
    )
    return simulate_oracle_catalog_recovery(
        prompt=prompt,
        initial_selected=initial_selected,
        expected=expected,
        searchable_catalog=searchable_catalog,
        initial_offered=offered,
        max_result_families=thresholds.tool_search_max_result_families,
        max_capabilities_per_family=thresholds.tool_search_max_capabilities_per_family,
        expansion_allowance=expansion_allowance,
        max_tool_turns=max_tool_turns,
        history=_history_messages(history),
        apply_local_projection=runtime == "local",
        offered_families=offered_families,
    )


def simulate_enabled_runtime_selection(
    *,
    prompt: str,
    expected: set[str],
    runtime: str,
    agent_key: str,
    thresholds: RoutingThresholds,
    calibrator=None,
) -> tuple[set[str], list[CapabilityDescriptor], str]:
    """Resolve capabilities in enabled mode and return selected families and tools."""
    request = CapabilityRoutingRequest(
        prompt=prompt,
        history=(),
        capabilities=tuple(list_agent_capabilities()),
        agent_key=agent_key,
        runtime=runtime,  # type: ignore[arg-type]
        mode="enabled",
        explicit_scope=None,
    )
    kwargs: dict = {"thresholds": thresholds}
    if calibrator is not None:
        kwargs["calibrator"] = calibrator
    decision = resolve_capabilities(request, **kwargs)
    selected = set(decision.selected_families)
    return selected, list(decision.offered_capabilities), decision.kind
