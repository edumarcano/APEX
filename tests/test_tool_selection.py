"""Regression coverage for unified explicit Agent tool selection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.agent.capabilities import CapabilityDescriptor
from core.agent.catalog import build_concrete_agent
from core.agent.loop import run_agent_loop
from core.agent.providers.contract import ProviderTurnResult
from core.agent.tool_catalog import build_tool_catalog
from core.agent.tool_schemas import project_descriptor_for_agent
from core.agent.tool_selection import resolve_selected_tools
from core.agent.types import AgentMessage, AgentQueryRequest
from core.api.cortex import build_tool_preflight
from core.api.models import (
    ToolPreflightRequest,
    ToolProfileCreateRequest,
    ToolProfileDefaultRequest,
    ToolProfileUpdateRequest,
)
from core.api.routers.cortex import (
    create_tool_profile,
    delete_tool_profile,
    set_tool_profile_default,
    update_tool_profile,
)
from core.settings.models import (
    SettingsPatch,
    ToolProfile,
    ToolProfilesPatch,
)
from core.settings.store import RuntimeSettingsStore


class _AnswerProvider:
    def __init__(self) -> None:
        self.tool_names: list[list[str]] = []

    def generate_turn(
        self,
        _messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        _profile: object,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        del system_instruction_override
        self.tool_names.append([tool.name for tool in tools])
        return ProviderTurnResult(message=AgentMessage(role="agent", content="Done."))


class UnifiedToolSelectionTests(unittest.TestCase):
    def test_catalog_groups_native_and_configured_mcp_tools(self) -> None:
        catalog = build_tool_catalog("panthera")
        self.assertEqual(catalog.default_profile_id, "all_allowed")
        self.assertTrue(any(group.kind == "apex_family" for group in catalog.groups))
        self.assertTrue(any(group.kind == "mcp_server" for group in catalog.groups))
        self.assertIn(
            "github_search_repositories",
            {tool.name for tool in catalog.tools},
        )

    def test_exact_local_selection_is_the_only_offered_descriptor(self) -> None:
        selection = resolve_selected_tools("sorex", ["get_weather_forecast"])
        self.assertEqual(
            selection.diagnostics.offered_tool_names,
            ["get_weather_forecast"],
        )
        self.assertEqual(selection.diagnostics.rejected_tools, [])

    def test_empty_selection_is_tool_free_and_has_zero_schema_tokens(self) -> None:
        selection = resolve_selected_tools("panthera", [])
        self.assertEqual(selection.descriptors, ())
        self.assertEqual(selection.diagnostics.offered_tool_names, [])
        self.assertEqual(selection.diagnostics.selected_schema_tokens, 0)

    def test_invalid_selection_is_structured_and_not_silently_dropped(self) -> None:
        selection = resolve_selected_tools("sorex", ["not_registered"])
        self.assertEqual(selection.diagnostics.rejected_tool_names, ["not_registered"])
        self.assertEqual(selection.diagnostics.rejected_tools[0].code, "invalid")

    def test_agent_policy_intersects_explicit_selection(self) -> None:
        selection = resolve_selected_tools("acinonyx", ["get_active_reminders"])
        self.assertEqual(selection.descriptors, ())
        self.assertEqual(selection.diagnostics.rejected_tools[0].code, "policy")

    def test_disconnected_mcp_selection_reports_runtime_reason(self) -> None:
        selection = resolve_selected_tools("panthera", ["brave_brave_web_search"])
        self.assertEqual(selection.descriptors, ())
        self.assertIn(
            selection.diagnostics.rejected_tools[0].code,
            {"mcp-disabled", "mcp-disconnected"},
        )

    def test_local_projection_is_shared_by_selection_and_model_schema(self) -> None:
        descriptor = CapabilityDescriptor(
            name="brave_brave_web_search",
            title="Brave Search",
            description="Verbose " * 100,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "remote_option": {"type": "string"},
                },
                "required": ["query"],
            },
            origin="mcp",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )
        projected = project_descriptor_for_agent("mus", descriptor)
        self.assertEqual(set(projected.input_schema["properties"]), {"query", "count"})
        self.assertIn("remote_option", descriptor.input_schema["properties"])

    def test_loop_receives_same_selected_tools_for_local_runtime(self) -> None:
        provider = _AnswerProvider()
        selection = resolve_selected_tools("sorex", ["get_weather_forecast"])
        response = run_agent_loop(
            AgentQueryRequest(
                prompt="Forecast",
                agent="sorex",
                selected_tool_names=["get_weather_forecast"],
            ),
            provider,
            build_concrete_agent("sorex", native_effort=None),
            selected_tools=list(selection.descriptors),
            tool_selection=selection.diagnostics,
        )
        self.assertEqual(provider.tool_names, [["get_weather_forecast"]])
        self.assertEqual(response.offered_tool_names, ["get_weather_forecast"])

    def test_preflight_uses_selected_schema_estimate_and_local_capacity(self) -> None:
        result = build_tool_preflight(
            ToolPreflightRequest(
                agent="sorex",
                prompt="Give me a short answer.",
                selected_tool_names=["get_weather_forecast"],
            )
        )
        self.assertTrue(result.breakdown.is_estimate)
        self.assertGreater(result.breakdown.selected_tool_schemas, 0)
        self.assertIsNotNone(result.breakdown.configured_context_window)
        self.assertGreater(result.breakdown.remaining_estimated_capacity or 0, 0)

    def test_preflight_includes_typed_prompt_and_returns_rejections_in_response(self) -> None:
        result = build_tool_preflight(
            ToolPreflightRequest(
                agent="sorex",
                prompt="This typed prompt must be counted.",
                selected_tool_names=["not_registered"],
            )
        )
        self.assertFalse(result.can_proceed)
        self.assertGreater(result.breakdown.current_prompt, 0)
        self.assertEqual(result.selection.rejected_tool_names, ["not_registered"])
        self.assertEqual(result.selection.rejected_tools[0].code, "invalid")

    def test_preflight_profile_only_resolution_preserves_empty_and_dynamic_profiles(self) -> None:
        no_tools = build_tool_preflight(
            ToolPreflightRequest(agent="panthera", tool_profile_id="no_tools")
        )
        self.assertTrue(no_tools.can_proceed)
        self.assertEqual(no_tools.selection.requested_tool_names, [])
        self.assertEqual(no_tools.selection.active_profile_id, "no_tools")

        all_allowed = build_tool_preflight(
            ToolPreflightRequest(agent="panthera", tool_profile_id="all_allowed")
        )
        self.assertTrue(all_allowed.can_proceed)
        self.assertEqual(
            set(all_allowed.selection.requested_tool_names),
            set(all_allowed.selection.offered_tool_names),
        )

        explicit_empty = build_tool_preflight(
            ToolPreflightRequest(
                agent="panthera",
                selected_tool_names=[],
                tool_profile_id="all_allowed",
            )
        )
        self.assertTrue(explicit_empty.can_proceed)
        self.assertEqual(explicit_empty.selection.offered_tool_names, [])
        self.assertIsNone(explicit_empty.selection.active_profile_id)

    def test_unknown_profile_is_a_structured_preflight_rejection(self) -> None:
        result = build_tool_preflight(
            ToolPreflightRequest(
                agent="panthera",
                tool_profile_id="missing_profile",
            )
        )
        self.assertFalse(result.can_proceed)
        self.assertEqual(result.selection.rejected_tools[0].code, "profile-invalid")

    def test_namespaced_catalog_groups_do_not_collide(self) -> None:
        catalog = build_tool_catalog("panthera")
        group_ids = {group.id for group in catalog.groups}
        self.assertTrue(all(group_id.startswith(("family:", "mcp:")) for group_id in group_ids))
        self.assertEqual(len(group_ids), len(catalog.groups))

    def test_native_catalog_uses_configuration_without_authenticating(self) -> None:
        with patch.dict("os.environ", {"OPENWEATHER_API_KEY": ""}, clear=False):
            catalog = build_tool_catalog("panthera")
        weather = next(
            tool for tool in catalog.tools if tool.name == "get_weather_forecast"
        )
        self.assertFalse(weather.available)
        self.assertIn("not configured", weather.unavailable_reason or "")

    def test_custom_profile_persists_explicit_stale_references(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex_tool_profiles_") as directory:
            root = Path(directory)
            config_path = root / "config.json"
            local_path = root / "config.local.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            store = RuntimeSettingsStore(
                config_path=config_path,
                local_config_path=local_path,
            )
            profile = ToolProfile(
                id="stale_research",
                name="Stale Research",
                description="Keeps a missing tool reference.",
                tool_names=("missing_mcp_tool",),
            )
            snapshot = store.apply_patch(
                SettingsPatch(
                    tool_profiles=ToolProfilesPatch(custom_profiles=[profile])
                )
            )
            self.assertEqual(
                snapshot.tool_profiles.custom_profiles[0].tool_names,
                ("missing_mcp_tool",),
            )
            persisted = json.loads(local_path.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["tool_profiles"]["custom_profiles"][0]["tool_names"],
                ["missing_mcp_tool"],
            )

    def test_profile_only_custom_selection_keeps_stale_references_strict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex_tool_profile_resolution_") as directory:
            root = Path(directory)
            config_path = root / "config.json"
            local_path = root / "config.local.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            store = RuntimeSettingsStore(
                config_path=config_path,
                local_config_path=local_path,
            )
            profile = ToolProfile(
                id="stale_custom",
                name="Stale Custom",
                tool_names=("get_active_reminders", "missing_mcp_tool"),
            )
            store.apply_patch(
                SettingsPatch(
                    tool_profiles=ToolProfilesPatch(custom_profiles=[profile])
                )
            )
            with patch(
                "core.agent.tool_profiles.get_settings_store",
                return_value=store,
            ):
                selection = resolve_selected_tools(
                    "panthera",
                    None,
                    tool_profile_id="stale_custom",
                )
        self.assertEqual(
            selection.diagnostics.active_profile_id,
            "stale_custom",
        )
        self.assertIn("get_active_reminders", selection.diagnostics.offered_tool_names)
        self.assertEqual(selection.diagnostics.rejected_tool_names, ["missing_mcp_tool"])

    def test_profile_routes_edit_default_and_delete_saved_profiles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="apex_tool_profile_routes_") as directory:
            root = Path(directory)
            config_path = root / "config.json"
            local_path = root / "config.local.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")
            store = RuntimeSettingsStore(
                config_path=config_path,
                local_config_path=local_path,
            )
            with (
                patch(
                    "core.api.routers.cortex.get_settings_store",
                    return_value=store,
                ),
                patch(
                    "core.agent.tool_profiles.get_settings_store",
                    return_value=store,
                ),
            ):
                created = create_tool_profile(
                    ToolProfileCreateRequest(
                        name="Route Profile",
                        tool_names=["missing_mcp_tool"],
                    )
                )
                self.assertTrue(
                    any(profile.id == "route_profile" for profile in created.profiles)
                )
                update_tool_profile(
                    "route_profile",
                    ToolProfileUpdateRequest(name="Renamed Route Profile"),
                )
                defaults = set_tool_profile_default(
                    ToolProfileDefaultRequest(
                        agent="panthera",
                        profile_id="route_profile",
                    )
                )
                self.assertEqual(
                    defaults.default_profile_by_agent["panthera"],
                    "route_profile",
                )
                deleted = delete_tool_profile("route_profile")
                self.assertNotIn(
                    "route_profile",
                    {profile.id for profile in deleted.profiles},
                )


if __name__ == "__main__":
    unittest.main()
