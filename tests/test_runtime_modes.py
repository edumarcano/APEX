"""Characterization coverage for DEV_MODE, DEMO_MODE, gate, and synthesis fallback."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from core.synthesis.models import SynthesisResult


class ConfigEnvParsingTests(unittest.TestCase):
    def test_parse_env_bool_truthy_falsy_and_invalid(self) -> None:
        from core import config

        self.assertTrue(config._parse_env_bool("true", key="X", default=False))
        self.assertTrue(config._parse_env_bool("1", key="X", default=False))
        self.assertTrue(config._parse_env_bool("YES", key="X", default=False))
        self.assertFalse(config._parse_env_bool("false", key="X", default=True))
        self.assertFalse(config._parse_env_bool("0", key="X", default=True))
        self.assertFalse(config._parse_env_bool(None, key="X", default=False))
        self.assertTrue(config._parse_env_bool("maybe", key="X", default=True))

    def test_is_dev_mode_reads_live_env(self) -> None:
        from core import config

        with mock.patch.dict(os.environ, {"DEV_MODE": "true"}, clear=False):
            self.assertTrue(config.is_dev_mode())
        with mock.patch.dict(os.environ, {"DEV_MODE": "false"}, clear=False):
            self.assertFalse(config.is_dev_mode())

    def test_dev_ai_synthesis_aliases_and_fallback(self) -> None:
        from core import config

        self.assertEqual(config._parse_dev_ai_synthesis(None), "raw")
        self.assertEqual(config._parse_dev_ai_synthesis("cloud"), "cloud")
        self.assertEqual(config._parse_dev_ai_synthesis("llm"), "cloud")
        self.assertEqual(config._parse_dev_ai_synthesis("slm"), "local")
        self.assertEqual(config._parse_dev_ai_synthesis("nope"), "raw")

    def test_dev_tts_playback_fallback(self) -> None:
        from core import config

        self.assertEqual(config._parse_dev_tts_playback(None), "pyttsx3")
        self.assertEqual(config._parse_dev_tts_playback("google"), "google")
        self.assertEqual(config._parse_dev_tts_playback("bad"), "pyttsx3")


class ScannerGateModeTests(unittest.TestCase):
    def test_dev_mode_bypasses_production_gate(self) -> None:
        from core import scanner

        with mock.patch.object(scanner.database, "initialize_db"), mock.patch.object(
            scanner, "is_dev_mode", return_value=True
        ), mock.patch.object(
            scanner, "_enforce_production_gate"
        ) as production_gate:
            self.assertTrue(scanner.should_run())
        production_gate.assert_not_called()

    def test_startup_gate_disabled_bypasses_checks(self) -> None:
        from core import scanner

        with mock.patch.object(scanner.database, "initialize_db"), mock.patch.object(
            scanner, "is_dev_mode", return_value=False
        ), mock.patch.object(
            scanner, "ENABLE_STARTUP_GATE", False
        ), mock.patch.object(
            scanner, "_enforce_production_gate"
        ) as production_gate:
            self.assertTrue(scanner.should_run())
        production_gate.assert_not_called()

    def test_production_gate_enforced_when_enabled(self) -> None:
        from core import scanner

        with mock.patch.object(scanner.database, "initialize_db"), mock.patch.object(
            scanner, "is_dev_mode", return_value=False
        ), mock.patch.object(
            scanner, "ENABLE_STARTUP_GATE", True
        ), mock.patch.object(
            scanner, "_enforce_production_gate", return_value=False
        ) as production_gate:
            self.assertFalse(scanner.should_run())
        production_gate.assert_called_once()

    def test_production_gate_requires_ssid_power_and_cooldown(self) -> None:
        from core import scanner

        with mock.patch.object(scanner, "get_current_ssid", return_value="HomeNet"), mock.patch.dict(
            os.environ, {"HOME_SSID": "HomeNet"}, clear=False
        ), mock.patch.object(
            scanner, "check_power", return_value=True
        ), mock.patch.object(
            scanner.database, "get_last_run", return_value=None
        ):
            self.assertTrue(scanner._enforce_production_gate())

        with mock.patch.object(scanner, "get_current_ssid", return_value="Other"), mock.patch.dict(
            os.environ, {"HOME_SSID": "HomeNet"}, clear=False
        ), mock.patch.object(scanner, "check_power", return_value=True):
            self.assertFalse(scanner._enforce_production_gate())


class BrainFallbackShapeTests(unittest.TestCase):
    def test_process_telemetry_returns_synthesis_dict_shape(self) -> None:
        from core import brain

        expected = SynthesisResult(
            briefing="Fallback briefing.",
            insights=["Deterministic privacy-safe briefing fallback active."],
            provider="raw",
            fallback_reason="configured_raw",
        )
        router = mock.Mock()
        router.synthesize.return_value = expected

        with mock.patch.object(brain, "is_dev_mode", return_value=True), mock.patch.object(
            brain, "DEV_AI_SYNTHESIS", "raw"
        ):
            result = brain.process_telemetry("weather clear", router=router)

        self.assertEqual(result["briefing"], "Fallback briefing.")
        self.assertEqual(result["provider"], "raw")
        self.assertEqual(result["fallback_reason"], "configured_raw")
        self.assertIn("insights", result)
        self.assertIsInstance(result["insights"], list)
        router.synthesize.assert_called_once()
        self.assertEqual(router.synthesize.call_args.args[2], "raw")

    def test_process_telemetry_defaults_to_cloud_outside_dev_mode(self) -> None:
        from core import brain

        expected = SynthesisResult(briefing="Cloud.", provider="gemini", profile="comet")
        router = mock.Mock()
        router.synthesize.return_value = expected

        with mock.patch.object(brain, "is_dev_mode", return_value=False):
            result = brain.process_telemetry("weather clear", router=router)

        self.assertEqual(result["provider"], "gemini")
        self.assertEqual(router.synthesize.call_args.args[2], "cloud")


class DemoHistoryEndpointTests(unittest.TestCase):
    def test_history_uses_mock_ledger_in_demo_mode(self) -> None:
        from fastapi.testclient import TestClient

        from core.api import app

        with mock.patch("core.api.DEMO_MODE", True), mock.patch(
            "core.api.OLLAMA_ENABLED", False
        ), mock.patch("core.api.database.initialize_db"):
            client = TestClient(app)
            response = client.get("/api/v1/briefings/history")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 3)
        self.assertIn("briefing", payload[0])
        self.assertIn("digest", payload[0])


if __name__ == "__main__":
    unittest.main()
