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
from core.settings.models import AgentSettings, FelisSettings, PantheraSettings
from tests.support.agent_fixtures import felis_settings, panthera_settings


class AgentSelectionTests(unittest.TestCase):
    def test_sandbox_mode_selects_panthera_with_sandbox_flag(self) -> None:
        agent_settings = AgentSettings(sandbox_mode=True)
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=True
        )
        self.assertEqual((mode, profile, effort), ("cloud", "panthera", "medium"))
        self.assertTrue(agent_settings.sandbox_mode)

    def test_cloud_settings_resolve_profile_and_effort(self) -> None:
        agent_settings = panthera_settings(
            model="gemini-3.6-flash",
            effort="high",
        )
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("cloud", "panthera", "high"))

    def test_local_settings_resolve_without_effort(self) -> None:
        agent_settings = felis_settings(model="qwen3:1.7b")
        mode, profile, effort = resolve_agent_selection(
            agent_settings, dev_mode=False
        )
        self.assertEqual((mode, profile, effort), ("local", "felis", None))

    def test_dev_only_local_model_remains_selectable_in_dev_mode(self) -> None:
        agent_settings = felis_settings(model="qwen3:4b-instruct")
        self.assertTrue(is_agent_visible("felis", dev_mode=True))
        self.assertEqual(agent_settings.felis.model, "qwen3:4b-instruct")


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
                "GEMINI_SANDBOX_API_KEY",
            },
        )

    def test_free_tier_gemini_models_route_to_sandbox_key(self) -> None:
        from core.agent.model_catalog import (
            ModelProfile,
            get_model_profile,
        )

        lite_profile = get_model_profile("gemini-3.5-flash-lite")
        self.assertIsNotNone(lite_profile)
        self.assertEqual(lite_profile.credential_env, "GEMINI_SANDBOX_API_KEY")

        # Custom/dynamic free-tier Gemini model also routes to sandbox key via __post_init__
        custom_free_tier = ModelProfile(
            model_id="gemini-3.5-flash-lite",
            display_name="Custom Flash Lite",
            provider="gemini",
            runtime="cloud",
            stability="experimental",
            credential_env="GEMINI_API_KEY",
            max_tool_turns=4,
            max_tool_calls=6,
            supports_encrypted_reasoning=True,
            hosted_capabilities=frozenset(),
        )
        self.assertEqual(custom_free_tier.credential_env, "GEMINI_SANDBOX_API_KEY")


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
    def test_runtime_roster_exposes_panthera_and_felis(self) -> None:
        visible = runtime_agent_order(dev_mode=False)
        self.assertEqual(visible, ("panthera", "felis"))
        development = runtime_agent_order(dev_mode=True)
        self.assertEqual(development, ("panthera", "felis"))

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
        self.assertEqual(
            luna_entry.effort_options,
            ["none", "minimal", "low", "medium", "high", "xhigh"],
        )

        felis = next(item for item in profiles if item.key == "felis")
        self.assertTrue(felis.model_catalog)
        gemma_entry = next(entry for entry in felis.model_catalog if entry.model_id == "gemma-4-E2B-Q4_K_M.gguf")
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


class ModelNativeReasoningTests(unittest.TestCase):
    def test_model_profiles_define_native_reasoning_options(self) -> None:
        from core.agent.model_catalog import get_model_profile

        luna = get_model_profile("gpt-5.6-luna")
        assert luna is not None
        self.assertEqual(
            luna.reasoning_options,
            ("none", "minimal", "low", "medium", "high", "xhigh"),
        )
        self.assertEqual(luna.default_reasoning, "medium")

        gemini_flash = get_model_profile("gemini-3.6-flash")
        assert gemini_flash is not None
        self.assertEqual(
            gemini_flash.reasoning_options,
            ("minimal", "low", "medium", "high"),
        )
        self.assertEqual(gemini_flash.default_reasoning, "medium")

        gemini_lite = get_model_profile("gemini-3.5-flash-lite")
        assert gemini_lite is not None
        self.assertEqual(
            gemini_lite.reasoning_options,
            ("minimal", "low", "medium", "high"),
        )
        self.assertEqual(gemini_lite.default_reasoning, "medium")

        grok_43 = get_model_profile("grok-4.3")
        assert grok_43 is not None
        self.assertEqual(
            grok_43.reasoning_options,
            ("low", "medium", "high"),
        )
        self.assertEqual(grok_43.default_reasoning, "medium")

        grok_45 = get_model_profile("grok-4.5")
        assert grok_45 is not None
        self.assertEqual(
            grok_45.reasoning_options,
            ("low", "medium", "high"),
        )
        self.assertEqual(grok_45.default_reasoning, "high")

        local_gemma = get_model_profile("gemma-4-E2B-Q4_K_M.gguf")
        assert local_gemma is not None
        self.assertEqual(local_gemma.reasoning_options, ())
        self.assertIsNone(local_gemma.default_reasoning)

    def test_reasoning_resolution_preserves_supported_native_levels(self) -> None:
        from core.agent.catalog import resolve_effort
        from core.agent.model_catalog import get_model_profile

        luna = get_model_profile("gpt-5.6-luna")
        assert luna is not None
        for option in ("none", "minimal", "low", "medium", "high", "xhigh"):
            _apex, native = resolve_effort(luna, option)
            self.assertEqual(native, option)

        # Unsupported option for Grok falls back to model default
        grok = get_model_profile("grok-4.3")
        assert grok is not None
        _apex, native = resolve_effort(grok, "minimal")
        self.assertEqual(native, "medium")

        # Unsupported option for Gemini falls back to default
        gemini = get_model_profile("gemini-3.6-flash")
        assert gemini is not None
        _apex, native = resolve_effort(gemini, "xhigh")
        self.assertEqual(native, "medium")

    def test_concrete_agent_profiles_define_provider(self) -> None:
        from core.agent.catalog import build_concrete_agent
        from core.agent.model_catalog import (
            CLOUD_MODEL_PROFILES,
            LOCAL_MODEL_PROFILES,
        )

        all_models = {**CLOUD_MODEL_PROFILES, **LOCAL_MODEL_PROFILES}
        for model_id, model_profile in all_models.items():
            agent_key = "panthera" if model_profile.runtime == "cloud" else "felis"
            concrete = build_concrete_agent(
                agent_key,
                native_effort="medium",
                model_id=model_id,
            )
            self.assertTrue(
                hasattr(concrete, "provider"),
                f"Concrete profile for {model_id} is missing 'provider'",
            )
            self.assertEqual(concrete.provider, model_profile.provider)


if __name__ == "__main__":
    unittest.main()
