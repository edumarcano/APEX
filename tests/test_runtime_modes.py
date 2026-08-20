"""Characterization coverage for DEV_MODE, DEMO_MODE, and synthesis fallback."""

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

    def test_dev_ai_synthesis_accepts_only_canonical_modes(self) -> None:
        from core import config

        from core import config

        self.assertEqual(config._parse_dev_ai_synthesis(None), "structured")
        self.assertEqual(config._parse_dev_ai_synthesis("flash"), "flash")
        self.assertEqual(config._parse_dev_ai_synthesis("focused"), "focused")
        self.assertEqual(config._parse_dev_ai_synthesis("structured"), "structured")
        self.assertEqual(config._parse_dev_ai_synthesis("cloud"), "structured")

    def test_dev_tts_playback_fallback(self) -> None:
        from core import config

        self.assertEqual(config._parse_dev_tts_playback(None), "pyttsx3")
        self.assertEqual(config._parse_dev_tts_playback("google"), "google")
        self.assertEqual(config._parse_dev_tts_playback("bad"), "pyttsx3")


class DemoHistoryEndpointTests(unittest.TestCase):
    def test_history_uses_mock_ledger_in_demo_mode(self) -> None:
        from fastapi.testclient import TestClient

        from core.api import app

        with mock.patch("core.api.routers.briefings.DEMO_MODE", True), mock.patch(
            "core.api.app.any_local_runtime_enabled", return_value=False
        ), mock.patch("core.api.app.database.initialize_db"):
            client = TestClient(app)
            response = client.get("/api/v1/briefings/history")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 3)
        self.assertIn("briefing", payload[0])
        self.assertIn("digest", payload[0])


if __name__ == "__main__":
    unittest.main()
