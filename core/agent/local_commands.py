"""Explicit local assistant command bundles and availability resolution."""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.capabilities import (
    CapabilityDescriptor,
    get_capability_descriptor,
)
from core.agent.tool_schemas import descriptor_to_openai_schema, estimate_json_tokens
from core.agent.types import LocalCommandStatus, LocalToolScope


@dataclass(frozen=True)
class LocalCommandDefinition:
    key: LocalToolScope
    label: str
    description: str
    tool_names: tuple[str, ...]

    @property
    def command(self) -> str:
        return f"/{self.key}"


@dataclass(frozen=True)
class ResolvedLocalCommand:
    scope: LocalToolScope
    descriptors: tuple[CapabilityDescriptor, ...]
    missing_tool_names: tuple[str, ...]


LOCAL_COMMAND_DEFINITIONS: tuple[LocalCommandDefinition, ...] = (
    LocalCommandDefinition(
        key="schedule",
        label="Schedule",
        description="Calendar events and pending reminders.",
        tool_names=("get_upcoming_calendar_events", "get_active_reminders"),
    ),
    LocalCommandDefinition(
        key="weather",
        label="Weather",
        description="Configured-location forecast up to five days.",
        tool_names=("get_weather_forecast",),
    ),
    LocalCommandDefinition(
        key="f1",
        label="Formula 1",
        description="Driver standings and season race calendar.",
        tool_names=("get_f1_driver_standings", "get_f1_season_calendar"),
    ),
    LocalCommandDefinition(
        key="mail",
        label="Mail",
        description="Search Gmail and retrieve a selected message.",
        tool_names=("search_gmail", "get_gmail_message"),
    ),
    LocalCommandDefinition(
        key="search",
        label="Web Search",
        description="Brave web search with a compact local schema.",
        tool_names=("brave_brave_web_search",),
    ),
    LocalCommandDefinition(
        key="market",
        label="Market",
        description="Quotes, symbols, company details, time series, and market news.",
        tool_names=(
            "alphavantage_time_series_daily",
            "alphavantage_global_quote",
            "alphavantage_symbol_search",
            "alphavantage_news_sentiment",
            "alphavantage_company_overview",
        ),
    ),
    LocalCommandDefinition(
        key="briefings",
        label="Briefings",
        description="Recent persisted APEX briefing history.",
        tool_names=("get_briefing_history",),
    ),
)

_DEFINITIONS_BY_KEY = {definition.key: definition for definition in LOCAL_COMMAND_DEFINITIONS}

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


def _project_local_descriptor(
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


def _estimate_schema_tokens(descriptors: list[CapabilityDescriptor]) -> int:
    if not descriptors:
        return 0
    return estimate_json_tokens(
        [descriptor_to_openai_schema(descriptor) for descriptor in descriptors]
    )


def resolve_local_command(
    scope: LocalToolScope,
) -> ResolvedLocalCommand:
    definition = _DEFINITIONS_BY_KEY[scope]
    descriptors: list[CapabilityDescriptor] = []
    missing: list[str] = []
    for tool_name in definition.tool_names:
        descriptor = get_capability_descriptor(tool_name)
        if descriptor is None or not descriptor.expose_to_assistant:
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
        available = not resolution.missing_tool_names
        statuses.append(
            LocalCommandStatus(
                key=definition.key,
                command=definition.command,
                label=definition.label,
                description=definition.description,
                tool_count=len(definition.tool_names),
                estimated_schema_tokens=_estimate_schema_tokens(
                    list(resolution.descriptors)
                ),
                available=available,
                unavailable_reason=(
                    None
                    if available
                    else "Required provider tools are not currently connected."
                ),
            )
        )
    return statuses
