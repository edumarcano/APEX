"""Runtime integration tests for live settings snapshots."""

from __future__ import annotations

import ast
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core.api import (
    _compute_confidence_and_failures,
    _evaluate_sports_trust,
    query_agent,
)
from core.agent.types import AgentQueryRequest
from core.settings.models import (
    FeaturesSettings,
    ModulesSettings,
    SettingsPatch,
)
from core.settings.store import (
    RuntimeSettingsStore,
    reset_settings_store_for_tests,
)
from core import speaker


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class ConfidenceSnapshotTests(unittest.TestCase):
    def test_sports_parent_disabled_ignores_modules(self) -> None:
        score, failures = _compute_confidence_and_failures(
            weather_report="clear",
            sports_report="F1 race telemetry unavailable. Barcelona fixture telemetry unavailable.",
            news_report="",
            email_report="",
            calendar_report="",
            f1_cache_penalty=False,
            features=FeaturesSettings(weather=True, sports=False),
            modules=ModulesSettings(f1=True, football=True),
        )
        self.assertEqual(score, 100.0)
        self.assertEqual(failures, [])

    def test_sports_trust_uses_explicit_modules(self) -> None:
        earned, total, failed = _evaluate_sports_trust(
            "F1 race telemetry unavailable.",
            modules=ModulesSettings(f1=True, football=False),
        )
        self.assertEqual(total, 1.0)
        self.assertEqual(earned, 0.0)
        self.assertTrue(failed)


class SportsClientSnapshotTests(unittest.TestCase):
    def test_disabled_modules_skip_network(self) -> None:
        from clients import sports_client

        with mock.patch.object(sports_client.requests, "get") as get_mock:
            report, refreshed, f1_map = sports_client.fetch_sports_snapshot(
                f1=False,
                football=False,
            )
        self.assertEqual(report, "")
        self.assertTrue(refreshed)
        self.assertIsNone(f1_map)
        get_mock.assert_not_called()


class SpeakBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_speak_")
        self.addCleanup(self._temp_dir.cleanup)
        root = Path(self._temp_dir.name)
        self.config_path = root / "config.json"
        self.local_path = root / "config.local.json"
        _write_json(
            self.config_path,
            {
                "tts_settings": {
                    "primary_tts": "pyttsx3",
                    "voice_gender": "female",
                },
            },
        )
        reset_settings_store_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._patcher = mock.patch(
            "core.speaker.get_settings_store",
            return_value=self.store,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)

    def test_explicit_gender_bound_for_call(self) -> None:
        seen: list[str] = []

        def fake_route(text: str, tts_strategy: str, *, gender: str) -> None:
            seen.append(gender)

        with mock.patch.object(speaker, "_route_tts_playback", side_effect=fake_route):
            with mock.patch.object(speaker.config, "is_dev_mode", return_value=False):
                speaker.speak("hello", tts_override="pyttsx3", voice_gender="male")
        self.assertEqual(seen, ["male"])

    def test_mid_speech_store_change_does_not_alter_bound_call(self) -> None:
        seen: list[str] = []
        started = threading.Event()
        release = threading.Event()

        def fake_route(text: str, tts_strategy: str, *, gender: str) -> None:
            seen.append(gender)
            started.set()
            release.wait(timeout=2.0)

        def mutate() -> None:
            started.wait(timeout=2.0)
            self.store.apply_patch(
                SettingsPatch.model_validate({"voice": {"gender": "male"}})
            )
            release.set()

        mutator = threading.Thread(target=mutate)
        with mock.patch.object(speaker, "_route_tts_playback", side_effect=fake_route):
            with mock.patch.object(speaker.config, "is_dev_mode", return_value=False):
                mutator.start()
                speaker.speak("hello", tts_override="pyttsx3", voice_gender="female")
                mutator.join(timeout=2.0)
        self.assertEqual(seen, ["female"])
        self.assertEqual(self.store.get_snapshot().voice.gender, "male")


class AssistantGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_assistant_")
        self.addCleanup(self._temp_dir.cleanup)
        root = Path(self._temp_dir.name)
        self.config_path = root / "config.json"
        self.local_path = root / "config.local.json"
        _write_json(
            self.config_path,
            {
                "ask_apex": {"enabled": True, "default_profile": "comet"},
            },
        )
        reset_settings_store_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._patcher = mock.patch(
            "core.api.get_settings_store",
            return_value=self.store,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)

    def test_disabled_assistant_blocks_new_query(self) -> None:
        from fastapi import HTTPException

        self.store.apply_patch(
            SettingsPatch.model_validate({"assistant": {"enabled": False}})
        )
        with self.assertRaises(HTTPException) as ctx:
            query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    history=[],
                    profile="comet",
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)


class FrozenImportAuditTests(unittest.TestCase):
    """Confirm active execution modules do not import editable frozen constants."""

    _FORBIDDEN = frozenset(
        {
            "FEATURE_WEATHER",
            "FEATURE_SPORTS",
            "FEATURE_NEWS",
            "FEATURE_EMAIL",
            "FEATURE_CALENDAR",
            "MODULE_F1",
            "MODULE_FOOTBALL",
            "ASK_APEX_ENABLED",
            "PRIMARY_TTS",
            "VOICE_GENDER",
            "DEFAULT_CLOUD_PROFILE",
        }
    )

    def test_active_paths_do_not_import_frozen_editable_constants(self) -> None:
        root = Path(__file__).resolve().parents[1]
        targets = [
            root / "core" / "api.py",
            root / "core" / "speaker.py",
            root / "clients" / "sports_client.py",
        ]
        violations: list[str] = []
        for path in targets:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "core.config":
                    for alias in node.names:
                        if alias.name in self._FORBIDDEN:
                            violations.append(f"{path.name}:{alias.name}")
                if isinstance(node, ast.Attribute):
                    # getattr(config, "PRIMARY_TTS") style
                    if (
                        isinstance(node.value, ast.Name)
                        and node.value.id == "config"
                        and node.attr in self._FORBIDDEN
                    ):
                        violations.append(f"{path.name}:config.{node.attr}")
        # Also scan speaker for string getattr of frozen keys.
        speaker_src = (root / "core" / "speaker.py").read_text(encoding="utf-8")
        for name in ("PRIMARY_TTS", "VOICE_GENDER"):
            if f'"{name}"' in speaker_src or f"'{name}'" in speaker_src:
                violations.append(f"speaker.py:getattr({name})")
        self.assertEqual(violations, [])


class BriefingCaptureTests(unittest.TestCase):
    def test_collection_uses_captured_features_not_later_patch(self) -> None:
        """Simulate briefing capture: later sports disable must not affect flags already captured."""
        features = FeaturesSettings(sports=True, weather=True)
        modules = ModulesSettings(f1=True, football=False)
        # Mid-run patch would update the store, but collection uses captured objects.
        later = FeaturesSettings(sports=False, weather=True)
        self.assertTrue(features.sports)
        self.assertFalse(later.sports)
        score, failures = _compute_confidence_and_failures(
            weather_report="ok",
            sports_report="F1_DATA:{}",
            news_report="",
            email_report="",
            calendar_report="",
            f1_cache_penalty=False,
            features=features,
            modules=modules,
        )
        self.assertNotIn("sports", failures)
        self.assertGreaterEqual(score, 50.0)


if __name__ == "__main__":
    unittest.main()
