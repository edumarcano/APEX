"""Policy-safe tool search recovery for incomplete capability routing."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from core.agent.capabilities import CapabilityDescriptor, CapabilityError, CapabilityErrorCategory
from core.agent.local_commands import estimate_schema_tokens, project_local_descriptor
from core.agent.routing.families import CAPABILITY_FAMILIES, get_family
from core.agent.routing.rules import apply_routing_rules
from core.agent.routing.service import _family_eligible, _is_routable
from core.agent.tool_policies import filter_agent_capabilities
from core.agent.types import AgentMessage

SEARCH_AVAILABLE_TOOLS_NAME = "search_available_tools"
_TOKEN = re.compile(r"[a-z0-9']+")
_DESCRIPTION_PREVIEW_CHARS = 160

# Schema budget semantics: ``max_expansion_schema_tokens`` is an *additional*
# expansion-token allowance counted from zero. Recovery may add at most this many
# schema tokens beyond the descriptors already offered when the request started.
# Cortex clamps the allowance to remaining agent headroom when applicable.


@dataclass(frozen=True, slots=True)
class ToolSearchRecoveryConfig:
    """Bounded recovery settings for one agent request."""

    enabled: bool
    searchable_catalog: tuple[CapabilityDescriptor, ...]
    offered_names: frozenset[str] = frozenset()
    offered_families: frozenset[str] = frozenset()
    max_search_calls: int = 1
    max_result_families: int = 3
    max_capabilities_per_family: int = 3
    max_expansion_schema_tokens: int | None = None
    apply_local_projection: bool = False


@dataclass
class ToolSearchRecoveryState:
    """Mutable per-request recovery progress tracked by the agent loop."""

    config: ToolSearchRecoveryConfig
    search_calls: int = 0
    search_attempted: bool = False
    search_succeeded: bool = False
    invoked: bool = False
    matched_families: list[str] = field(default_factory=list)
    recovered_families: list[str] = field(default_factory=list)
    results_already_offered: list[str] = field(default_factory=list)
    expansion_blocked_by_budget: list[str] = field(default_factory=list)
    pending_descriptors: list[CapabilityDescriptor] = field(default_factory=list)
    blocked_descriptors: list[CapabilityDescriptor] = field(default_factory=list)
    expanded_tool_count: int = 0
    search_turns_used: int = 0
    expansion_turns_used: int = 0
    recovered_tool_invocation_turns: int = 0
    usable_recovery_turn_available: bool = True
    search_offered: bool = False
    _recovered_tool_names: set[str] = field(default_factory=set)
    _offered_names: set[str] = field(default_factory=set)

    def register_offered(self, descriptors: Sequence[CapabilityDescriptor]) -> None:
        self._offered_names.update(descriptor.name for descriptor in descriptors)

    def queue_recovery_descriptors(self, output: dict[str, Any]) -> None:
        self.matched_families.clear()
        self.results_already_offered.clear()
        for family in output.get("already_offered_families", []):
            if isinstance(family, str):
                self.results_already_offered.append(family)
        for match in output.get("matches", []):
            if not isinstance(match, dict):
                continue
            family = match.get("family")
            if not isinstance(family, str):
                continue
            self.matched_families.append(family)
            if family in self.config.offered_families:
                self.results_already_offered.append(family)
                continue
            family_added = 0
            for descriptor in self.config.searchable_catalog:
                if descriptor.routing_family != family:
                    continue
                if descriptor.name in self._offered_names:
                    continue
                if descriptor.name == SEARCH_AVAILABLE_TOOLS_NAME:
                    continue
                if any(pending.name == descriptor.name for pending in self.pending_descriptors):
                    continue
                if any(blocked.name == descriptor.name for blocked in self.blocked_descriptors):
                    continue
                projected = descriptor
                if self.config.apply_local_projection and descriptor.routing_family:
                    projected = project_local_descriptor(
                        descriptor.routing_family,  # type: ignore[arg-type]
                        descriptor,
                    )
                self.pending_descriptors.append(projected)
                family_added += 1
                if family_added >= self.config.max_capabilities_per_family:
                    break


def recovery_usable_tool_turns(max_tool_turns: int, current_turn: int) -> int:
    """Return tool-enabled turns remaining after ``current_turn`` (final turn excluded)."""
    if max_tool_turns <= 0:
        return 0
    final_turn_index = max_tool_turns - 1
    if current_turn >= final_turn_index:
        return 0
    return final_turn_index - current_turn


def can_offer_search_recovery(max_tool_turns: int, current_turn: int) -> bool:
    """Return whether search may be offered on this turn.

  Recovery needs one tool-enabled turn for the search call and at least one
  subsequent tool-enabled turn for expanded schemas to become usable.
    """
    return recovery_usable_tool_turns(max_tool_turns, current_turn) >= 2


def can_expand_recovery_schemas(max_tool_turns: int, current_turn: int) -> bool:
    """Return whether expanded recovery schemas may be offered on this turn."""
    return current_turn < max_tool_turns - 1


def build_searchable_catalog(
    capabilities: Sequence[CapabilityDescriptor],
    *,
    runtime: str,
    agent_key: str,
    offered_names: Sequence[str] | None = None,
) -> tuple[CapabilityDescriptor, ...]:
    """Return read-only routable capabilities already allowed for this agent/runtime."""
    excluded = set(offered_names or ())
    filtered = filter_agent_capabilities(agent_key, capabilities)
    return tuple(
        descriptor
        for descriptor in filtered
        if _is_routable(descriptor)
        and descriptor.routing_family is not None
        and _family_eligible(descriptor.routing_family, runtime)
        and descriptor.name != SEARCH_AVAILABLE_TOOLS_NAME
        and descriptor.name not in excluded
    )


def _family_search_text(family_key: str) -> Counter[str]:
    family = get_family(family_key)
    if family is None:
        return Counter()
    return Counter(
        _TOKEN.findall(
            " ".join(
                [
                    family.key,
                    family.label,
                    family.description,
                    *family.semantic_examples,
                ]
            ).lower()
        )
    )


def _descriptor_search_text(descriptor: CapabilityDescriptor) -> Counter[str]:
    family = get_family(descriptor.routing_family or "")
    family_text = ""
    if family is not None:
        family_text = " ".join([family.label, family.description])
    return Counter(
        _TOKEN.findall(
            " ".join(
                [
                    descriptor.name,
                    descriptor.title,
                    descriptor.description,
                    family_text,
                ]
            ).lower()
        )
    )


def _cosine_overlap(query: Counter[str], document: Counter[str]) -> float:
    if not query or not document:
        return 0.0
    overlap = sum(min(query[token], document[token]) for token in query)
    query_norm = math.sqrt(sum(value * value for value in query.values())) or 1.0
    document_norm = math.sqrt(sum(value * value for value in document.values())) or 1.0
    return overlap / (query_norm * document_norm)


def rank_searchable_families(
    query: str,
    catalog: Sequence[CapabilityDescriptor],
    *,
    max_results: int,
    history: Sequence[AgentMessage | object] = (),
    excluded_families: Sequence[str] | None = None,
) -> list[str]:
    """Lexically rank searchable families for a recovery query."""
    query_tokens = Counter(_TOKEN.findall(query.lower()))
    if not query_tokens:
        return []
    excluded = set(excluded_families or ())
    families: dict[str, float] = {}
    history_messages = [
        item if isinstance(item, AgentMessage) else AgentMessage(**item)  # type: ignore[arg-type]
        for item in history
        if isinstance(item, (AgentMessage, dict))
    ]
    rule_families = {
        match.family
        for match in apply_routing_rules(query, history_messages)
        if match.family != "none"
    }
    for descriptor in catalog:
        family_key = descriptor.routing_family
        if family_key is None or family_key in excluded:
            continue
        descriptor_score = _cosine_overlap(query_tokens, _descriptor_search_text(descriptor))
        family_score = _cosine_overlap(query_tokens, _family_search_text(family_key))
        families[family_key] = max(
            families.get(family_key, 0.0),
            descriptor_score,
            family_score * 0.9,
        )
    for family_key in rule_families:
        if family_key in excluded:
            continue
        if any(descriptor.routing_family == family_key for descriptor in catalog):
            families[family_key] = max(families.get(family_key, 0.0), 0.75)
    ranked = sorted(families.items(), key=lambda item: (-item[1], item[0]))
    return [family for family, score in ranked if score > 0.0][:max_results]


def _compact_capability(descriptor: CapabilityDescriptor) -> dict[str, str]:
    description = descriptor.description.strip()
    if len(description) > _DESCRIPTION_PREVIEW_CHARS:
        description = description[: _DESCRIPTION_PREVIEW_CHARS - 1].rstrip() + "…"
    return {
        "name": descriptor.name,
        "title": descriptor.title,
        "description": description,
    }


SEARCH_QUERY_MIN_LENGTH = 1
SEARCH_QUERY_MAX_LENGTH = 500


def validate_search_query(query: str) -> str:
    """Validate and normalize a tool-search query."""
    cleaned = query.strip()
    if len(cleaned) < SEARCH_QUERY_MIN_LENGTH:
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            "Tool search requires a non-empty query.",
        )
    if len(cleaned) > SEARCH_QUERY_MAX_LENGTH:
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            f"Tool search query must be at most {SEARCH_QUERY_MAX_LENGTH} characters.",
        )
    return cleaned


def execute_tool_search(
    catalog: Sequence[CapabilityDescriptor],
    query: str,
    *,
    max_results: int,
    max_capabilities_per_family: int,
    history: Sequence[AgentMessage | object] = (),
    excluded_families: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Search a pre-filtered catalog and return compact family/capability metadata."""
    cleaned = validate_search_query(query)
    bounded_results = max(1, max_results)
    excluded = set(excluded_families or ())
    all_ranked = rank_searchable_families(
        cleaned,
        catalog,
        max_results=bounded_results + len(excluded),
        history=history,
    )
    already_offered = [family for family in all_ranked if family in excluded]
    ranked_families = [family for family in all_ranked if family not in excluded][:bounded_results]
    matches: list[dict[str, Any]] = []
    for family_key in ranked_families:
        family = get_family(family_key)
        if family is None:
            continue
        capabilities = [
            _compact_capability(descriptor)
            for descriptor in catalog
            if descriptor.routing_family == family_key
        ][:max_capabilities_per_family]
        if not capabilities:
            continue
        matches.append(
            {
                "family": family_key,
                "family_label": family.label,
                "capabilities": capabilities,
            }
        )
    return {
        "query": cleaned,
        "match_count": len(matches),
        "matches": matches,
        "truncated": len(ranked_families) >= bounded_results,
        "already_offered_families": already_offered,
    }


