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
from core.settings.models import AgentSettings, LynxSettings, PantheraSettings
from tests.support.agent_fixtures import lynx_settings, panthera_settings


class AgentSelectionTests(unittest.TestCase):
    def test_sandbox_mode_selects_panthera_with_sandbox_flag(self) -> None:
        agent_settings = AgentSettings(sandbox_mode=True)
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=True
        )
        self.assertEqual((mode, profile, effort), ("cloud", "panthera", "focused"))
        self.assertTrue(agent_settings.sandbox_mode)

    def test_cloud_settings_resolve_profile_and_effort(self) -> None:
        agent_settings = panthera_settings(
            model="gemini-3.6-flash",
            effort="extended",
        )
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("cloud", "panthera", "extended"))

    def test_local_settings_resolve_without_effort(self) -> None:
        agent_settings = lynx_settings(model="qwen3:1.7b")
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("local", "lynx", None))

    def test_dev_only_local_model_remains_selectable_in_dev_mode(self) -> None:
        agent_settings = lynx_settings(model="qwen3:4b-instruct")
        self.assertTrue(is_agent_visible("lynx", dev_mode=True))
        self.assertEqual(agent_settings.lynx.model, "qwen3:4b-instruct")


class CredentialIsolationTests(unittest.TestCase):
    def test_cloud_models_use_provider_env_keys(self) -> None:
        from core.agent.model_catalog import get_model_profile

        env_keys = {
            get_model_profile("gpt-5.6-luna").credential_env,
            get_model_profile("gemini-3.6-flash").credential_env,
            get_model_profile("grok-4.3").credential_env,
            get_model_profile("gemini-3.5-flash-lite").credential_env,
        }
        self.assertEqual(
            env_keys,
            {
                "OPENAI_API_KEY",
                "GEMINI_API_KEY",
                "XAI_API_KEY",
            },
        )

    def test_agent_has_credentials_is_independent_per_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "openai", "GEMINI_API_KEY": ""},
            clear=False,
        ), mock.patch(
            "core.agent.catalog.resolve_selected_model_profile"
        ) as resolve_profile:
            from core.agent.model_catalog import get_model_profile

            resolve_profile.side_effect = [
                get_model_profile("gpt-5.6-luna"),
                get_model_profile("gemini-3.6-flash"),
            ]
            self.assertTrue(agent_has_credentials("panthera"))
            self.assertFalse(agent_has_credentials("panthera"))

    def test_missing_credential_message_uses_provider_display_names(self) -> None:
        with mock.patch(
            "core.agent.catalog.resolve_selected_model_profile"
        ) as resolve_profile:
            from core.agent.model_catalog import get_model_profile

            resolve_profile.side_effect = lambda *_args: get_model_profile("gpt-5.6-luna")
            self.assertIn("OpenAI API key", credential_missing_message("panthera"))
            resolve_profile.side_effect = lambda *_args: get_model_profile("gemini-3.6-flash")
            self.assertIn("Google API key", credential_missing_message("panthera"))
            resolve_profile.side_effect = lambda *_args: get_model_profile("grok-4.5")
            self.assertIn("SpaceXAI API key", credential_missing_message("panthera"))


class DemoRosterTests(unittest.TestCase):
    def test_runtime_roster_exposes_panthera_and_lynx(self) -> None:
        visible = runtime_agent_order(dev_mode=False)
        self.assertEqual(visible, ("panthera", "lynx"))
        development = runtime_agent_order(dev_mode=True)
        self.assertEqual(development, ("panthera", "lynx"))

    def test_demo_agent_query_rejects_unknown_profile(self) -> None:
        from core.api.demo import run_demo_agent_query

        with mock.patch("core.agent.catalog.is_agent_visible", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                run_demo_agent_query(
                    AgentQueryRequest(prompt="status", agent="panthera")
                )
        self.assertEqual(ctx.exception.status_code, 404)


class ProfileStatusMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cloud_status_cache()
        self.addCleanup(clear_cloud_status_cache)

    def test_panthera_reports_configured_model_and_effective_native_tools(self) -> None:
        settings = mock.Mock()
        settings.ask_apex.panthera.hosted_tools.google_search = False
        settings.ask_apex.panthera.hosted_tools.google_maps = True
        settings.ask_apex.panthera.hosted_tools.x_search = True
        settings.ask_apex.panthera.model = "gemini-3.6-flash"
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
            mock.patch(
                "core.api.cortex.resolve_selected_model_profile"
            ) as resolve_profile,
        ):
            from core.agent.model_catalog import get_model_profile

            resolve_profile.return_value = get_model_profile("gemini-3.6-flash")
            store.return_value.get_snapshot.return_value = settings
            profiles = build_agent_statuses()

        panthera = next(item for item in profiles if item.key == "panthera")
        self.assertTrue(panthera.description)
        self.assertEqual(panthera.status, "configured")
        self.assertEqual(panthera.status_source, "configuration")
        self.assertIsNone(panthera.provider_account_tier)
        self.assertEqual(
            panthera.native_tools,
            {"google_search": False, "google_maps": True, "x_search": False},
        )
        self.assertTrue(panthera.model_catalog)
        luna_entry = next(entry for entry in panthera.model_catalog if entry.model_id == "gpt-5.6-luna")
        self.assertEqual(luna_entry.pricing.billing_basis, "standard")
        self.assertEqual(luna_entry.pricing.input_per_million, 0.2)
        self.assertTrue(luna_entry.supports_effort)
        self.assertEqual(luna_entry.effort_options, ["light", "focused", "extended"])

        lynx = next(item for item in profiles if item.key == "lynx")
        self.assertTrue(lynx.model_catalog)
        gemma_entry = next(entry for entry in lynx.model_catalog if entry.model_id == "gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(gemma_entry.pricing.billing_basis, "local")
        self.assertEqual(gemma_entry.pricing.input_per_million, 0.0)
        self.assertFalse(gemma_entry.supports_effort)
        self.assertTrue(gemma_entry.context_options)
        self.assertIn(16384, gemma_entry.context_options)
        self.assertEqual(gemma_entry.reasoning_modes, ["none", "focused"])

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
