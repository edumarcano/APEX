"""Focused tests for process host identity, locking, and private control."""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest import mock

from core.host.identity import create_host_context, create_host_identity
from core.host.profile_lock import ProfileAlreadyRunningError, ProfileLock
from core.host.processes import OwnedProcessRegistry, redirect_stdout_to_stderr
from core.host.protocol import (
    MAX_FRAME_BYTES,
    ControlChannel,
    ControlProtocolError,
    decode_frame,
    encode_envelope,
    validate_envelope,
)
from core.runtime_paths import RuntimePaths


def _lock_process(connection: object, root: str, crash_after_lock: bool = False) -> None:
    """Spawn target: acquire a real profile lock and synchronize with parent."""
    try:
        lease = ProfileLock(root).acquire()
        inheritable = os.get_inheritable(lease._file.fileno())  # noqa: SLF001
        connection.send(("acquired", inheritable))
        if crash_after_lock:
            os._exit(0)
        connection.recv()
        lease.release()
        connection.send(("released", None))
    except ProfileAlreadyRunningError:
        connection.send(("busy", None))
    finally:
        connection.close()


class HostProfileLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "profile"
        self.context = multiprocessing.get_context("spawn")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _start_holder(self, root: Path, *, crash_after_lock: bool = False):
        parent, child = self.context.Pipe()
        process = self.context.Process(target=_lock_process, args=(child, str(root), crash_after_lock))
        process.start()
        child.close()
        self.assertTrue(parent.poll(10), "lock child did not report acquisition")
        status = parent.recv()
        return process, parent, status

    def test_profile_alias_is_exclusive_and_distinct_root_is_available(self) -> None:
        alias = self.root.parent / "profile" / "." / "child" / ".."
        process, channel, status = self._start_holder(alias)
        try:
            self.assertEqual(status, ("acquired", False))
            with self.assertRaises(ProfileAlreadyRunningError):
                ProfileLock(self.root).acquire()
            with ProfileLock(self.root.parent / "other-profile") as other:
                self.assertTrue(other.acquired)
        finally:
            channel.send("release")
            self.assertTrue(channel.poll(5))
            self.assertEqual(channel.recv()[0], "released")
            process.join(5)
            channel.close()
        self.assertEqual(process.exitcode, 0)

    def test_stale_marker_is_not_ownership_and_marker_is_retained(self) -> None:
        self.root.mkdir(parents=True)
        marker = self.root / ".apex-host.lock"
        marker.write_bytes(b"\0")
        with ProfileLock(self.root) as lease:
            self.assertTrue(lease.acquired)
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_bytes(), b"\0")

    def test_os_releases_lock_after_process_crash(self) -> None:
        process, channel, status = self._start_holder(self.root, crash_after_lock=True)
        channel.close()
        process.join(5)
        self.assertEqual(status, ("acquired", False))
        self.assertEqual(process.exitcode, 0)
        with ProfileLock(self.root) as lease:
            self.assertTrue(lease.acquired)


