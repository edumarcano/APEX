"""Characterization coverage for API health, locking, parsers, and trigger modes."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.settings.store import RuntimeSettingsStore, reset_settings_store_for_tests


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class ApiCharacterizationBase(unittest.TestCase):
    """Shared TestClient setup with an isolated settings store and SQLite file."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_api_char_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        self.db_path = self._dir / "apex_memory.db"
        _write_json(
            self.config_path,
            {
                "features": {
                    "weather": True,
                    "sports": True,
                    "news": False,
                    "email": False,
                    "calendar": False,
                    "market": True,
                },
                "modules": {"football": False, "f1": True},
                "ask_apex": {"enabled": True, "default_profile": "comet"},
                "tts_settings": {
                    "primary_tts": "pyttsx3",
                    "voice_gender": "female",
                },
                "ollama": {"enabled": False},
            },
        )
        reset_settings_store_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store", return_value=self.store
            ),
            mock.patch("core.api.briefing.get_settings_store", return_value=self.store),
            mock.patch(
                "core.api.assistant.get_settings_store", return_value=self.store
            ),
            mock.patch("core.speaker.get_settings_store", return_value=self.store),
            mock.patch("core.api.app.OLLAMA_ENABLED", False),
            mock.patch("core.api.assistant.OLLAMA_ENABLED", False),
            mock.patch("core.database.DB_NAME", str(self.db_path)),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)

        from core import database
        from core.api import app, global_pipeline_state

        database.initialize_db()
        global_pipeline_state.reset()
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=True)


class HealthAndStatusTests(ApiCharacterizationBase):
    def test_health_endpoint_payload(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "online", "system": "APEX"})

    def test_status_offline_when_idle(self) -> None:
        response = self.client.get("/api/v1/status")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "No active pipeline run. System is OFFLINE.",
        )

    def test_status_snapshot_when_active(self) -> None:
        from core.api import global_pipeline_state

        global_pipeline_state.update(2, "COLLECTION")
        self.addCleanup(global_pipeline_state.reset)
        response = self.client.get("/api/v1/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["step"], 2)
        self.assertEqual(payload["label"], "COLLECTION")
        self.assertIn("timestamp", payload)
        self.assertIn("is_speaking", payload)
        self.assertIn("synthesis", payload)

    def test_boot_config_exposes_runtime_mode_flags(self) -> None:
        with mock.patch(
            "core.api.routers.system.is_dev_mode", return_value=True
        ), mock.patch("core.api.routers.system.DEMO_MODE", False):
            response = self.client.get("/api/v1/config")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["dev_mode_active"])
        self.assertFalse(payload["demo_mode_active"])


