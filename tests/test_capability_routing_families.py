"""Regression coverage for capability routing family taxonomy and assignments."""

from __future__ import annotations

import unittest

from core.agent.capabilities import (
    CapabilityDescriptor,
    get_capability_descriptor,
    list_agent_capabilities,
    register_capability,
    unregister_capability,
)
from core.agent.local_commands import (
    LOCAL_COMMAND_DEFINITIONS,
    resolve_local_command,
)
from core.agent.routing.families import CAPABILITY_FAMILIES, get_family
from core.agent.tools import register_native_capabilities

_EXPECTED_NATIVE_FAMILIES: dict[str, str] = {
    "get_weather_forecast": "weather",
    "get_f1_driver_standings": "f1",
    "get_f1_season_calendar": "f1",
    "get_upcoming_calendar_events": "schedule",
    "get_active_reminders": "schedule",
    "get_briefing_history": "briefings",
    "search_gmail": "mail",
    "get_gmail_message": "mail",
    "list_microsoft_todo_lists": "todo",
    "list_microsoft_todo_tasks": "todo",
}

_EXPECTED_MCP_PREFIX_FAMILIES: dict[str, str] = {
    "github_": "github",
    "brave_": "search",
    "alphavantage_": "market",
}


class CapabilityRoutingFamilyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        register_native_capabilities()

    def test_central_taxonomy_has_required_families(self) -> None:
        keys = {family.key for family in CAPABILITY_FAMILIES}
        self.assertEqual(
            keys,
            {
                "schedule",
                "weather",
                "f1",
                "mail",
                "search",
                "market",
                "briefings",
                "todo",
                "github",
                "none",
            },
        )

    def test_native_capabilities_map_to_expected_families(self) -> None:
        for name, expected_family in _EXPECTED_NATIVE_FAMILIES.items():
            descriptor = get_capability_descriptor(name)
            self.assertIsNotNone(descriptor, msg=name)
            assert descriptor is not None
            self.assertEqual(descriptor.routing_family, expected_family, msg=name)

    def test_no_descriptor_maps_to_more_than_one_family(self) -> None:
        family_by_name: dict[str, str] = {}
        for descriptor in list_agent_capabilities():
            family = descriptor.routing_family
            if family is None:
                continue
            self.assertNotIn(
                descriptor.name,
                family_by_name,
                msg=f"{descriptor.name} would map to multiple families",
            )
            family_by_name[descriptor.name] = family

    def test_known_mcp_prefix_assignments_when_present(self) -> None:
        for descriptor in list_agent_capabilities():
            if descriptor.origin != "mcp":
                continue
            matched_prefix = None
            for prefix, expected in _EXPECTED_MCP_PREFIX_FAMILIES.items():
                if descriptor.name.startswith(prefix):
                    matched_prefix = expected
                    break
            if matched_prefix is not None:
                self.assertEqual(descriptor.routing_family, matched_prefix)

    def test_unknown_mcp_provider_remains_unclassified(self) -> None:
        name = "demo_echo_routing_probe"
        descriptor = CapabilityDescriptor(
            name=name,
            title="Demo",
            description="Probe.",
            input_schema={"type": "object", "properties": {}},
            origin="mcp",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=False,
        )

        def _handler() -> dict[str, str]:
            return {"ok": "true"}

        register_capability(descriptor, _handler)
        try:
            stored = get_capability_descriptor(name)
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertIsNone(stored.routing_family)
        finally:
            unregister_capability(name)

    def test_local_command_enabled_families_resolve(self) -> None:
        for definition in LOCAL_COMMAND_DEFINITIONS:
            if definition.key == "none":
                resolution = resolve_local_command("none")
                self.assertEqual(resolution.descriptors, ())
                continue
            resolution = resolve_local_command(definition.key)
            for descriptor in resolution.descriptors:
                self.assertEqual(descriptor.routing_family, definition.family_key)

    def test_family_definitions_reference_valid_keys(self) -> None:
        for family in CAPABILITY_FAMILIES:
            self.assertIs(get_family(family.key), family)
            for tool_name in family.tool_priority:
                self.assertIsInstance(tool_name, str)

    def test_github_family_not_local_command_enabled(self) -> None:
        github = get_family("github")
        self.assertIsNotNone(github)
        assert github is not None
        self.assertFalse(github.local_command_enabled)
        self.assertFalse(github.local_auto_enabled)
        self.assertTrue(github.cloud_auto_enabled)


if __name__ == "__main__":
    unittest.main()
