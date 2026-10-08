from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import wave
import pyttsx3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "smoke_backend_bundle.py"
_spec = importlib.util.spec_from_file_location("smoke_backend_bundle", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
smoke = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smoke
_spec.loader.exec_module(smoke)
PROBE_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "smoke" / "probe.py"
_probe_spec = importlib.util.spec_from_file_location("backend_bundle_probe", PROBE_PATH)
assert _probe_spec is not None and _probe_spec.loader is not None
probe = importlib.util.module_from_spec(_probe_spec)
sys.modules[_probe_spec.name] = probe
_probe_spec.loader.exec_module(probe)
ESPEAK_HOOK_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "rthook_espeak.py"
_espeak_hook_spec = importlib.util.spec_from_file_location("backend_bundle_espeak_hook", ESPEAK_HOOK_PATH)
assert _espeak_hook_spec is not None and _espeak_hook_spec.loader is not None
espeak_hook = importlib.util.module_from_spec(_espeak_hook_spec)
_espeak_hook_spec.loader.exec_module(espeak_hook)


class BackendBundleSmokeHarnessTests(unittest.TestCase):
    def test_sapi_export_diagnostic_observes_real_worker_without_claiming_empty_wav_success(self) -> None:
        callbacks = []
        private_sentinel = "private voice and exception sentinel"
        engine = Mock()
        engine.getProperty.return_value = [SimpleNamespace(id=private_sentinel, name=private_sentinel)]

        def connect(event: str, callback: object) -> None:
            self.assertEqual(event, "error")
            callbacks.append(callback)

        def save_empty_wav(_text: str, output_path: str) -> None:
            with wave.open(output_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)

        def run_and_report_errors() -> None:
            class FakeSapiError(Exception):
                hresult = -2147467259

            for _ in range(5):
                callbacks[0](engine, exception=FakeSapiError(private_sentinel))

        engine.connect.side_effect = connect
        engine.save_to_file.side_effect = save_empty_wav
        engine.runAndWait.side_effect = run_and_report_errors
        stdout = io.StringIO()
        with patch.object(pyttsx3, "init", return_value=engine), contextlib.redirect_stdout(stdout):
            exit_code = probe.main(["sapi-export-diagnostic", "--voice-gender", "female"])

        self.assertEqual(exit_code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "diagnostic", report)
        self.assertEqual(report["scenario"], "sapi-export-diagnostic")
        self.assertEqual(report["voice_gender"], "female")
        self.assertEqual(report["worker_exit_code"], 0)
        self.assertTrue(report["wav_present"])
        self.assertEqual(report["wav_frames"], 0)
        self.assertEqual(report["wav_rate"], 22050)
        self.assertEqual(report["wav_channels"], 1)
        self.assertEqual(report["wav_sample_width_bytes"], 2)
        self.assertEqual(report["wav_duration_seconds"], 0)
        self.assertEqual(report["error_event_count"], 5)
        self.assertEqual(report["errors"], [
            {"exception_type": "FakeSapiError", "hresult": -2147467259, "sapi_save_to_file_line_offset": None},
            {"exception_type": "FakeSapiError", "hresult": -2147467259, "sapi_save_to_file_line_offset": None},
            {"exception_type": "FakeSapiError", "hresult": -2147467259, "sapi_save_to_file_line_offset": None},
        ])
        self.assertNotIn(private_sentinel, stdout.getvalue())
        self.assertEqual(engine.stop.call_count, 1)

    @unittest.skipUnless(sys.platform == "win32", "SAPI COM driver is Windows-specific")
    def test_sapi_export_diagnostic_finds_actual_driver_line_without_exposing_traceback(self) -> None:
        import comtypes.client
        import pyttsx3.engine
        from pyttsx3.drivers import sapi5

        private_sentinel = "private COM traceback sentinel"

        class FakeComError(Exception):
            hresult = -2147200966

        driver_code = None
        actual_driver_offsets: list[int] = []

        class FakeToken:
            Id = private_sentinel

            @staticmethod
            def GetDescription() -> str:
                return private_sentinel

            @staticmethod
            def GetAttribute(name: str) -> str:
                return {"Language": "409", "Gender": "Female", "Age": "Adult"}[name]

        class FakeVoice:
            def __init__(self) -> None:
                self.Voice = FakeToken()
                self.AudioOutputStream = object()
                self.Rate = 0

            def GetVoices(self) -> list[FakeToken]:
                return [FakeToken()]

            def Speak(self, _text: str) -> None:
                caller = sys._getframe(1)
                if caller.f_code is driver_code:
                    actual_driver_offsets.append(caller.f_lineno - caller.f_code.co_firstlineno)
                raise FakeComError(private_sentinel)

        class FakeFileStream:
            def Open(self, filename: str, _mode: int) -> None:
                with wave.open(filename, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(22050)

            def close(self) -> None:
                return None

        voice = FakeVoice()

        def create_object(name: str) -> object:
            return voice if name == "SAPI.SPVoice" else FakeFileStream()

        with patch.object(comtypes.client, "CreateObject", side_effect=create_object), \
             patch.object(comtypes.client, "GetEvents", return_value=object()):
            engine = pyttsx3.engine.Engine(driverName="sapi5")
            self.assertIsInstance(engine.proxy._driver, sapi5.SAPI5Driver)
            driver_code = engine.proxy._driver.save_to_file.__code__
            stdout = io.StringIO()
            with patch.object(pyttsx3, "init", return_value=engine), contextlib.redirect_stdout(stdout):
                exit_code = probe.main(["sapi-export-diagnostic", "--voice-gender", "female"])

        self.assertEqual(exit_code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report.get("status"), "diagnostic", report)
        self.assertEqual(report["worker_exit_code"], 0)
        self.assertEqual(report["wav_frames"], 0)
        self.assertEqual(report["error_event_count"], 1)
        self.assertEqual(len(report["errors"]), 1)
        diagnostic_error = report["errors"][0]
        self.assertEqual(diagnostic_error["exception_type"], "FakeComError")
        self.assertEqual(diagnostic_error["hresult"], -2147200966)
        self.assertIsInstance(diagnostic_error["sapi_save_to_file_line_offset"], int)
        self.assertEqual(diagnostic_error["sapi_save_to_file_line_offset"], actual_driver_offsets[0])
        self.assertGreater(diagnostic_error["sapi_save_to_file_line_offset"], 0)
        self.assertLessEqual(diagnostic_error["sapi_save_to_file_line_offset"], 256)
        self.assertNotIn(private_sentinel, stdout.getvalue())

    def test_sapi_export_diagnostic_preserves_nonzero_worker_exit(self) -> None:
        engine = Mock()
        engine.getProperty.return_value = []
        stdout = io.StringIO()
        with patch.object(pyttsx3, "init", return_value=engine), contextlib.redirect_stdout(stdout):
            exit_code = probe.main(["sapi-export-diagnostic", "--voice-gender", "male"])

        self.assertEqual(exit_code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "diagnostic")
        self.assertEqual(report["worker_exit_code"], 3)
        self.assertFalse(report["wav_present"])
        self.assertEqual(report["wav_bytes"], 0)
        self.assertEqual(report["error_event_count"], 0)
        self.assertEqual(report["errors"], [])
        self.assertEqual(engine.stop.call_count, 1)

    def test_audio_worker_reports_empty_wav_metadata_without_relaxing_validation(self) -> None:
        from core import speaker

        output = io.BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
        empty_wav = output.getvalue()
        private_sentinel = "private voice sentinel"
        engine = Mock()
        engine.getProperty.return_value = [
            SimpleNamespace(id=private_sentinel, name=private_sentinel),
        ]
        self.assertEqual(speaker._audio_duration_seconds(empty_wav, "audio/wav"), 0.0)
        with (
            patch.object(speaker, "_synthesize_pyttsx3_wav", return_value=empty_wav) as synthesis,
            patch.object(pyttsx3, "init", return_value=engine) as initialize_engine,
        ):
            with self.assertRaisesRegex(ValueError, "speech_audio_chunk_duration_invalid") as raised:
                probe._audio_worker()

        synthesis.assert_called_once()
        initialize_engine.assert_called_once_with()
        engine.getProperty.assert_called_once_with("voices")
        engine.stop.assert_called_once_with()
        diagnostic_text = str(raised.exception).split("; diagnostic=", 1)[1]
        diagnostic = json.loads(diagnostic_text)
        self.assertEqual(diagnostic["wav_bytes"], len(empty_wav))
        self.assertEqual(diagnostic["nframes"], 0)
        self.assertEqual(diagnostic["framerate"], 16000)
        self.assertEqual(diagnostic["channels"], 1)
        self.assertEqual(diagnostic["sample_width_bytes"], 2)
        self.assertEqual(diagnostic["duration_seconds"], 0.0)
        self.assertEqual(diagnostic["sapi_voice_count"], 1)
        self.assertIsNone(diagnostic["sapi_inventory_error_type"])
        self.assertNotIn(private_sentinel, diagnostic_text)
        self.assertEqual(set(diagnostic), {
            "wav_bytes",
            "nframes",
            "framerate",
            "channels",
            "sample_width_bytes",
            "duration_seconds",
            "sapi_voice_count",
            "sapi_inventory_error_type",
        })

    def test_semantic_assets_accepts_baseline_and_lazy_first_search_contracts(self) -> None:
        fts = {"retrieval_mode": "fts_only", "results": [{"id": "fts"}]}
        semantic = {"retrieval_mode": "semantic", "results": [{"id": "semantic"}]}
        with patch("core.retrieval.docs.search_documentation", side_effect=(fts, semantic)), \
                patch("core.retrieval.embedding.FastEmbedAdapter"), \
                patch("core.retrieval.service.RetrievalService") as service_factory, \
                patch("core.retrieval.store.RetrievalStore"), \
                patch("core.runtime_paths.get_runtime_paths", return_value=SimpleNamespace(
                    fastembed_cache_dir=Path("cached-model"), data_root=Path("profile")
                )):
            service = service_factory.return_value
            service.prepare.return_value = SimpleNamespace(mode="semantic", error_category=None)
            service.release_if_idle = None
            service.close.return_value = True

            evidence = probe._semantic_assets()

        self.assertEqual(evidence["initial_retrieval_mode"], "fts_only")
        self.assertEqual(evidence["retrieval_mode"], "semantic")
        self.assertEqual(evidence["idle_release_status"], "baseline_unavailable")
        service.prepare.assert_called_once_with(allow_download=False)

        with patch("core.retrieval.docs.search_documentation", side_effect=(semantic, semantic)), \
                patch("core.retrieval.embedding.FastEmbedAdapter"), \
                patch("core.retrieval.service.RetrievalService") as service_factory, \
                patch("core.retrieval.store.RetrievalStore"), \
                patch("core.runtime_paths.get_runtime_paths", return_value=SimpleNamespace(
                    fastembed_cache_dir=Path("cached-model"), data_root=Path("profile")
                )):
            service = service_factory.return_value
            service.release_if_idle = None
            service.close.return_value = True

            evidence = probe._semantic_assets()

        self.assertEqual(evidence["initial_retrieval_mode"], "semantic")
        self.assertEqual(evidence["retrieval_mode"], "semantic")
        self.assertEqual(evidence["idle_release_status"], "baseline_unavailable")
        service.prepare.assert_not_called()

    def test_semantic_assets_requires_successful_runtime_close(self) -> None:
        semantic = {"retrieval_mode": "semantic", "results": [{"id": "semantic"}]}
        with patch("core.retrieval.docs.search_documentation", return_value=semantic), \
                patch("core.retrieval.embedding.FastEmbedAdapter"), \
                patch("core.retrieval.service.RetrievalService") as service_factory, \
                patch("core.retrieval.store.RetrievalStore"), \
                patch("core.runtime_paths.get_runtime_paths", return_value=SimpleNamespace(
                    fastembed_cache_dir=Path("cached-model"), data_root=Path("profile")
                )):
            service = service_factory.return_value
            service.release_if_idle = None
            service.close.return_value = False

            with self.assertRaisesRegex(RuntimeError, "did not close"):
                probe._semantic_assets()

            service.close.assert_called_once_with(timeout_seconds=30.0)

    def _ascii_temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory(dir=Path.cwd())
        if not Path(temporary.name).as_posix().isascii():
            temporary.cleanup()
            self.skipTest("the checkout path does not provide an ASCII temporary root")
        return temporary

    def test_espeak_hook_preserves_ascii_data_path_without_resolving_alias(self) -> None:
        with self._ascii_temporary_directory() as temporary:
            data_path = Path(temporary) / "espeak-ng-data"
            data_path.mkdir()
            (data_path / "phontab").write_bytes(b"eSpeak data")
            resolver = Mock(side_effect=AssertionError("ASCII path must remain unchanged"))

            result = espeak_hook._resolve_data_path(data_path, short_path_resolver=resolver)

            self.assertEqual(result, str(data_path))
            resolver.assert_not_called()

    def test_espeak_api_hook_preserves_ascii_argument_and_forwards_none(self) -> None:
        received = []

        def original_init(_self: object, library: str, data_path: str | None) -> str:
            received.append((library, data_path))
            return "native initializer result"

        api_module = SimpleNamespace(EspeakAPI=SimpleNamespace(__init__=original_init))
        resolver = Mock(side_effect=AssertionError("ASCII and None paths must not be resolved"))
        espeak_hook._patch_espeak_api(api_module, short_path_resolver=resolver)

        self.assertEqual(resolver.call_count, 0)
        result = api_module.EspeakAPI.__init__(object(), "espeak.dll", None)
        self.assertEqual(result, "native initializer result")
        self.assertEqual(received[-1], ("espeak.dll", None))
        resolver.assert_not_called()

        with self._ascii_temporary_directory() as temporary:
            data_path = Path(temporary) / "espeak-ng-data"
            data_path.mkdir()
            (data_path / "phontab").write_bytes(b"eSpeak data")
            self.assertEqual(
                api_module.EspeakAPI.__init__(object(), "espeak.dll", str(data_path)),
                "native initializer result",
            )
            self.assertEqual(received[-1], ("espeak.dll", str(data_path)))
            resolver.assert_not_called()

    def test_espeak_api_hook_preserves_original_exceptions(self) -> None:
        def original_init(_self: object, _library: str, _data_path: str | None) -> None:
            raise ValueError("native initialization failed")

        api_module = SimpleNamespace(EspeakAPI=SimpleNamespace(__init__=original_init))
        espeak_hook._patch_espeak_api(api_module)

        with self.assertRaisesRegex(ValueError, "native initialization failed"):
            api_module.EspeakAPI.__init__(object(), "espeak.dll", None)

    def test_espeak_api_hook_restores_ascii_alias_after_wrapper_path_resolution(self) -> None:
        try:
            from phonemizer.backend.espeak import api as espeak_api
            from phonemizer.backend.espeak.wrapper import EspeakWrapper
        except ImportError:
            self.skipTest("Kokoro phonemizer extra is not installed in this test environment")

        with self._ascii_temporary_directory() as temporary:
            data_path = Path(temporary) / "eSpeak 測試" / "espeak-ng-data"
            data_path.mkdir(parents=True)
            (data_path / "phontab").write_bytes(b"eSpeak data")
            alias_path = espeak_hook._get_short_path_name(str(data_path))
            if not alias_path or not alias_path.isascii() or not os.path.samefile(alias_path, data_path):
                self.skipTest("Windows did not provide an ASCII short-path alias for this fixture")

            received: list[str | None] = []
            original_data_path = EspeakWrapper._ESPEAK_DATA_PATH
            original_library = EspeakWrapper._ESPEAK_LIBRARY

            def capture_init(_self: object, _library: str, native_path: str | None) -> None:
                received.append(native_path)

            resolver = Mock(wraps=espeak_hook._get_short_path_name)
            try:
                with patch.object(espeak_api.EspeakAPI, "__init__", capture_init):
                    espeak_hook._patch_espeak_api(espeak_api, short_path_resolver=resolver)
                    EspeakWrapper.set_data_path(str(data_path))
                    EspeakWrapper.set_library("espeak-ng.dll")
                    resolver.assert_not_called()
                    EspeakWrapper()

                resolver.assert_called_once_with(str(data_path.resolve()))
                self.assertEqual(len(received), 1)
                self.assertTrue(received[0].isascii())
                self.assertEqual(received[0], alias_path)
            finally:
                EspeakWrapper._ESPEAK_DATA_PATH = original_data_path
                EspeakWrapper._ESPEAK_LIBRARY = original_library

    def test_espeak_hook_requires_a_verified_ascii_alias_for_unicode_path(self) -> None:
        with self._ascii_temporary_directory() as temporary:
            data_path = Path(temporary) / "eSpeak 測試" / "espeak-ng-data"
            data_path.mkdir(parents=True)
            (data_path / "phontab").write_bytes(b"eSpeak data")
            alias_path = espeak_hook._get_short_path_name(str(data_path))

            if not alias_path or not alias_path.isascii() or not os.path.samefile(alias_path, data_path):
                self.skipTest("Windows did not provide an ASCII short-path alias for this fixture")
            self.assertEqual(espeak_hook._resolve_data_path(data_path), alias_path)

    def test_espeak_hook_fails_actionably_when_no_alias_is_available(self) -> None:
        with self._ascii_temporary_directory() as temporary:
            data_path = Path(temporary) / "eSpeak 測試" / "espeak-ng-data"
            data_path.mkdir(parents=True)
            (data_path / "phontab").write_bytes(b"eSpeak data")
            resolver = Mock(return_value=None)

            with self.assertRaisesRegex(RuntimeError, "ASCII-only path"):
                espeak_hook._resolve_data_path(data_path, short_path_resolver=resolver)
            resolver.assert_called_once_with(str(data_path))

    def test_espeak_hook_rejects_an_alias_to_another_complete_directory(self) -> None:
        with self._ascii_temporary_directory() as temporary:
            root = Path(temporary)
            data_path = root / "eSpeak 測試" / "espeak-ng-data"
            other_path = root / "other" / "espeak-ng-data"
            data_path.mkdir(parents=True)
            other_path.mkdir(parents=True)
            (data_path / "phontab").write_bytes(b"data")
            (other_path / "phontab").write_bytes(b"different data")

            with self.assertRaisesRegex(RuntimeError, "ASCII-only path"):
                espeak_hook._resolve_data_path(data_path, short_path_resolver=lambda _path: str(other_path))

    def test_espeak_hook_rejects_a_data_directory_without_phontab(self) -> None:
        with self._ascii_temporary_directory() as temporary:
            data_path = Path(temporary) / "espeak-ng-data"
            data_path.mkdir()
            resolver = Mock()

            with self.assertRaisesRegex(RuntimeError, "missing phontab"):
                espeak_hook._resolve_data_path(data_path, short_path_resolver=resolver)
            resolver.assert_not_called()

    def test_bounded_tail_retains_only_the_most_recent_bytes(self) -> None:
        tail = smoke.BoundedTail(limit=5)
        tail.append(b"abc")
        tail.append(b"defg")
        self.assertEqual(tail.text(), "cdefg")

    def test_sanitized_environment_drops_pythonpath_credentials_and_developer_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            with patch.dict(os.environ, {
                "PATH": r"C:\Developer\Python;C:\Developer\Node",
                "PYTHONPATH": r"C:\checkout",
                "GOOGLE_APPLICATION_CREDENTIALS": r"C:\secret\credentials.json",
                "OPENAI_API_KEY": "not-a-real-key",
                "SYSTEMROOT": r"C:\Windows",
            }, clear=True):
                env = smoke._sanitized_environment(root, root / "profile")
            self.assertEqual(env["PATH"], os.pathsep.join((r"C:\Windows\System32", r"C:\Windows")))
            self.assertNotIn("PYTHONPATH", env)
            self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", env)
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertEqual(env["PYTHON_DOTENV_DISABLED"], "1")
            self.assertEqual(Path(env["APEX_DATA_DIR"]), (root / "profile").resolve())

    def test_occupied_port_is_reported_without_process_interaction(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            try:
                listener.bind(("127.0.0.1", 8000))
            except OSError:
                self.skipTest("127.0.0.1:8000 is already occupied")
            listener.listen(1)
            self.assertFalse(smoke._port_available())
            self.assertEqual(listener.getsockname()[1], 8000)

    def test_report_fails_only_for_failed_checks(self) -> None:
        report = smoke.Report()
        report.add("optional-model-assets", "unverified", "not supplied")
        self.assertFalse(report.failed)
        report.add("runtime-identity", "failed", "identity mismatch")
        self.assertTrue(report.failed)

    def test_shutdown_rejects_a_host_that_exited_without_stopped_frame(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.wait(timeout=10)
        try:
            with self.assertRaisesRegex(RuntimeError, "no stopped envelope was observed"):
                smoke._stop_host(process, smoke.queue.Queue(), smoke.BoundedTail(), "launch-id")
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_envelope_queue_deadline_uses_timeout_error_contract(self) -> None:
        with self.assertRaisesRegex(TimeoutError, "timed out waiting"):
            smoke._next_envelope(smoke.queue.Queue(), smoke.time.monotonic() + 0.01)

    def test_startup_deadline_reports_envelope_stage_process_and_stderr(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        stderr = smoke.BoundedTail()
        stderr.append(b"host diagnostic")
        try:
            with self.assertRaisesRegex(
                RuntimeError,
                r"waiting for ready envelope.*pid=.*exit_code=None.*host diagnostic",
            ):
                smoke._next_startup_envelope(
                    smoke.queue.Queue(),
                    process,
                    stderr,
                    stage="ready",
                    timeout=0.01,
                )
        finally:
            process.kill()
            process.wait(timeout=5)

    def test_report_console_json_is_ascii_safe_and_report_file_keeps_unicode(self) -> None:
        result = {"checks": [{"status": "failed", "detail": "Kokoro 🚀 lookup failed"}]}
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", write_through=True)
        probe_buffer = io.BytesIO()
        probe_stream = io.TextIOWrapper(probe_buffer, encoding="cp1252", errors="strict", write_through=True)
        try:
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
                report_path = Path(temporary) / "report.json"
                smoke._emit_report(result, report_path, stream)
                probe._write_json_line(result, probe_stream)
                console = json.loads(buffer.getvalue().decode("cp1252"))
                probe_console = json.loads(probe_buffer.getvalue().decode("cp1252"))
                report_text = report_path.read_text(encoding="utf-8")
                saved = json.loads(report_text)
            self.assertEqual(console, result)
            self.assertEqual(probe_console, result)
            self.assertEqual(saved, result)
            self.assertIn("Kokoro 🚀 lookup failed", report_text)
        finally:
            stream.detach()
            probe_stream.detach()

    def test_source_probe_verifies_real_fts_documentation_search(self) -> None:
        project = Path(__file__).resolve().parents[1]
        probe = project / "packaging" / "windows" / "smoke" / "probe.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "profile"
            env = smoke._sanitized_environment(root, profile)
            result = subprocess.run(
                [sys.executable, str(probe), "retrieval"],
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-2048:])
            evidence = json.loads(result.stdout)["evidence"]
            self.assertEqual(evidence["retrieval_mode"], "fts_only")
            self.assertGreater(evidence["results"], 0)
            self.assertTrue((profile / "smoke-retrieval-fts.db").exists())

    def test_managed_host_diagnostic_preserves_control_entrypoint_and_restores_wrappers(self) -> None:
        import core.backend_host as backend

        calls: dict[str, object] = {}
        original_main = backend.main
        production_serve = backend._serve
        production_http_json = backend._http_json

        async def fake_serve(*args, **kwargs):
            calls["serve"] = (args, kwargs)
            return 23

        def fake_http_json(url: str, *, timeout: float = 0.5):
            calls["http"] = (url, timeout)
            return {"status": "ready"}

        def backend_main(argv: list[str]) -> int:
            self.assertEqual(argv, ["serve", "--managed"])
            calls["http_result"] = backend._http_json("http://127.0.0.1:8000/api/v1/health/ready")
            return asyncio.run(backend._serve("opaque-start-id", channel="real-control-channel"))

        stderr = io.StringIO()
        with patch.object(backend, "main", backend_main), \
                patch.object(backend, "_serve", fake_serve), \
                patch.object(backend, "_http_json", fake_http_json), \
                patch.object(probe.faulthandler, "dump_traceback_later"), \
                patch.object(probe.faulthandler, "cancel_dump_traceback_later"), \
                contextlib.redirect_stderr(stderr):
            result = probe._managed_host_diagnostic()
            self.assertIs(backend._serve, fake_serve)
            self.assertIs(backend._http_json, fake_http_json)
            self.assertIs(backend.main, backend_main)

        self.assertEqual(result, 23)
        self.assertEqual(calls["serve"], (("opaque-start-id",), {"channel": "real-control-channel"}))
        self.assertEqual(calls["http"], ("http://127.0.0.1:8000/api/v1/health/ready", 0.5))
        self.assertEqual(calls["http_result"], {"status": "ready"})
        self.assertIs(backend._serve, production_serve)
        self.assertIs(backend._http_json, production_http_json)
        self.assertIs(backend.main, original_main)
        self.assertIn('"kind":"serve_enter"', stderr.getvalue())
        self.assertIn('"kind":"http_self_probe"', stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