def search_available_tools(query: str, max_results: int = 3) -> dict[str, Any]:
    """Capability handler stub; runtime recovery dispatches in the agent loop."""
    raise CapabilityError(
        CapabilityErrorCategory.UNAVAILABLE,
        "Tool search recovery is not active for this request.",
    )


def get_search_available_tools_descriptor() -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=SEARCH_AVAILABLE_TOOLS_NAME,
        title="Search Available Tools",
        description=(
            "Search the read-only APEX capabilities already authorized for this "
            "request. Returns compact family and capability metadata only. It "
            "cannot execute tools, reveal unauthorized capabilities, or access "
            "provider-hosted Search, Maps, or X tools. Use at most once per "
            "request when the initially offered tools may be incomplete."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language description of the capability needed, "
                        "such as 'email from Sarah' or 'stock quote'."
                    ),
                    "minLength": 1,
                    "maxLength": 500,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum families to return.",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        origin="native",
        risk="read",
        expose_to_agent=False,
        expose_to_mcp_server=False,
        expose_to_client_display=True,
        routing_family=None,
    )


def expand_pending_descriptors(
    *,
    pending: Sequence[CapabilityDescriptor],
    offered: list[CapabilityDescriptor],
    expansion_allowance: int | None,
    blocked: list[CapabilityDescriptor] | None = None,
) -> tuple[list[CapabilityDescriptor], int, list[CapabilityDescriptor]]:
    """Append pending recovery descriptors up to the additional expansion allowance.

    ``expansion_allowance`` counts only tokens added by recovery expansion, not
    schemas already present in ``offered``. Oversized descriptors are skipped so
    smaller later descriptors may still fit. Descriptors that cannot be added are
    moved to ``blocked`` and are not retried on later turns.
    """
    if not pending:
        return [], 0, list(blocked or [])
    added: list[CapabilityDescriptor] = []
    expansion_tokens_used = 0
    still_pending: list[CapabilityDescriptor] = []
    blocked_out = list(blocked or [])
    blocked_names = {descriptor.name for descriptor in blocked_out}

    for descriptor in pending:
        if any(existing.name == descriptor.name for existing in offered):
            continue
        if descriptor.name in blocked_names:
            continue
        tokens = estimate_schema_tokens([descriptor])
        if expansion_allowance is not None and expansion_tokens_used + tokens > expansion_allowance:
            blocked_out.append(descriptor)
            blocked_names.add(descriptor.name)
            continue
        offered.append(descriptor)
        added.append(descriptor)
        expansion_tokens_used += tokens

    return added, len(added), blocked_out


