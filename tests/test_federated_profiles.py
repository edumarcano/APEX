"""Focused coverage for federated profile registry and schema-6 settings."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.agent.profiles import (
    PROFILE_SPECS,
    build_concrete_profile,
    compose_profile_system_instruction,
    migrate_schema5_ask_apex,
    migrate_schema5_briefing,
    profile_has_credentials,
    resolve_effort,
    resolve_assistant_selection,
    runtime_profile_order,
)
from core.agent.capabilities import CapabilityDescriptor
from core.agent.tool_policies import (
    filter_profile_capabilities,
    hosted_tools_for_profile,
)
from core.agent.types import AgentQueryRequest, AgentQueryResponse
from core.api.assistant import _execute_agent_turn, query_agent
from core.api.assistant import build_agent_profile_statuses
from core.settings.models import AssistantSettings, SETTINGS_SCHEMA_VERSION


class SchemaMigrationTests(unittest.TestCase):
    def test_legacy_cloud_profiles_map_to_panthera(self) -> None:
        for legacy in ("comet", "nova", "pulsar"):
            with self.subTest(legacy=legacy):
                migrated = migrate_schema5_ask_apex(
                    {"enabled": True, "default_profile": legacy}
                )
                self.assertEqual(migrated["mode"], "cloud")
                self.assertEqual(migrated["cloud_profile"], "panthera")
                self.assertEqual(migrated["cloud_effort"], "focused")
                self.assertEqual(migrated["local_profile"], "mus")

    def test_legacy_local_profiles_map_to_local_mus(self) -> None:
        for legacy in ("lynx", "acinonyx", "neofelis"):
            with self.subTest(legacy=legacy):
                migrated = migrate_schema5_ask_apex({"default_profile": legacy})
                self.assertEqual(migrated["mode"], "local")
                self.assertEqual(migrated["local_profile"], "mus")
                self.assertEqual(migrated["cloud_profile"], "panthera")
                self.assertEqual(migrated["cloud_effort"], "focused")

    def test_legacy_briefing_modes_map_to_panthera(self) -> None:
        for legacy in (
            "comet",
            "lynx",
            "acinonyx",
            "neofelis",
            "pulsar",
            "structured_digest",
        ):
            with self.subTest(legacy=legacy):
                self.assertEqual(
                    migrate_schema5_briefing({"default_mode": legacy}),
                    {"default_mode": "panthera"},
                )


class AssistantSelectionTests(unittest.TestCase):
    def test_dev_mode_selects_acinonyx(self) -> None:
        assistant = AssistantSettings()
        mode, profile, effort = resolve_assistant_selection(
            assistant, dev_mode=True
        )
        self.assertEqual((mode, profile, effort), ("cloud", "acinonyx", "focused"))

    def test_cloud_settings_resolve_profile_and_effort(self) -> None:
        assistant = AssistantSettings(
            mode="cloud",
            cloud_profile="neofelis",
            cloud_effort="extended",
        )
        mode, profile, effort = resolve_assistant_selection(
            assistant, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("cloud", "neofelis", "extended"))

    def test_local_settings_resolve_without_effort(self) -> None:
        assistant = AssistantSettings(mode="local", local_profile="sorex")
        mode, profile, effort = resolve_assistant_selection(
            assistant, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("local", "sorex", None))


class CredentialIsolationTests(unittest.TestCase):
    def test_each_cloud_profile_uses_distinct_env_keys(self) -> None:
        env_keys = {
            PROFILE_SPECS[key].credential_env
            for key in ("panthera", "neofelis", "delphinus", "orcinus", "acinonyx")
        }
        self.assertEqual(
            env_keys,
            {
                "OPENAI_API_KEY",
                "GEMINI_API_KEY",
                "XAI_API_KEY",
                "GEMINI_SANDBOX_API_KEY",
            },
        )

    def test_profile_has_credentials_is_independent_per_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "openai", "GEMINI_API_KEY": ""},
            clear=False,
        ):
            self.assertTrue(profile_has_credentials("panthera"))
            self.assertFalse(profile_has_credentials("neofelis"))


class ProfileIdentityTests(unittest.TestCase):
    _IDENTITIES = {
        "acinonyx": (
            "You are Apex Acinonyx, an Apex Intelligence Profile powered by "
            "Gemini 3.5 Flash Lite. You are the development-only privacy sandbox."
        ),
        "panthera": (
            "You are Apex Panthera, an Apex Intelligence Profile powered by "
            "GPT-5.6 Luna."
        ),
        "neofelis": (
            "You are Apex Neofelis, an Apex Intelligence Profile powered by "
            "Gemini 3.6 Flash."
        ),
        "delphinus": (
            "You are Apex Delphinus, an Apex Intelligence Profile powered by Grok 4.3."
        ),
        "orcinus": (
            "You are Apex Orcinus, an Apex Intelligence Profile powered by Grok 4.5."
        ),
        "sorex": (
            "You are Apex Sorex, an Apex Intelligence Profile powered by "
            "Qwen3 1.7B through Ollama."
        ),
        "mus": (
            "You are Apex Mus, an Apex Intelligence Profile powered by "
            "Qwen3 4B Instruct through Ollama."
        ),
    }

    def test_every_profile_has_the_expected_immutable_identity(self) -> None:
        self.assertEqual(set(PROFILE_SPECS), set(self._IDENTITIES))
        for key, identity in self._IDENTITIES.items():
            with self.subTest(profile=key):
                self.assertEqual(PROFILE_SPECS[key].identity_instruction, identity)
                _apex_effort, native_effort = resolve_effort(key, None)
                profile = build_concrete_profile(key, native_effort=native_effort)
                self.assertTrue(profile.system_instruction.startswith(identity))

    def test_effective_request_prompts_preserve_identity_with_runtime_overrides(self) -> None:
        captured_instructions: dict[str, str] = {}

        def capture_loop(*_args, **kwargs):
            profile = _args[2]
            captured_instructions[profile.display_name] = kwargs[
                "system_instruction_override"
            ]
            return AgentQueryResponse(answer="ok", profile_used={}, session_id=None)

        with (
            mock.patch("core.api.assistant._create_provider", return_value=mock.Mock()),
            mock.patch("core.api.assistant.run_agent_loop", side_effect=capture_loop),
            mock.patch(
                "core.api.assistant.config.AGENT_SYSTEM_PROMPT", "Cloud runtime prompt."
            ),
            mock.patch(
                "core.api.assistant.config.LOCAL_AGENT_SYSTEM_PROMPT", "Local runtime prompt."
            ),
        ):
            for key, identity in self._IDENTITIES.items():
                _apex_effort, native_effort = resolve_effort(key, None)
                profile = build_concrete_profile(key, native_effort=native_effort)
                _execute_agent_turn(
                    AgentQueryRequest(prompt="Identify yourself.", profile=key),
                    profile,
                    profile_key=key,
                    api_key="test",
                    resolved_apex_effort=None,
                    resolved_native_effort=native_effort,
                )
                instruction = captured_instructions[profile.display_name]
                self.assertTrue(instruction.startswith(identity))
                expected_runtime_prompt = (
                    "Local runtime prompt."
                    if PROFILE_SPECS[key].mode == "local"
                    else "Cloud runtime prompt."
                )
                self.assertIn(expected_runtime_prompt, instruction)

    def test_identity_composition_keeps_identity_when_base_prompt_is_empty(self) -> None:
        identity = PROFILE_SPECS["panthera"].identity_instruction
        self.assertEqual(compose_profile_system_instruction("panthera", "  "), identity)


class LocalEffortRejectionTests(unittest.TestCase):
    def test_local_profile_rejects_effort_with_400(self) -> None:
        with mock.patch("core.api.assistant.DEMO_MODE", False), mock.patch(
            "core.api.assistant.get_settings_store"
        ) as store_mock:
            store_mock.return_value.get_snapshot.return_value.assistant.enabled = True
            with self.assertRaises(HTTPException) as ctx:
                query_agent(
                    AgentQueryRequest(
                        prompt="hello",
                        profile="sorex",
                        effort="focused",
                    )
                )
        self.assertEqual(ctx.exception.status_code, 400)


class AcinonyxPolicyTests(unittest.TestCase):
    def test_acinonyx_rejects_production_history_and_uses_safe_tools(self) -> None:
        captured: dict[str, object] = {}

        class Provider:
            def generate_turn(
                self,
                _messages,
                tools,
                _profile,
                system_instruction_override=None,
            ):
                captured["tools"] = tools
                captured["override"] = system_instruction_override
                from core.agent.providers.contract import ProviderTurnResult
                from core.agent.types import AgentMessage

                return ProviderTurnResult(
                    message=AgentMessage(role="model", content="Sandbox."),
                )

        with (
            mock.patch("core.api.assistant.DEMO_MODE", False),
            mock.patch("core.api.assistant.is_dev_mode", return_value=True),
            mock.patch("core.api.assistant.is_profile_visible", return_value=True),
            mock.patch(
                "core.api.assistant.get_settings_store"
            ) as store_mock,
            mock.patch("core.api.assistant._execute_agent_turn") as execute,
            mock.patch.dict(
                "os.environ", {"GEMINI_SANDBOX_API_KEY": "sandbox"}, clear=False
            ),
        ):
            store_mock.return_value.get_snapshot.return_value.assistant.enabled = True
            execute.side_effect = (
                lambda payload, *args, **kwargs: captured.update(
                    {
                        "snapshot_id": payload.snapshot_id,
                        "briefing_id": payload.briefing_id,
                        "history": list(payload.history),
                        "disable_tools": kwargs.get("disable_tools"),
                        "disable_hud_context": kwargs.get("disable_hud_context"),
                    }
                )
                or __import__(
                    "core.agent.types", fromlist=["AgentQueryResponse"]
                ).AgentQueryResponse(answer="ok", profile_used={}, session_id=None)
            )
            query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    profile="acinonyx",
                    snapshot_id="snap-1",
                    history=[
                        __import__(
                            "core.agent.types", fromlist=["AgentMessage"]
                        ).AgentMessage(role="user", content="prior production turn")
                    ],
                )
            )

        self.assertEqual(captured["snapshot_id"], "snap-1")
        self.assertIsNone(captured["briefing_id"])
        self.assertEqual(captured.get("history"), [])
        self.assertFalse(captured["disable_tools"])
        self.assertFalse(captured["disable_hud_context"])

    def test_acinonyx_capability_policy_is_an_explicit_allowlist(self) -> None:
        def descriptor(name: str) -> CapabilityDescriptor:
            return CapabilityDescriptor(
                name=name,
                title=name,
                description=name,
                input_schema={"type": "object", "properties": {}},
                origin="mcp" if "_" in name and name.startswith(("brave", "github", "alphavantage")) else "native",
                risk="read",
                expose_to_assistant=True,
                expose_to_mcp_server=False,
                expose_to_client_display=True,
            )

        filtered = filter_profile_capabilities(
            "acinonyx",
            [
                descriptor("get_weather_forecast"),
                descriptor("get_active_reminders"),
                descriptor("brave_brave_web_search"),
                descriptor("alphavantage_quote"),
                descriptor("github_list_issues"),
            ],
        )
        self.assertEqual(
            [item.name for item in filtered],
            [
                "get_weather_forecast",
                "brave_brave_web_search",
                "alphavantage_quote",
            ],
        )

    def test_hosted_tool_policy_matches_profiles_and_toggles(self) -> None:
        self.assertEqual(
            hosted_tools_for_profile(
                "neofelis", neofelis_google_search_enabled=True
            ),
            frozenset({"google_search", "google_maps"}),
        )
        self.assertEqual(
            hosted_tools_for_profile(
                "neofelis", neofelis_google_search_enabled=False
            ),
            frozenset({"google_maps"}),
        )
        self.assertEqual(
            hosted_tools_for_profile(
                "neofelis",
                neofelis_google_search_enabled=False,
                neofelis_google_maps_enabled=False,
            ),
            frozenset(),
        )
        self.assertEqual(
            hosted_tools_for_profile(
                "delphinus", neofelis_google_search_enabled=True
            ),
            frozenset({"x_search"}),
        )
        self.assertEqual(
            hosted_tools_for_profile(
                "delphinus",
                neofelis_google_search_enabled=True,
                delphinus_x_search_enabled=False,
            ),
            frozenset(),
        )
        self.assertEqual(
            hosted_tools_for_profile(
                "orcinus",
                neofelis_google_search_enabled=True,
                orcinus_x_search_enabled=False,
            ),
            frozenset(),
        )


class DemoRosterTests(unittest.TestCase):
    def test_runtime_roster_hides_dev_only_acinonyx_outside_dev(self) -> None:
        visible = runtime_profile_order(dev_mode=False)
        self.assertNotIn("acinonyx", visible)
        self.assertIn("panthera", visible)
        self.assertIn("sorex", visible)

    def test_demo_agent_query_rejects_hidden_profile(self) -> None:
        from core.api.demo import run_demo_agent_query

        with mock.patch("core.agent.profiles.is_profile_visible", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                run_demo_agent_query(
                    AgentQueryRequest(prompt="status", profile="acinonyx")
                )
        self.assertEqual(ctx.exception.status_code, 404)


class ProfileStatusMetadataTests(unittest.TestCase):
    def test_neofelis_reports_configured_model_and_effective_native_tools(self) -> None:
        settings = mock.Mock()
        settings.assistant.neofelis_google_search_enabled = False
        with (
            mock.patch("core.api.assistant.OLLAMA_ENABLED", False),
            mock.patch("core.api.assistant.is_dev_mode", return_value=False),
            mock.patch("core.api.assistant.profile_has_credentials", return_value=True),
            mock.patch("core.api.assistant.get_settings_store") as store,
        ):
            store.return_value.get_snapshot.return_value = settings
            profiles = build_agent_profile_statuses()

        neofelis = next(item for item in profiles if item.key == "neofelis")
        self.assertEqual(neofelis.configured_model, "gemini-3.6-flash")
        self.assertTrue(neofelis.description)
        self.assertEqual(
            neofelis.native_tools,
            {"google_search": False, "google_maps": True},
        )


class SettingsSchemaVersionTests(unittest.TestCase):
    def test_settings_schema_version_is_seven(self) -> None:
        self.assertEqual(SETTINGS_SCHEMA_VERSION, 7)


if __name__ == "__main__":
    unittest.main()
