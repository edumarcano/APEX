"""Explicit local Agent command bundles and availability resolution."""

from __future__ import annotations

import os

from dataclasses import dataclass

from core.agent.capabilities import (
    CapabilityDescriptor,
    get_capability_descriptor,
    list_agent_capabilities,
)
from core.agent.routing.families import CAPABILITY_FAMILIES, get_family
from core.agent.tool_schemas import descriptor_to_openai_schema, estimate_json_tokens
from core.agent.types import LocalCommandStatus, LocalToolScope

_LOCAL_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The concise web search query.",
            "minLength": 1,
        },
        "count": {
            "type": "integer",
            "description": "Maximum results to return.",
            "minimum": 1,
            "maximum": 10,
            "default": 5,
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LocalCommandDefinition:
    key: LocalToolScope
    label: str
    description: str
    family_key: str

    @property
    def command(self) -> str:
        return f"/{self.key}"


@dataclass(frozen=True)
class ResolvedLocalCommand:
    scope: LocalToolScope
    descriptors: tuple[CapabilityDescriptor, ...]
    missing_tool_names: tuple[str, ...]


def _build_command_definitions() -> tuple[LocalCommandDefinition, ...]:
    definitions: list[LocalCommandDefinition] = []
    for family in CAPABILITY_FAMILIES:
        if not family.local_command_enabled:
            continue
        definitions.append(
            LocalCommandDefinition(
                key=family.key,  # type: ignore[arg-type]
                label=family.label,
                description=family.description,
                family_key=family.key,
            )
        )
    definitions.append(
        LocalCommandDefinition(
            key="none",
            label="No Tools",
            description="Force a tool-free local turn.",
            family_key="none",
        )
    )
    return tuple(definitions)


LOCAL_COMMAND_DEFINITIONS: tuple[LocalCommandDefinition, ...] = _build_command_definitions()

_DEFINITIONS_BY_KEY = {definition.key: definition for definition in LOCAL_COMMAND_DEFINITIONS}


def _ordered_family_tool_names(family_key: str) -> tuple[str, ...]:
    family = get_family(family_key)
    if family is None or family_key == "none":
        return ()
    priority = list(family.tool_priority)
    priority_set = set(priority)
    registered = [
        descriptor.name
        for descriptor in list_agent_capabilities()
        if descriptor.routing_family == family_key
        and descriptor.expose_to_agent
        and descriptor.risk == "read"
    ]
    ordered: list[str] = [name for name in priority if name in registered]
    for name in sorted(registered):
        if name not in priority_set:
            ordered.append(name)
    return tuple(ordered)


def project_local_descriptor(
    scope: LocalToolScope,
    descriptor: CapabilityDescriptor,
) -> CapabilityDescriptor:
    """Return a smaller model-facing schema without changing the registry."""
    if scope == "search" and descriptor.name == "brave_brave_web_search":
        return descriptor.model_copy(
            update={
                "description": (
                    "Search the public web for current information. Use a concise "
                    "query and request no more results than needed."
                ),
                "input_schema": _LOCAL_SEARCH_SCHEMA,
            }
        )
    return descriptor


def _project_local_descriptor(
    scope: LocalToolScope,
    descriptor: CapabilityDescriptor,
) -> CapabilityDescriptor:
    return project_local_descriptor(scope, descriptor)


def project_local_descriptors(
    scope: LocalToolScope | None,
    descriptors: tuple[CapabilityDescriptor, ...] | list[CapabilityDescriptor],
) -> tuple[CapabilityDescriptor, ...]:
    """Apply local schema projections to routed or command-resolved descriptors."""
    if scope is None:
        return tuple(descriptors)
    return tuple(_project_local_descriptor(scope, descriptor) for descriptor in descriptors)


def estimate_schema_tokens(descriptors: list[CapabilityDescriptor]) -> int:
    if not descriptors:
        return 0
    return estimate_json_tokens(
        [descriptor_to_openai_schema(descriptor) for descriptor in descriptors]
    )


def _estimate_schema_tokens(descriptors: list[CapabilityDescriptor]) -> int:
    return estimate_schema_tokens(descriptors)


def resolve_local_command(
    scope: LocalToolScope,
) -> ResolvedLocalCommand:
    definition = _DEFINITIONS_BY_KEY[scope]
    if definition.family_key == "none":
        return ResolvedLocalCommand(
            scope=scope,
            descriptors=(),
            missing_tool_names=(),
        )

    tool_names = _ordered_family_tool_names(definition.family_key)
    descriptors: list[CapabilityDescriptor] = []
    missing: list[str] = []
    for tool_name in tool_names:
        descriptor = get_capability_descriptor(tool_name)
        if descriptor is None or not descriptor.expose_to_agent:
            missing.append(tool_name)
        else:
            descriptors.append(_project_local_descriptor(scope, descriptor))
    return ResolvedLocalCommand(
        scope=scope,
        descriptors=tuple(descriptors),
        missing_tool_names=tuple(missing),
    )


def list_local_command_statuses() -> list[LocalCommandStatus]:
    statuses: list[LocalCommandStatus] = []
    for definition in LOCAL_COMMAND_DEFINITIONS:
        resolution = resolve_local_command(definition.key)
        tool_names = _ordered_family_tool_names(definition.family_key)
        todo_not_configured = definition.key == "todo" and not os.getenv(
            "MICROSOFT_TODO_CLIENT_ID", ""
        ).strip()
        if definition.key == "none":
            available = True
            unavailable_reason = None
        else:
            available = not resolution.missing_tool_names and not todo_not_configured
            unavailable_reason = None
            if todo_not_configured:
                unavailable_reason = "Microsoft To Do is not configured."
            elif not available:
                unavailable_reason = (
                    "Required provider tools are not currently connected."
                )
        statuses.append(
            LocalCommandStatus(
                key=definition.key,
                command=definition.command,
                label=definition.label,
                description=definition.description,
                tool_count=len(tool_names) if definition.key != "none" else 0,
                estimated_schema_tokens=_estimate_schema_tokens(
                    list(resolution.descriptors)
                ),
                available=available,
                unavailable_reason=unavailable_reason,
            )
        )
    return statuses
