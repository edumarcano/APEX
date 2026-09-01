"""Regression coverage for persisted singular Apex Agent settings."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from core.settings.models import (
    AgentSettingsPatch,
    CloudSettingsPatch,
    FeaturesPatch,
    LocalSettingsPatch,
    SettingsPatch,
)
from core.settings.store import RuntimeSettingsStore, SettingsPersistenceError


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


class SettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_settings_")
        self.addCleanup(self._temp_dir.cleanup)
        root = Path(self._temp_dir.name)
        self.config_path = root / "config.json"
        self.local_path = root / "config.local.json"
        _write_json(self.config_path, {"ask_apex": {"enabled": True}})

    def _store(self) -> RuntimeSettingsStore:
        return RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )

    def test_fresh_settings_use_apex_and_the_default_cloud_model(self) -> None:
        settings = self._store().get_snapshot().ask_apex

        self.assertEqual(settings.selected_model, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(settings.cloud.effort, "low")
        self.assertEqual(settings.local.context_window, 16384)

    def test_model_selection_updates_the_matching_runtime_memory(self) -> None:
        store = self._store()
        settings = store.apply_patch(
            SettingsPatch(
                ask_apex=AgentSettingsPatch(
                    selected_model="gemma-4-E2B-Q4_K_M.gguf",
                    local=LocalSettingsPatch(context_window=32768),
                )
            )
        ).ask_apex

        self.assertEqual(settings.selected_model, "gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(settings.local.last_model, "gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(settings.local.context_window, 32768)
        written = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(written["ask_apex"]["selected_model"], settings.selected_model)

    def test_cloud_and_local_controls_are_independent(self) -> None:
        settings = self._store().apply_patch(
            SettingsPatch(
                ask_apex=AgentSettingsPatch(
                    cloud=CloudSettingsPatch(effort="high", personal_context_enabled=True),
                    local=LocalSettingsPatch(personal_context_enabled=True),
                )
            )
        ).ask_apex

        self.assertEqual(settings.cloud.effort, "high")
        self.assertTrue(settings.cloud.personal_context_enabled)
        self.assertTrue(settings.local.personal_context_enabled)

    def test_invalid_models_are_rejected_at_the_patch_boundary(self) -> None:
        with self.assertRaises(ValidationError):
            SettingsPatch.model_validate(
                {"ask_apex": {"selected_model": "not-a-model"}}
            )
        with self.assertRaises(ValidationError):
            SettingsPatch.model_validate(
                {"ask_apex": {"cloud": {"last_model": "gemma-4-E2B-Q4_K_M.gguf"}}}
            )

    def test_stale_local_agent_settings_are_ignored_without_rewriting_the_file(self) -> None:
        _write_json(
            self.local_path,
            {
                "ask_apex": {
                    "obsolete_agent": "retired",
                },
            },
        )

        store = self._store()
        settings = store.get_snapshot().ask_apex

        self.assertFalse(store.local_override_active)
        self.assertEqual(settings.selected_model, "deepseek/deepseek-v4-flash-0731")
        self.assertIn("obsolete_agent", store.load_warning or "")
        self.assertEqual(
            json.loads(self.local_path.read_text(encoding="utf-8")),
            {"ask_apex": {"obsolete_agent": "retired"}},
        )

    def test_persistence_failure_keeps_the_published_snapshot_unchanged(self) -> None:
        store = self._store()
        before = store.get_snapshot()
        with mock.patch("os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(SettingsPersistenceError):
                store.apply_patch(SettingsPatch(features=FeaturesPatch(sports=True)))

        self.assertEqual(store.get_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