@dataclass(frozen=True, slots=True)
class RecoverySimulationResult:
    initial_selected: set[str]
    final_selected: set[str]
    initial_offered_names: tuple[str, ...]
    matched_descriptor_names: tuple[str, ...]
    expanded_descriptor_names: tuple[str, ...]
    blocked_descriptor_names: tuple[str, ...]
    final_offered_names: tuple[str, ...]
    final_schema_tokens: int
    final_tool_count: int
    invoked: bool
    search_turns_used: int
    expansion_turns_used: int
    recovered_tool_invocation_turns: int
    false_positive: set[str]
    search_attempted: bool
    search_succeeded: bool
    expanded_families: set[str]
    expansion_tokens_used: int


def _recovery_result(
    *,
    initial_selected: set[str],
    initial_offered: Sequence[CapabilityDescriptor],
    final_offered: Sequence[CapabilityDescriptor],
    matched: Sequence[CapabilityDescriptor] = (),
    expanded: Sequence[CapabilityDescriptor] = (),
    blocked: Sequence[CapabilityDescriptor] = (),
    search_attempted: bool = False,
    search_succeeded: bool = False,
    search_turns_used: int = 0,
    expansion_turns_used: int = 0,
    recovered_tool_invocation_turns: int = 0,
    expected: set[str] | None = None,
) -> RecoverySimulationResult:
    final_families = {
        descriptor.routing_family
        for descriptor in final_offered
        if descriptor.routing_family is not None
    }
    expanded_families = {
        descriptor.routing_family
        for descriptor in expanded
        if descriptor.routing_family is not None
    }
    expansion_tokens_used = estimate_schema_tokens(expanded)
    false_positive = final_families - (expected or set())
    invoked = bool(expanded_families)
    return RecoverySimulationResult(
        initial_selected=initial_selected,
        final_selected=final_families,
        initial_offered_names=tuple(descriptor.name for descriptor in initial_offered),
        matched_descriptor_names=tuple(descriptor.name for descriptor in matched),
        expanded_descriptor_names=tuple(descriptor.name for descriptor in expanded),
        blocked_descriptor_names=tuple(descriptor.name for descriptor in blocked),
        final_offered_names=tuple(descriptor.name for descriptor in final_offered),
        final_schema_tokens=estimate_schema_tokens(final_offered),
        final_tool_count=len(final_offered),
        invoked=invoked,
        search_turns_used=search_turns_used,
        expansion_turns_used=expansion_turns_used,
        recovered_tool_invocation_turns=recovered_tool_invocation_turns,
        false_positive=false_positive,
        search_attempted=search_attempted,
        search_succeeded=search_succeeded,
        expanded_families=expanded_families,
        expansion_tokens_used=expansion_tokens_used,
    )


