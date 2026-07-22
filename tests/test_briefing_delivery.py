"""Branch 3 briefing delivery: generate, voice modes, and trigger reuse."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.settings.models import SettingsPatch, VoicePatch
from core.settings.normalize import snapshot_from_merged
from core.settings.store import RuntimeSettingsStore, reset_settings_store_for_tests
from core.synthesis.models import SynthesisResult
from core.telemetry.models import TelemetryModuleEntry, TelemetrySnapshot
from core.telemetry.service import reset_telemetry_service_for_tests


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _module(name: str, text: str = "") -> TelemetryModuleEntry:
    return TelemetryModuleEntry(
        name=name,
        status="healthy",
        freshness="live",
        reason_code="ok",
        observed_at="2026-07-22T12:00:00+00:00",
        display_text=text,
        data={},
    )


def _snapshot(snapshot_id: str = "snap-1") -> TelemetrySnapshot:
    modules = {
        name: _module(name, f"{name} ok")
        for name in ("weather", "news", "email", "calendar", "f1", "football", "reminders")
    }
    return TelemetrySnapshot(
        snapshot_id=snapshot_id,
        collected_at="2026-07-22T12:00:00+00:00",
        modules=modules,
        sync_health_score=100.0,
        connector_health=[],
        failed_connectors=[],
    )


class BriefingDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="apex_briefing_delivery_")
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        self.config_path = root / "config.json"
        self.local_path = root / "config.local.json"
        self.db_path = root / "apex_memory.db"
        _write_json(
            self.config_path,
            {
                "features": {
                    "weather": True,
                    "sports": False,
                    "news": False,
                    "email": False,
                    "calendar": False,
                    "market": False,
                },
                "modules": {"football": False, "f1": False},
                "ask_apex": {"enabled": True, "default_profile": "comet"},
                "briefing": {"default_mode": "comet"},
                "tts_settings": {
                    "primary_tts": "pyttsx3",
                    "voice_gender": "female",
                    "voice_mode": "automatic",
                },
                "ollama": {"enabled": False},
            },
        )
        reset_settings_store_for_tests()
        reset_telemetry_service_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store", return_value=self.store
            ),
            mock.patch("core.api.briefing.get_settings_store", return_value=self.store),
            mock.patch("core.api.voice.get_settings_store", return_value=self.store),
            mock.patch(
                "core.telemetry.service.get_settings_store", return_value=self.store
            ),
            mock.patch("core.speaker.get_settings_store", return_value=self.store),
            mock.patch("core.speaker.try_speak", return_value=True),
            mock.patch("core.speaker.speak"),
            mock.patch("core.api.app.OLLAMA_ENABLED", False),
            mock.patch("core.database.DB_NAME", str(self.db_path)),
        ]
        for patcher in self._patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(reset_settings_store_for_tests)
        self.addCleanup(reset_telemetry_service_for_tests)

        from core import database
        from core.api import app, global_pipeline_state
        from core.api.state import _TRIGGER_LOCK

        database.initialize_db()
        global_pipeline_state.reset()
        if _TRIGGER_LOCK.locked():
            _TRIGGER_LOCK.release()
        self.client = TestClient(app, raise_server_exceptions=True)

    def _seed_snapshot(self, snapshot_id: str = "snap-1") -> TelemetrySnapshot:
        from core.telemetry.service import get_telemetry_service

        snap = _snapshot(snapshot_id)
        get_telemetry_service().store.set(snap)
        return snap

    def test_generate_requires_current_snapshot(self) -> None:
        response = self.client.post(
            "/api/v1/briefings/generate",
            json={"snapshot_id": "missing", "mode": "structured_digest"},
        )
        self.assertEqual(response.status_code, 409)

    def test_generate_from_snapshot_without_connector_calls(self) -> None:
        snap = self._seed_snapshot("snap-gen")
        with mock.patch(
            "core.telemetry.service.TelemetryService.refresh",
            side_effect=AssertionError("connectors must not run"),
        ), mock.patch(
            "core.brain.process_telemetry",
            return_value=SynthesisResult(
                briefing="Generated briefing.",
                insights=["One"],
                provider="raw",
                fallback_reason="configured_raw",
            ).model_dump(),
        ):
            response = self.client.post(
                "/api/v1/briefings/generate",
                json={"snapshot_id": snap.snapshot_id, "mode": "structured_digest"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["briefing"], "Generated briefing.")
        self.assertEqual(payload["metadata"]["briefing_mode"], "structured_digest")
        self.assertEqual(payload["metadata"]["snapshot_id"], "snap-gen")

    def test_generate_stale_snapshot_id_conflicts(self) -> None:
        self._seed_snapshot("current")
        response = self.client.post(
            "/api/v1/briefings/generate",
            json={"snapshot_id": "stale", "mode": "comet"},
        )
        self.assertEqual(response.status_code, 409)

    def test_voice_off_returns_403(self) -> None:
        self.store.apply_patch(SettingsPatch(voice=VoicePatch(mode="off")))
        response = self.client.post(
            "/api/v1/voice/speak",
            json={"text": "APEX online. Ready for operations."},
        )
        self.assertEqual(response.status_code, 403)

    def test_voice_manual_allows_speak(self) -> None:
        self.store.apply_patch(SettingsPatch(voice=VoicePatch(mode="manual")))
        response = self.client.post(
            "/api/v1/voice/speak",
            json={"text": "Manual replay."},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "spoken")

    def test_settings_schema_v3_exposes_briefing_and_voice_mode(self) -> None:
        response = self.client.get("/api/v1/settings")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(payload["settings"]["briefing"]["default_mode"], "comet")
        self.assertEqual(payload["settings"]["voice"]["mode"], "automatic")

    def test_trigger_uses_default_mode_and_skips_speak_when_manual(self) -> None:
        from core.telemetry.service import get_telemetry_service

        self.store.apply_patch(SettingsPatch(voice=VoicePatch(mode="manual")))
        snap = _snapshot("trigger-snap")

        def fake_collect() -> TelemetrySnapshot:
            get_telemetry_service().store.set(snap)
            return snap

        with mock.patch(
            "core.telemetry.service.TelemetryService.collect_for_briefing",
            side_effect=fake_collect,
        ), mock.patch(
            "core.brain.process_telemetry",
            return_value=SynthesisResult(
                briefing="Trigger briefing.",
                insights=["Insight"],
                provider="gemini",
                profile="comet",
            ).model_dump(),
        ) as process, mock.patch("core.api.briefing.speaker.speak") as speak:
            response = self.client.post("/api/v1/trigger")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["briefing"], "Trigger briefing.")
        self.assertEqual(payload["metadata"]["briefing_mode"], "comet")
        self.assertFalse(payload["metadata"]["spoken"])
        process.assert_called_once()
        self.assertEqual(process.call_args.kwargs.get("mode"), "comet")
        speak.assert_not_called()


class SettingsV3NormalizeTests(unittest.TestCase):
    def test_missing_v3_fields_default_safely(self) -> None:
        snap = snapshot_from_merged(
            {
                "features": {},
                "modules": {},
                "ask_apex": {},
                "tts_settings": {"primary_tts": "google", "voice_gender": "male"},
            }
        )
        self.assertEqual(snap.briefing.default_mode, "comet")
        self.assertEqual(snap.voice.mode, "automatic")
        self.assertEqual(snap.voice.engine, "google")
        self.assertEqual(snap.voice.gender, "male")


if __name__ == "__main__":
    unittest.main()
