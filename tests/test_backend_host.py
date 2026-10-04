"""Production subprocess coverage for the lifecycle-owning host entry point."""

from __future__ import annotations

import asyncio
from collections import deque
import os
import queue
import socket
import signal
import subprocess
import tempfile
import threading
import time
import textwrap
import unittest
import uuid
import urllib.request
from types import SimpleNamespace
from pathlib import Path

from core.host.protocol import ControlEnvelope, decode_frame, encode_envelope
from core.backend_host import (
    _HardStopWatchdog,
    _host_uvicorn_server_type,
    _make_desktop_preferences_sink,
)
from core.host.processes import python_child_invocation
from core.host.profile_lock import ProfileLock


class BackendHostSubprocessTests(unittest.TestCase):
    def test_desktop_preferences_sink_waits_for_ready_and_reads_latest_snapshot(self) -> None:
        sent = []

        class Channel:
            def send(self, envelope) -> None:
                sent.append(envelope)

        state = SimpleNamespace(desktop=SimpleNamespace(
            launch_on_startup=False,
            completion_notifications=False,
        ))
        store = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(desktop=state.desktop))
        readiness = SimpleNamespace(ready=False)
        publish = _make_desktop_preferences_sink(
            Channel(),
            str(uuid.uuid4()),
            ready_predicate=lambda: readiness.ready,
            get_settings_store=lambda: store,
        )

        publish()
        self.assertEqual(sent, [])
        state.desktop = SimpleNamespace(
            launch_on_startup=True,
            completion_notifications=True,
        )
        readiness.ready = True
        publish()
        state.desktop = SimpleNamespace(
            launch_on_startup=False,
            completion_notifications=True,
        )
        publish()

        self.assertEqual([event.request_id for event in sent], ["desktop:1", "desktop:2"])
        self.assertEqual(sent[0].payload["launch_on_startup"], True)
        self.assertEqual(sent[0].payload["completion_notifications"], True)
        self.assertEqual(sent[1].payload["launch_on_startup"], False)

    @unittest.skipUnless(os.name == "nt", "Windows native import ordering")
    def test_windows_numpy_is_ready_before_host_threads_start(self) -> None:
        bootstrap = textwrap.dedent("""
            import sys
            from unittest.mock import patch
            from core import backend_host

            class StopBeforeThreads(Exception):
                pass

            def check_native_import(_watchdog):
                numpy = sys.modules.get("numpy")
                assert numpy is not None, "NumPy was not loaded before host threads"
                assert numpy.arange(3).sum() == 3
                raise StopBeforeThreads

            with patch.object(backend_host._HardStopWatchdog, "start", check_native_import):
                try:
                    backend_host.main(["serve", "--managed"])
                except StopBeforeThreads:
                    pass
                else:
                    raise AssertionError("host did not reach its first thread start")
        """)
        command, environment = python_child_invocation(["-B", "-c", bootstrap])
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))

    def _assert_api_port_available(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            self.skipTest("127.0.0.1:8000 is already owned by another process")
        finally:
            probe.close()

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

    def _spawn_managed_host(
        self,
        data_root: Path,
        *,
        demo_mode: bool = False,
        bootstrap_script: str | None = None,
        drain_seconds: int = 30,
    ):
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
        environment["DEMO_MODE"] = "true" if demo_mode else "false"
        data_root.mkdir(parents=True, exist_ok=True)
        (data_root / "config.json").write_text(
            '{"ollama":{"enabled":false},"llama_cpp":{"enabled":false},'
            f'"cortex_runs":{{"shutdown_drain_seconds":{drain_seconds}}}}}',
            encoding="utf-8",
        )
        python_args = (
            ["-B", "-c", bootstrap_script]
            if bootstrap_script is not None
            else ["-B", "-m", "core.backend_host", "serve", "--managed"]
        )
        command, environment = python_child_invocation(python_args, env=environment)
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
        stderr_tail: deque[str] = deque(maxlen=64)

        def drain() -> None:
            assert process.stdout is not None
            while True:
                line = process.stdout.readline(64 * 1024 + 1)
                messages.put(line or None)
                if not line:
                    return

        threading.Thread(target=drain, daemon=True).start()
        def drain_stderr() -> None:
            assert process.stderr is not None
            while True:
                line = process.stderr.readline(4096)
                if not line:
                    return
                stderr_tail.append(line.decode("utf-8", errors="replace").rstrip())

        threading.Thread(target=drain_stderr, daemon=True).start()
        return process, messages, stderr_tail

    def _start_managed_host(
        self,
        data_root: Path,
        *,
        demo_mode: bool = False,
        bootstrap_script: str | None = None,
        drain_seconds: int = 30,
    ):
        process, messages, stderr_tail = self._spawn_managed_host(
            data_root,
            demo_mode=demo_mode,
            bootstrap_script=bootstrap_script,
            drain_seconds=drain_seconds,
        )
        launch_id = str(uuid.uuid4())
        assert process.stdin is not None
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
        return process, messages, launch_id, stderr_tail

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

    def _stop_managed_host(
        self,
        process,
        messages: queue.Queue[bytes | None],
        stderr_tail: deque[str],
    ) -> None:
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
        deadline = time.monotonic() + 70
        seen: list[str] = []
        while time.monotonic() < deadline:
            try:
                raw = messages.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                self.fail(
                    "backend host did not finish control shutdown; "
                    f"frames={seen}, exit_code={process.poll()}, stderr={list(stderr_tail)}"
                )
            self.assertIsNotNone(raw, "backend host closed control channel before stopped")
            envelope = decode_frame(raw)
            seen.append(envelope.type)
            if envelope.type == "error":
                self.fail(
                    f"backend host reported shutdown error: {envelope.payload}; "
                    f"stderr={list(stderr_tail)}"
                )
            if envelope.type == "stopped":
                self.assertEqual(envelope.request_id, request_id)
                break
        else:
            self.fail("backend host did not report stopped")
        exit_code = process.wait(timeout=10)
        self.assertEqual(exit_code, 0, list(stderr_tail))
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    def test_managed_api_startup_shutdown_and_restart_preserve_profile(self) -> None:
        self._assert_api_port_available()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            marker = data_root / "operator-sentinel.txt"
            process, messages, launch_id, stderr_tail = self._start_managed_host(data_root)
            try:
                ready = self._next_message(messages)
                identity = ready.payload
                self.assertEqual(ready.request_id, launch_id)
                self.assertEqual(identity["pid"], process.pid)
                self.assertEqual(identity["hosting_mode"], "managed")
                self.assertEqual(identity["launch_id"], launch_id)
                self.assertEqual(identity["shutdown_timeout_seconds"], 60)
                marker.write_text("preserve", encoding="utf-8")

                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open("http://127.0.0.1:8000/api/v1/runtime", timeout=3) as response:
                    import json

                    self.assertEqual(json.loads(response.read(64 * 1024)), identity)

                create_request = urllib.request.Request(
                    "http://127.0.0.1:8000/api/v1/cortex/conversations",
                    data=b'{"title":"host persistence sentinel"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with opener.open(create_request, timeout=3) as response:
                    self.assertEqual(response.status, 201)
                    conversation_id = json.loads(response.read(64 * 1024))["id"]

                self._stop_managed_host(process, messages, stderr_tail)
                self.assertTrue((data_root / "apex_memory.db").is_file())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

            restarted, restart_messages, restart_launch_id, restart_stderr = self._start_managed_host(data_root)
            try:
                ready = self._next_message(restart_messages)
                self.assertEqual(ready.request_id, restart_launch_id)
                self.assertNotEqual(ready.payload["instance_id"], identity["instance_id"])
                self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(
                    f"http://127.0.0.1:8000/api/v1/cortex/conversations/{conversation_id}",
                    timeout=3,
                ) as response:
                    persisted = json.loads(response.read(64 * 1024))
                self.assertEqual(persisted["id"], conversation_id)
                self.assertEqual(persisted["title"], "host persistence sentinel")

                self._stop_managed_host(restarted, restart_messages, restart_stderr)
            finally:
                if restarted.poll() is None:
                    restarted.kill()
                    restarted.wait(timeout=10)
                for stream in (restarted.stdin, restarted.stdout, restarted.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

    def test_malformed_start_frame_is_rejected_before_profile_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            process, messages, _stderr_tail = self._spawn_managed_host(data_root)
            try:
                assert process.stdin is not None
                process.stdin.write(
                    b'{"version":2,"type":"start","request_id":"bad",'
                    b'"payload":{"launch_id":"00000000-0000-0000-0000-000000000000"}}\n'
                )
                process.stdin.flush()
                raw = messages.get(timeout=5)
                self.assertIsNotNone(raw)
                response = decode_frame(raw)
                self.assertEqual(response.type, "error")
                self.assertEqual(response.payload, {"code": "protocol_error"})
                self.assertNotEqual(process.wait(timeout=5), 0)
                self.assertFalse((data_root / "apex_memory.db").exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

    def test_parent_eof_after_ready_uses_the_orderly_shutdown_path(self) -> None:
        self._assert_api_port_available()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            process, messages, launch_id, stderr_tail = self._start_managed_host(
                data_root, demo_mode=True
            )
            try:
                ready = self._next_message(messages)
                self.assertEqual(ready.request_id, launch_id)
                assert process.stdin is not None
                process.stdin.close()
                seen: list[object] = []
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    raw = messages.get(timeout=max(0.1, deadline - time.monotonic()))
                    self.assertIsNotNone(raw)
                    envelope = decode_frame(raw)
                    seen.append(envelope)
                    if envelope.type == "error":
                        self.assertEqual(envelope.payload, {"code": "protocol_error"})
                        self.assertEqual(envelope.request_id, launch_id)
                        break
                else:
                    self.fail(f"parent EOF did not complete shutdown: {list(stderr_tail)}")
                self.assertNotEqual(process.wait(timeout=10), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

    def test_hard_deadline_exits_process_and_releases_profile_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            script = textwrap.dedent(
                """
                import threading
                import core.backend_host as host
                from core.tracing import set_tracing_service

                class BlockedTracing:
                    def initialize(self):
                        pass
                    def shutdown(self):
                        threading.Event().wait()

                host.HTTP_GRACE_SECONDS = 0.1
                host.DEPENDENCY_CLEANUP_SECONDS = 0.1
                host.FORCED_CHILD_CLEANUP_SECONDS = 0.1
                set_tracing_service(BlockedTracing())
                raise SystemExit(host.serve(hosting_mode="managed"))
                """
            )
            process, messages, _launch_id, stderr_tail = self._start_managed_host(
                data_root,
                demo_mode=True,
                bootstrap_script=script,
                drain_seconds=1,
            )
            try:
                ready = self._next_message(messages)
                self.assertEqual(ready.type, "ready")
                assert process.stdin is not None
                shutdown_id = str(uuid.uuid4())
                process.stdin.write(
                    encode_envelope(
                        ControlEnvelope(1, "shutdown", shutdown_id, {})
                    )
                )
                process.stdin.flush()
                self.assertNotEqual(process.wait(timeout=8), 0, list(stderr_tail))
                with ProfileLock(data_root):
                    pass
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()

    def test_duplicate_profile_owner_is_rejected_before_database_creation(self) -> None:
        self._assert_api_port_available()
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            process = None
            with ProfileLock(data_root):
                process, messages, _launch_id, _stderr_tail = self._start_managed_host(data_root)
                try:
                    raw = messages.get(timeout=5)
                    self.assertIsNotNone(raw)
                    response = decode_frame(raw)
                    self.assertEqual(response.type, "error")
                    self.assertEqual(response.payload, {"code": "profile_in_use"})
                    self.assertNotEqual(process.wait(timeout=5), 0)
                    self.assertFalse((data_root / "apex_memory.db").exists())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None and not stream.closed:
                            stream.close()

    def test_port_conflict_is_reported_before_profile_or_database_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_root = Path(temp_dir) / "profile"
            occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                occupied.bind(("127.0.0.1", 8000))
            except OSError:
                occupied.close()
                self.skipTest("127.0.0.1:8000 is already owned by another process")
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
                if process.stderr is not None:
                    process.stderr.close()
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
