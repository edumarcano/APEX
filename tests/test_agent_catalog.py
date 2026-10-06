"""Coverage for the singular APEX Agent model catalog."""

from __future__ import annotations

import unittest
from unittest import mock

from core.agent.catalog import AGENT_SPECS, build_agent_used_metadata, resolve_model_selection
from core.agent import model_catalog
from core.agent.model_catalog import ModelProfile, get_model_profile, visible_cloud_models, visible_local_models
from core.settings.models import AgentSettings, CloudSettings, LocalSettings


class ApexAgentCatalogTests(unittest.TestCase):
    def test_catalog_has_one_native_agent(self) -> None:
        self.assertEqual(tuple(AGENT_SPECS), ("apex",))
        self.assertEqual(AGENT_SPECS["apex"].display_name, "Lynx")
        self.assertEqual(AGENT_SPECS["apex"].canonical_name, "APEX Agent")

    def test_response_metadata_runtime_comes_from_the_resolved_model(self) -> None:
        cloud = build_agent_used_metadata(
            "apex", provider="openrouter", configured_model="z-ai/glm-5.3-flash",
            resolved_model=None, requested_effort="low", resolved_effort="low", runtime="cloud",
        )
        local = build_agent_used_metadata(
            "apex", provider="llama_cpp", configured_model="gemma-4-E2B-Q4_K_M.gguf",
            resolved_model=None, requested_effort=None, resolved_effort=None, runtime="local",
        )

        self.assertEqual(cloud["runtime"], "cloud")
        self.assertEqual(local["runtime"], "local")

    def test_selected_cloud_model_resolves_runtime_and_effort(self) -> None:
        settings = AgentSettings(
            selected_model="gemini-3.7-flash",
            cloud=CloudSettings(last_model="gemini-3.7-flash", effort="high"),
        )
        self.assertEqual(
            resolve_model_selection(settings),
            ("cloud", "gemini-3.7-flash", "high"),
        )

    def test_selected_local_model_has_no_cloud_effort(self) -> None:
        settings = AgentSettings(
            selected_model="gemma-4-E2B-Q4_K_M.gguf",
            local=LocalSettings(last_model="gemma-4-E2B-Q4_K_M.gguf"),
        )
        self.assertEqual(
            resolve_model_selection(settings),
            ("local", "gemma-4-E2B-Q4_K_M.gguf", None),
        )

    @staticmethod
    def _model(model_id: str, runtime: str) -> ModelProfile:
        provider = "openrouter" if runtime == "cloud" else "llama_cpp"
        return ModelProfile(
            model_id=model_id,
            display_name=model_id,
            provider=provider,
            runtime=runtime,
            stability="stable",
            credential_env=None,
            max_tool_turns=2,
            max_tool_calls=2,
            supports_encrypted_reasoning=False,
            hosted_capabilities=frozenset(),
        )

    def test_visible_catalogs_preserve_runtime_order(self) -> None:
        cloud = {
            "cloud-first": self._model("cloud-first", "cloud"),
            "cloud-last": self._model("cloud-last", "cloud"),
        }
        local = {
            "local-first": self._model("local-first", "local"),
            "local-last": self._model("local-last", "local"),
        }
        with mock.patch.dict(model_catalog.CLOUD_MODEL_PROFILES, cloud, clear=True), mock.patch.dict(
            model_catalog.LOCAL_MODEL_PROFILES, local, clear=True
        ):
            self.assertEqual(
                [profile.model_id for profile in visible_cloud_models()],
                ["cloud-first", "cloud-last"],
            )
            self.assertEqual(
                [profile.model_id for profile in visible_local_models()],
                ["local-first", "local-last"],
            )

    def test_cloud_profiles_keep_provider_specific_credentials(self) -> None:
        expected = {
            "openai/gpt-6-luna": "OPENROUTER_API_KEY",
            "z-ai/glm-5.3-flash": "OPENROUTER_API_KEY",
            "gemini-3.7-flash": "GEMINI_API_KEY",
        }
        self.assertEqual(
            {model_id: get_model_profile(model_id).credential_env for model_id in expected},
            expected,
        )

    def test_gpt_6_luna_profile_attributes(self) -> None:
        profile = get_model_profile("openai/gpt-6-luna")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.display_name, "GPT-6 Luna")
        self.assertEqual(profile.provider, "openrouter")
        self.assertEqual(profile.runtime, "cloud")
        self.assertEqual(profile.stability, "stable")
        self.assertEqual(profile.credential_env, "OPENROUTER_API_KEY")
        self.assertEqual(profile.reasoning_options, ("none", "low", "medium", "high", "xhigh", "max"))
        self.assertEqual(profile.default_reasoning, "medium")
        self.assertFalse(profile.supports_encrypted_reasoning)
        self.assertEqual(profile.hosted_capabilities, frozenset())
        self.assertEqual(profile.maximum_context_window, 1_048_576)

    def test_glm_5_3_flash_profile_attributes(self) -> None:
        profile = get_model_profile("z-ai/glm-5.3-flash")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.display_name, "GLM 5.3 Flash")
        self.assertEqual(profile.provider, "openrouter")
        self.assertEqual(profile.runtime, "cloud")
        self.assertEqual(profile.stability, "stable")
        self.assertEqual(profile.credential_env, "OPENROUTER_API_KEY")
        self.assertEqual(profile.reasoning_options, ("low", "high", "max"))
        self.assertEqual(profile.default_reasoning, "low")
        self.assertFalse(profile.supports_encrypted_reasoning)
        self.assertEqual(profile.hosted_capabilities, frozenset())
        self.assertEqual(profile.maximum_context_window, 1_048_576)

    def test_cortex_agent_endpoint_returns_one_catalog(self) -> None:
        from fastapi.testclient import TestClient
        from core.api.app import app

        with mock.patch("core.api.routers.cortex.get_settings_store") as store:
            snapshot = mock.Mock()
            snapshot.ask_apex = AgentSettings()
            snapshot.agent_display_name = ""
            store.return_value.get_snapshot.return_value = snapshot
            response = TestClient(app).get("/api/v1/cortex/agent")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["key"], "apex")
        self.assertEqual(payload["display_name"], "Lynx")
        self.assertEqual(payload["canonical_name"], "APEX Agent")
        self.assertEqual(payload["selected_model"], "z-ai/glm-5.3-flash")
        self.assertTrue(payload["model_catalog"])
        runtimes = {model["runtime"] for model in payload["model_catalog"]}
        self.assertIn("cloud", runtimes)
        self.assertIn("local", runtimes)
        local_model = next(
            model for model in payload["model_catalog"] if model["runtime"] == "local"
        )
        self.assertIn("status", local_model)
        self.assertIn("active", local_model)
        self.assertIn("loading", local_model)
        self.assertIn("loaded_model", local_model)

    def test_resolve_agent_display_name_prefers_saved_value(self) -> None:
        from core.agent.catalog import resolve_agent_display_name

        self.assertEqual(resolve_agent_display_name(""), "Lynx")
        self.assertEqual(resolve_agent_display_name("   "), "Lynx")
        self.assertEqual(resolve_agent_display_name("Nova"), "Nova")

    def test_provider_display_names_mapping(self) -> None:
        from core.agent.catalog import _PROVIDER_DISPLAY_NAMES

        self.assertEqual(_PROVIDER_DISPLAY_NAMES["gemini"], "Google AI Studio")
        self.assertEqual(_PROVIDER_DISPLAY_NAMES["openrouter"], "OpenRouter")
        self.assertEqual(_PROVIDER_DISPLAY_NAMES["llama_cpp"], "llama.cpp")
