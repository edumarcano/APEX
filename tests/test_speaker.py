from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from core import speaker


class SpeakerTextTests(unittest.TestCase):
    def tearDown(self) -> None:
        speaker._CANCEL_EVENT.clear()

    def test_prepare_text_preserves_unicode_and_strips_markdown(self) -> None:
        value = speaker.prepare_text(
            "# Résumé\n**Café** in São Paulo — [details](https://example.com). 東京"
        )
        self.assertEqual(value, "Résumé Café in São Paulo — details. 東京")

    def test_chunk_text_uses_sentence_boundaries_and_hard_cap(self) -> None:
        text = "First sentence. Second sentence is a little longer! Third sentence?"
        chunks = speaker.chunk_text(text, max_chars=32)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(" ".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 32 for chunk in chunks))


class SpeakerAdmissionTests(unittest.TestCase):
    def tearDown(self) -> None:
        speaker._CANCEL_EVENT.clear()

    @patch.object(speaker.psutil, "cpu_percent", return_value=99.0)
    @patch.object(speaker.psutil, "virtual_memory")
    def test_kokoro_rejects_hard_ram_and_sustained_cpu_pressure(
        self,
        virtual_memory: MagicMock,
        _cpu_percent: MagicMock,
    ) -> None:
        virtual_memory.return_value.percent = 95.0
        allowed, reason, throttled = speaker._admit_kokoro()
        self.assertEqual((allowed, reason, throttled), (False, "kokoro_ram_pressure", True))

        virtual_memory.return_value.percent = 60.0
        with patch.object(speaker, "KOKORO_CPU_RECOVERY_SECONDS", 0.0):
            allowed, reason, throttled = speaker._admit_kokoro()
        self.assertEqual((allowed, reason, throttled), (False, "kokoro_cpu_timeout", True))

    @patch.object(speaker.psutil, "cpu_percent")
    @patch.object(speaker.psutil, "virtual_memory")
    def test_kokoro_waits_through_transient_cpu_spike(
        self,
        virtual_memory: MagicMock,
        cpu_percent: MagicMock,
    ) -> None:
        virtual_memory.return_value.percent = 60.0
        cpu_percent.side_effect = [95.0, 70.0, 65.0]
        allowed, reason, throttled = speaker._admit_kokoro()
        self.assertTrue(allowed)
        self.assertIsNone(reason)
        self.assertTrue(throttled)


class SpeakerRoutingTests(unittest.TestCase):
    def tearDown(self) -> None:
        speaker._CANCEL_EVENT.clear()

    def test_kokoro_failure_never_calls_google(self) -> None:
        with (
            patch.object(speaker, "_admit_kokoro", return_value=(True, None, False)),
            patch.object(speaker, "chunk_text", return_value=["hello"]),
            patch.object(speaker, "_speak_streamed", side_effect=RuntimeError("boom")),
            patch.object(speaker, "_speak_pyttsx3_local", return_value=True) as local,
            patch.object(speaker, "fetch_google_audio") as google,
        ):
            resolved = speaker._route_tts_playback("hello", "kokoro", gender="female")
        self.assertEqual(resolved, "pyttsx3")
        local.assert_called_once()
        google.assert_not_called()

    def test_synthesis_timeout_is_bounded(self) -> None:
        def slow() -> str:
            time.sleep(0.1)
            return "late"

        with self.assertRaisesRegex(TimeoutError, "tts_synthesis_timeout"):
            speaker._run_with_timeout(slow, 0.01)

    def test_playback_cancellation_stops_active_mixer(self) -> None:
        fake_music = MagicMock()
        fake_music.get_busy.side_effect = [True, False]
        with (
            patch.object(speaker.pygame.mixer, "get_init", return_value=(44100, -16, 2)),
            patch.object(speaker.pygame.mixer, "music", fake_music),
            patch.object(speaker.pygame.time, "wait", side_effect=lambda _ms: speaker.cancel()),
        ):
            with self.assertRaisesRegex(RuntimeError, "speech_cancelled"):
                speaker._play_audio_bytes(b"audio")
        fake_music.stop.assert_called()

    def test_progressive_stream_synthesizes_next_chunk_during_playback(self) -> None:
        synthesized_second = threading.Event()

        def synthesize(_engine: str, text: str, *, gender: str) -> bytes:
            if text == "second":
                synthesized_second.set()
            return text.encode()

        def play(data: bytes) -> None:
            if data == b"first":
                self.assertTrue(synthesized_second.wait(timeout=1.0))

        with (
            patch.object(speaker, "_synthesize_chunk", side_effect=synthesize),
            patch.object(speaker, "_play_audio_bytes", side_effect=play),
        ):
            self.assertTrue(
                speaker._speak_streamed("kokoro", ["first", "second"], gender="female")
            )


class SpeakerReadinessTests(unittest.TestCase):
    def tearDown(self) -> None:
        speaker._KOKORO_CLIENT = None
        speaker._CANCEL_EVENT.clear()

    def test_kokoro_readiness_rejects_missing_or_corrupt_assets(self) -> None:
        missing = MagicMock()
        missing.is_file.return_value = False
        with patch.object(speaker, "_kokoro_paths", return_value=(missing, missing)):
            self.assertFalse(speaker._ensure_kokoro_ready(probe=False))

        model = MagicMock()
        voices = MagicMock()
        for path in (model, voices):
            path.is_file.return_value = True
            path.stat.return_value.st_size = 10
        with (
            patch.object(speaker, "_kokoro_paths", return_value=(model, voices)),
            patch.dict(
                "sys.modules",
                {"kokoro_onnx": MagicMock(Kokoro=MagicMock(side_effect=ValueError("corrupt")))},
            ),
        ):
            self.assertFalse(speaker._ensure_kokoro_ready(probe=False))

        self.assertFalse(speaker.readiness_snapshot()["kokoro"]["ready"])


if __name__ == "__main__":
    unittest.main()
