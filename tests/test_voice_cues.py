"""Contextual voice cue formatting and briefing status selection."""

from __future__ import annotations

import threading
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

from core.api.briefing import _collection_voice_cue
from core.telemetry.models import TelemetryModuleEntry, TelemetrySnapshot
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
            "Good morning, Chief. I have your telemetry at hand. I’m standing by to brief you.",
        )
        self.assertEqual(
            format_voice_cue(
                "activation_loading",
                now=datetime(2026, 9, 23, 17),
            ),
            "Good evening. I’m gathering your telemetry and standing by for a briefing.",
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
                    "activation_loading",
                    now=datetime(2026, 9, 23, hour),
                )
                self.assertTrue(text.startswith(f"{salutation}."))

    def test_briefing_cue_copy_uses_public_mode_names(self) -> None:
        cases = {
            "start_with_briefing": "Good morning, Chief. I’m gathering your telemetry for your Focused briefing.",
            "briefing_refresh": "I’m refreshing your telemetry for your Focused briefing.",
            "briefing_existing_snapshot": "I’m preparing your Focused briefing now.",
            "briefing_collection_complete": "I’ve gathered what’s available. I’m preparing your Focused briefing.",
            "briefing_partial_sources": "Some sources didn’t respond. I’ll use what’s available while preparing your Focused briefing.",
            "briefing_sources_unavailable": "None of your telemetry sources responded. I’m preparing your Focused briefing with that limitation.",
            "briefing_no_snapshot": "I couldn’t gather usable telemetry, so I can’t prepare your briefing yet.",
            "briefing_generation_failed": "I couldn’t finish your Focused briefing this time. You can try again when you’re ready.",
        }
        for cue, expected in cases.items():
            with self.subTest(cue=cue):
                self.assertEqual(
                    format_voice_cue(
                        cue,  # type: ignore[arg-type]
                        mode="focused",
                        user_designation="Chief",
                        now=datetime(2026, 9, 23, 8),
                    ),
                    expected,
                )

    def test_refresh_outcomes_distinguish_disabled_unavailable_and_stale_retained(self) -> None:
        disabled = TelemetryModuleEntry(
            name="calendar", status="disabled", freshness="none", reason_code="disabled"
        )
        healthy = TelemetryModuleEntry(
            name="weather", status="healthy", freshness="live", reason_code="ok"
        )
        unavailable = TelemetryModuleEntry(
            name="news", status="unavailable", freshness="none", reason_code="timeout"
        )
        stale_retained = TelemetryModuleEntry(
            name="email", status="healthy", freshness="stale", reason_code="timeout"
        )

        self.assertEqual(
            _collection_voice_cue(TelemetrySnapshot(modules={"weather": healthy, "calendar": disabled})),
            "briefing_collection_complete",
        )
        self.assertEqual(
            _collection_voice_cue(TelemetrySnapshot(modules={"weather": healthy, "news": unavailable, "calendar": disabled})),
            "briefing_partial_sources",
        )
        self.assertEqual(
            _collection_voice_cue(TelemetrySnapshot(modules={"news": unavailable, "calendar": disabled})),
            "briefing_sources_unavailable",
        )
        self.assertEqual(
            _collection_voice_cue(TelemetrySnapshot(modules={"email": stale_retained, "calendar": disabled})),
            "briefing_partial_sources",
        )


class BriefingCueFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        from core.api.state import _TRIGGER_LOCK, global_pipeline_state

        self.lock = _TRIGGER_LOCK
        self.state = global_pipeline_state
        self.state.reset()
        self.addCleanup(self.state.reset)

    def test_collection_conflict_does_not_play_no_snapshot_cue(self) -> None:
        from core.api.briefing import trigger_briefing
        from core.telemetry.service import RefreshInProgressError

        settings = SimpleNamespace(get_snapshot=lambda: SimpleNamespace())
        service = SimpleNamespace(
            collect_for_briefing=mock.Mock(side_effect=RefreshInProgressError("busy"))
        )
        with (
            mock.patch("core.api.briefing.DEMO_MODE", False),
            mock.patch("core.api.briefing.is_dev_mode", return_value=True),
            mock.patch("core.api.briefing.get_settings_store", return_value=settings),
            mock.patch("core.api.briefing.get_telemetry_service", return_value=service),
            mock.patch("core.api.briefing._speak_voice_cue_best_effort") as speak,
        ):
            with self.assertRaises(HTTPException) as caught:
                trigger_briefing(mode="focused")

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual([call.args[0] for call in speak.call_args_list], ["start_with_briefing"])
        self.assertFalse(self.lock.locked())

    def test_collection_failure_plays_no_snapshot_after_start_cue(self) -> None:
        from core.api.briefing import trigger_briefing

        settings = SimpleNamespace(get_snapshot=lambda: SimpleNamespace())
        service = SimpleNamespace(
            collect_for_briefing=mock.Mock(side_effect=RuntimeError("collector failed"))
        )
        with (
            mock.patch("core.api.briefing.DEMO_MODE", False),
            mock.patch("core.api.briefing.is_dev_mode", return_value=True),
            mock.patch("core.api.briefing.get_settings_store", return_value=settings),
            mock.patch("core.api.briefing.get_telemetry_service", return_value=service),
            mock.patch("core.api.briefing._speak_voice_cue_best_effort") as speak,
        ):
            with self.assertRaisesRegex(RuntimeError, "collector failed"):
                trigger_briefing(mode="focused")

        self.assertEqual(
            [call.args[0] for call in speak.call_args_list],
            ["start_with_briefing", "briefing_no_snapshot"],
        )
        self.assertFalse(self.lock.locked())

    def test_generation_failure_waits_for_filler_and_releases_pipeline_lock(self) -> None:
        from core.api.briefing import _synthesize_from_snapshot
        from core.api.state import _TRIGGER_LOCK

        filler_started = threading.Event()
        allow_filler_to_finish = threading.Event()
        spoken: list[str] = []

        def fake_speak(text: str) -> None:
            if text.startswith("I’m preparing your Focused briefing now."):
                spoken.append("filler_started")
                filler_started.set()
                if not allow_filler_to_finish.wait(timeout=2):
                    raise AssertionError("filler did not receive its completion signal")
                spoken.append("filler_finished")
            else:
                spoken.append("generation_failure")

        def fail_synthesis(*_args: object, **_kwargs: object) -> None:
            self.assertTrue(filler_started.wait(timeout=2))
            allow_filler_to_finish.set()
            raise RuntimeError("generation failed")

        settings = SimpleNamespace(
            user_designation="Chief",
            voice=SimpleNamespace(mode="automatic", engine="google", gender="female"),
        )
        router = mock.Mock()
        router.prepare_mode.return_value = None
        router.synthesize_mode.side_effect = fail_synthesis
        self.assertTrue(_TRIGGER_LOCK.acquire(blocking=False))
        self.state.begin_run("voice-cue-test")

        with (
            mock.patch("core.api.briefing.get_settings_store", return_value=SimpleNamespace(get_snapshot=lambda: settings)),
            mock.patch("core.api.briefing.is_dev_mode", return_value=False),
            mock.patch("core.api.briefing.SynthesisRouter", return_value=router),
            mock.patch("core.api.briefing.speaker.speak", side_effect=fake_speak),
        ):
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                _synthesize_from_snapshot(
                    snapshot=TelemetrySnapshot(snapshot_id="snap", modules={}),
                    mode="focused",
                    run_id="voice-cue-test",
                    speak_fillers=True,
                    cue_context="existing_snapshot",
                )

        self.assertEqual(spoken, ["filler_started", "filler_finished", "generation_failure"])
        self.assertFalse(_TRIGGER_LOCK.locked())


if __name__ == "__main__":
    unittest.main()
