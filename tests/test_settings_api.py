"""API and boot-config tests for live runtime settings."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.settings.models import SettingsPatch, VoicePatch
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
                "mode": "cloud",
                "cloud_profile": "panthera",
                "cloud_effort": "focused",
                "local_profile": "mus",
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
        self.assertEqual(payload["schema_version"], 6)
        self.assertTrue(payload["settings"]["features"]["market"])
        self.assertTrue(payload["settings"]["features"]["weather"])
        self.assertEqual(payload["settings"]["briefing"]["default_mode"], "panthera")
        self.assertEqual(payload["settings"]["voice"]["mode"], "automatic")
        self.assertTrue(payload["settings"]["modules"]["f1"])
        self.assertEqual(payload["settings"]["assistant"]["cloud_profile"], "panthera")
        self.assertEqual(payload["settings"]["assistant"]["mode"], "cloud")
        self.assertEqual(payload["settings"]["voice"]["engine"], "google")
        self.assertFalse(payload["settings"]["mcp"]["enabled"])
        self.assertFalse(payload["settings"]["mcp"]["servers"]["github"]["enabled"])
        self.assertIn("local_file_present", payload)
        self.assertIn("local_override_active", payload)
        self.assertIn("load_warning", payload)
        self.assertIn("dev_mode_active", payload)
        self.assertIn("demo_mode_active", payload)

    def test_market_patch_is_exposed_by_boot_config(self) -> None:
        response = self.client.patch(
            "/api/v1/settings", json={"features": {"market": False}}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["settings"]["features"]["market"])

        boot = self.client.get("/api/v1/config")
        self.assertEqual(boot.status_code, 200)
        self.assertFalse(boot.json()["market_enabled"])

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
        response = self.client.patch(
            "/api/v1/settings",
            json={"features": {"weather": True, "unknown": True}},
        )
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
            json={"assistant": {"cloud_profile": "not-a-profile"}},
        )
        self.assertEqual(response.status_code, 422)

    def test_empty_patch_returns_current_without_write(self) -> None:
        response = self.client.patch("/api/v1/settings", json={})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.local_path.is_file())

    def test_persistence_failure_leaves_snapshot_unchanged(self) -> None:
        before = self.client.get("/api/v1/settings").json()["settings"]
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
        after = self.client.get("/api/v1/settings").json()["settings"]
        self.assertEqual(after, before)
        self.assertFalse(after["features"]["news"])

    def test_concurrent_different_field_patches_merge(self) -> None:
        errors: list[BaseException] = []

        def patch_news() -> None:
            try:
                result = self.client.patch(
                    "/api/v1/settings",
                    json={"features": {"news": True}},
                )
                if result.status_code != 200:
                    errors.append(AssertionError(result.text))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        def patch_gender() -> None:
            try:
                result = self.client.patch(
                    "/api/v1/settings",
                    json={"voice": {"gender": "male"}},
                )
                if result.status_code != 200:
                    errors.append(AssertionError(result.text))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=patch_news),
            threading.Thread(target=patch_gender),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        snapshot = self.store.get_snapshot()
        self.assertTrue(snapshot.features.news)
        self.assertEqual(snapshot.voice.gender, "male")

    def test_config_boot_reads_store_including_local_profile(self) -> None:
        self.store.apply_patch(
            SettingsPatch.model_validate(
                {"assistant": {"enabled": False, "mode": "local", "local_profile": "sorex"}}
            )
        )
        response = self.client.get("/api/v1/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_profile"], "sorex")
        self.assertFalse(payload["ask_apex_enabled"])
        self.assertIn("max_session_messages", payload)
        self.assertIn("dev_mode_active", payload)
        self.assertIn("demo_mode_active", payload)

    def test_dev_demo_not_patchable(self) -> None:
        response = self.client.patch(
            "/api/v1/settings",
            json={"dev_mode_active": True},
        )
        self.assertEqual(response.status_code, 422)

    def test_unavailable_profile_remains_valid_default(self) -> None:
        response = self.client.patch(
            "/api/v1/settings",
            json={"assistant": {"cloud_profile": "neofelis"}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["settings"]["assistant"]["cloud_profile"],
            "neofelis",
        )
        config_payload = self.client.get("/api/v1/config").json()
        self.assertEqual(config_payload["default_profile"], "neofelis")


class SettingsApiVoicePatchSmokeTests(unittest.TestCase):
    def test_voice_patch_model_round_trip(self) -> None:
        patch = SettingsPatch(voice=VoicePatch(engine="kokoro", gender="male"))
        dumped = patch.model_dump(exclude_none=True)
        self.assertEqual(dumped["voice"]["engine"], "kokoro")
        self.assertEqual(dumped["voice"]["gender"], "male")


if __name__ == "__main__":
    unittest.main()
