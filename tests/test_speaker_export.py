from __future__ import annotations

import io
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch


class SpeakerExportTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "SAPI COM driver is Windows-specific")
    def test_owned_memory_stream_allows_actual_sapi_worker_file_export_without_default_device(self) -> None:
        import comtypes.client
        import pyttsx3
        import pyttsx3.engine
        from pyttsx3.drivers import sapi5

        class FakeComError(Exception):
            hresult = -2147200966

        class FakeVoiceToken:
            def __init__(self, voice_id: str, gender: str) -> None:
                self.Id = voice_id
                self.gender = gender

            def GetDescription(self) -> str:
                return self.Id

            def GetAttribute(self, name: str) -> str:
                return {"Language": "409", "Gender": self.gender, "Age": "Adult"}[name]

        class FakeMemoryStream:
            pass

        class FakeFileStream:
            def __init__(self, events: list[object]) -> None:
                self.events = events
                self.path: str | None = None

            def Open(self, filename: str, _mode: int) -> None:
                self.path = filename
                self.events.append("file-open")
                with wave.open(filename, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(22050)

            def write_fixture_audio(self) -> None:
                if self.path is None:
                    raise AssertionError("SAPI spoke before opening its file stream")
                with wave.open(self.path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(22050)
                    wav_file.writeframes(b"\0\0" * 256)

            def close(self) -> None:
                self.events.append("file-close")

        class FakeSpVoice:
            def __init__(self, events: list[object]) -> None:
                self.events = events
                self._voice = FakeVoiceToken("voice-male", "Male")
                self._audio_output_stream: object | None = None
                self.Rate = 0
                self.EventInterests = 0

            @property
            def Voice(self) -> FakeVoiceToken:
                return self._voice

            @Voice.setter
            def Voice(self, token: FakeVoiceToken) -> None:
                self._voice = token

            @property
            def AudioOutputStream(self) -> object:
                if self._audio_output_stream is None:
                    raise FakeComError("no default audio output stream")
                return self._audio_output_stream

            @AudioOutputStream.setter
            def AudioOutputStream(self, stream: object) -> None:
                self._audio_output_stream = stream

            def GetVoices(self) -> list[FakeVoiceToken]:
                return [FakeVoiceToken("voice-male", "Male"), FakeVoiceToken("voice-female", "Female")]

            def Speak(self, _text: str) -> None:
                self.events.append("speak")
                stream = self.AudioOutputStream
                if not isinstance(stream, FakeFileStream):
                    raise AssertionError("speech output was not redirected to the requested file")
                stream.write_fixture_audio()

        for gender in ("male", "female"):
            with self.subTest(gender=gender), tempfile.TemporaryDirectory(prefix="apex-speaker-export-") as temporary:
                events: list[object] = []
                voice = FakeSpVoice(events)
                memory_stream = FakeMemoryStream()

                def create_object(name: str) -> object:
                    if name == "SAPI.SPVoice":
                        return voice
                    if name == "SAPI.SpMemoryStream":
                        return memory_stream
                    if name == "SAPI.SPFileStream":
                        return FakeFileStream(events)
                    raise AssertionError("unexpected SAPI COM class")

                engine: pyttsx3.engine.Engine | None = None

                def initialize_engine() -> pyttsx3.engine.Engine:
                    nonlocal engine
                    engine = pyttsx3.engine.Engine(driverName="sapi5")
                    return engine

                from core.backend_host import main as backend_main

                output_path = Path(temporary) / "speech.wav"
                with (
                    patch.object(comtypes.client, "CreateObject", side_effect=create_object),
                    patch.object(comtypes.client, "GetEvents", return_value=object()),
                    patch.object(pyttsx3, "init", side_effect=initialize_engine),
                    patch.object(
                        sys,
                        "stdin",
                        new=io.StringIO(
                            '{"text":"A worker-owned speech fixture.","gender":"' + gender + '"}'
                        ),
                    ),
                ):
                    exit_code = backend_main(["worker", "speech-export", str(output_path)])

                self.assertEqual(exit_code, 0, events)
                self.assertTrue(output_path.is_file())
                with wave.open(str(output_path), "rb") as wav_file:
                    self.assertGreater(wav_file.getnframes(), 0)
                self.assertIsNotNone(engine)
                self.assertIsInstance(engine.proxy._driver, sapi5.SAPI5Driver)
                self.assertEqual(engine.getProperty("rate"), 175)
                self.assertIs(voice.AudioOutputStream, memory_stream)
                self.assertEqual(voice.Voice.gender, gender.title())
                self.assertIn("speak", events)
                self.assertIn("file-close", events)
                self.assertLess(events.index("file-open"), events.index("speak"))
                self.assertLess(events.index("speak"), events.index("file-close"))


if __name__ == "__main__":
    unittest.main()