class ParserAndSanitizerTests(unittest.TestCase):
    def test_parse_digest_payload_accepts_valid(self) -> None:
        from core.api.models import DigestPayload, parse_digest_payload

        parsed = parse_digest_payload(
            {
                "confidence_score": 80.0,
                "failed_connectors": ["news"],
                "insights": ["Check calendar"],
            }
        )
        self.assertIsInstance(parsed, DigestPayload)
        self.assertEqual(parsed.confidence_score, 80.0)
        self.assertEqual(parsed.failed_connectors, ["news"])
        self.assertEqual(parsed.insights, ["Check calendar"])

    def test_parse_digest_payload_malformed_falls_back(self) -> None:
        from core.api.models import parse_digest_payload

        parsed = parse_digest_payload("not-a-dict")
        self.assertEqual(parsed.confidence_score, 0.0)
        self.assertEqual(parsed.failed_connectors, [])
        self.assertEqual(parsed.insights, [])

        parsed_partial = parse_digest_payload({"confidence_score": "bad"})
        self.assertEqual(parsed_partial.confidence_score, 0.0)

    def test_parse_runtime_metadata_legacy_and_malformed(self) -> None:
        from core.api.models import parse_runtime_metadata

        self.assertIsNone(parse_runtime_metadata(None))
        self.assertIsNone(parse_runtime_metadata("legacy-string"))
        self.assertIsNone(
            parse_runtime_metadata({"dev_mode_active": True})  # missing required fields
        )
        valid = parse_runtime_metadata(
            {
                "dev_mode_active": False,
                "demo_mode_active": False,
                "synthesis_strategy": "cloud",
                "tts_strategy": "google",
                "active_tts_engine": "google",
                "system_load_throttled": False,
            }
        )
        self.assertIsNotNone(valid)
        assert valid is not None
        self.assertEqual(valid.synthesis_strategy, "cloud")

    def test_clean_for_tts_strips_markdown_and_non_ascii(self) -> None:
        from core.api.tts import clean_for_tts

        cleaned = clean_for_tts(
            "# Header\n**bold** and *italic*\n- list item\n`code`\n予定 emoji 🙂"
        )
        self.assertNotIn("#", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("`", cleaned)
        self.assertNotIn("予定", cleaned)
        self.assertNotIn("🙂", cleaned)
        self.assertIn("bold", cleaned)
        self.assertIn("italic", cleaned)
        self.assertIn("list item", cleaned)


class TriggerLockAndCleanupTests(ApiCharacterizationBase):
    def test_trigger_returns_409_when_lock_held(self) -> None:
        from core.api.state import _TRIGGER_LOCK

        acquired = _TRIGGER_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        self.addCleanup(
            lambda: _TRIGGER_LOCK.release() if _TRIGGER_LOCK.locked() else None
        )
        response = self.client.post("/api/v1/trigger")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Pipeline run already active.")

    def test_speak_and_cleanup_releases_lock_and_resets_state(self) -> None:
        from core.api.state import _TRIGGER_LOCK, _speak_and_cleanup, global_pipeline_state

        acquired = _TRIGGER_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        global_pipeline_state.update(4, "DELIVERY")

        with mock.patch("core.api.state.speaker.speak") as speak_mock:
            _speak_and_cleanup(
                "Briefing complete.",
                tts_override="pyttsx3",
                voice_gender="female",
                lock=_TRIGGER_LOCK,
            )

        speak_mock.assert_called_once()
        self.assertFalse(_TRIGGER_LOCK.locked())
        self.assertIsNone(global_pipeline_state.get_state())

    def test_speak_and_cleanup_releases_lock_when_speak_raises(self) -> None:
        from core.api.state import _TRIGGER_LOCK, _speak_and_cleanup, global_pipeline_state

        acquired = _TRIGGER_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        global_pipeline_state.update(4, "DELIVERY")

        with mock.patch(
            "core.api.state.speaker.speak", side_effect=RuntimeError("tts boom")
        ):
            with self.assertRaises(RuntimeError):
                _speak_and_cleanup("Briefing", lock=_TRIGGER_LOCK)

        self.assertFalse(_TRIGGER_LOCK.locked())
        self.assertIsNone(global_pipeline_state.get_state())


class TriggerModeCharacterizationTests(ApiCharacterizationBase):
    def test_production_gate_failure_returns_403_and_releases_lock(self) -> None:
        from core.api.state import _TRIGGER_LOCK

        with mock.patch("core.api.briefing.DEMO_MODE", False), mock.patch(
            "core.api.briefing.scanner.should_run", return_value=False
        ):
            response = self.client.post("/api/v1/trigger")

        self.assertEqual(response.status_code, 403)
        self.assertIn("System gate failed", response.json()["detail"])
        self.assertFalse(_TRIGGER_LOCK.locked())

    def test_demo_mode_returns_success_payload_shape(self) -> None:
        from core.api.state import _TRIGGER_LOCK

        def _immediate_thread(*_a: object, target=None, kwargs=None, **_k: object):
            thread = mock.Mock()

            def start() -> None:
                if target is not None:
                    target(**(kwargs or {}))

            thread.start = start
            thread.join = mock.Mock()
            return thread

        with mock.patch("core.api.briefing.DEMO_MODE", True), mock.patch(
            "core.api.briefing._DEMO_STAGE_DELAY_SECONDS", 0
        ), mock.patch(
            "core.api.tts.scanner.is_system_throttled", return_value=False
        ), mock.patch("core.api.briefing.speaker.speak"), mock.patch(
            "core.api.state.speaker.speak"
        ), mock.patch(
            "core.api.briefing.threading.Thread", side_effect=_immediate_thread
        ):
            response = self.client.post("/api/v1/trigger")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertIn("briefing", payload)
        self.assertIn("telemetry", payload)
        self.assertIn("digest", payload)
        self.assertIn("metadata", payload)
        self.assertTrue(payload["metadata"]["demo_mode_active"])
        self.assertFalse(_TRIGGER_LOCK.locked())

    def test_dev_mode_skips_ledger_and_uses_dev_tts(self) -> None:
        from core.api.state import _TRIGGER_LOCK
        from core.synthesis.models import SynthesisResult

        def _immediate_thread(*_a: object, target=None, kwargs=None, **_k: object):
            thread = mock.Mock()

            def start() -> None:
                if target is not None:
                    target(**(kwargs or {}))

            thread.start = start
            thread.join = mock.Mock()
            return thread

        synthesis = SynthesisResult(
            briefing="Dev briefing.",
            insights=["Insight one"],
            provider="raw",
            fallback_reason="configured_raw",
        )

        with mock.patch("core.api.briefing.DEMO_MODE", False), mock.patch(
            "core.api.briefing.is_dev_mode", return_value=True
        ), mock.patch("core.api.briefing.DEV_AI_SYNTHESIS", "raw"), mock.patch(
            "core.api.briefing.DEV_TTS_PLAYBACK", "pyttsx3"
        ), mock.patch(
            "core.api.briefing.scanner.should_run", return_value=True
        ), mock.patch(
            "core.api.briefing.database.log_run"
        ) as log_run, mock.patch(
            "core.api.briefing.database.save_briefing"
        ) as save_briefing, mock.patch(
            "core.api.briefing.weather_client.fetch_weather_data",
            return_value="Current temperature is 70 degrees.",
        ), mock.patch(
            "core.api.briefing.sports_client.fetch_sports_snapshot",
            return_value=("F1 telemetry clear.", True, None),
        ), mock.patch(
            "core.api.briefing.news_client.fetch_news_data", return_value=""
        ), mock.patch(
            "core.api.briefing.database.fetch_unread_reminders", return_value=[]
        ), mock.patch(
            "core.api.briefing.brain.process_telemetry",
            return_value=synthesis.model_dump(),
        ), mock.patch(
            "core.api.briefing.speaker.speak"
        ), mock.patch(
            "core.api.state.speaker.speak"
        ), mock.patch(
            "core.api.briefing.threading.Thread", side_effect=_immediate_thread
        ), mock.patch(
            "core.api.briefing.SynthesisRouter.prepare", return_value=None
        ), mock.patch(
            "core.api.tts.scanner.is_system_throttled", return_value=False
        ):
            response = self.client.post("/api/v1/trigger")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["briefing"], "Dev briefing.")
        self.assertTrue(payload["metadata"]["dev_mode_active"])
        self.assertFalse(payload["metadata"]["demo_mode_active"])
        self.assertEqual(payload["metadata"]["tts_strategy"], "pyttsx3")
        log_run.assert_not_called()
        save_briefing.assert_not_called()
        self.assertFalse(_TRIGGER_LOCK.locked())


class ConcurrentTriggerLockTests(ApiCharacterizationBase):
    def test_second_concurrent_trigger_gets_409(self) -> None:
        from core.api.state import _TRIGGER_LOCK

        gate = threading.Event()
        first_entered = threading.Event()
        results: list[int] = []

        def _blocking_should_run() -> bool:
            first_entered.set()
            gate.wait(timeout=5)
            return False

        def _first_call() -> None:
            with mock.patch("core.api.briefing.DEMO_MODE", False), mock.patch(
                "core.api.briefing.scanner.should_run", side_effect=_blocking_should_run
            ):
                response = self.client.post("/api/v1/trigger")
            results.append(response.status_code)

        worker = threading.Thread(target=_first_call)
        worker.start()
        self.assertTrue(first_entered.wait(timeout=5))
        with mock.patch("core.api.briefing.DEMO_MODE", False):
            second = self.client.post("/api/v1/trigger")
        results.append(second.status_code)
        gate.set()
        worker.join(timeout=5)

        self.assertIn(409, results)
        self.assertIn(403, results)
        self.assertFalse(_TRIGGER_LOCK.locked())


if __name__ == "__main__":
    unittest.main()
