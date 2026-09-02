"""Coverage for the singular Apex Agent model catalog."""

from __future__ import annotations

import unittest
from unittest import mock

from core.agent.catalog import AGENT_SPECS, build_agent_used_metadata, resolve_model_selection
from core.agent.model_catalog import get_model_profile, visible_cloud_models, visible_local_models
from core.settings.models import AgentSettings, CloudSettings, LocalSettings


class ApexAgentCatalogTests(unittest.TestCase):
    def test_catalog_has_one_native_agent(self) -> None:
        self.assertEqual(tuple(AGENT_SPECS), ("apex",))
        self.assertEqual(AGENT_SPECS["apex"].display_name, "Apex Agent")

    def test_response_metadata_runtime_comes_from_the_resolved_model(self) -> None:
        cloud = build_agent_used_metadata(
            "apex", provider="openrouter", configured_model="deepseek/deepseek-v4-flash-0731",
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

    def test_visible_catalogs_are_ordered_by_runtime(self) -> None:
        self.assertEqual(
            [profile.model_id for profile in visible_cloud_models()],
            ["deepseek/deepseek-v4-flash-0731", "gpt-5.6-luna", "gemini-3.7-flash"],
        )
        self.assertEqual(
            [profile.model_id for profile in visible_local_models()],
            [
                "gemma-4-E2B-Q4_K_M.gguf",
                "gemma-4-E4B-Q4_K_M.gguf",
                "Qwen3.5-4B-Q4_K_M.gguf",
            ],
        )

    def test_cloud_profiles_keep_provider_specific_credentials(self) -> None:
        expected = {
            "gpt-5.6-luna": "OPENAI_API_KEY",
            "deepseek/deepseek-v4-flash-0731": "OPENROUTER_API_KEY",
            "gemini-3.7-flash": "GEMINI_API_KEY",
        }
        self.assertEqual(
            {model_id: get_model_profile(model_id).credential_env for model_id in expected},
            expected,
        )

    def test_cortex_agent_endpoint_returns_one_catalog(self) -> None:
        from fastapi.testclient import TestClient
        from core.api.app import app

        with mock.patch("core.api.routers.cortex.get_settings_store") as store:
            store.return_value.get_snapshot.return_value.ask_apex = AgentSettings()
            response = TestClient(app).get("/api/v1/cortex/agent")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["key"], "apex")
        self.assertEqual(payload["selected_model"], "deepseek/deepseek-v4-flash-0731")
        self.assertTrue(payload["model_catalog"])
        local_model = next(
            model for model in payload["model_catalog"] if model["runtime"] == "local"
        )
        self.assertIn("status", local_model)
        self.assertIn("active", local_model)
        self.assertIn("loading", local_model)
        self.assertIn("loaded_model", local_model)
