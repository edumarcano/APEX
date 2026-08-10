"""Coverage for Apex Agent catalog selection, visibility, and status metadata."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException
from core.agent.catalog import (
    AGENT_SPECS,
    agent_has_credentials,
    credential_missing_message,
    resolve_agent_selection,
    is_agent_visible,
    runtime_agent_order,
)
from core.agent.types import AgentQueryRequest
from core.api.cortex import build_agent_statuses
from core.agent.providers.cloud_verification import clear_cloud_status_cache
from core.settings.models import AgentSettings


class AgentSelectionTests(unittest.TestCase):
    def test_dev_mode_selects_acinonyx(self) -> None:
        agent_settings = AgentSettings()
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=True
        )
        self.assertEqual((mode, profile, effort), ("cloud", "acinonyx", "focused"))

    def test_cloud_settings_resolve_profile_and_effort(self) -> None:
        agent_settings = AgentSettings(
            runtime="cloud",
            cloud_agent="neofelis",
            effort="extended",
        )
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("cloud", "panthera", "extended"))

    def test_local_settings_resolve_without_effort(self) -> None:
        agent_settings = AgentSettings(runtime="local", local_agent="sorex")
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("local", "apodemus", None))

    def test_hidden_local_agent_falls_back_outside_dev_mode(self) -> None:
        agent_settings = AgentSettings(runtime="local", local_agent="mus")
        self.assertEqual(
            resolve_agent_selection(agent_settings, dev_mode=False),
            ("local", "apodemus", None),
        )

    def test_dev_mode_keeps_mus_selectable(self) -> None:
        agent_settings = AgentSettings(runtime="local", local_agent="mus")
        self.assertTrue(is_agent_visible("mus", dev_mode=True))
        self.assertEqual(agent_settings.local_agent, "mus")


class CredentialIsolationTests(unittest.TestCase):
    def test_each_cloud_agent_uses_distinct_env_keys(self) -> None:
        env_keys = {
            AGENT_SPECS[key].credential_env
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

    def test_agent_has_credentials_is_independent_per_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "openai", "GEMINI_API_KEY": ""},
            clear=False,
        ):
            self.assertTrue(agent_has_credentials("panthera"))
            self.assertFalse(agent_has_credentials("neofelis"))

    def test_missing_credential_message_uses_provider_display_names(self) -> None:
        self.assertIn("Google API key", credential_missing_message("neofelis"))
        self.assertIn("SpaceXAI API key", credential_missing_message("orcinus"))
        self.assertIn("GEMINI_API_KEY", credential_missing_message("neofelis"))
        self.assertIn("XAI_API_KEY", credential_missing_message("orcinus"))


class DemoRosterTests(unittest.TestCase):
    def test_runtime_roster_hides_dev_only_agents_outside_dev(self) -> None:
        visible = runtime_agent_order(dev_mode=False)
        self.assertNotIn("acinonyx", visible)
        self.assertEqual(visible, ("panthera", "apodemus", "neotoma"))
        development = runtime_agent_order(dev_mode=True)
        self.assertEqual(development[0], "acinonyx")
        self.assertIn("unnamed-experimental-agent", development)
        self.assertTrue(set(visible).issubset(development))

    def test_demo_agent_query_rejects_hidden_profile(self) -> None:
        from core.api.demo import run_demo_agent_query

        with mock.patch("core.agent.catalog.is_agent_visible", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                run_demo_agent_query(
                    AgentQueryRequest(prompt="status", agent="acinonyx")
                )
        self.assertEqual(ctx.exception.status_code, 404)


class ProfileStatusMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cloud_status_cache()
        self.addCleanup(clear_cloud_status_cache)

    def test_neofelis_reports_configured_model_and_effective_native_tools(self) -> None:
        settings = mock.Mock()
        settings.ask_apex.neofelis_google_search_enabled = False
        backend = mock.Mock()
        backend.provider = "ollama"
        backend.enabled = False
        with (
            mock.patch("core.api.cortex.iter_local_runtime_backends", return_value=()),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch(
                "core.api.cortex.get_system_vitals",
                return_value={"cpu": 0.0, "ram": 0.0},
            ),
            mock.patch("core.api.cortex.get_active_local_model", return_value=None),
            mock.patch("core.api.cortex.get_loading_local_model", return_value=None),
            mock.patch(
                "core.api.cortex.get_idle_unload_remaining_seconds",
                return_value=None,
            ),
            mock.patch("core.api.cortex.is_local_execution_active", return_value=False),
            mock.patch("core.api.cortex.is_dev_mode", return_value=True),
            mock.patch("core.api.cortex.agent_has_credentials", return_value=True),
            mock.patch(
                "core.api.cortex.local_context_window_for_agent",
                return_value=None,
            ),
            mock.patch(
                "core.api.cortex.local_reasoning_mode_for_agent",
                return_value="none",
            ),
            mock.patch("core.api.cortex.get_settings_store") as store,
        ):
            store.return_value.get_snapshot.return_value = settings
            profiles = build_agent_statuses()

        neofelis = next(item for item in profiles if item.key == "neofelis")
        self.assertTrue(neofelis.description)
        self.assertEqual(neofelis.status, "configured")
        self.assertEqual(neofelis.status_source, "configuration")
        self.assertIsNone(neofelis.provider_account_tier)
        self.assertEqual(
            neofelis.native_tools,
            {"google_search": False, "google_maps": True},
        )
        for profile in profiles:
            with self.subTest(agent=profile.key):
                self.assertTrue(profile.configured_model)
                if profile.context_window_options:
                    self.assertEqual(
                        profile.context_window_options,
                        sorted(set(profile.context_window_options)),
                    )
                    self.assertIn(
                        profile.default_context_window,
                        profile.context_window_options,
                    )
                    self.assertIn(profile.context_window, profile.context_window_options)
                    self.assertTrue(
                        set(profile.context_window_high_resource_options).issubset(
                            profile.context_window_options
                        )
                    )
                if profile.reasoning_mode_options:
                    self.assertIn(
                        profile.default_reasoning_mode,
                        profile.reasoning_mode_options,
                    )
                    self.assertIn(profile.reasoning_mode, profile.reasoning_mode_options)

if __name__ == "__main__":
    unittest.main()
