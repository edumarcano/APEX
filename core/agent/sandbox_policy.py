"""DEV_MODE sandbox policy overlay for Panthera and Felis."""

from __future__ import annotations

from collections.abc import Iterable

from core.agent.capabilities import CapabilityDescriptor

_SANDBOX_NATIVE_TOOLS = frozenset(
    {
        "get_weather_forecast",
        "get_f1_driver_standings",
        "get_f1_season_calendar",
        "search_apex_docs",
    }
)
_SANDBOX_MCP_PREFIXES = ("brave_", "alphavantage_")


def is_sandbox_active(*, sandbox_mode: bool, dev_mode: bool) -> bool:
    """Return whether sandbox restrictions apply to the current query."""
    return dev_mode and sandbox_mode


def filter_sandbox_capabilities(
    capabilities: Iterable[CapabilityDescriptor],
) -> list[CapabilityDescriptor]:
    """Return the capability allowlist for sandbox-mode queries."""
    return [
        descriptor
        for descriptor in capabilities
        if is_sandbox_capability_allowed(descriptor.name)
    ]


def is_sandbox_capability_allowed(name: str) -> bool:
    """Return whether a capability name is safe for sandbox-mode queries."""
    return name in _SANDBOX_NATIVE_TOOLS or name.startswith(_SANDBOX_MCP_PREFIXES)
