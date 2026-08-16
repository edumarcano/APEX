"""Agent-specific APEX capability and provider-hosted tool policies."""

from __future__ import annotations

from collections.abc import Iterable

from core.agent.capabilities import CapabilityDescriptor
from core.agent.model_catalog import ModelProfile
from core.agent.sandbox_policy import filter_sandbox_capabilities, is_sandbox_active


def filter_agent_capabilities(
    agent_key: str,
    capabilities: Iterable[CapabilityDescriptor],
    *,
    sandbox_mode: bool = False,
    dev_mode: bool = False,
) -> list[CapabilityDescriptor]:
    """Return the capabilities that an Agent may discover and invoke."""
    available = list(capabilities)
    if is_sandbox_active(sandbox_mode=sandbox_mode, dev_mode=dev_mode):
        return filter_sandbox_capabilities(available)
    return available


def hosted_tools_for_model(
    model_profile: ModelProfile,
    *,
    google_search_enabled: bool,
    google_maps_enabled: bool = True,
    x_search_enabled: bool = True,
) -> frozenset[str]:
    """Resolve provider-hosted grounding from model capabilities and settings."""
    tools: set[str] = set()
    caps = model_profile.hosted_capabilities
    if "google_search" in caps and google_search_enabled:
        tools.add("google_search")
    if "google_maps" in caps and google_maps_enabled:
        tools.add("google_maps")
    if "x_search" in caps and x_search_enabled:
        tools.add("x_search")
    return frozenset(tools)


def hosted_tools_for_agent(
    agent_key: str,
    *,
    google_search_enabled: bool = True,
    google_maps_enabled: bool = True,
    x_search_enabled: bool = True,
) -> frozenset[str]:
    """Resolve provider-hosted tools for Panthera's selected cloud model."""
    if agent_key != "panthera":
        return frozenset()
    from core.agent.catalog import resolve_selected_model_profile

    return hosted_tools_for_model(
        resolve_selected_model_profile(agent_key),
        google_search_enabled=google_search_enabled,
        google_maps_enabled=google_maps_enabled,
        x_search_enabled=x_search_enabled,
    )


def effective_native_tools(
    model_profile: ModelProfile,
    *,
    google_search_enabled: bool,
    google_maps_enabled: bool,
    x_search_enabled: bool,
) -> dict[str, bool]:
    """Return hosted-tool availability and effective enabled state for the HUD."""
    enabled = hosted_tools_for_model(
        model_profile,
        google_search_enabled=google_search_enabled,
        google_maps_enabled=google_maps_enabled,
        x_search_enabled=x_search_enabled,
    )
    return {
        "google_search": "google_search" in enabled,
        "google_maps": "google_maps" in enabled,
        "x_search": "x_search" in enabled,
    }
