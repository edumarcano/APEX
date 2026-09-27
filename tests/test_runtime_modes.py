"""Coverage for offline development and speech-runtime configuration."""

from __future__ import annotations

import os
import unittest
from unittest import mock


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

    def test_dev_tts_playback_fallback(self) -> None:
        from core import config

        self.assertEqual(config._parse_dev_tts_playback(None), "pyttsx3")
        self.assertEqual(config._parse_dev_tts_playback("google"), "google")
        self.assertEqual(config._parse_dev_tts_playback("bad"), "pyttsx3")


if __name__ == "__main__":
    unittest.main()
