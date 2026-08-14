"""Provider-neutral Agent tool catalog and grouping metadata.

The capability registry remains the source of truth for descriptors, schemas,
risk, exposure flags, and handlers.  This module only supplies stable grouping
metadata and joins registered capabilities with MCP configuration/runtime
state for the selector UI.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from core.agent.capabilities import (
    CapabilityDescriptor,
    get_capability_descriptor,
    list_agent_capabilities,
    namespaced_capability_name,
)
from core.agent.tool_policies import filter_agent_capabilities, hosted_tools_for_agent
from core.agent.tool_schemas import (
    descriptor_to_openai_schema,
    estimate_json_tokens,
    project_descriptor_for_agent,
)
from core.agent.types import (
    AgentKey,
    ToolCatalogGroup,
    ToolCatalogResponse,
    ToolCatalogTool,
    ToolProfileMetadata,
)
from core.config import DEMO_MODE, PROJECT_ROOT
from core.mcp import get_mcp_manager, load_mcp_config
from core.mcp.models import McpRuntimeConfig, McpServerConfig


@dataclass(frozen=True, slots=True)
class ApexToolFamily:
    """Curated grouping metadata for native APEX capabilities."""

    id: str
    label: str
    description: str
    tool_names: tuple[str, ...]


APEX_TOOL_FAMILIES: tuple[ApexToolFamily, ...] = (
    ApexToolFamily(
        "schedule",
        "Schedule",
        "Calendar events and pending reminders.",
        ("get_upcoming_calendar_events", "get_active_reminders"),
    ),
    ApexToolFamily(
        "weather",
        "Weather",
        "Configured-location forecast up to five days.",
        ("get_weather_forecast",),
    ),
    ApexToolFamily(
        "formula_1",
        "Formula 1",
        "Driver standings and season race calendar.",
        ("get_f1_driver_standings", "get_f1_season_calendar"),
    ),
    ApexToolFamily(
        "mail",
        "Mail",
        "Search Gmail and retrieve a selected message.",
        ("search_gmail", "get_gmail_message"),
    ),
    ApexToolFamily(
        "web_search",
        "Web Search",
        "Search capabilities from connected public-web providers.",
        (),
    ),
    ApexToolFamily(
        "market",
        "Market",
        "Quotes, symbols, company details, time series, and market news.",
        (),
    ),
    ApexToolFamily(
        "briefings",
        "Briefings",
        "Recent persisted APEX briefing history.",
        ("get_briefing_history",),
    ),
    ApexToolFamily(
        "microsoft_todo",
        "Microsoft To Do",
        "Microsoft To Do lists, tasks, and approval-gated task actions.",
        (
            "list_microsoft_todo_lists",
            "list_microsoft_todo_tasks",
            "create_microsoft_todo_task",
            "update_microsoft_todo_task",
            "complete_microsoft_todo_task",
            "reopen_microsoft_todo_task",
            "delete_microsoft_todo_task",
        ),
    ),
)

_FAMILY_BY_TOOL: dict[str, str] = {
    tool_name: family.id
    for family in APEX_TOOL_FAMILIES
    for tool_name in family.tool_names
}
_FAMILY_BY_TOOL.update(
    {
        # These are optional category metadata for filtering, diagnostics, and
        # future provider substitution. MCP capabilities still render only in
        # their server group.
        "brave_brave_web_search": "web_search",
        "brave_brave_news_search": "web_search",
        "alphavantage_symbol_search": "market",
        "alphavantage_global_quote": "market",
        "alphavantage_time_series_daily": "market",
        "alphavantage_company_overview": "market",
        "alphavantage_news_sentiment": "market",
    }
)

_KNOWN_MCP_SERVER_IDS = frozenset(("github", "brave", "alphavantage"))
_NAME_SANITIZE = re.compile(r"[^a-z0-9_]+")


def _normalized_remote_name(name: str) -> str:
    """Mirror MCP manager's stable remote-name normalization."""
    lowered = name.strip().lower().replace("-", "_").replace(".", "_")
    cleaned = _NAME_SANITIZE.sub("_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return "tool"
    if not cleaned[0].isalpha():
        return f"tool_{cleaned}"
    return cleaned


def server_id_for_tool(name: str) -> str | None:
    """Return the MCP namespace for a namespaced capability, if known."""
    prefix = name.split("_", 1)[0] if "_" in name else ""
    return prefix if prefix in _KNOWN_MCP_SERVER_IDS else None


def family_for_tool(name: str) -> str | None:
    """Return optional category metadata for a capability."""
    return _FAMILY_BY_TOOL.get(name)


def _category_for_tool(name: str, source_id: str | None = None) -> str | None:
    """Return category metadata, including configured MCP aliases."""
    category = family_for_tool(name)
    if category is not None:
        return category
    return {
        "brave": "web_search",
        "alphavantage": "market",
    }.get(source_id or "")


def _configured_mcp_tools(
    config: McpRuntimeConfig,
) -> dict[str, tuple[str, McpServerConfig, str]]:
    """Return configured allowlisted tool names keyed by stable capability name."""
    configured: dict[str, tuple[str, McpServerConfig, str]] = {}
    for server_id, server in config.servers.items():
        for remote_name in server.tool_allowlist:
            try:
                capability_name = namespaced_capability_name(
                    server_id, _normalized_remote_name(remote_name)
                )
            except ValueError:
                continue
            configured[capability_name] = (server_id, server, remote_name)
    return configured


def _mcp_availability(
    capability_name: str,
    *,
    config: McpRuntimeConfig,
    configured: dict[str, tuple[str, McpServerConfig, str]],
) -> tuple[bool, str | None]:
    """Check runtime connection and persistent allowlist without changing MCP."""
    configured_tool = configured.get(capability_name)
    if configured_tool is None:
        return False, "The tool is not present in the persistent MCP allowlist."
    configured_server_id, server_config, remote_name = configured_tool
    server_id = server_id_for_tool(capability_name) or configured_server_id
    if not config.enabled or not server_config.enabled:
        return False, "The MCP server is disabled in runtime settings."

    manager = get_mcp_manager()
    if manager is None:
        return False, "The MCP server is disconnected from the APEX runtime."

    try:
        snapshot = manager.status_snapshot()
        server_status = next(
            (server for server in snapshot.servers if server.id == server_id), None
        )
    except Exception:
        server_status = None

    if server_status is None:
        return False, "The MCP server is not connected to the APEX runtime."
    if server_status.status != "connected":
        return False, server_status.reason or "The MCP server is unavailable."
    if capability_name not in server_status.registered_tools:
        return (
            False,
            f"MCP tool {remote_name!r} was not discovered or registered.",
        )
    return True, None


def _native_availability(name: str) -> tuple[bool, str | None]:
    """Resolve native availability from local configuration and cached health.

    Catalog construction must stay read-only: this function only inspects
    environment/configuration, persisted credential markers, and the latest
    in-memory connector snapshot. It never authenticates or calls a provider.
    """
    connector_name = {
        "get_weather_forecast": "weather",
        "get_upcoming_calendar_events": "calendar",
        "search_gmail": "email",
        "get_gmail_message": "email",
    }.get(name)
    if connector_name is not None:
        try:
            from core.telemetry.service import get_telemetry_service

            snapshot = get_telemetry_service().latest()
            health = (
                snapshot.modules.get(connector_name) if snapshot is not None else None
            )
        except Exception:
            health = None
        if health is not None and health.status in {"unavailable", "disabled"}:
            reason = health.reason_code.replace("_", " ").strip()
            if reason and reason != "ok":
                return False, f"{connector_name.title()} is unavailable ({reason})."

    if name == "get_weather_forecast" and not os.getenv("TARGET_LOCATION", "").strip():
        return False, "Weather is not configured (TARGET_LOCATION is missing)."

    if name in {"get_upcoming_calendar_events", "search_gmail", "get_gmail_message"}:
        credentials_path = PROJECT_ROOT / "credentials.json"
        token_path = PROJECT_ROOT / "token.json"
        if not credentials_path.exists():
            return False, "Google Workspace credentials are not configured."
        if not token_path.exists():
            return False, "Google Workspace authentication is required."

    if name in {"list_microsoft_todo_lists", "list_microsoft_todo_tasks"}:
        if not os.getenv("MICROSOFT_TODO_CLIENT_ID", "").strip():
            return False, "Microsoft To Do is not configured."
        try:
            from clients.microsoft_auth import get_microsoft_auth_service

            auth_service = get_microsoft_auth_service()
            if auth_service is not None:
                auth_status = auth_service.status_snapshot()
                if auth_status.state == "authentication-required":
                    return False, "Microsoft To Do authentication is required."
                if auth_status.state in {"disconnected", "degraded", "not-configured"}:
                    return False, (
                        auth_status.auth_error_message
                        or "Microsoft To Do is disconnected."
                    )
        except Exception:
            return False, "Microsoft To Do runtime is unavailable."

    return True, None


def _profile_metadata() -> list[ToolProfileMetadata]:
    # Import lazily to keep the settings -> agent model dependency acyclic.
    from core.agent.tool_profiles import list_tool_profiles

    return [
        ToolProfileMetadata(
            id=profile.id,
            name=profile.name,
            description=profile.description,
            tool_names=list(profile.tool_names),
            built_in=profile.built_in,
            dynamic=profile.dynamic,
        )
        for profile in list_tool_profiles()
    ]


def _default_profile(agent_key: str) -> tuple[str, str]:
    from core.agent.tool_profiles import default_profile_for_agent

    profile = default_profile_for_agent(agent_key)
    return profile.id, profile.name


def build_tool_catalog(agent_key: str = "panthera") -> ToolCatalogResponse:
    """Build the complete provider-neutral catalog for one Apex Agent."""
    from core.agent.catalog import AGENT_SPECS

    if agent_key not in AGENT_SPECS:
        raise ValueError(f"Unknown Agent: {agent_key!r}")

    from core.settings import get_settings_store

    settings = get_settings_store().get_snapshot()
    hosted_tools = hosted_tools_for_agent(
        agent_key,
        neofelis_google_search_enabled=settings.ask_apex.neofelis_google_search_enabled,
        neofelis_google_maps_enabled=settings.ask_apex.neofelis_google_maps_enabled,
        delphinus_x_search_enabled=settings.ask_apex.delphinus_x_search_enabled,
        orcinus_x_search_enabled=settings.ask_apex.orcinus_x_search_enabled,
    )
    config = load_mcp_config()
    configured_mcp = _configured_mcp_tools(config)
    descriptors = {
        descriptor.name: descriptor for descriptor in list_agent_capabilities()
    }
    for capability_name in configured_mcp:
        descriptor = get_capability_descriptor(capability_name)
        if descriptor is not None:
            descriptors[capability_name] = descriptor

    from core.actions.runtime import get_action_service

    action_service = get_action_service()

    def action_allowed(descriptor: CapabilityDescriptor) -> bool:
        return (
            not DEMO_MODE
            and descriptor.origin == "native"
            and descriptor.risk in {"write", "destructive"}
            and action_service is not None
            and action_service.supports(descriptor.name)
        )

    allowed = {
        descriptor.name
        for descriptor in filter_agent_capabilities(agent_key, descriptors.values())
        if descriptor.expose_to_agent
        and (descriptor.risk == "read" or action_allowed(descriptor))
    }

    catalog_tools: dict[str, ToolCatalogTool] = {}
    for name, descriptor in descriptors.items():
        configured = configured_mcp.get(name)
        server_id = (
            configured[0]
            if configured is not None
            else server_id_for_tool(name)
        )
        if descriptor.origin == "mcp" and server_id is None:
            server_id = server_id_for_tool(name) or "mcp"
        source_id = server_id or "apex"
        if descriptor.origin == "mcp":
            available, unavailable_reason = _mcp_availability(
                name, config=config, configured=configured_mcp
            )
        else:
            available, unavailable_reason = _native_availability(name)

        allowed_for_agent = name in allowed
        if not allowed_for_agent:
            unavailable_reason = (
                "This tool is outside the selected Agent policy."
                if descriptor.name in descriptors
                else unavailable_reason
            )
        if descriptor.risk != "read" and not action_allowed(descriptor):
            allowed_for_agent = False
            unavailable_reason = (
                "This tool risk is not permitted for Agent turns."
                if descriptor.origin == "mcp" or DEMO_MODE
                else "This action capability has no registered executor and verifier."
            )

        projected = project_descriptor_for_agent(agent_key, descriptor)
        schema_tokens = estimate_json_tokens(
            descriptor_to_openai_schema(projected)
        )
        family_id = _category_for_tool(name, source_id)
        catalog_tools[name] = ToolCatalogTool(
            name=name,
            label=descriptor.title,
            description=descriptor.description,
            origin=descriptor.origin,
            source_id=source_id,
            apex_family=family_id,
            risk=descriptor.risk,
            available=available and allowed_for_agent,
            unavailable_reason=unavailable_reason,
            estimated_schema_tokens=schema_tokens,
            allowed_for_agent=allowed_for_agent,
        )

    # Configured-but-not-discovered MCP tools remain visible as unavailable
    # entries so stale selections and persistent references are never erased.
    for name, (server_id, server_config, remote_name) in configured_mcp.items():
        if name in catalog_tools:
            continue
        _available, unavailable_reason = _mcp_availability(
            name, config=config, configured=configured_mcp
        )
        risk = server_config.tool_risks.get(remote_name, "read")
        allowed_for_agent = (
            risk == "read"
            and (
                agent_key != "acinonyx"
                or name.startswith(("brave_", "alphavantage_"))
            )
        )
        if not allowed_for_agent:
            unavailable_reason = (
                "This tool is outside the selected Agent policy."
                if risk == "read"
                else "This tool risk is not permitted for Agent turns."
            )
        catalog_tools[name] = ToolCatalogTool(
            name=name,
            label=remote_name.replace("_", " ").replace("-", " ").title(),
            description=f"MCP tool {remote_name} from server {server_id}.",
            origin="mcp",
            source_id=server_id,
            risk=risk,
            available=False,
            unavailable_reason=unavailable_reason
            or "The MCP tool has not been discovered yet.",
            estimated_schema_tokens=0,
            allowed_for_agent=allowed_for_agent,
        )

    # Keep explicit profile references visible even when a capability vanished
    # from both the registry and MCP configuration.
    for profile in _profile_metadata():
        for name in profile.tool_names:
            if name in catalog_tools:
                continue
            server_id = server_id_for_tool(name)
            origin = "mcp" if server_id is not None else "native"
            allowed_for_agent = (
                agent_key != "acinonyx"
                or name.startswith(("brave_", "alphavantage_"))
            )
            catalog_tools[name] = ToolCatalogTool(
                name=name,
                label=name.replace("_", " ").title(),
                description=(
                    "This profile references a capability that is not currently "
                    "registered or configured."
                ),
                origin=origin,  # type: ignore[arg-type]
                source_id=server_id or "apex",
                apex_family=_category_for_tool(name, server_id),
                risk="read",
                available=False,
                unavailable_reason=(
                    "This capability is no longer registered or configured."
                ),
                estimated_schema_tokens=0,
                allowed_for_agent=allowed_for_agent,
            )

    for tool in catalog_tools.values():
        if tool.origin == "mcp" and tool.apex_family is None:
            tool.apex_family = _category_for_tool(tool.name, tool.source_id)

    groups: list[ToolCatalogGroup] = []

    for family in APEX_TOOL_FAMILIES:
        tools = [
            catalog_tools[name]
            for name in catalog_tools
            if catalog_tools[name].origin == "native"
            and catalog_tools[name].apex_family == family.id
        ]
        if not tools:
            continue
        groups.append(
            ToolCatalogGroup(
                id=f"family:{family.id}",
                label=family.label,
                kind="apex_family",
                tool_count=len(tools),
                schema_token_subtotal=sum(
                    tool.estimated_schema_tokens for tool in tools
                ),
                tools=tools,
            )
        )

    mcp_groups: dict[str, list[ToolCatalogTool]] = {}
    for tool in catalog_tools.values():
        if tool.origin != "mcp" or not tool.source_id:
            continue
        server_id = tool.source_id
        mcp_groups.setdefault(server_id, []).append(tool)
    for server_id in sorted(mcp_groups):
        tools = mcp_groups[server_id]
        groups.append(
            ToolCatalogGroup(
                id=f"mcp:{server_id}",
                label=server_id.title(),
                kind="mcp_server",
                tool_count=len(tools),
                schema_token_subtotal=sum(
                    tool.estimated_schema_tokens for tool in tools
                ),
                tools=tools,
            )
        )
    ungrouped_tools = [
        tool
        for tool in catalog_tools.values()
        if tool.origin == "native" and tool.apex_family is None
    ]
    if ungrouped_tools:
        groups.append(
            ToolCatalogGroup(
                id="family:other",
                label="Other",
                kind="apex_family",
                tool_count=len(ungrouped_tools),
                schema_token_subtotal=sum(
                    tool.estimated_schema_tokens for tool in ungrouped_tools
                ),
                tools=ungrouped_tools,
            )
        )

    profile_id, profile_name = _default_profile(agent_key)
    default_tools = [
        tool.name
        for tool in catalog_tools.values()
        if tool.available
    ]
    if profile_id != "all_allowed":
        from core.agent.tool_profiles import resolve_profile_names

        default_tools = resolve_profile_names(
            agent_key, profile_id, available_names=set(default_tools)
        )

    context_window: int | None = None
    reserved_response_tokens: int | None = None
    if AGENT_SPECS[agent_key].runtime == "local":
        from core.agent.catalog import (
            build_concrete_agent,
            local_context_window_for_agent,
            local_reasoning_mode_for_agent,
        )

        profile = build_concrete_agent(
            agent_key,
            native_effort=None,
            local_context_window=local_context_window_for_agent(agent_key),
            local_reasoning_mode=local_reasoning_mode_for_agent(agent_key),
        )
        context_window = profile.context_window
        reserved_response_tokens = profile.final_answer_max_tokens

    return ToolCatalogResponse(
        agent=agent_key,  # type: ignore[arg-type]
        groups=groups,
        tools=list(catalog_tools.values()),
        profiles=_profile_metadata(),
        default_profile_id=profile_id,
        default_profile_name=profile_name,
        default_selected_tool_names=default_tools,
        provider_hosted_tools=sorted(hosted_tools),
        context_window=context_window,
        reserved_response_tokens=reserved_response_tokens,
    )
