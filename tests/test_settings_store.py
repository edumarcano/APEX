"""Regression coverage for persisted singular APEX Agent settings."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

from core.config import CORTEX_CONVERSATIONS_ARCHIVED_RETENTION_DAYS
from core.settings.models import (
    AgentSettingsPatch,
    CloudSettingsPatch,
    FeaturesPatch,
    LocalSettingsPatch,
    SettingsPatch,
)
from core.settings.normalize import NormalizationIssues, normalize_layer
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

        self.assertEqual(settings.selected_model, "z-ai/glm-5.3-flash")
        self.assertEqual(settings.cloud.effort, "low")
        self.assertEqual(settings.local.context_window, 16384)

    def test_retired_news_feature_in_disk_config_is_ignored_without_losing_preferences(self) -> None:
        _write_json(self.config_path, {
            "features": {
                "weather": True,
                "sports": True,
                "news": True,
                "email": True,
                "calendar": False,
                "market": True,
            },
            "ask_apex": {"enabled": True},
        })
        store = self._store()

        loaded = store.get_snapshot().features
        self.assertTrue(loaded.weather)
        self.assertTrue(loaded.sports)
        self.assertTrue(loaded.email)
        self.assertTrue(loaded.market)
        self.assertFalse(loaded.calendar)
        self.assertFalse(hasattr(loaded, "news"))

        updated = store.apply_patch(
            SettingsPatch.model_validate({"features": {"weather": False}})
        ).features
        self.assertFalse(updated.weather)
        self.assertTrue(updated.sports)
        self.assertTrue(updated.email)
        self.assertTrue(updated.market)
        self.assertFalse(updated.calendar)
        self.assertFalse(hasattr(updated, "news"))

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

    def test_activity_report_folder_settings_persist_only_in_the_local_layer(self) -> None:
        folder = self._temp_root() / "synced reports"
        settings = self._store().apply_patch(SettingsPatch.model_validate({
            "activity_report_folder": {
                "enabled": True,
                "folder_path": str(folder),
            },
        }))

        self.assertTrue(settings.activity_report_folder.enabled)
        self.assertEqual(settings.activity_report_folder.folder_path, str(folder))
        local = json.loads(self.local_path.read_text(encoding="utf-8"))
        tracked = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(local["activity_report_folder"], {
            "enabled": True,
            "folder_path": str(folder),
        })
        self.assertNotIn("activity_report_folder", tracked)

    def test_activity_report_folder_rejects_relative_paths_and_ignores_tracked_values(self) -> None:
        with self.assertRaises(ValidationError):
            SettingsPatch.model_validate({"activity_report_folder": {"folder_path": "relative"}})

        _write_json(self.config_path, {
            "activity_report_folder": {"enabled": True, "folder_path": str(self.config_path.parent), },
        })
        settings = self._store().get_snapshot().activity_report_folder
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.folder_path, "")

    def test_report_folder_rejects_client_id_field(self) -> None:
        folder = self._temp_root() / "legacy report folder"
        original = {
            "activity_report_folder": {
                "enabled": True,
                "folder_path": str(folder),
                "client_id": "grok-bot",
            },
            "microsoft_todo": {"reminder_list_id": "personal"},
        }
        _write_json(self.local_path, original)

        store = self._store()
        snapshot = store.get_snapshot()
        self.assertTrue(snapshot.activity_report_folder.enabled)
        self.assertEqual(snapshot.activity_report_folder.folder_path, str(folder))
        self.assertIsNotNone(store.load_warning)
        self.assertEqual(json.loads(self.local_path.read_text(encoding="utf-8")), original)

        store.apply_patch(SettingsPatch(user_designation="Operator"))
        saved = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(
            saved["activity_report_folder"],
            {"enabled": True, "folder_path": str(folder), "client_id": "grok-bot"},
        )
        self.assertEqual(saved["microsoft_todo"], {"reminder_list_id": "personal"})

    def test_agent_display_name_is_local_only_and_validated(self) -> None:
        _write_json(self.config_path, {"agent_display_name": "Tracked"})
        store = self._store()
        self.assertEqual(store.get_snapshot().agent_display_name, "")

        _write_json(self.local_path, {"agent_display_name": "  Nova  Agent  "})
        store = self._store()
        self.assertEqual(store.get_snapshot().agent_display_name, "Nova Agent")

        store.apply_patch(SettingsPatch(agent_display_name=""))
        saved = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["agent_display_name"], "")

        _write_json(self.local_path, {"agent_display_name": "x" * 81})
        store = self._store()
        self.assertFalse(store.local_override_active)
        self.assertIn("agent_display_name", store.load_warning or "")

        with self.assertRaises(ValidationError):
            SettingsPatch.model_validate({"agent_display_name": "x" * 81})

    def _temp_root(self) -> Path:
        return self.config_path.parent

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
        self.assertEqual(settings.selected_model, "z-ai/glm-5.3-flash")
        self.assertIn("obsolete_agent", store.load_warning or "")
        self.assertEqual(
            json.loads(self.local_path.read_text(encoding="utf-8")),
            {"ask_apex": {"obsolete_agent": "retired"}},
        )

    def test_legacy_briefing_preferences_are_inert_and_not_mapped(self) -> None:
        original = {
            "briefing": {"default_mode": "structured", "model_id": "old/model"},
            "ask_apex": {"selected_model": "gpt-5.6-luna"},
        }
        _write_json(self.local_path, original)

        store = self._store()
        settings = store.get_snapshot()

        self.assertEqual(settings.ask_apex.selected_model, "gpt-5.6-luna")
        self.assertFalse(hasattr(settings, "briefing"))
        self.assertEqual(json.loads(self.local_path.read_text(encoding="utf-8")), original)

        store.apply_patch(SettingsPatch(user_designation="Operator"))
        saved = json.loads(self.local_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["briefing"], original["briefing"])
        self.assertEqual(saved["user_designation"], "Operator")

    def test_legacy_agent_tool_defaults_are_not_used_as_runtime_defaults(self) -> None:
        _write_json(self.local_path, {
            "tool_profiles": {"default_profile_by_agent": {"apex": "custom"}},
        })

        settings = self._store().get_snapshot().tool_profiles

        self.assertEqual(settings.default_profile_by_runtime, {})
        self.assertTrue(self._store().local_override_active)

    def test_unsupported_engine_uses_the_normal_invalid_engine_path(self) -> None:
        issues = NormalizationIssues()
        normalized = normalize_layer(
            {"tts_settings": {"primary_tts": "unsupported"}},
            layer_name="config.local.json",
            issues=issues,
        )

        self.assertNotIn("tts_settings", normalized)
        self.assertTrue(any("not a valid engine" in item for item in issues.errors))

    def test_persistence_failure_keeps_the_published_snapshot_unchanged(self) -> None:
        store = self._store()
        before = store.get_snapshot()
        with mock.patch("os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(SettingsPersistenceError):
                store.apply_patch(SettingsPatch(features=FeaturesPatch(sports=True)))

        self.assertEqual(store.get_snapshot(), before)


class ConversationRetentionConfigTests(unittest.TestCase):
    def test_default_retention_is_thirty_days(self) -> None:
        self.assertEqual(CORTEX_CONVERSATIONS_ARCHIVED_RETENTION_DAYS, 30)

    def test_retention_config_is_not_treated_as_an_unknown_editable_setting(self) -> None:
        issues = NormalizationIssues()

        normalized = normalize_layer(
            {"cortex_conversations": {"archived_retention_days": 30}},
            layer_name="config.json",
            issues=issues,
        )

        self.assertEqual(normalized, {})
        self.assertEqual(issues.warnings, [])


if __name__ == "__main__":
    unittest.main()
