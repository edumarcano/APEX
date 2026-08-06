"""Canonical Agent tool selection, policy intersection, and schema projection."""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.capabilities import CapabilityDescriptor, get_capability_descriptor
from core.agent.tool_catalog import build_tool_catalog
from core.agent.tool_profiles import (
    default_profile_names,
    get_tool_profile,
    resolve_profile_names,
)
from core.agent.tool_schemas import (
    descriptor_to_openai_schema,
    estimate_json_tokens,
    project_descriptor_for_agent,
)
from core.agent.types import (
    ToolSelectionDiagnostics,
    ToolSelectionFailure,
    ToolCatalogResponse,
)


@dataclass(frozen=True, slots=True)
class ResolvedToolSelection:
    """Immutable selection result shared by catalog, preflight, and execution."""

    descriptors: tuple[CapabilityDescriptor, ...]
    diagnostics: ToolSelectionDiagnostics
    catalog: ToolCatalogResponse

    @property
    def failures(self) -> tuple[ToolSelectionFailure, ...]:
        return tuple(self.diagnostics.rejected_tools)


def _failure_code(reason: str, *, allowed: bool) -> str:
    lowered = reason.lower()
    if not allowed:
        if "risk" in lowered:
            return "risk-rejected"
        if "exposed" in lowered or "policy" in lowered:
            return "policy"
        return "not-exposed"
    if "authentication" in lowered or "sign-in" in lowered:
        return "authentication-required"
    if "configuration" in lowered or "not configured" in lowered:
        return "configuration-required"
    if "allowlist" in lowered:
        return "mcp-not-allowlisted"
    if "disabled" in lowered:
        return "mcp-disabled"
    if "disconnected" in lowered or "connected" in lowered:
        return "mcp-disconnected"
    if "runtime" in lowered or "degraded" in lowered:
        return "runtime-unavailable"
    return "unavailable"


def _dedupe_names(names: list[str]) -> list[str]:
    """Normalize stable names without silently dropping invalid blank entries."""
    normalized: list[str] = []
    seen: set[str] = set()
    for name in names:
        candidate = name.strip()
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _requested_names(
    agent_key: str,
    selected_tool_names: list[str] | None,
    tool_profile_id: str | None,
    *,
    catalog: ToolCatalogResponse,
) -> tuple[list[str], str | None, str | None, ToolSelectionFailure | None]:
    """Resolve omitted selection versus an explicit empty selection."""
    available_names = {
        tool.name
        for tool in catalog.tools
        if tool.available and tool.allowed_for_agent
    }

    if selected_tool_names is not None:
        names = _dedupe_names(selected_tool_names)
        active_profile_id: str | None = None
        active_profile_name: str | None = None
        profile = get_tool_profile(tool_profile_id)
        if profile is not None:
            resolved_profile_names = resolve_profile_names(
                agent_key,
                profile.id,
                available_names=available_names,
            )
            if set(resolved_profile_names) == set(names):
                active_profile_id = profile.id
                active_profile_name = profile.name
        return names, active_profile_id, active_profile_name, None

    if tool_profile_id is None:
        profile, names = default_profile_names(
            agent_key,
            available_names=available_names,
        )
        return (
            _dedupe_names(names),
            profile.id,
            profile.name,
            None,
        )

    profile = get_tool_profile(tool_profile_id)
    if profile is None:
        return (
            [],
            None,
            None,
            ToolSelectionFailure(
                name=tool_profile_id.strip(),
                code="profile-invalid",
                reason="The requested tool profile does not exist.",
            ),
        )
    return (
        _dedupe_names(
            resolve_profile_names(
                agent_key,
                profile.id,
                available_names=available_names,
            )
        ),
        profile.id,
        profile.name,
        None,
    )


def resolve_selected_tools(
    agent_key: str,
    selected_tool_names: list[str] | None = None,
    *,
    tool_profile_id: str | None = None,
) -> ResolvedToolSelection:
    """Resolve explicit names through policy, exposure, runtime, and MCP state.

    No requested name is silently dropped.  Every invalid, unauthorized, or
    unavailable name is represented by a structured failure in the result.
    """
    catalog = build_tool_catalog(agent_key)
    requested, active_profile_id, active_profile_name, profile_failure = _requested_names(
        agent_key,
        selected_tool_names,
        tool_profile_id,
        catalog=catalog,
    )
    catalog_by_name = {tool.name: tool for tool in catalog.tools}
    descriptors: list[CapabilityDescriptor] = []
    failures: list[ToolSelectionFailure] = (
        [profile_failure] if profile_failure is not None else []
    )

    for name in requested:
        catalog_tool = catalog_by_name.get(name)
        if catalog_tool is None:
            failures.append(
                ToolSelectionFailure(
                    name=name,
                    code="invalid",
                    reason="The selected capability is not registered or catalogued.",
                )
            )
            continue
        if not catalog_tool.allowed_for_agent:
            reason = (
                catalog_tool.unavailable_reason
                or "This tool is outside the selected Agent policy."
            )
            failures.append(
                ToolSelectionFailure(
                    name=name,
                    code=_failure_code(reason, allowed=False),  # type: ignore[arg-type]
                    reason=reason,
                )
            )
            continue
        if not catalog_tool.available:
            reason = (
                catalog_tool.unavailable_reason
                or "The selected capability is currently unavailable."
            )
            failures.append(
                ToolSelectionFailure(
                    name=name,
                    code=_failure_code(reason, allowed=True),  # type: ignore[arg-type]
                    reason=reason,
                )
            )
            continue
        descriptor = get_capability_descriptor(name)
        if descriptor is None or not descriptor.expose_to_agent:
            failures.append(
                ToolSelectionFailure(
                    name=name,
                    code="not-exposed",
                    reason="The capability is not exposed to Agent turns.",
                )
            )
            continue
        if descriptor.risk != "read":
            failures.append(
                ToolSelectionFailure(
                    name=name,
                    code="risk-rejected",
                    reason="This tool risk is not permitted for Agent turns.",
                )
            )
            continue
        descriptors.append(project_descriptor_for_agent(agent_key, descriptor))

    selected_schema_tokens = (
        estimate_json_tokens(
            [descriptor_to_openai_schema(descriptor) for descriptor in descriptors]
        )
        if descriptors
        else 0
    )
    diagnostics = ToolSelectionDiagnostics(
        requested_tool_names=requested,
        offered_tool_names=[descriptor.name for descriptor in descriptors],
        rejected_tool_names=[failure.name for failure in failures],
        rejected_tools=failures,
        selected_schema_tokens=selected_schema_tokens,
        active_profile_id=active_profile_id,
        active_profile_name=active_profile_name,
    )
    return ResolvedToolSelection(
        descriptors=tuple(descriptors),
        diagnostics=diagnostics,
        catalog=catalog,
    )


def selection_as_response_fields(
    selection: ResolvedToolSelection,
) -> dict[str, object]:
    """Return compatibility fields alongside the canonical diagnostics object."""
    diagnostics = selection.diagnostics
    return {
        "resolved_tool_selection": diagnostics,
        "requested_tool_names": diagnostics.requested_tool_names,
        "offered_tool_names": diagnostics.offered_tool_names,
        "rejected_tool_names": diagnostics.rejected_tool_names,
        "selected_schema_tokens": diagnostics.selected_schema_tokens,
        "active_tool_profile_id": diagnostics.active_profile_id,
        "active_tool_profile_name": diagnostics.active_profile_name,
    }

