"""Production subprocess coverage for the lifecycle-owning host entry point."""

from __future__ import annotations

import asyncio
import os
import queue
import socket
import signal
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
import urllib.request
from types import SimpleNamespace
from pathlib import Path

from core.host.protocol import ControlEnvelope, decode_frame, encode_envelope
from core.backend_host import _HardStopWatchdog, _host_uvicorn_server_type
from core.host.processes import python_child_invocation


class BackendHostSubprocessTests(unittest.TestCase):
    def test_watchdog_exit_is_not_blocked_by_timeout_report(self) -> None:
        report_entered = threading.Event()
        release_report = threading.Event()
        exited = threading.Event()

        def report() -> None:
            report_entered.set()
            release_report.wait()

        watchdog = _HardStopWatchdog(
            budget_seconds=0.05,
            forced_cleanup_seconds=0,
            terminate=lambda _timeout: None,
            exit_process=lambda _code: exited.set(),
            protocol_error=report,
        )
        watchdog.start()
        watchdog.arm()
        try:
            self.assertTrue(exited.wait(1))
            self.assertTrue(report_entered.wait(1))
        finally:
            release_report.set()
            watchdog.cancel()

    def test_owned_uvicorn_server_preserves_host_signal_handlers(self) -> None:
        import uvicorn

        app = SimpleNamespace(state=SimpleNamespace(http_shutdown_timed_out=False))
        server_type = _host_uvicorn_server_type(uvicorn.Server, app)
        server = server_type(uvicorn.Config(lambda _scope, _receive, _send: None))
        sig = getattr(signal, "SIGTERM", signal.SIGINT)
        handler = signal.getsignal(sig)
        with server.capture_signals():
            self.assertIs(signal.getsignal(sig), handler)

    def test_owned_uvicorn_server_marks_canceled_http_grace(self) -> None:
        started = asyncio.Event()

        class ServerBase:
            async def _wait_tasks_to_complete(self) -> None:
                started.set()
                await asyncio.Future()

        app = SimpleNamespace(state=SimpleNamespace(http_shutdown_timed_out=False))
        server = _host_uvicorn_server_type(ServerBase, app)()

        async def cancel_wait() -> None:
            task = asyncio.create_task(server._wait_tasks_to_complete())
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(cancel_wait())
        self.assertTrue(app.state.http_shutdown_timed_out)

    def _start_managed_host(self, data_root: Path):
        environment = {
            key: os.environ[key]
            for key in (
                "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
            )
            if key in os.environ
        }
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        environment["PYTHON_DOTENV_DISABLED"] = "1"
        environment["PYTHONFAULTHANDLER"] = "1"
        environment["APEX_DATA_DIR"] = str(data_root)
        environment["DEV_MODE"] = "true"
        environment["DEMO_MODE"] = "false"
        data_root.mkdir(parents=True, exist_ok=True)
        (data_root / "config.json").write_text(
            '{"ollama":{"enabled":false},"llama_cpp":{"enabled":false},'
            '"cortex_runs":{"shutdown_drain_seconds":1}}',
            encoding="utf-8",
        )
        command, environment = python_child_invocation(
            ["-B", "-m", "core.backend_host", "serve", "--managed"], env=environment
        )
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None
        messages: queue.Queue[bytes | None] = queue.Queue()

        def drain() -> None:
            assert process.stdout is not None
            while True:
                line = process.stdout.readline(64 * 1024 + 1)
                messages.put(line or None)
                if not line:
                    return

        threading.Thread(target=drain, daemon=True).start()
        launch_id = str(uuid.uuid4())
        process.stdin.write(
            encode_envelope(
                ControlEnvelope(
                    version=1,
                    type="start",
                    request_id=launch_id,
                    payload={"launch_id": launch_id},
                )
            )
        )
        process.stdin.flush()
        return process, messages, launch_id

    def _next_message(self, messages: queue.Queue[bytes | None], timeout: float = 60):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.fail("backend host did not emit the expected lifecycle frame")
            raw = messages.get(timeout=remaining)
            self.assertIsNotNone(raw, "backend host closed its control channel")
            envelope = decode_frame(raw)
            if envelope.type == "error":
                self.fail(f"backend host reported safe startup error: {envelope.payload}")
            if envelope.type in {"ready", "stopped"}:
                return envelope

    def _stop_managed_host(self, process, messages: queue.Queue[bytes | None]) -> None:
        assert process.stdin is not None
        request_id = str(uuid.uuid4())
        process.stdin.write(
            encode_envelope(
                ControlEnvelope(
                    version=1,
                    type="shutdown",
                    request_id=request_id,
                    payload={},
                )
            )
        )
        process.stdin.flush()
        deadline = time.monotonic() + 40
        seen: list[str] = []
        while time.monotonic() < deadline:
            try:
                raw = messages.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                self.fail(
                    "backend host did not finish control shutdown; "
                    f"frames={seen}, exit_code={process.poll()}"
                )
            self.assertIsNotNone(raw, "backend host closed control channel before stopped")
            envelope = decode_frame(raw)
            seen.append(envelope.type)
            if envelope.type == "error":
                self.fail(f"backend host reported shutdown error: {envelope.payload}")
            if envelope.type == "stopped":
                self.assertEqual(envelope.request_id, request_id)
                break
        else:
            self.fail("backend host did not report stopped")
        exit_code = process.wait(timeout=10)
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        self.assertEqual(exit_code, 0, stderr)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()

    def test_managed_api_startup_shutdown_and_restart_preserve_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            marker = data_root / "operator-sentinel.txt"
            process, messages, launch_id = self._start_managed_host(data_root)
            try:
                ready = self._next_message(messages)
                identity = ready.payload
                self.assertEqual(ready.request_id, launch_id)
                self.assertEqual(identity["pid"], process.pid)
                self.assertEqual(identity["hosting_mode"], "managed")
                self.assertEqual(identity["launch_id"], launch_id)
                marker.write_text("preserve", encoding="utf-8")

                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open("http://127.0.0.1:8000/api/v1/runtime", timeout=3) as response:
                    import json

                    self.assertEqual(json.loads(response.read(64 * 1024)), identity)

                self._stop_managed_host(process, messages)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)

            restarted, restart_messages, restart_launch_id = self._start_managed_host(data_root)
            try:
                ready = self._next_message(restart_messages)
                self.assertEqual(ready.request_id, restart_launch_id)
                self.assertNotEqual(ready.payload["instance_id"], identity["instance_id"])
                self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
                self._stop_managed_host(restarted, restart_messages)
            finally:
                if restarted.poll() is None:
                    restarted.kill()
                    restarted.wait(timeout=10)

    def test_port_conflict_is_reported_before_profile_or_database_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(("127.0.0.1", 8000))
            occupied.listen(1)
            process = None
            try:
                environment = {
                    key: os.environ[key]
                    for key in (
                        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
                        "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
                    )
                    if key in os.environ
                }
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
                environment["PYTHON_DOTENV_DISABLED"] = "1"
                environment["APEX_DATA_DIR"] = str(data_root)
                environment["DEV_MODE"] = "true"
                environment["DEMO_MODE"] = "false"
                command, environment = python_child_invocation(
                    ["-B", "-m", "core.backend_host", "serve", "--managed"],
                    env=environment,
                )
                process = subprocess.Popen(
                    command,
                    cwd=Path(__file__).resolve().parents[1],
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                assert process.stdin is not None and process.stdout is not None
                messages: queue.Queue[bytes | None] = queue.Queue()
                threading.Thread(
                    target=lambda: self._drain_output(process, messages), daemon=True
                ).start()
                launch_id = str(uuid.uuid4())
                process.stdin.write(
                    encode_envelope(
                        ControlEnvelope(
                            version=1,
                            type="start",
                            request_id=launch_id,
                            payload={"launch_id": launch_id},
                        )
                    )
                )
                process.stdin.flush()
                raw = messages.get(timeout=5)
                self.assertIsNotNone(raw)
                response = decode_frame(raw)
                self.assertEqual(response.type, "error")
                self.assertEqual(response.payload, {"code": "port_in_use"})
                self.assertEqual(response.request_id, launch_id)
                self.assertNotEqual(process.wait(timeout=5), 0)
                self.assertFalse(data_root.exists())
                process.stdin.close()
                process.stdout.close()
            finally:
                if process is not None and process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                occupied.close()

    @staticmethod
    def _drain_output(process, messages: queue.Queue[bytes | None]) -> None:
        assert process.stdout is not None
        while True:
            line = process.stdout.readline(64 * 1024 + 1)
            messages.put(line or None)
            if not line:
                return


if __name__ == "__main__":
    unittest.main()
