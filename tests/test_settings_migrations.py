"""Settings migrations for retired Agent and briefing selections."""

from __future__ import annotations

import unittest

from core.agent.catalog import (
    migrate_schema15_ask_apex,
    migrate_schema5_briefing,
    migrate_schema7_ask_apex,
)


class SettingsMigrationTests(unittest.TestCase):
    def test_legacy_cloud_agents_map_to_panthera(self) -> None:
        for legacy in ("comet", "nova", "pulsar"):
            with self.subTest(legacy=legacy):
                migrated = migrate_schema7_ask_apex(
                    {"enabled": True, "default_profile": legacy}
                )
                self.assertEqual(migrated["runtime"], "cloud")
                self.assertEqual(migrated["cloud_agent"], "panthera")
                self.assertEqual(migrated["effort"], "focused")
                self.assertEqual(migrated["local_agent"], "apodemus")

    def test_legacy_local_agents_map_to_local_apodemus(self) -> None:
        for legacy in ("lynx", "acinonyx", "neofelis"):
            with self.subTest(legacy=legacy):
                migrated = migrate_schema7_ask_apex({"default_profile": legacy})
                self.assertEqual(migrated["runtime"], "local")
                self.assertEqual(migrated["local_agent"], "apodemus")
                self.assertEqual(migrated["cloud_agent"], "panthera")
                self.assertEqual(migrated["effort"], "focused")

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

    def test_schema15_maps_legacy_cloud_agents_to_panthera_models(self) -> None:
        expectations = {
            "neofelis": ("gemini", "gemini-3.6-flash"),
            "delphinus": ("xai", "grok-4.3"),
            "orcinus": ("xai", "grok-4.5"),
            "acinonyx": ("gemini", "gemini-3.5-flash-lite"),
        }
        for legacy, (provider, model) in expectations.items():
            with self.subTest(legacy=legacy):
                migrated = migrate_schema15_ask_apex(
                    {"runtime": "cloud", "cloud_agent": legacy, "effort": "extended"}
                )
                self.assertEqual(migrated["agent"], "panthera")
                self.assertEqual(migrated["panthera"]["provider"], provider)
                self.assertEqual(migrated["panthera"]["model"], model)
                self.assertEqual(migrated["panthera"]["effort"], "extended")

    def test_schema15_maps_legacy_local_agents_to_lynx_models(self) -> None:
        expectations = {
            "apodemus": ("llama_cpp", "gemma-4-E2B-Q4_K_M.gguf"),
            "neotoma": ("llama_cpp", "gemma-4-E4B-Q4_K_M.gguf"),
            "sorex": ("ollama", "qwen3:1.7b"),
            "mus": ("ollama", "qwen3:4b-instruct"),
        }
        for legacy, (runtime, model) in expectations.items():
            with self.subTest(legacy=legacy):
                migrated = migrate_schema15_ask_apex(
                    {"runtime": "local", "local_agent": legacy}
                )
                self.assertEqual(migrated["agent"], "lynx")
                self.assertEqual(migrated["lynx"]["runtime"], runtime)
                self.assertEqual(migrated["lynx"]["model"], model)

    def test_schema15_preserves_hosted_tool_toggles(self) -> None:
        migrated = migrate_schema15_ask_apex(
            {
                "runtime": "cloud",
                "cloud_agent": "neofelis",
                "neofelis_google_search_enabled": False,
                "neofelis_google_maps_enabled": False,
                "delphinus_x_search_enabled": False,
                "orcinus_x_search_enabled": False,
            }
        )
        hosted = migrated["panthera"]["hosted_tools"]
        self.assertFalse(hosted["google_search"])
        self.assertFalse(hosted["google_maps"])
        self.assertFalse(hosted["x_search"])


if __name__ == "__main__":
    unittest.main()
