"""Runtime integration tests for live settings snapshots."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core.api.cortex import query_agent
from core.agent.types import AgentQueryRequest
from core.settings.models import (
    SettingsPatch,
)
from core.settings.store import (
    RuntimeSettingsStore,
    reset_settings_store_for_tests,
)
from core import speaker


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


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

    def test_mid_speech_store_change_does_not_alter_bound_call(self) -> None:
        seen: list[str] = []
        started = threading.Event()
        release = threading.Event()

        def fake_route(text: str, tts_strategy: str, *, gender: str) -> str:
            seen.append(gender)
            started.set()
            release.wait(timeout=2.0)
            return "pyttsx3"

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
                "ask_apex": {"enabled": True, "agent": "cloud"},
            },
        )
        reset_settings_store_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._patcher = mock.patch(
            "core.api.cortex.get_settings_store",
            return_value=self.store,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)

    def test_disabled_assistant_blocks_new_query(self) -> None:
        from fastapi import HTTPException

        self.store.apply_patch(
            SettingsPatch.model_validate({"ask_apex": {"enabled": False}})
        )
        with self.assertRaises(HTTPException) as ctx:
            query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    history=[],
                    agent="cloud",
                )
            )
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
