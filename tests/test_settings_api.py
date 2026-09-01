"""API and boot-config tests for live runtime settings."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.settings.models import SettingsPatch, FootballPatch, FootballTeamPatch, MarketPatch
from core.settings.store import (
    RuntimeSettingsStore,
    SettingsPersistenceError,
    reset_settings_store_for_tests,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class SettingsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_settings_api_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        self.base = {
            "features": {
                "weather": True,
                "sports": True,
                "news": False,
                "email": False,
                "calendar": True,
                "market": True,
            },
            "modules": {"football": False, "f1": True},
            "ask_apex": {
                "enabled": True,
                "selected_model": "gpt-5.6-luna",
                "cloud": {
                    "last_model": "gpt-5.6-luna",
                    "effort": "medium",
                },
                "local": {
                    "last_model": "gemma-4-E2B-Q4_K_M.gguf",
                },
            },
            "tts_settings": {
                "primary_tts": "google",
                "voice_gender": "female",
            },
        }
        _write_json(self.config_path, self.base)
        reset_settings_store_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._store_patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store", return_value=self.store
            ),
            mock.patch("core.speaker.get_settings_store", return_value=self.store),
        ]
        for patcher in self._store_patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)

        # Import after patches so handlers resolve the test store.
        from core.api import app

        self.client = TestClient(app)

    def test_get_settings_envelope(self) -> None:
        response = self.client.get("/api/v1/settings")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], 19)
        self.assertTrue(payload["settings"]["features"]["market"])
        self.assertTrue(payload["settings"]["features"]["weather"])
        self.assertEqual(payload["settings"]["briefing"]["default_mode"], "flash")
        self.assertEqual(payload["settings"]["voice"]["mode"], "automatic")
        self.assertTrue(payload["settings"]["modules"]["f1"])
        ask_apex = payload["settings"]["ask_apex"]
        self.assertEqual(ask_apex["selected_model"], "gpt-5.6-luna")
        self.assertEqual(ask_apex["cloud"]["last_model"], "gpt-5.6-luna")
        self.assertEqual(ask_apex["local"]["last_model"], "gemma-4-E2B-Q4_K_M.gguf")
        self.assertTrue(ask_apex["cloud"]["hosted_tools"]["google_maps"])
        self.assertTrue(ask_apex["cloud"]["hosted_tools"]["x_search"])
        self.assertEqual(payload["settings"]["voice"]["engine"], "google")
        self.assertFalse(payload["settings"]["mcp"]["enabled"])
        self.assertFalse(payload["settings"]["mcp"]["servers"]["github"]["enabled"])
        self.assertIn("local_file_present", payload)
        self.assertIn("local_override_active", payload)
        self.assertIn("load_warning", payload)
        self.assertIn("dev_mode_active", payload)
        self.assertIn("demo_mode_active", payload)

    def test_patch_football_and_market_symbol_lists(self) -> None:
        response = self.client.patch(
            "/api/v1/settings",
            json={
                "football": {
                    "teams": [{"id": 81, "name": "Barcelona"}],
                },
                "market": {"symbols": ["SPY", "AAPL"]},
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["settings"]["football"]["teams"],
            [{"id": 81, "name": "Barcelona"}],
        )
        self.assertEqual(payload["settings"]["market"]["symbols"], ["SPY", "AAPL"])

        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(
            written["football"]["teams"],
            [{"id": 81, "name": "Barcelona"}],
        )
        self.assertEqual(written["market"]["symbols"], ["SPY", "AAPL"])

    def test_market_patch_is_exposed_by_boot_config(self) -> None:
        response = self.client.patch(
            "/api/v1/settings", json={"features": {"market": False}}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["settings"]["features"]["market"])

        boot = self.client.get("/api/v1/config")
        self.assertEqual(boot.status_code, 200)
        self.assertFalse(boot.json()["market_enabled"])

    def test_focused_briefing_default_mode_persists_and_is_restored_on_boot(self) -> None:
        response = self.client.patch(
            "/api/v1/settings",
            json={"briefing": {"default_mode": "focused"}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["settings"]["briefing"]["default_mode"], "focused")

        boot = self.client.get("/api/v1/config")
        self.assertEqual(boot.status_code, 200)
        self.assertEqual(boot.json()["briefing_default_mode"], "focused")

        reloaded = self.client.get("/api/v1/settings")
        self.assertEqual(reloaded.json()["settings"]["briefing"]["default_mode"], "focused")

    def test_dev_flash_synthesis_reports_its_fixed_runtime_and_model(self) -> None:
        with mock.patch("core.api.routers.system.is_dev_mode", return_value=True), mock.patch(
            "core.api.routers.system.DEV_AI_SYNTHESIS", "flash"
        ), mock.patch("core.api.routers.system.DEMO_MODE", False):
            response = self.client.get("/api/v1/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synthesis_strategy"], "local")
        self.assertEqual(response.json()["synthesis_model_id"], "gemma-4-E2B-Q4_K_M.gguf")

    def test_partial_patch_persists_and_returns_resolved(self) -> None:
        response = self.client.patch(
            "/api/v1/settings",
            json={"features": {"news": True}, "voice": {"gender": "male"}},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["settings"]["features"]["news"])
        self.assertTrue(payload["settings"]["features"]["weather"])
        self.assertEqual(payload["settings"]["voice"]["gender"], "male")
        self.assertEqual(payload["settings"]["voice"]["engine"], "google")
        self.assertTrue(payload["local_file_present"])
        self.assertTrue(self.local_path.is_file())

        again = self.client.get("/api/v1/settings").json()
        self.assertTrue(again["settings"]["features"]["news"])
        self.assertEqual(again["settings"]["voice"]["gender"], "male")

    def test_unknown_field_rejected(self) -> None:
        for payload in (
            {"features": {"weather": True, "unknown": True}},
            {"briefing": {"default_mode": "unknown-mode"}},
            {"ask_apex": {"cloud": {"provider": "gemini"}}},
            {"ask_apex": {"local": {"runtime": "ollama"}}},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch("/api/v1/settings", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_mcp_patch_rejects_advanced_or_unknown_fields(self) -> None:
        for payload in (
            {"mcp": {"servers": {"custom": {"enabled": True}}}},
            {"mcp": {"servers": {"github": {"url": "https://unsafe.test"}}}},
            {"mcp": {"auth_token": "secret"}},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch("/api/v1/settings", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_mcp_patch_preserves_advanced_local_configuration(self) -> None:
        advanced = {
            "unrelated": {"keep": True},
            "mcp": {
                "enabled": False,
                "servers": {
                    "github": {
                        "enabled": False,
                        "url": "https://example.test/mcp",
                        "auth_env": "GITHUB_TOKEN_NAME_ONLY",
                        "tool_allowlist": ["search_code"],
                    },
                    "custom": {
                        "enabled": True,
                        "transport": "http",
                        "url": "https://custom.test/mcp",
                    },
                },
            },
        }
        _write_json(self.local_path, advanced)
        store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        store.apply_patch(
            SettingsPatch.model_validate(
                {
                    "mcp": {
                        "enabled": True,
                        "servers": {"github": {"enabled": True}},
                    }
                }
            )
        )
        persisted = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertTrue(persisted["mcp"]["enabled"])
        self.assertTrue(persisted["mcp"]["servers"]["github"]["enabled"])
        self.assertEqual(
            persisted["mcp"]["servers"]["github"]["tool_allowlist"],
            ["search_code"],
        )
        self.assertEqual(
            persisted["mcp"]["servers"]["custom"]["url"],
            "https://custom.test/mcp",
        )
        self.assertEqual(persisted["unrelated"], {"keep": True})

    def test_malformed_mcp_enablement_fails_closed_with_warning(self) -> None:
        _write_json(
            self.local_path,
            {
                "mcp": {
                    "enabled": "yes",
                    "servers": {"github": {"enabled": "yes", "url": "preserved"}},
                }
            },
        )
        store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self.assertFalse(store.get_snapshot().mcp.enabled)
        self.assertFalse(store.get_snapshot().mcp.servers.github.enabled)
        self.assertIn("Configuration warning", store.load_warning or "")
        store.apply_patch(
            SettingsPatch.model_validate({"mcp": {"enabled": True}})
        )
        persisted = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["mcp"]["servers"]["github"]["url"],
            "preserved",
        )

    def test_mcp_save_reconciles_running_manager(self) -> None:
        manager = mock.Mock()
        manager.reconfigure = mock.AsyncMock()
        resolved = mock.sentinel.resolved_mcp_config
        with (
            mock.patch(
                "core.api.routers.system.get_mcp_manager",
                return_value=manager,
            ),
            mock.patch(
                "core.api.routers.system.load_mcp_config",
                return_value=resolved,
            ),
        ):
            response = self.client.patch(
                "/api/v1/settings",
                json={
                    "mcp": {
                        "enabled": True,
                        "servers": {"github": {"enabled": True}},
                    }
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["settings"]["mcp"]["enabled"])
        manager.reconfigure.assert_awaited_once_with(resolved)

    def test_mcp_persistence_failure_does_not_reconcile(self) -> None:
        manager = mock.Mock()
        manager.reconfigure = mock.AsyncMock()
        with (
            mock.patch.object(
                self.store,
                "apply_patch",
                side_effect=SettingsPersistenceError("disk full"),
            ),
            mock.patch(
                "core.api.routers.system.get_mcp_manager",
                return_value=manager,
            ),
        ):
            response = self.client.patch(
                "/api/v1/settings",
                json={"mcp": {"enabled": True}},
            )
        self.assertEqual(response.status_code, 500)
        manager.reconfigure.assert_not_awaited()

    def test_invalid_profile_rejected(self) -> None:
        response = self.client.patch(
            "/api/v1/settings",
            json={"ask_apex": {"selected_model": "not-a-model"}},
        )
        self.assertEqual(response.status_code, 422)

    def test_empty_patch_returns_current_without_write(self) -> None:
        response = self.client.patch("/api/v1/settings", json={})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.local_path.is_file())

    def test_persistence_failure_leaves_snapshot_unchanged(self) -> None:
        with mock.patch.object(
            self.store,
            "apply_patch",
            side_effect=SettingsPersistenceError("disk full"),
        ):
            response = self.client.patch(
                "/api/v1/settings",
                json={"features": {"news": True}},
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("config.local.json", response.json()["detail"])

    def test_config_boot_reads_store_including_selected_local_model(self) -> None:
        self.store.apply_patch(
            SettingsPatch.model_validate(
                {
                    "ask_apex": {
                        "enabled": False,
                        "selected_model": "qwen3:1.7b",
                        "local": {"last_model": "qwen3:1.7b"},
                    }
                }
            )
        )
        with mock.patch("core.agent.catalog.is_dev_mode", return_value=False):
            response = self.client.get("/api/v1/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cortex_initial_selection"]["agent"], "apex")
        self.assertEqual(payload["cortex_initial_selection"]["model_id"], "qwen3:1.7b")
        self.assertEqual(payload["cortex_initial_selection"]["runtime"], "local")
        self.assertFalse(payload["ask_apex_enabled"])
        self.assertIn("max_recent_conversation_messages", payload)
        self.assertIn("dev_mode_active", payload)
        self.assertIn("demo_mode_active", payload)

    def test_dev_demo_not_patchable(self) -> None:
        response = self.client.patch(
            "/api/v1/settings",
            json={"dev_mode_active": True},
        )
        self.assertEqual(response.status_code, 422)

    def test_unavailable_dev_model_remains_a_valid_selected_model(self) -> None:
        with mock.patch("core.settings.normalize.is_dev_mode", return_value=True):
            response = self.client.patch(
                "/api/v1/settings",
                json={
                    "ask_apex": {
                        "selected_model": "gemini-3.6-flash",
                        "cloud": {"last_model": "gemini-3.6-flash"},
                    }
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["settings"]["ask_apex"]["selected_model"],
            "gemini-3.6-flash",
        )
        with mock.patch("core.agent.catalog.is_dev_mode", return_value=False):
            config_payload = self.client.get("/api/v1/config").json()
        self.assertEqual(config_payload["cortex_initial_selection"]["agent"], "apex")

if __name__ == "__main__":
    unittest.main()