def simulate_oracle_catalog_recovery(
    *,
    prompt: str,
    initial_selected: set[str],
    expected: set[str],
    searchable_catalog: Sequence[CapabilityDescriptor],
    initial_offered: Sequence[CapabilityDescriptor],
    max_result_families: int,
    max_capabilities_per_family: int,
    expansion_allowance: int | None,
    max_tool_turns: int = 4,
    history: Sequence[AgentMessage | object] = (),
    apply_local_projection: bool = False,
    offered_families: frozenset[str] | None = None,
) -> RecoverySimulationResult:
    """Oracle upper-bound helper: one bounded search using the request prompt.

    This simulates catalog recovery when the agent would search with the original
    user prompt. It does not model agent-initiated search decisions.
    """
    initial_offered_list = list(initial_offered)
    if expected <= {
        descriptor.routing_family
        for descriptor in initial_offered_list
        if descriptor.routing_family is not None
    }:
        return _recovery_result(
            initial_selected=initial_selected,
            initial_offered=initial_offered_list,
            final_offered=initial_offered_list,
            expected=expected,
        )

    if not can_offer_search_recovery(max_tool_turns, current_turn=0):
        return _recovery_result(
            initial_selected=initial_selected,
            initial_offered=initial_offered_list,
            final_offered=initial_offered_list,
            expected=expected,
        )

    if not searchable_catalog or expansion_allowance == 0:
        return _recovery_result(
            initial_selected=initial_selected,
            initial_offered=initial_offered_list,
            final_offered=initial_offered_list,
            expected=expected,
        )

    excluded_families = offered_families or frozenset(
        descriptor.routing_family
        for descriptor in initial_offered_list
        if descriptor.routing_family is not None
    )
    search_result = execute_tool_search(
        searchable_catalog,
        prompt,
        max_results=max_result_families,
        max_capabilities_per_family=max_capabilities_per_family,
        history=history,
        excluded_families=sorted(excluded_families),
    )
    search_attempted = True
    search_succeeded = search_result["match_count"] > 0
    search_turns_used = 1

    config = ToolSearchRecoveryConfig(
        enabled=True,
        searchable_catalog=tuple(searchable_catalog),
        offered_families=excluded_families,
        max_result_families=max_result_families,
        max_capabilities_per_family=max_capabilities_per_family,
        max_expansion_schema_tokens=expansion_allowance,
        apply_local_projection=apply_local_projection,
    )
    state = ToolSearchRecoveryState(config=config)
    state.register_offered(initial_offered_list)
    state.queue_recovery_descriptors(search_result)
    matched = list(state.pending_descriptors)

    offered = list(initial_offered_list)
    added, _, blocked = expand_pending_descriptors(
        pending=state.pending_descriptors,
        offered=offered,
        expansion_allowance=expansion_allowance,
    )
    expansion_turns_used = 1 if added else 0
    if can_expand_recovery_schemas(max_tool_turns, current_turn=1) and added:
        recovered_tool_invocation_turns = 1
    else:
        recovered_tool_invocation_turns = 0

    return _recovery_result(
        initial_selected=initial_selected,
        initial_offered=initial_offered_list,
        final_offered=offered,
        matched=matched,
        expanded=added,
        blocked=blocked,
        search_attempted=search_attempted,
        search_succeeded=search_succeeded,
        search_turns_used=search_turns_used,
        expansion_turns_used=expansion_turns_used,
        recovered_tool_invocation_turns=recovered_tool_invocation_turns,
        expected=expected,
    )
