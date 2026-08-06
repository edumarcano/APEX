"""Policy-safe tool search recovery for incomplete capability routing."""

from __future__ import annotations

import contextvars
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from core.agent.capabilities import CapabilityDescriptor, CapabilityError, CapabilityErrorCategory
from core.agent.local_commands import estimate_schema_tokens
from core.agent.routing.families import CAPABILITY_FAMILIES, get_family
from core.agent.routing.rules import apply_routing_rules
from core.agent.routing.service import _family_eligible, _is_routable
from core.agent.tool_policies import filter_agent_capabilities

SEARCH_AVAILABLE_TOOLS_NAME = "search_available_tools"
_TOKEN = re.compile(r"[a-z0-9']+")
_DESCRIPTION_PREVIEW_CHARS = 160

_CURRENT_SEARCH_CATALOG: contextvars.ContextVar[
    tuple[CapabilityDescriptor, ...] | None
] = contextvars.ContextVar("tool_search_catalog", default=None)


@dataclass(frozen=True, slots=True)
class ToolSearchRecoveryConfig:
    """Bounded recovery settings for one agent request."""

    enabled: bool
    searchable_catalog: tuple[CapabilityDescriptor, ...]
    max_search_calls: int = 1
    max_result_families: int = 3
    max_capabilities_per_family: int = 3
    max_expansion_schema_tokens: int | None = None


@dataclass
class ToolSearchRecoveryState:
    """Mutable per-request recovery progress tracked by the agent loop."""

    config: ToolSearchRecoveryConfig
    search_calls: int = 0
    invoked: bool = False
    recovered_families: list[str] = field(default_factory=list)
    pending_descriptors: list[CapabilityDescriptor] = field(default_factory=list)
    expanded_tool_count: int = 0
    extra_turns: int = 0
    _offered_names: set[str] = field(default_factory=set)

    def register_offered(self, descriptors: Sequence[CapabilityDescriptor]) -> None:
        self._offered_names.update(descriptor.name for descriptor in descriptors)

    def queue_recovery_descriptors(self, output: dict[str, Any]) -> None:
        families = [
            match["family"]
            for match in output.get("matches", [])
            if isinstance(match, dict) and isinstance(match.get("family"), str)
        ]
        self.recovered_families.extend(families)
        for family in families:
            family_added = 0
            for descriptor in self.config.searchable_catalog:
                if descriptor.routing_family != family:
                    continue
                if descriptor.name in self._offered_names:
                    continue
                if descriptor.name == SEARCH_AVAILABLE_TOOLS_NAME:
                    continue
                if any(
                    pending.name == descriptor.name for pending in self.pending_descriptors
                ):
                    continue
                self.pending_descriptors.append(descriptor)
                family_added += 1
                if family_added >= self.config.max_capabilities_per_family:
                    break


def activate_search_catalog(
    catalog: Sequence[CapabilityDescriptor],
) -> contextvars.Token:
    return _CURRENT_SEARCH_CATALOG.set(tuple(catalog))


def deactivate_search_catalog(token: contextvars.Token) -> None:
    _CURRENT_SEARCH_CATALOG.reset(token)


def get_current_search_catalog() -> tuple[CapabilityDescriptor, ...] | None:
    return _CURRENT_SEARCH_CATALOG.get()


