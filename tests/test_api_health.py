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
from core.host.identity import create_host_context
from core.runtime_paths import RuntimePaths


class ApiHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="apex_health_")
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        from core.api.app import app

        stale = getattr(app.state, "host_context", None)
        if stale is not None and stale.profile_lock.acquired:
            stale.release()
        app.state.host_context = None
        app.state.lifecycle_entered = False
        app.state.lifecycle_established = False
        app.state.lifecycle_cleanup_complete = False
        app.state.http_shutdown_timed_out = False
        runtime_paths = mock.patch(
            "core.runtime_paths.get_runtime_paths",
            return_value=RuntimePaths(resource_root=root, data_root=root),
        )
        runtime_paths.start()
        self.addCleanup(runtime_paths.stop)
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

    def test_runtime_identity_requires_established_lifecycle_and_hides_paths(self) -> None:
        from core.api.app import app

        root = Path(self.temp_dir.name) / "profile"
        context = create_host_context(
            RuntimePaths(resource_root=root, data_root=root), frozen=False
        )
        old_context = getattr(app.state, "host_context", None)
        old_established = getattr(app.state, "lifecycle_established", False)
        app.state.host_context = context
        app.state.lifecycle_established = True
        try:
            response = self.client.get("/api/v1/runtime")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload, context.identity.as_dict())
            self.assertNotIn(str(root), response.text)

            app.state.lifecycle_established = False
            unavailable = self.client.get("/api/v1/runtime")
            self.assertEqual(unavailable.status_code, 503)
        finally:
            context.release()
            app.state.host_context = old_context
            app.state.lifecycle_established = old_established

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
