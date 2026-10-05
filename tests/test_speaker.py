from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
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
    def setUp(self) -> None:
        speaker._CANCEL_EVENT.clear()

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
        synthesis_started = threading.Event()
        release_synthesis = threading.Event()
        synthesis_finished = threading.Event()
        call_finished = threading.Event()
        outcome: list[Exception] = []

        def slow() -> str:
            synthesis_started.set()
            if not release_synthesis.wait(timeout=5.0):
                raise TimeoutError("test synthesis release watchdog expired")
            synthesis_finished.set()
            return "late"

        def run_synthesis() -> None:
            try:
                speaker._run_with_timeout(slow, 0.05)
            except Exception as exc:
                outcome.append(exc)
            else:
                outcome.append(AssertionError("speech synthesis call did not time out"))
            finally:
                call_finished.set()

        caller = threading.Thread(target=run_synthesis)
        try:
            caller.start()
            self.assertTrue(synthesis_started.wait(timeout=1.0))
            self.assertTrue(call_finished.wait(timeout=1.0))
            self.assertFalse(synthesis_finished.is_set())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], TimeoutError)
            self.assertRegex(str(outcome[0]), "tts_synthesis_timeout")
        finally:
            release_synthesis.set()
            caller.join(timeout=1.0)
            self.assertFalse(caller.is_alive())
            self.assertTrue(synthesis_finished.wait(timeout=1.0))

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

    def test_kokoro_synthesis_rejects_missing_or_corrupt_assets(self) -> None:
        missing = MagicMock()
        missing.is_file.return_value = False
        with patch.object(speaker, "_kokoro_paths", return_value=(missing, missing)):
            with self.assertRaisesRegex(FileNotFoundError, "Kokoro model asset unavailable"):
                speaker._synthesize_kokoro_chunk("hello", gender="female")

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
            with self.assertRaisesRegex(ValueError, "corrupt"):
                speaker._synthesize_kokoro_chunk("hello", gender="female")

        self.assertFalse(speaker.readiness_snapshot()["kokoro"]["ready"])

    def test_kokoro_asset_paths_use_managed_data_root(self) -> None:
        import tempfile
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temp_dir:
            # Exercise normalization even on hosts whose temporary path has
            # no short-name/long-name alias difference.
            weights_dir = (
                Path(temp_dir) / "uncreated" / ".." / "core" / "weights" / "kokoro"
            )
            expected_dir = Path(temp_dir).resolve() / "core" / "weights" / "kokoro"
            with patch(
                "core.speaker.get_runtime_paths",
                return_value=SimpleNamespace(kokoro_weights_dir=weights_dir),
            ):
                paths = speaker._kokoro_paths()
                self.assertEqual(
                    paths,
                    (
                        expected_dir / "kokoro-v1.0.onnx",
                        expected_dir / "voices-v1.0.bin",
                    ),
                )
                self.assertFalse(expected_dir.exists())


class SpeakerKokoroLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._reset_kokoro()

    def tearDown(self) -> None:
        speaker.close_kokoro(1.0)
        self._reset_kokoro()
        speaker._CANCEL_EVENT.clear()

    @staticmethod
    def _reset_kokoro() -> None:
        with speaker._KOKORO_STATE:
            speaker._KOKORO_CLIENT = None
            speaker._KOKORO_ACTIVE_WORKERS = 0
            speaker._KOKORO_LAST_COMPLETED_AT = None
            speaker._KOKORO_CLOSING = False
        speaker._set_readiness("kokoro", ready=False, reason="not_initialized")

    @staticmethod
    def _kokoro_paths():
        model = MagicMock()
        voices = MagicMock()
        for path in (model, voices):
            path.is_file.return_value = True
            path.stat.return_value.st_size = 10
        return model, voices

    def test_startup_does_not_construct_or_probe_kokoro(self) -> None:
        original_initialized = speaker._INITIALIZED
        speaker._INITIALIZED = False
        settings = MagicMock()
        settings.voice.engine = "kokoro"
        with (
            patch.object(speaker, "get_settings_store") as settings_store,
            patch.object(speaker.pygame.mixer, "get_init", return_value=(44100, -16, 2)),
            patch.object(speaker.pygame.mixer, "init"),
            patch.object(speaker.config, "is_dev_mode", return_value=False),
            patch.dict("sys.modules", {"kokoro_onnx": MagicMock(Kokoro=MagicMock())}),
        ):
            settings_store.return_value.get_snapshot.return_value = settings
            constructor = __import__("sys").modules["kokoro_onnx"].Kokoro
            speaker.initialize()
        constructor.assert_not_called()
        self.assertIsNone(speaker._KOKORO_CLIENT)
        speaker._INITIALIZED = original_initialized

    def test_saved_preparation_loads_on_demand_but_cached_playback_does_not(self) -> None:
        import numpy as np

        fake_client = MagicMock()
        fake_client.create.return_value = (np.zeros(8000, dtype=np.float32), 8000)
        constructor = MagicMock(return_value=fake_client)
        with (
            patch.object(speaker, "_kokoro_paths", return_value=self._kokoro_paths()),
            patch.dict("sys.modules", {"kokoro_onnx": MagicMock(Kokoro=constructor)}),
            patch.object(speaker, "_admit_kokoro_for_event", return_value=(True, None)),
            patch.object(speaker, "_play_cached_audio_bytes"),
        ):
            self.assertTrue(speaker.try_play_cached_audio(
                [{"audio": b"saved", "content_type": "audio/wav", "duration_seconds": 1.0}],
                playback_id="cached",
                cancellation_event=threading.Event(),
            ))
            self.assertIsNone(speaker._KOKORO_CLIENT)
            constructor.assert_not_called()

            chunks, engine = speaker.synthesize_audio(
                "Prepare this speech.",
                tts_override="kokoro",
                voice_gender="female",
                cancellation_event=threading.Event(),
            )

        self.assertEqual(engine, "kokoro")
        self.assertEqual(len(chunks), 1)
        constructor.assert_called_once()
        fake_client.create.assert_called_once()
        self.assertTrue(speaker.readiness_snapshot()["kokoro"]["ready"])

    def test_idle_boundary_releases_and_next_demand_reloads(self) -> None:
        import numpy as np

        first_client = MagicMock()
        second_client = MagicMock()
        second_client.create.return_value = (np.zeros(8, dtype=np.float32), 8000)
        speaker._KOKORO_CLIENT = first_client
        speaker._KOKORO_LAST_COMPLETED_AT = 100.0
        now = 100.0 + speaker.KOKORO_IDLE_SECONDS - 0.001
        with patch.object(speaker.time, "monotonic", side_effect=lambda: now):
            self.assertFalse(speaker.release_kokoro_if_idle())
        now += 0.001
        with patch.object(speaker.time, "monotonic", side_effect=lambda: now):
            self.assertTrue(speaker.release_kokoro_if_idle())
        self.assertEqual(speaker.readiness_snapshot()["kokoro"], {
            "ready": False,
            "reason": "idle_timeout",
        })

        with (
            patch.object(speaker, "_kokoro_paths", return_value=self._kokoro_paths()),
            patch.dict("sys.modules", {"kokoro_onnx": MagicMock(Kokoro=lambda *_: second_client)}),
            patch.object(speaker.time, "monotonic", side_effect=lambda: now + 1),
        ):
            result = speaker._synthesize_kokoro_chunk("hello", gender="female")
        self.assertTrue(result.startswith(b"RIFF"))
        second_client.create.assert_called_once()
        self.assertTrue(speaker.readiness_snapshot()["kokoro"]["ready"])

    def test_timed_out_native_worker_pins_session_until_create_returns(self) -> None:
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        client = MagicMock()

        def slow_create(*_args, **_kwargs):
            started.set()
            if not release.wait(2.0):
                raise TimeoutError("test watchdog expired")
            finished.set()
            return [0.0], 8000

        client.create.side_effect = slow_create
        outcome: list[Exception] = []

        def synthesize() -> None:
            try:
                speaker._synthesize_kokoro_chunk("hello", gender="female")
            except Exception as exc:  # noqa: BLE001
                outcome.append(exc)

        with (
            patch.object(speaker, "_kokoro_paths", return_value=self._kokoro_paths()),
            patch.dict("sys.modules", {"kokoro_onnx": MagicMock(Kokoro=lambda *_: client)}),
            patch.object(speaker, "TTS_SYNTHESIS_TIMEOUT_SECONDS", 0.02),
        ):
            caller = threading.Thread(target=synthesize)
            caller.start()
            self.assertTrue(started.wait(1.0))
            caller.join(1.0)
            self.assertFalse(caller.is_alive())
            self.assertIsInstance(outcome[0], TimeoutError)
            self.assertFalse(finished.is_set())
            self.assertIsNone(speaker._KOKORO_LAST_COMPLETED_AT)
            self.assertFalse(speaker.release_kokoro_if_idle())
            self.assertFalse(speaker.close_kokoro(0.0))
            self.assertIs(speaker._KOKORO_CLIENT, client)
            release.set()
            self.assertTrue(finished.wait(1.0))
            self.assertTrue(speaker.close_kokoro(1.0))

        self.assertIsNone(speaker._KOKORO_CLIENT)
        self.assertEqual(speaker._KOKORO_ACTIVE_WORKERS, 0)
        self.assertIsNotNone(speaker._KOKORO_LAST_COMPLETED_AT)

    def test_failed_native_create_advances_idle_age_and_can_be_released(self) -> None:
        client = MagicMock()
        client.create.side_effect = RuntimeError("native inference failed")
        now = 50.0
        with (
            patch.object(speaker, "_kokoro_paths", return_value=self._kokoro_paths()),
            patch.dict("sys.modules", {"kokoro_onnx": MagicMock(Kokoro=lambda *_: client)}),
            patch.object(speaker.time, "monotonic", side_effect=lambda: now),
        ):
            with self.assertRaisesRegex(RuntimeError, "native inference failed"):
                speaker._synthesize_kokoro_chunk("hello", gender="female")
        self.assertEqual(speaker._KOKORO_LAST_COMPLETED_AT, now)

        with patch.object(
            speaker.time,
            "monotonic",
            side_effect=lambda: now + speaker.KOKORO_IDLE_SECONDS,
        ):
            self.assertTrue(speaker.release_kokoro_if_idle())
        self.assertIsNone(speaker._KOKORO_CLIENT)
        self.assertEqual(speaker.readiness_snapshot()["kokoro"], {
            "ready": False,
            "reason": "idle_timeout",
        })

    def test_pressure_falls_back_to_local_speech_and_cancellation_does_not(self) -> None:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(8000)
            wav_file.writeframes(bytes([0, 0]) * 800)
        local_audio = output.getvalue()
        with (
            patch.object(speaker, "_admit_kokoro_for_event", return_value=(False, "kokoro_ram_pressure")),
            patch.object(speaker, "_synthesize_pyttsx3_wav", return_value=local_audio) as local,
            patch.object(speaker, "fetch_google_audio") as google,
        ):
            chunks, engine = speaker.synthesize_audio(
                "Use the local fallback.",
                tts_override="kokoro",
                voice_gender="female",
                cancellation_event=threading.Event(),
            )
        self.assertEqual(engine, "pyttsx3")
        self.assertEqual(chunks[0]["audio"], local_audio)
        local.assert_called_once()
        google.assert_not_called()

        cancellation = threading.Event()
        cancellation.set()
        with (
            patch.object(speaker, "_admit_kokoro_for_event", return_value=(False, "speech_cancelled")),
            patch.object(speaker, "_synthesize_pyttsx3_wav") as local,
        ):
            with self.assertRaisesRegex(RuntimeError, "speech_cancelled"):
                speaker.synthesize_audio(
                    "Do not speak after cancellation.",
                    tts_override="kokoro",
                    voice_gender="female",
                    cancellation_event=cancellation,
                )
        local.assert_not_called()


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
        self.assertEqual(
            command[1:],
            ["-m", "core.backend_host", "worker", "speech-export", command[-1]],
        )
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