def build_searchable_catalog(
    capabilities: Sequence[CapabilityDescriptor],
    *,
    runtime: str,
    agent_key: str,
) -> tuple[CapabilityDescriptor, ...]:
    """Return read-only routable capabilities already allowed for this agent/runtime."""
    filtered = filter_agent_capabilities(agent_key, capabilities)
    return tuple(
        descriptor
        for descriptor in filtered
        if _is_routable(descriptor)
        and descriptor.routing_family is not None
        and _family_eligible(descriptor.routing_family, runtime)
        and descriptor.name != SEARCH_AVAILABLE_TOOLS_NAME
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
    history: Sequence[object] = (),
) -> list[str]:
    """Lexically rank searchable families for a recovery query."""
    query_tokens = Counter(_TOKEN.findall(query.lower()))
    if not query_tokens:
        return []
    families: dict[str, float] = {}
    rule_families = {
        match.family
        for match in apply_routing_rules(query, history)  # type: ignore[arg-type]
        if match.family != "none"
    }
    for descriptor in catalog:
        family_key = descriptor.routing_family
        if family_key is None:
            continue
        descriptor_score = _cosine_overlap(query_tokens, _descriptor_search_text(descriptor))
        family_score = _cosine_overlap(query_tokens, _family_search_text(family_key))
        families[family_key] = max(
            families.get(family_key, 0.0),
            descriptor_score,
            family_score * 0.9,
        )
    for family_key in rule_families:
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


def execute_tool_search(
    catalog: Sequence[CapabilityDescriptor],
    query: str,
    *,
    max_results: int,
    max_capabilities_per_family: int,
    history: Sequence[object] = (),
) -> dict[str, Any]:
    """Search a pre-filtered catalog and return compact family/capability metadata."""
    cleaned = query.strip()
    if not cleaned:
        raise CapabilityError(
            CapabilityErrorCategory.INVALID_INPUT,
            "Tool search requires a non-empty query.",
        )
    bounded_results = max(1, min(max_results, 5))
    ranked_families = rank_searchable_families(
        cleaned,
        catalog,
        max_results=bounded_results,
        history=history,
    )
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
    }


def search_available_tools(query: str, max_results: int = 3) -> dict[str, Any]:
    """Capability handler: search only the active request's searchable catalog."""
    catalog = get_current_search_catalog()
    if catalog is None:
        raise CapabilityError(
            CapabilityErrorCategory.UNAVAILABLE,
            "Tool search recovery is not active for this request.",
        )
    bounded_results = max(1, min(int(max_results), 5))
    return execute_tool_search(
        catalog,
        query,
        max_results=bounded_results,
        max_capabilities_per_family=3,
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
                    "description": "Maximum families to return, between 1 and 5.",
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
    schema_budget: int | None,
) -> tuple[list[CapabilityDescriptor], int]:
    """Append pending recovery descriptors up to the remaining schema budget."""
    if not pending:
        return [], 0
    added: list[CapabilityDescriptor] = []
    used_tokens = estimate_schema_tokens(offered)
    for descriptor in pending:
        tokens = estimate_schema_tokens([descriptor])
        if schema_budget is not None and used_tokens + tokens > schema_budget:
            break
        if any(existing.name == descriptor.name for existing in offered):
            continue
        offered.append(descriptor)
        added.append(descriptor)
        used_tokens += tokens
    return added, len(added)


def simulate_tool_search_recovery(
    *,
    prompt: str,
    initial_selected: set[str],
    expected: set[str],
    searchable_families: set[str],
    max_result_families: int = 3,
    history: Sequence[object] = (),
) -> tuple[set[str], bool, int, set[str]]:
    """Benchmark helper: recover missing families with one bounded search call."""
    if expected <= initial_selected:
        return initial_selected, False, 0, set()

    remaining = searchable_families - initial_selected
    catalog = tuple(
        CapabilityDescriptor(
            name=f"bench_{family}",
            title=family,
            description=family,
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=False,
            routing_family=family,
        )
        for family in sorted(remaining)
    )
    ranked = rank_searchable_families(
        prompt,
        catalog,
        max_results=max_result_families,
        history=history,
    )
    recovered = {family for family in ranked if family in remaining}
    final_selected = set(initial_selected)
    final_selected.update(recovered)
    false_positive = final_selected - expected
    invoked = bool(recovered) and not (expected <= initial_selected)
    extra_turns = 1 if invoked else 0
    return final_selected, invoked, extra_turns, false_positive
