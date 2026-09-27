from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
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


class SpeakerCachedAudioTests(unittest.TestCase):
    def tearDown(self) -> None:
        speaker._CANCEL_EVENT.clear()
        with speaker._CACHED_PLAYBACK_LOCK:
            speaker._CACHED_PLAYBACK_ID = None
            speaker._CACHED_PLAYBACK_EVENT = None

    @staticmethod
    def _wav_bytes(marker: int) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(bytes([marker, 0]) * 800)
        return output.getvalue()

    def test_synthesize_audio_keeps_ordered_wav_chunks_separate(self) -> None:
        synthesized_text: list[str] = []
        first_text = "First " + ("detail " * 28) + "ends."
        second_text = "Second " + ("detail " * 28) + "ends."

        def synthesize(text, *, gender, cancellation_event):
            synthesized_text.append(text)
            return self._wav_bytes(len(synthesized_text))

        with patch.object(speaker, "_synthesize_pyttsx3_wav", side_effect=synthesize):
            chunks, resolved = speaker.synthesize_audio(
                f"{first_text} {second_text}",
                tts_override="pyttsx3",
                voice_gender="female",
                cancellation_event=threading.Event(),
            )

        self.assertEqual(resolved, "pyttsx3")
        self.assertEqual(synthesized_text, [first_text, second_text])
        self.assertEqual(len(chunks), 2)
        self.assertEqual([chunk["audio"] for chunk in chunks], [
            self._wav_bytes(1),
            self._wav_bytes(2),
        ])
        self.assertEqual([chunk["content_type"] for chunk in chunks], ["audio/wav"] * 2)
        self.assertTrue(all(chunk["duration_seconds"] == 0.1 for chunk in chunks))

    def test_cached_playback_holds_one_shared_lock_for_ordered_chunks(self) -> None:
        played: list[bytes] = []

        def play(
            data: bytes,
            _cancellation_event: threading.Event,
            *,
            deadline: float,
        ) -> None:
            self.assertFalse(speaker._SPEAK_LOCK.acquire(blocking=False))
            played.append(data)

        with patch.object(speaker, "_play_cached_audio_bytes", side_effect=play):
            self.assertTrue(speaker.try_play_cached_audio(
                [
                    {"audio": b"first", "content_type": "audio/wav", "duration_seconds": 0.1},
                    {"audio": b"second", "content_type": "audio/wav", "duration_seconds": 0.1},
                ],
                playback_id="briefing-a",
                cancellation_event=threading.Event(),
            ))

        self.assertEqual(played, [b"first", b"second"])
        self.assertFalse(speaker._SPEAK_LOCK.locked())

    def test_cached_stop_cancels_only_matching_playback_owner(self) -> None:
        started = threading.Event()
        cancellation_event = threading.Event()
        played: list[bytes] = []
        errors: list[str] = []

        def play(
            data: bytes,
            cancellation: threading.Event,
            *,
            deadline: float,
        ) -> None:
            played.append(data)
            started.set()
            cancellation.wait(timeout=2)
            if cancellation.is_set():
                raise RuntimeError("speech_cancelled")

        def run_playback() -> None:
            try:
                speaker.try_play_cached_audio(
                    [
                        {"audio": b"first", "content_type": "audio/mpeg", "duration_seconds": 0.1},
                        {"audio": b"second", "content_type": "audio/mpeg", "duration_seconds": 0.1},
                    ],
                    playback_id="briefing-a",
                    cancellation_event=cancellation_event,
                )
            except RuntimeError as exc:
                errors.append(str(exc))

        with (
            patch.object(speaker, "_play_cached_audio_bytes", side_effect=play),
            patch.object(speaker.pygame.mixer, "get_init", return_value=None),
        ):
            playback = threading.Thread(target=run_playback)
            playback.start()
            self.assertTrue(started.wait(timeout=1))
            self.assertFalse(speaker.cancel_cached_audio("briefing-b"))
            self.assertFalse(cancellation_event.is_set())
            self.assertTrue(speaker.cancel_cached_audio("briefing-a"))
            playback.join(timeout=1)

        self.assertFalse(playback.is_alive())
        self.assertEqual(errors, ["speech_cancelled"])
        self.assertEqual(played, [b"first"])
        self.assertFalse(speaker._CANCEL_EVENT.is_set())

    def test_cached_stop_keeps_shared_lock_until_mixer_stop_finishes(self) -> None:
        owner_playing = threading.Event()
        cancellation_event = threading.Event()
        mixer_stop_started = threading.Event()
        release_mixer_stop = threading.Event()
        contender_finished = threading.Event()
        contender_started = threading.Event()
        owner_result: list[bool] = []
        stop_result: list[bool] = []
        contender_result: list[bool] = []

        def play(
            data: bytes,
            cancellation: threading.Event,
            *,
            deadline: float,
        ) -> None:
            if data == b"owner":
                owner_playing.set()
                cancellation.wait(timeout=2)
                if cancellation.is_set():
                    raise RuntimeError("speech_cancelled")
            else:
                contender_started.set()

        def mixer_stop() -> None:
            mixer_stop_started.set()
            if not release_mixer_stop.wait(timeout=2):
                raise TimeoutError("mixer stop release was not signaled")

        def run_owner() -> None:
            try:
                owner_result.append(speaker.try_play_cached_audio(
                    [{"audio": b"owner", "content_type": "audio/wav", "duration_seconds": 1}],
                    playback_id="owner",
                    cancellation_event=cancellation_event,
                ))
            except RuntimeError:
                owner_result.append(False)

        def cancel_owner() -> None:
            stop_result.append(speaker.cancel_cached_audio("owner"))

        def try_unrelated() -> None:
            contender_result.append(speaker.try_play_cached_audio(
                [{"audio": b"unrelated", "content_type": "audio/wav", "duration_seconds": 1}],
                playback_id="unrelated",
                cancellation_event=threading.Event(),
            ))
            contender_finished.set()

        with (
            patch.object(speaker, "_play_cached_audio_bytes", side_effect=play),
            patch.object(speaker.pygame.mixer, "get_init", return_value=(44100, -16, 2)),
            patch.object(speaker.pygame.mixer, "music") as music,
        ):
            music.stop.side_effect = mixer_stop
            owner_thread = threading.Thread(target=run_owner)
            owner_thread.start()
            self.assertTrue(owner_playing.wait(timeout=1))

            stop_thread = threading.Thread(target=cancel_owner)
            stop_thread.start()
            self.assertTrue(mixer_stop_started.wait(timeout=1))

            contender_thread = threading.Thread(target=try_unrelated)
            contender_thread.start()
            self.assertTrue(contender_finished.wait(timeout=1))
            self.assertEqual(contender_result, [False])
            self.assertFalse(contender_started.is_set())

            release_mixer_stop.set()
            stop_thread.join(timeout=1)
            owner_thread.join(timeout=1)
            contender_thread.join(timeout=1)

        self.assertFalse(stop_thread.is_alive())
        self.assertFalse(owner_thread.is_alive())
        self.assertFalse(contender_thread.is_alive())
        self.assertEqual(stop_result, [True])
        self.assertEqual(owner_result, [False])

    def test_cached_playback_times_out_when_mixer_never_finishes(self) -> None:
        music = MagicMock()
        music.get_busy.return_value = True
        monotonic = iter([0.0, 0.0, 0.0, 6.0])
        with (
            patch.object(speaker.pygame.mixer, "get_init", return_value=(44100, -16, 2)),
            patch.object(speaker.pygame.mixer, "music", music),
            patch.object(speaker.pygame.time, "wait"),
            patch.object(speaker.time, "monotonic", side_effect=lambda: next(monotonic)),
        ):
            with self.assertRaisesRegex(TimeoutError, "cached_audio_playback_timeout"):
                speaker.try_play_cached_audio(
                    [{
                        "audio": b"audio",
                        "content_type": "audio/wav",
                        "duration_seconds": 0.01,
                    }],
                    playback_id="stuck-mixer",
                    cancellation_event=threading.Event(),
                )

        music.stop.assert_called()

    def test_pyttsx3_export_is_bounded_and_cleans_temporary_output(self) -> None:
        real_temporary_directory = tempfile.TemporaryDirectory
        temporary_paths: list[str] = []

        @contextmanager
        def tracking_temporary_directory(*args, **kwargs):
            with real_temporary_directory(*args, **kwargs) as directory:
                temporary_paths.append(directory)
                yield directory

        class FakeProcess:
            def __init__(self, output: bytes) -> None:
                self.output = output
                self.returncode: int | None = None
                self.output_path: str | None = None
                self.input_bytes: bytes | None = None

            def poll(self):
                return self.returncode

            def communicate(self, *, input=None, timeout=None):
                self.input_bytes = input
                self.output_path = command[-1]
                Path(self.output_path).write_bytes(self.output)
                self.returncode = 0
                return b"", b""

            def wait(self, timeout=None):
                self.returncode = self.returncode or 0
                return self.returncode

            def terminate(self):
                self.returncode = 1

            def kill(self):
                self.returncode = 1

        payload_bytes = b"bounded-wav"
        fake_process = FakeProcess(payload_bytes)
        command: list[str] = []

        def create_process(args, **kwargs):
            command[:] = args
            return fake_process

        with (
            patch.object(speaker.tempfile, "TemporaryDirectory", tracking_temporary_directory),
            patch.object(speaker.subprocess, "Popen", side_effect=create_process) as popen,
        ):
            result = speaker._synthesize_pyttsx3_wav(
                "A short saved briefing.",
                gender="female",
                cancellation_event=threading.Event(),
            )

        self.assertEqual(result, payload_bytes)
        self.assertEqual(json.loads(fake_process.input_bytes), {
            "text": "A short saved briefing.",
            "gender": "female",
        })
        self.assertEqual(command[1:3], ["-m", "core.speaker_export"])
        self.assertEqual(popen.call_args.kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(len(temporary_paths), 1)
        self.assertFalse(os.path.exists(temporary_paths[0]))

    def test_pyttsx3_export_rejects_oversized_wav_and_cleans_output(self) -> None:
        real_temporary_directory = tempfile.TemporaryDirectory
        temporary_paths: list[str] = []

        @contextmanager
        def tracking_temporary_directory(*args, **kwargs):
            with real_temporary_directory(*args, **kwargs) as directory:
                temporary_paths.append(directory)
                yield directory

        class FakeProcess:
            returncode: int | None = None

            def poll(self):
                return self.returncode

            def communicate(self, *, input=None, timeout=None):
                Path(command[-1]).write_bytes(b"x" * 9)
                self.returncode = 0
                return b"", b""

            def wait(self, timeout=None):
                return self.returncode or 0

            def terminate(self):
                self.returncode = 1

            def kill(self):
                self.returncode = 1

        command: list[str] = []

        def create_process(args, **kwargs):
            command[:] = args
            return FakeProcess()

        with (
            patch.object(speaker.tempfile, "TemporaryDirectory", tracking_temporary_directory),
            patch.object(speaker.subprocess, "Popen", side_effect=create_process),
            patch.object(speaker, "MAX_CACHED_AUDIO_CHUNK_BYTES", 8),
        ):
            with self.assertRaisesRegex(ValueError, "pyttsx3_audio_size_invalid"):
                speaker._synthesize_pyttsx3_wav(
                    "A short saved briefing.",
                    gender="female",
                    cancellation_event=threading.Event(),
                )

        self.assertEqual(len(temporary_paths), 1)
        self.assertFalse(os.path.exists(temporary_paths[0]))

    def test_pyttsx3_export_timeout_kills_child_and_cleans_output(self) -> None:
        real_temporary_directory = tempfile.TemporaryDirectory
        temporary_paths: list[str] = []

        @contextmanager
        def tracking_temporary_directory(*args, **kwargs):
            with real_temporary_directory(*args, **kwargs) as directory:
                temporary_paths.append(directory)
                yield directory

        class FakeProcess:
            returncode: int | None = None
            killed = False

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 1
                return self.returncode

            def terminate(self):
                self.returncode = 1

            def kill(self):
                self.killed = True
                self.returncode = 1

        process = FakeProcess()
        with (
            patch.object(speaker.tempfile, "TemporaryDirectory", tracking_temporary_directory),
            patch.object(speaker.subprocess, "Popen", return_value=process),
            patch.object(speaker, "TTS_SYNTHESIS_TIMEOUT_SECONDS", 0.0),
        ):
            with self.assertRaisesRegex(TimeoutError, "pyttsx3_synthesis_timeout"):
                speaker._synthesize_pyttsx3_wav(
                    "A short saved briefing.",
                    gender="female",
                    cancellation_event=threading.Event(),
                )

        self.assertTrue(process.killed)
        self.assertEqual(len(temporary_paths), 1)
        self.assertFalse(os.path.exists(temporary_paths[0]))


if __name__ == "__main__":
    unittest.main()
