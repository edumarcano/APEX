from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
