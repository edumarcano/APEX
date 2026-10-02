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
from pathlib import Path
from unittest.mock import patch

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


class BackendBundleSmokeHarnessTests(unittest.TestCase):
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
