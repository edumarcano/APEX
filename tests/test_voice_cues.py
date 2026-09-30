"""Contextual activation and telemetry-refresh voice cues."""

from __future__ import annotations

import unittest
from datetime import datetime

from core.speaker import prepare_text
from core.voice_cues import format_voice_cue


class VoiceCueFormattingTests(unittest.TestCase):
    def test_activation_cues_use_local_daypart_and_optional_normalized_vocative(self) -> None:
        ready = format_voice_cue(
            "activation_ready",
            user_designation="  Chief.  ",
            now=datetime(2026, 9, 23, 8),
        )
        self.assertEqual(ready, "Your Overview is ready.")
        self.assertEqual(
            format_voice_cue("activation_no_fresh_telemetry"),
            "I couldn’t find an available telemetry source for your Overview. Please try again.",
        )
        self.assertEqual(
            format_voice_cue("activation_loading", now=datetime(2026, 9, 23, 17)),
            "Good evening. I’m collecting telemetry for your Overview.",
        )
        self.assertEqual(
            format_voice_cue(
                "activation_loading",
                user_designation="  Chief.  ",
                now=datetime(2026, 9, 23, 8),
            ),
            "Good morning, Chief. I’m collecting telemetry for your Overview.",
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

    def test_refresh_failure_cue_and_reminder_speech_cleanup(self) -> None:
        self.assertEqual(
            format_voice_cue("activation_refresh_failed"),
            "I couldn’t refresh your Overview telemetry just now. Please try again.",
        )
        self.assertEqual(
            prepare_text("**Hello** `world` café"),
            "Hello world café",
        )

    def test_briefing_and_highlights_cues(self) -> None:
        self.assertEqual(
            format_voice_cue("briefing_generating", briefing_profile="catch_up"),
            "I’m preparing your Catch Up briefing.",
        )
        self.assertEqual(
            format_voice_cue("briefing_generating"),
            "I’m preparing your briefing.",
        )
        for cue in ("briefing_ready", "briefing_failed", "highlights_ready", "highlights_failed"):
            with self.subTest(cue=cue):
                self.assertTrue(format_voice_cue(cue).strip())


if __name__ == "__main__":
    unittest.main()
