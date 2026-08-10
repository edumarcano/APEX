"""Settings migrations for retired Agent and briefing selections."""

from __future__ import annotations

import unittest

from core.agent.catalog import (
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


if __name__ == "__main__":
    unittest.main()
