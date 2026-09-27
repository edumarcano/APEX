"""Health and current boot-configuration API contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.api import app
from core.settings.store import RuntimeSettingsStore


class ApiHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="apex_health_")
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        config_path = root / "config.json"
        config_path.write_text(
            json.dumps({"features": {"weather": True}, "ask_apex": {"enabled": True}}),
            encoding="utf-8",
        )
        self.settings = RuntimeSettingsStore(
            config_path=config_path,
            local_config_path=root / "config.local.json",
        )
        self.patches = [
            mock.patch("core.api.routers.system.get_settings_store", return_value=self.settings),
            mock.patch("core.database.DB_NAME", str(root / "apex_memory.db")),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        from core import database

        database.initialize_db()
        self.client = TestClient(app, raise_server_exceptions=True)

    def test_root_liveness_and_readiness_remain_available(self) -> None:
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json(), {"status": "online", "system": "APEX"})

        live = self.client.get("/api/v1/health/live")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json(), {"status": "live"})

        ready = self.client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(
            ready.json(), {"status": "ready", "config": "ok", "database": "ok"}
        )

    def test_boot_config_exposes_current_agent_and_no_legacy_pipeline_fields(self) -> None:
        response = self.client.get("/api/v1/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("cortex_initial_selection", payload)
        self.assertEqual(payload["cortex_initial_selection"]["agent"], "apex")
        self.assertNotIn("briefing_default_mode", payload)
        self.assertNotIn("synthesis_strategy", payload)


if __name__ == "__main__":
    unittest.main()
