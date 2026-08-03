"""Agent-specific APEX capability and provider-hosted tool policies."""

from __future__ import annotations

from collections.abc import Iterable

from core.agent.capabilities import CapabilityDescriptor


_ACINONYX_NATIVE_TOOLS = frozenset(
    {
        "get_weather_forecast",
        "get_f1_driver_standings",
        "get_f1_season_calendar",
    }
)
_ACINONYX_MCP_PREFIXES = ("brave_", "alphavantage_")


def filter_agent_capabilities(
    agent_key: str,
    capabilities: Iterable[CapabilityDescriptor],
) -> list[CapabilityDescriptor]:
    """Return the capabilities that a agent may discover and invoke.

    Production cloud Agents retain the complete APEX read-capability surface.
    Acinonyx is an explicit allowlist so newly registered personal or private MCP
    capabilities fail closed without requiring policy updates.
    """
    available = list(capabilities)
    if agent_key != "acinonyx":
        return available
    return [
        descriptor
        for descriptor in available
        if descriptor.name in _ACINONYX_NATIVE_TOOLS
        or descriptor.name.startswith(_ACINONYX_MCP_PREFIXES)
    ]


def hosted_tools_for_agent(
    agent_key: str,
    *,
    neofelis_google_search_enabled: bool,
    neofelis_google_maps_enabled: bool = True,
    delphinus_x_search_enabled: bool = True,
    orcinus_x_search_enabled: bool = True,
) -> frozenset[str]:
    """Resolve provider-hosted grounding independently from APEX tools."""
    if agent_key == "neofelis":
        tools = set()
        if neofelis_google_search_enabled:
            tools.add("google_search")
        if neofelis_google_maps_enabled:
            tools.add("google_maps")
        return frozenset(tools)
    if agent_key == "delphinus" and delphinus_x_search_enabled:
        return frozenset({"x_search"})
    if agent_key == "orcinus" and orcinus_x_search_enabled:
        return frozenset({"x_search"})
    return frozenset()
