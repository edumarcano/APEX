"""Focused coverage for federated profile registry and schema-6 settings."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.agent.profiles import (
    PROFILE_SPECS,
    migrate_schema5_ask_apex,
    migrate_schema5_briefing,
    profile_has_credentials,
    resolve_assistant_selection,
    runtime_profile_order,
)
from core.agent.types import AgentQueryRequest
from core.api.assistant import query_agent
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


class AcinonyxFailClosedTests(unittest.TestCase):
    def test_acinonyx_strips_hud_context_and_tools(self) -> None:
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
                    briefing_id=3,
                    history=[
                        __import__(
                            "core.agent.types", fromlist=["AgentMessage"]
                        ).AgentMessage(role="user", content="prior production turn")
                    ],
                )
            )

        self.assertIsNone(captured["snapshot_id"])
        self.assertIsNone(captured["briefing_id"])
        self.assertEqual(captured.get("history"), [])
        self.assertTrue(captured["disable_tools"])
        self.assertTrue(captured["disable_hud_context"])


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


class SettingsSchemaVersionTests(unittest.TestCase):
    def test_settings_schema_version_is_six(self) -> None:
        self.assertEqual(SETTINGS_SCHEMA_VERSION, 6)


if __name__ == "__main__":
    unittest.main()