class HostIdentityTests(unittest.TestCase):
    def _paths(self, resource: Path, data: Path) -> RuntimePaths:
        return RuntimePaths(resource_root=resource, data_root=data)

    @mock.patch("core.host.identity.importlib.metadata.version", return_value="2.0.0")
    def test_identity_is_typed_and_does_not_disclose_profile_path(self, _version: mock.Mock) -> None:
        resource = Path(tempfile.gettempdir()) / "resources"
        data = Path(tempfile.gettempdir()) / "private-profile-name"
        launch_id = str(uuid.uuid4())
        identity = create_host_identity(
            self._paths(resource, data),
            hosting_mode="managed",
            launch_id=launch_id,
            shutdown_timeout_seconds=60,
            frozen=False,
        )
        self.assertEqual(identity.app_id, "apex")
        self.assertEqual(identity.app_version, "2.0.0")
        self.assertEqual(identity.build_id, "source:2.0.0")
        self.assertEqual(identity.hosting_mode, "managed")
        self.assertEqual(identity.launch_id, launch_id)
        self.assertEqual(len(identity.data_root_fingerprint), 64)
        self.assertNotIn(str(data), repr(identity))
        self.assertNotIn(str(data), json.dumps(identity.as_dict()))
        with self.assertRaises(ValueError):
            create_host_identity(self._paths(resource, data), hosting_mode="managed", frozen=False)

    @mock.patch("core.host.identity.importlib.metadata.version", return_value="2.0.0")
    def test_frozen_manifest_is_required_and_context_releases_failed_identity(self, _version: mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = self._paths(root / "resources", root / "profile")
            paths.resource_root.mkdir()
            with self.assertRaisesRegex(RuntimeError, "manifest"):
                create_host_identity(paths, frozen=True)
            with self.assertRaisesRegex(RuntimeError, "manifest"):
                create_host_context(paths, frozen=True)
            lease = ProfileLock(paths.data_root).acquire()
            lease.release()
            (paths.resource_root / "build-info.json").write_text(
                json.dumps({"build_id": "frozen:abc123"}), encoding="utf-8"
            )
            self.assertEqual(create_host_identity(paths, frozen=True).build_id, "frozen:abc123")


class HostProtocolTests(unittest.TestCase):
    def _envelope(self, **updates: object) -> dict[str, object]:
        value: dict[str, object] = {
            "version": 1,
            "type": "start",
            "request_id": "request-1",
            "payload": {"launch_id": str(uuid.uuid4())},
        }
        value.update(updates)
        return value

    def test_rejects_bad_shape_version_correlation_and_oversized_frames(self) -> None:
        for value in (
            {**self._envelope(), "extra": True},
            self._envelope(version=True),
            self._envelope(version=2),
            self._envelope(version=1.0),
            self._envelope(type="device_request"),
            self._envelope(payload=[]),
            self._envelope(request_id="bad\nrequest"),
        ):
            with self.subTest(value=value), self.assertRaises(ControlProtocolError):
                validate_envelope(value)
        with self.assertRaises(ControlProtocolError):
            validate_envelope(self._envelope(), expected_request_id="different")
        with self.assertRaises(ControlProtocolError):
            decode_frame(b"x" * (MAX_FRAME_BYTES + 1))
        with self.assertRaises(ControlProtocolError):
            encode_envelope(self._envelope(payload={"long": "x" * MAX_FRAME_BYTES}))

    def test_ready_requires_complete_privacy_preserving_identity_shape(self) -> None:
        request_id = str(uuid.uuid4())
        identity = {
            "app_id": "apex",
            "app_version": "2.0.0",
            "build_id": "source:2.0.0",
            "instance_id": str(uuid.uuid4()),
            "pid": os.getpid(),
            "hosting_mode": "managed",
            "launch_id": str(uuid.uuid4()),
            "data_root_fingerprint": "a" * 64,
            "shutdown_timeout_seconds": 60,
        }
        envelope = {"version": 1, "type": "ready", "request_id": request_id, "payload": identity}
        self.assertEqual(decode_frame(encode_envelope(envelope)).payload, identity)
        with self.assertRaises(ControlProtocolError):
            decode_frame(encode_envelope({**envelope, "payload": {**identity, "data_root": "secret"}}))

    def test_start_completion_and_error_payloads_are_allowlisted(self) -> None:
        launch_id = str(uuid.uuid4())
        start = self._envelope(payload={"launch_id": launch_id})
        self.assertEqual(decode_frame(encode_envelope(start)).payload["launch_id"], launch_id)
        completion = {
            "version": 1,
            "type": "completion",
            "request_id": "request-2",
            "payload": {
                "instance_id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "status": "completed",
            },
        }
        validate_envelope(completion)
        desktop_preferences = {
            "version": 1,
            "type": "desktop_preferences",
            "request_id": "desktop:1",
            "payload": {
                "instance_id": str(uuid.uuid4()),
                "launch_on_startup": False,
                "completion_notifications": True,
            },
        }
        self.assertEqual(
            decode_frame(encode_envelope(desktop_preferences)).payload,
            desktop_preferences["payload"],
        )
        for invalid in (
            {**desktop_preferences["payload"], "launch_on_startup": 1},
            {**desktop_preferences["payload"], "extra": False},
        ):
            with self.subTest(payload=invalid), self.assertRaises(ControlProtocolError):
                validate_envelope({**desktop_preferences, "payload": invalid})
        for request_id in ("desktop:0", "desktop:01", "desktop:-1", "desktop:next"):
            with self.subTest(request_id=request_id), self.assertRaises(ControlProtocolError):
                validate_envelope({**desktop_preferences, "request_id": request_id})
        non_string_instance = {
            **desktop_preferences["payload"],
            "instance_id": uuid.UUID(desktop_preferences["payload"]["instance_id"]),
        }
        with self.assertRaises(ControlProtocolError):
            validate_envelope({**desktop_preferences, "payload": non_string_instance})
        with self.assertRaises(ControlProtocolError):
            validate_envelope({**completion, "payload": {**completion["payload"], "detail": "private"}})
        with self.assertRaises(ControlProtocolError):
            validate_envelope(
                {"version": 1, "type": "error", "request_id": "request-3", "payload": {"message": "secret"}}
            )

    def test_channel_reports_broken_writer_without_blocking_sender(self) -> None:
        class BrokenWriter(io.BytesIO):
            def write(self, _data: bytes) -> int:
                raise BrokenPipeError

        release_reader = threading.Event()

        class HeldReader:
            def readline(self, _size: int = -1) -> bytes:
                release_reader.wait(2)
                return b""

        failure = threading.Event()
        reasons: list[str] = []

        def on_failure(reason: str) -> None:
            reasons.append(reason)
            failure.set()

        writer = BrokenWriter()
        channel = ControlChannel(
            HeldReader(),
            writer,
            on_failure=on_failure,
        )
        try:
            channel.send(self._envelope())
            self.assertTrue(failure.wait(2))
            self.assertIn("writer_failed", reasons)
        finally:
            release_reader.set()
            channel.close()

    def test_channel_reads_a_valid_incoming_frame(self) -> None:
        channel = ControlChannel(
            io.BytesIO(encode_envelope(self._envelope())),
            io.BytesIO(),
        )
        try:
            self.assertEqual(channel.receive(timeout=2).type, "start")
        finally:
            channel.close()

    def test_deeply_nested_json_reports_protocol_failure(self) -> None:
        failed = threading.Event()
        reasons: list[str] = []

        def on_failure(reason: str) -> None:
            reasons.append(reason)
            failed.set()

        nested = b"[" * 12000 + b"0" + b"]" * 12000
        frame = (
            b'{"version":1,"type":"start","request_id":"nested",'
            b'"payload":{"launch_id":' + nested + b"}}\n"
        )
        self.assertLess(len(frame), MAX_FRAME_BYTES)
        channel = ControlChannel(io.BytesIO(frame), io.BytesIO(), on_failure=on_failure)
        try:
            self.assertTrue(failed.wait(2))
            self.assertEqual(reasons, ["reader_failed"])
        finally:
            channel.close()

    def test_incoming_queue_overflow_is_reported(self) -> None:
        frame = encode_envelope(self._envelope())
        overflow = threading.Event()

        def on_failure(reason: str) -> None:
            if reason == "incoming_queue_full":
                overflow.set()

        channel = ControlChannel(
            io.BytesIO(frame * 3), io.BytesIO(), on_failure=on_failure, queue_size=1
        )
        try:
            self.assertTrue(overflow.wait(2), "incoming queue overflow was not reported")
        finally:
            channel.close()

    def test_writer_handles_partial_writes_and_flushes_before_close(self) -> None:
        class PartialWriter(io.BytesIO):
            def write(self, data: bytes) -> int:
                return super().write(data[:3])

        writer = PartialWriter()
        channel = ControlChannel(io.BytesIO(), writer)
        envelope = self._envelope()
        frame = encode_envelope(envelope)
        try:
            channel.send(envelope)
            self.assertTrue(channel.flush(timeout=2))
            self.assertEqual(writer.getvalue(), frame)
        finally:
            channel.close()

    def test_outgoing_queue_overflow_is_bounded_and_reported(self) -> None:
        entered = threading.Event()
        release_writer = threading.Event()
        release_reader = threading.Event()
        failed = threading.Event()

        class HeldReader:
            def readline(self, _size: int = -1) -> bytes:
                release_reader.wait(2)
                return b""

        class HeldWriter:
            def write(self, data: bytes) -> int:
                entered.set()
                release_writer.wait(2)
                return len(data)

            def flush(self) -> None:
                return None

        channel = ControlChannel(
            HeldReader(),
            HeldWriter(),
            on_failure=lambda reason: failed.set() if reason == "outgoing_queue_full" else None,
            queue_size=1,
        )
        try:
            channel.send(self._envelope())
            self.assertTrue(entered.wait(2))
            channel.send(self._envelope())
            with self.assertRaisesRegex(RuntimeError, "queue is full"):
                channel.send(self._envelope())
            self.assertTrue(failed.wait(2))
        finally:
            release_writer.set()
            release_reader.set()
            channel.close(join_timeout=2)


class HostProcessTests(unittest.TestCase):
    def test_registry_stops_only_explicitly_registered_processes(self) -> None:
        owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        external = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        registry = OwnedProcessRegistry()
        try:
            registration = registry.register_owned_process(owned, kind="speech")
            self.assertEqual(registration.kind, "speech")
            registry.terminate_owned_processes(timeout_seconds=0)
            self.assertIsNotNone(owned.poll())
            self.assertIsNone(external.poll())
        finally:
            for process in (owned, external):
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    @unittest.skipUnless(os.name == "nt", "stdout descriptor isolation is a Windows host contract")
    def test_stdout_isolation_keeps_private_pipe_and_redirects_application_output(self) -> None:
        code = (
            "from core.host.processes import redirect_stdout_to_stderr; "
            "import sys; control=redirect_stdout_to_stderr(); "
            "print('app-output'); control.write(b'private-control\\n'); control.close()"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            check=True,
            timeout=10,
        )
        self.assertIn(b"private-control", proc.stdout)
        self.assertIn(b"app-output", proc.stderr)


if __name__ == "__main__":
    unittest.main()
