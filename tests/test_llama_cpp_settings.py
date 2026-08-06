"""Tests for editable llama.cpp runtime settings and live host resolution."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.agent.providers.llama_cpp_lifecycle import LlamaCppRuntimeBackend
from core.settings.models import FeaturesPatch, LlamaCppPatch, SettingsPatch
from core.settings.normalize import normalize_layer
from core.settings.store import RuntimeSettingsStore, SettingsPersistenceError, reset_settings_store_for_tests


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class LlamaCppSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_llama_cpp_settings_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        _write_json(
            self.config_path,
            {
                "llama_cpp": {
                    "enabled": False,
                    "host": "http://127.0.0.1:8080",
                    "request_timeout_seconds": 180,
                    "resource_gates": {
                        "apodemus": {"ram_limit": 82.0, "cpu_limit": 92.0}
                    },
                }
            },
        )

    def _store(self) -> RuntimeSettingsStore:
        return RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )

    def test_tracked_defaults_remain_disabled(self) -> None:
        store = self._store()
        snap = store.get_snapshot()
        self.assertFalse(snap.llama_cpp.enabled)
        self.assertEqual(snap.llama_cpp.host, "http://127.0.0.1:8080")

    def test_local_enabled_override(self) -> None:
        _write_json(
            self.local_path,
            {"llama_cpp": {"enabled": True, "host": "http://localhost:9090"}},
        )
        store = self._store()
        snap = store.get_snapshot()
        self.assertTrue(snap.llama_cpp.enabled)
        self.assertEqual(snap.llama_cpp.host, "http://localhost:9090")
        self.assertTrue(store.local_override_active)

    def test_patch_persists_only_editable_fields(self) -> None:
        store = self._store()
        store.apply_patch(
            SettingsPatch(llama_cpp=LlamaCppPatch(enabled=True, host="http://127.0.0.1:8181"))
        )
        local = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(local["llama_cpp"]["enabled"], True)
        self.assertEqual(local["llama_cpp"]["host"], "http://127.0.0.1:8181")
        self.assertNotIn("resource_gates", local["llama_cpp"])
        self.assertNotIn("request_timeout_seconds", local["llama_cpp"])

    def test_advanced_local_fields_survive_unrelated_patch(self) -> None:
        _write_json(
            self.local_path,
            {
                "llama_cpp": {
                    "enabled": True,
                    "host": "http://127.0.0.1:8080",
                    "request_timeout_seconds": 240,
                    "resource_gates": {"apodemus": {"ram_limit": 70.0, "cpu_limit": 80.0}},
                },
                "features": {"weather": True},
            },
        )
        store = self._store()
        store.apply_patch(SettingsPatch(features=FeaturesPatch(weather=False)))
        local = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(local["llama_cpp"]["request_timeout_seconds"], 240)
        self.assertEqual(
            local["llama_cpp"]["resource_gates"]["apodemus"]["ram_limit"], 70.0
        )
        self.assertFalse(local["features"]["weather"])

    def test_invalid_host_is_rejected(self) -> None:
        store = self._store()
        with self.assertRaises(SettingsPersistenceError):
            store.apply_patch(
                SettingsPatch(
                    llama_cpp=LlamaCppPatch(host="http://example.com:8080")
                )
            )

    def test_malformed_port_is_rejected(self) -> None:
        store = self._store()
        with self.assertRaises(SettingsPersistenceError) as raised:
            store.apply_patch(
                SettingsPatch(
                    llama_cpp=LlamaCppPatch(host="http://localhost:notaport")
                )
            )
        self.assertIn("valid port", str(raised.exception))

    def test_schema_eight_local_file_loads_with_defaults(self) -> None:
        _write_json(
            self.local_path,
            {
                "schema_version": 8,
                "ask_apex": {"apodemus_context_window": 16384},
            },
        )
        store = self._store()
        snap = store.get_snapshot()
        self.assertEqual(snap.ask_apex.apodemus_context_window, 16384)
        self.assertFalse(snap.llama_cpp.enabled)
        self.assertEqual(snap.llama_cpp.host, "http://127.0.0.1:8080")


class LlamaCppHostNormalizationTests(unittest.TestCase):
    def test_accepts_ipv6_loopback(self) -> None:
        normalized = normalize_layer(
            {"llama_cpp": {"enabled": True, "host": "http://[::1]:8080"}},
            layer_name="config.local.json",
        )
        self.assertEqual(normalized["llama_cpp"]["host"], "http://[::1]:8080")

    def test_rejects_credentials(self) -> None:
        from core.settings.normalize import NormalizationIssues

        issues = NormalizationIssues()
        normalized = normalize_layer(
            {"llama_cpp": {"host": "http://user:pass@127.0.0.1:8080"}},
            layer_name="config.local.json",
            issues=issues,
        )
        self.assertNotIn("host", normalized.get("llama_cpp", {}))
        self.assertTrue(any("credentials" in error for error in issues.errors))

    def test_rejects_malformed_port(self) -> None:
        from core.settings.normalize import NormalizationIssues

        issues = NormalizationIssues()
        normalized = normalize_layer(
            {"llama_cpp": {"host": "http://localhost:notaport"}},
            layer_name="config.local.json",
            issues=issues,
        )
        self.assertNotIn("host", normalized.get("llama_cpp", {}))
        self.assertTrue(any("valid port" in error for error in issues.errors))


class LlamaCppRuntimeIntegrationTests(unittest.TestCase):
    def test_runtime_uses_resolved_host_for_models_probe(self) -> None:
        backend = LlamaCppRuntimeBackend()
        session = mock.Mock()
        response = mock.Mock()
        response.raise_for_status = mock.Mock()
        response.json.return_value = {"data": []}
        session.get.return_value = response

        with (
            mock.patch(
                "core.agent.providers.llama_cpp_runtime.get_settings_store"
            ) as get_store,
            mock.patch(
                "core.agent.providers.llama_cpp_lifecycle._SESSION",
                session,
            ),
            mock.patch(
                "core.agent.providers.llama_cpp_supervisor.get_llama_cpp_server_supervisor"
            ) as get_supervisor,
        ):
            get_store.return_value.get_snapshot.return_value.llama_cpp.enabled = True
            get_store.return_value.get_snapshot.return_value.llama_cpp.host = (
                "http://localhost:9191"
            )
            get_supervisor.return_value.ensure_ready.return_value = None
            get_supervisor.return_value.maybe_stop_after_idle.return_value = None
            backend.get_status_snapshot(force_refresh=True)

        session.get.assert_called_once()
        self.assertEqual(session.get.call_args.args[0], "http://localhost:9191/models")

    def test_settings_patch_invalidates_status_cache(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(prefix="apex_llama_cpp_api_")
        self.addCleanup(temp_dir.cleanup)
        config_path = Path(temp_dir.name) / "config.json"
        local_path = Path(temp_dir.name) / "config.local.json"
        _write_json(
            config_path,
            {"llama_cpp": {"enabled": False, "host": "http://127.0.0.1:8080"}},
        )
        reset_settings_store_for_tests()
        store = RuntimeSettingsStore(
            config_path=config_path,
            local_config_path=local_path,
        )
        patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store",
                return_value=store,
            ),
            mock.patch("core.speaker.get_settings_store", return_value=store),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)

        from core.api import app

        client = TestClient(app)
        backend = LlamaCppRuntimeBackend()
        backend._status_snapshot = {  # type: ignore[assignment]
            "provider": "llama_cpp",
            "reachable": True,
            "installed_models": [],
            "loaded_models": [],
            "sampled_at": 0.0,
        }
        with mock.patch(
            "core.api.routers.system.get_local_runtime_backend",
            return_value=backend,
        ):
            response = client.patch(
                "/api/v1/settings",
                json={"llama_cpp": {"enabled": True}},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(backend._status_snapshot)

    def test_settings_response_exposes_only_editable_llama_cpp_fields(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(prefix="apex_llama_cpp_api_get_")
        self.addCleanup(temp_dir.cleanup)
        config_path = Path(temp_dir.name) / "config.json"
        local_path = Path(temp_dir.name) / "config.local.json"
        _write_json(
            config_path,
            {
                "llama_cpp": {
                    "enabled": False,
                    "host": "http://127.0.0.1:8080",
                    "resource_gates": {"apodemus": {"ram_limit": 82.0, "cpu_limit": 92.0}},
                }
            },
        )
        reset_settings_store_for_tests()
        store = RuntimeSettingsStore(
            config_path=config_path,
            local_config_path=local_path,
        )
        patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store",
                return_value=store,
            ),
            mock.patch("core.speaker.get_settings_store", return_value=store),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)

        from core.api import app

        client = TestClient(app)
        payload = client.get("/api/v1/settings").json()
        llama_cpp = payload["settings"]["llama_cpp"]
        self.assertEqual(
            set(llama_cpp.keys()),
            {"enabled", "managed", "host", "executable_path", "preset_path"},
        )
        self.assertNotIn("resource_gates", payload["settings"])
        self.assertNotIn("request_timeout_seconds", payload["settings"])
