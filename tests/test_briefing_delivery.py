"""Branch 3 briefing delivery: generate, voice modes, and trigger reuse."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.agent.types import CostEstimate, TokenUsage
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
                "ask_apex": {"enabled": True, "cloud_agent": "panthera"},
                "briefing": {"default_mode": "panthera"},
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
            mock.patch("core.api.app.get_settings_store", return_value=self.store),
            mock.patch("core.api.voice.get_settings_store", return_value=self.store),
            mock.patch(
                "core.telemetry.service.get_settings_store", return_value=self.store
            ),
            mock.patch("core.speaker.get_settings_store", return_value=self.store),
            mock.patch("core.speaker.try_speak", return_value="pyttsx3"),
            mock.patch("core.speaker.speak"),
            mock.patch("core.api.app.any_local_runtime_enabled", return_value=False),
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
            json={"snapshot_id": "stale", "mode": "panthera"},
        )
        self.assertEqual(response.status_code, 409)

    def test_panthera_metadata_reports_resolution_usage_and_cost(self) -> None:
        snap = self._seed_snapshot("panthera-metadata")
        synthesis = SynthesisResult(
            briefing="Panthera briefing.",
            insights=["One"],
            provider="openrouter",
            agent="panthera",
            resolved_model="deepseek/deepseek-v4-flash-0731",
            fallback_steps=["panthera:openrouter_timeout", "felis:local_model_missing"],
            provider_ms=321.5,
            usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            cost_estimate=CostEstimate(
                token_cost=0.000044,
                hosted_tool_cost=0.0,
                total_cost=0.000044,
                pricing_version="test",
                completeness="complete",
            ),
        )
        with mock.patch("core.api.briefing.is_dev_mode", return_value=False), mock.patch(
            "core.brain.process_telemetry", return_value=synthesis.model_dump()
        ):
            response = self.client.post(
                "/api/v1/briefings/generate",
                json={"snapshot_id": snap.snapshot_id, "mode": "panthera"},
            )
        self.assertEqual(response.status_code, 200)
        metadata = response.json()["metadata"]
        self.assertEqual(metadata["synthesis_resolved_model"], "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(metadata["synthesis_fallback_steps"], synthesis.fallback_steps)
        self.assertEqual(metadata["synthesis_usage"]["total_tokens"], 120)
        self.assertEqual(metadata["synthesis_provider_ms"], 321.5)
        self.assertEqual(metadata["synthesis_cost_estimate"]["total_cost"], 0.000044)

    def test_demo_generate_requires_current_snapshot_and_preserves_mode(self) -> None:
        snap = self._seed_snapshot("demo-current")
        with mock.patch("core.api.briefing.DEMO_MODE", True), mock.patch(
            "core.telemetry.service.TelemetryService.refresh",
            side_effect=AssertionError("demo generation must not collect"),
        ):
            stale = self.client.post(
                "/api/v1/briefings/generate",
                json={"snapshot_id": "stale", "mode": "felis"},
            )
            response = self.client.post(
                "/api/v1/briefings/generate",
                json={"snapshot_id": snap.snapshot_id, "mode": "felis"},
            )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(response.status_code, 200)
        metadata = response.json()["metadata"]
        self.assertEqual(metadata["snapshot_id"], "demo-current")
        self.assertEqual(metadata["briefing_mode"], "felis")

    def test_removed_ollama_briefing_modes_are_rejected(self) -> None:
        snap = self._seed_snapshot("briefing-mode-validation")
        response = self.client.post(
            "/api/v1/briefings/generate",
            json={"snapshot_id": snap.snapshot_id, "mode": "mus"},
        )
        self.assertEqual(response.status_code, 422)

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

    def test_voice_delivery_failure_returns_stable_503(self) -> None:
        self.store.apply_patch(SettingsPatch(voice=VoicePatch(mode="manual")))
        with mock.patch(
            "core.api.voice.speaker.try_speak",
            side_effect=RuntimeError("speech_delivery_failed"),
        ):
            response = self.client.post(
                "/api/v1/voice/speak",
                json={"text": "Manual replay."},
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "Speech delivery failed.")

    def test_trigger_uses_default_mode_and_skips_speak_when_manual(self) -> None:
        from core.telemetry.service import get_telemetry_service

        self.store.apply_patch(SettingsPatch(voice=VoicePatch(mode="manual")))
        snap = _snapshot("trigger-snap")

        def fake_collect() -> TelemetrySnapshot:
            get_telemetry_service().store.set(snap)
            return snap

        with mock.patch("core.api.briefing.is_dev_mode", return_value=False), mock.patch(
            "core.telemetry.service.TelemetryService.collect_for_briefing",
            side_effect=fake_collect,
        ), mock.patch(
            "core.brain.process_telemetry",
            return_value=SynthesisResult(
                briefing="Trigger briefing.",
                insights=["Insight"],
                provider="openai",
                agent="panthera",
            ).model_dump(),
        ) as process, mock.patch("core.api.briefing.speaker.speak") as speak:
            response = self.client.post("/api/v1/trigger")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["briefing"], "Trigger briefing.")
        self.assertEqual(payload["metadata"]["briefing_mode"], "panthera")
        self.assertFalse(payload["metadata"]["spoken"])
        process.assert_called_once()
        self.assertEqual(process.call_args.kwargs.get("mode"), "panthera")
        speak.assert_not_called()

    def test_trigger_accepts_an_explicit_session_mode(self) -> None:
        from core.telemetry.service import get_telemetry_service

        self.store.apply_patch(SettingsPatch(voice=VoicePatch(mode="manual")))
        snap = _snapshot("trigger-override-snap")

        def fake_collect() -> TelemetrySnapshot:
            get_telemetry_service().store.set(snap)
            return snap

        with mock.patch(
            "core.telemetry.service.TelemetryService.collect_for_briefing",
            side_effect=fake_collect,
        ), mock.patch(
            "core.brain.process_telemetry",
            return_value=SynthesisResult(
                briefing="Structured trigger briefing.",
                insights=["Insight"],
                provider="raw",
            ).model_dump(),
        ) as process, mock.patch("core.api.briefing.speaker.speak") as speak:
            response = self.client.post(
                "/api/v1/trigger",
                json={"mode": "structured_digest"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["metadata"]["briefing_mode"], "structured_digest")
        self.assertEqual(process.call_args.kwargs.get("mode"), "structured_digest")
        speak.assert_not_called()

    def test_automatic_delivery_is_recorded_in_persisted_metadata(self) -> None:
        snap = self._seed_snapshot("spoken-snap")
        with mock.patch("core.api.briefing.is_dev_mode", return_value=False), mock.patch(
            "core.brain.process_telemetry",
            return_value=SynthesisResult(
                briefing="Automatic briefing.",
                insights=[],
                provider="raw",
                fallback_reason="configured_raw",
            ).model_dump(),
        ), mock.patch("core.api.briefing.database.save_briefing") as save:
            response = self.client.post(
                "/api/v1/briefings/generate",
                json={"snapshot_id": snap.snapshot_id, "mode": "structured_digest"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["metadata"]["spoken"])
        self.assertTrue(save.call_args.args[2]["spoken"])

    def test_get_briefing_targets_returns_fixed_targets(self) -> None:
        response = self.client.get("/api/v1/briefings/targets")
        self.assertEqual(response.status_code, 200)
        targets = response.json()
        self.assertEqual([t["mode"] for t in targets], ["panthera", "felis", "structured_digest"])
        panthera = next(t for t in targets if t["mode"] == "panthera")
        self.assertEqual(panthera["model_id"], "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(panthera["provider"], "openrouter")
        self.assertEqual(panthera["runtime"], "cloud")
        self.assertIsNotNone(panthera["pricing"])
        felis = next(t for t in targets if t["mode"] == "felis")
        self.assertEqual(felis["model_id"], "gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(felis["provider"], "llama_cpp")
        self.assertEqual(felis["runtime"], "local")
        structured = next(t for t in targets if t["mode"] == "structured_digest")
        self.assertEqual(structured["runtime"], "none")
        self.assertEqual(structured["status"], "available")

    def test_get_briefing_targets_felis_available_with_runtime_alias(self) -> None:
        backend_mock = mock.MagicMock(enabled=True)
        backend_mock.get_status_snapshot.return_value = {
            "reachable": True,
            "installed_models": ["gemma-4-e2b-16k"],
        }
        with (
            mock.patch(
                "core.agent.local_runtime.registry.get_local_runtime_backend",
                return_value=backend_mock,
            ),
            mock.patch(
                "core.agent.local_runtime.coordinator.get_system_vitals",
                return_value={"cpu": 0.0, "ram": 0.0},
            ),
        ):
            response = self.client.get("/api/v1/briefings/targets")
            self.assertEqual(response.status_code, 200)
            felis = next(t for t in response.json() if t["mode"] == "felis")
            self.assertEqual(felis["status"], "available")
            self.assertIsNone(felis["reason"])

    def test_get_briefing_targets_felis_not_installed_when_aliases_absent(self) -> None:
        backend_mock = mock.MagicMock(enabled=True)
        backend_mock.get_status_snapshot.return_value = {
            "reachable": True,
            "installed_models": ["unrelated-model-alias"],
        }
        with mock.patch(
            "core.agent.local_runtime.registry.get_local_runtime_backend",
            return_value=backend_mock,
        ):
            response = self.client.get("/api/v1/briefings/targets")
            self.assertEqual(response.status_code, 200)
            felis = next(t for t in response.json() if t["mode"] == "felis")
            self.assertEqual(felis["status"], "model_not_installed")
            self.assertIn("gemma-4-E2B-Q4_K_M.gguf", felis["reason"])

    def test_get_briefing_targets_felis_provider_unreachable(self) -> None:
        backend_mock = mock.MagicMock(enabled=True)
        backend_mock.get_status_snapshot.return_value = {
            "reachable": False,
            "installed_models": [],
        }
        with mock.patch(
            "core.agent.local_runtime.registry.get_local_runtime_backend",
            return_value=backend_mock,
        ):
            response = self.client.get("/api/v1/briefings/targets")
            self.assertEqual(response.status_code, 200)
            felis = next(t for t in response.json() if t["mode"] == "felis")
            self.assertEqual(felis["status"], "provider_unreachable")
            self.assertEqual(felis["reason"], "llama.cpp is unreachable")

    def test_get_briefing_targets_felis_insufficient_ram(self) -> None:
        backend_mock = mock.MagicMock(enabled=True)
        backend_mock.get_status_snapshot.return_value = {
            "reachable": True,
            "installed_models": ["gemma-4-e2b-16k"],
            "loaded_models": [],
        }
        with mock.patch(
            "core.agent.local_runtime.registry.get_local_runtime_backend",
            return_value=backend_mock,
        ), mock.patch(
            "core.agent.local_runtime.coordinator.check_resource_gate",
            return_value=(False, "insufficient_ram"),
        ):
            response = self.client.get("/api/v1/briefings/targets")
            self.assertEqual(response.status_code, 200)
            felis = next(t for t in response.json() if t["mode"] == "felis")
            self.assertEqual(felis["status"], "insufficient_ram")
            self.assertIn("memory pressure", felis["reason"])

    def test_get_briefing_targets_felis_available_when_already_resident(self) -> None:
        backend_mock = mock.MagicMock(enabled=True)
        backend_mock.get_status_snapshot.return_value = {
            "reachable": True,
            "installed_models": ["gemma-4-e2b-16k"],
            "loaded_models": [
                {"name": "gemma-4-e2b-16k", "model": "gemma-4-e2b-16k", "state": "loaded"}
            ],
        }
        with mock.patch(
            "core.agent.local_runtime.registry.get_local_runtime_backend",
            return_value=backend_mock,
        ), mock.patch(
            "core.agent.local_runtime.coordinator.check_resource_gate",
            return_value=(False, "insufficient_ram"),
        ):
            response = self.client.get("/api/v1/briefings/targets")
            self.assertEqual(response.status_code, 200)
            felis = next(t for t in response.json() if t["mode"] == "felis")
            self.assertEqual(felis["status"], "available")
            self.assertIsNone(felis["reason"])


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
        self.assertEqual(snap.briefing.default_mode, "panthera")
        self.assertEqual(snap.voice.mode, "automatic")
        self.assertEqual(snap.voice.engine, "google")
        self.assertEqual(snap.voice.gender, "male")


if __name__ == "__main__":
    unittest.main()
