"""Contextual activation and telemetry-refresh voice cues."""

from __future__ import annotations

import unittest
from datetime import datetime

from core.api.tts import clean_for_tts
from core.voice_cues import format_voice_cue


class VoiceCueFormattingTests(unittest.TestCase):
    def test_activation_cues_use_local_daypart_and_optional_normalized_vocative(self) -> None:
        ready = format_voice_cue(
            "activation_ready",
            user_designation="  Chief.  ",
            now=datetime(2026, 9, 23, 8),
        )
        self.assertEqual(
            ready,
            "Good morning, Chief. I’ve collected fresh telemetry for Overview.",
        )
        self.assertEqual(
            format_voice_cue("activation_no_fresh_telemetry"),
            "I couldn’t find an available telemetry source for Overview. Please try again.",
        )
        self.assertEqual(
            format_voice_cue("activation_loading", now=datetime(2026, 9, 23, 17)),
            "Good evening. I’m collecting telemetry for Overview.",
        )

    def test_daypart_boundaries(self) -> None:
        expected = {
            4: "Good evening",
            5: "Good morning",
            11: "Good morning",
            12: "Good afternoon",
            16: "Good afternoon",
            17: "Good evening",
        }
        for hour, salutation in expected.items():
            with self.subTest(hour=hour):
                text = format_voice_cue(
                    "activation_loading", now=datetime(2026, 9, 23, hour)
                )
                self.assertTrue(text.startswith(f"{salutation}."))

    def test_telemetry_failure_cue_and_reminder_speech_cleanup(self) -> None:
        self.assertEqual(
            format_voice_cue("telemetry_refresh_failed"),
            "I couldn’t refresh your Overview telemetry just now. Please try again.",
        )
        self.assertEqual(
            clean_for_tts("**Hello** `world` café Ãƒbroken"),
            "Hello world café",
        )


if __name__ == "__main__":
    unittest.main()
