"""Characterization coverage for launcher orchestration helpers."""

from __future__ import annotations

import os
import io
import subprocess
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import launcher
from core.host.protocol import ControlEnvelope, encode_envelope


class LauncherHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._logging_patch = mock.patch.object(launcher, "configure_logging")
        self._logging_patch.start()
        self.addCleanup(self._logging_patch.stop)

    def test_sanitized_env_keeps_only_allowlisted_keys(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "C:\\Windows\\System32",
                "SYSTEMROOT": "C:\\Windows",
                "TEMP": "C:\\Temp",
                "TMP": "C:\\Temp",
                "PYTHONPATH": "C:\\repo",
                "GEMINI_API_KEY": "secret",
                "HOME_SSID": "HomeNet",
            },
            clear=False,
        ):
            sanitized = launcher._get_sanitized_env()

        self.assertEqual(sanitized["PATH"], "C:\\Windows\\System32")
        self.assertEqual(sanitized["PYTHONPATH"], "C:\\repo")
        self.assertNotIn("GEMINI_API_KEY", sanitized)
        self.assertNotIn("HOME_SSID", sanitized)
        self.assertTrue(
            set(sanitized).issubset(
                {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PYTHONPATH"}
            )
        )

    def test_resolve_windows_browser_bins_prefers_custom_path(self) -> None:
        custom = Path("C:/Browsers/custom.exe")
        with mock.patch.object(launcher, "CUSTOM_BROWSER_PATH", str(custom)), mock.patch.dict(
            os.environ,
            {
                "PROGRAMFILES": "C:\\Program Files",
                "PROGRAMFILES(X86)": "C:\\Program Files (x86)",
                "LOCALAPPDATA": "C:\\Users\\test\\AppData\\Local",
            },
            clear=False,
        ):
            bins = launcher._resolve_windows_browser_bins()

        self.assertEqual(bins[0], custom)
        self.assertTrue(
            any(path.name.lower() == "chrome.exe" for path in bins),
            msg="Expected Chrome candidate after custom path",
        )
        self.assertTrue(
            any(path.name.lower() == "msedge.exe" for path in bins),
            msg="Expected Edge candidate after custom path",
        )

    def test_terminate_process_is_noop_when_already_exited(self) -> None:
        proc = mock.Mock(spec=subprocess.Popen)
        proc.poll.return_value = 0
        launcher._terminate_process(proc)
        proc.terminate.assert_not_called()
        proc.kill.assert_not_called()

    def test_terminate_process_kills_after_wait_timeout(self) -> None:
        proc = mock.Mock(spec=subprocess.Popen)
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired(cmd="uvicorn", timeout=10)
        launcher._terminate_process(proc)
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_control_reader_rejects_mismatched_request_correlation(self) -> None:
        launch_id = str(uuid.uuid4())
        wrong_id = str(uuid.uuid4())
        identity = {
            "app_id": "apex",
            "app_version": "2.1.0",
            "build_id": "source:2.1.0",
            "instance_id": str(uuid.uuid4()),
            "pid": 123,
            "hosting_mode": "managed",
            "launch_id": launch_id,
            "data_root_fingerprint": "a" * 64,
            "shutdown_timeout_seconds": 60,
        }
        frame = encode_envelope(
            ControlEnvelope(1, "starting", wrong_id, identity)
        )
        process = mock.Mock(spec=subprocess.Popen)
        process.poll.return_value = None
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(frame)
        control = launcher._ManagedBackendControl(process, launch_id)

        control.wait_ready(1)
        self.assertTrue(control.failed)
        self.assertEqual(control.error_code, "protocol_error")

    def test_control_reader_accepts_desktop_preferences_and_answers_device_unsupported(self) -> None:
        from core.host.protocol import decode_frame

        launch_id = str(uuid.uuid4())
        instance_id = str(uuid.uuid4())
        identity = {
            "app_id": "apex",
            "app_version": "2.1.0",
            "build_id": "source:2.1.0",
            "instance_id": instance_id,
            "pid": 123,
            "hosting_mode": "managed",
            "launch_id": launch_id,
            "data_root_fingerprint": "a" * 64,
            "shutdown_timeout_seconds": 60,
        }
        frames = [
            ControlEnvelope(1, "starting", launch_id, identity),
            ControlEnvelope(1, "ready", launch_id, identity),
            ControlEnvelope(
                1,
                "desktop_preferences",
                "desktop:1",
                {
                    "instance_id": instance_id,
                    "launch_on_startup": False,
                    "completion_notifications": False,
                },
            ),
            ControlEnvelope(
                1,
                "device_preferences",
                "device-prefs:4",
                {"instance_id": instance_id, "revision": 4, "location_enabled": True},
            ),
            ControlEnvelope(1, "stopping", launch_id, {}),
            ControlEnvelope(1, "stopped", launch_id, {}),
        ]
        process = mock.Mock(spec=subprocess.Popen)
        process.poll.return_value = None
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(b"".join(encode_envelope(frame) for frame in frames))
        control = launcher._ManagedBackendControl(process, launch_id)
        control._reader.join(2)

        self.assertFalse(control._reader.is_alive())
        self.assertFalse(control.failed)
        self.assertEqual(control.identity, identity)
        outgoing = [
            decode_frame(line)
            for line in process.stdin.getvalue().splitlines(keepends=True)
        ]
        device_states = [frame for frame in outgoing if frame.type == "device_state"]
        self.assertEqual(len(device_states), 1)
        self.assertEqual(
            device_states[0].payload,
            {
                "instance_id": instance_id,
                "revision": 4,
                "permission": "unsupported",
                "availability": "unsupported",
            },
        )
        self.assertEqual(device_states[0].request_id, "device-state:1")

    def test_wait_for_services_rejects_unowned_pid_and_failed_control(self) -> None:
        backend = mock.Mock(spec=subprocess.Popen)
        static = mock.Mock(spec=subprocess.Popen)
        backend.pid = 100
        backend.poll.return_value = None
        static.poll.return_value = None
        launch_id = str(uuid.uuid4())
        identity = {
            "pid": 101,
            "launch_id": launch_id,
            "hosting_mode": "managed",
            "build_id": "expected-build",
            "data_root_fingerprint": "a" * 64,
        }
        control = SimpleNamespace(
            identity=identity,
            launch_id=launch_id,
            error_code=None,
            failed=False,
        )
        with mock.patch.object(launcher, "_control_for", return_value=control), mock.patch.object(
            launcher, "_expected_profile_build", return_value=("expected-build", "a" * 64)
        ):
            reason = launcher.wait_for_services(backend, static)
        self.assertIn("identity did not match", reason or "")

        identity["pid"] = backend.pid
        control.failed = True
        with mock.patch.object(launcher, "_control_for", return_value=control), mock.patch.object(
            launcher, "_expected_profile_build", return_value=("expected-build", "a" * 64)
        ):
            reason = launcher.wait_for_services(backend, static)
        self.assertIn("control channel", reason or "")

    def test_wait_for_services_admits_only_matching_runtime_and_build_profile(self) -> None:
        backend = mock.Mock(spec=subprocess.Popen)
        static = mock.Mock(spec=subprocess.Popen)
        backend.pid = 100
        backend.poll.return_value = None
        static.poll.return_value = None
        launch_id = str(uuid.uuid4())
        identity = {
            "pid": backend.pid,
            "launch_id": launch_id,
            "hosting_mode": "managed",
            "build_id": "expected-build",
            "data_root_fingerprint": "a" * 64,
        }
        control = SimpleNamespace(
            identity=identity,
            launch_id=launch_id,
            error_code=None,
            failed=False,
        )
        with mock.patch.object(launcher, "_control_for", return_value=control), mock.patch.object(
            launcher, "_expected_profile_build", return_value=("expected-build", "a" * 64)
        ), mock.patch.object(launcher, "_http_json", return_value=identity), mock.patch.object(
            launcher, "_http_ok", return_value=True
        ):
            self.assertIsNone(launcher.wait_for_services(backend, static))

        for key, value in (
            ("build_id", "other-build"),
            ("data_root_fingerprint", "b" * 64),
        ):
            bad_identity = {**identity, key: value}
            control.identity = bad_identity
            with mock.patch.object(launcher, "_control_for", return_value=control), mock.patch.object(
                launcher, "_expected_profile_build", return_value=("expected-build", "a" * 64)
            ):
                reason = launcher.wait_for_services(backend, static)
            self.assertIn("identity did not match", reason or "")

        control.identity = identity
        wrong_runtime = {**identity, "instance_id": str(uuid.uuid4())}
        with mock.patch.object(launcher, "_control_for", return_value=control), mock.patch.object(
            launcher, "_expected_profile_build", return_value=("expected-build", "a" * 64)
        ), mock.patch.object(launcher, "_http_json", return_value=wrong_runtime), mock.patch.object(
            launcher, "_http_ok", return_value=True
        ):
            reason = launcher.wait_for_services(backend, static)
        self.assertIn("runtime identity", reason or "")

    def test_runtime_monitor_fails_when_owned_control_pipe_closes(self) -> None:
        backend = mock.Mock(spec=subprocess.Popen)
        backend.poll.return_value = None
        control = SimpleNamespace(failed=True, error_code=None)
        with mock.patch.object(launcher, "_control_for", return_value=control):
            reason = launcher._child_exit_reason("uvicorn", backend)
        self.assertIn("control channel", reason or "")

    def test_launch_background_servers_sets_pythonpath_and_commands(self) -> None:
        created: list[dict[str, object]] = []
        real_popen = subprocess.Popen

        def _fake_popen(cmd: list[str], **kwargs: object) -> mock.Mock:
            created.append({"cmd": cmd, "kwargs": kwargs})
            handle = mock.Mock(spec=real_popen)
            handle.poll.return_value = None
            if "stdout" in kwargs:
                handle.stdin = io.BytesIO()
                handle.stdout = io.BytesIO()
            return handle

        with mock.patch.object(launcher.subprocess, "Popen", side_effect=_fake_popen):
            uvicorn_proc, static_proc = launcher.launch_background_servers()

        self.assertEqual(len(created), 2)
        uvicorn_cmd = created[0]["cmd"]
        static_cmd = created[1]["cmd"]
        self.assertEqual(
            uvicorn_cmd[-4:],
            ["-m", "core.backend_host", "serve", "--managed"],
        )
        self.assertIn("-m", uvicorn_cmd)
        self.assertEqual(created[0]["kwargs"]["stdin"], subprocess.PIPE)
        self.assertEqual(created[0]["kwargs"]["stdout"], subprocess.PIPE)
        self.assertIn("http.server", static_cmd)
        self.assertIn("5500", static_cmd)
        self.assertIn("--bind", static_cmd)
        self.assertIn("127.0.0.1", static_cmd)
        self.assertIn("dist", static_cmd)

        uvicorn_env = created[0]["kwargs"]["env"]
        static_env = created[1]["kwargs"]["env"]
        assert isinstance(uvicorn_env, dict)
        assert isinstance(static_env, dict)
        self.assertIn(str(launcher.ROOT_DIR), uvicorn_env["PYTHONPATH"])
        self.assertIn(str(launcher.ROOT_DIR), static_env["PYTHONPATH"])
        self.assertNotIn("GEMINI_API_KEY", static_env)
        self.assertIsNotNone(uvicorn_proc)
        self.assertIsNotNone(static_proc)

    def test_launch_background_servers_cleans_up_after_second_spawn_failure(self) -> None:
        uvicorn_proc = mock.Mock(spec=subprocess.Popen)
        uvicorn_proc.poll.return_value = None
        uvicorn_proc.stdin = io.BytesIO()
        uvicorn_proc.stdout = io.BytesIO()

        with mock.patch.object(
            launcher.subprocess,
            "Popen",
            side_effect=[uvicorn_proc, OSError("static spawn failed")],
        ), mock.patch.object(launcher, "_terminate_process") as terminate:
            with self.assertRaises(OSError):
                launcher.launch_background_servers()

        terminate.assert_called_once_with(uvicorn_proc)

    def test_main_suppresses_browser_when_api_times_out(self) -> None:
        uvicorn_proc = mock.Mock(spec=subprocess.Popen)
        static_proc = mock.Mock(spec=subprocess.Popen)
        uvicorn_proc.poll.return_value = None
        static_proc.poll.return_value = None

        with mock.patch.object(
            launcher, "launch_background_servers", return_value=(uvicorn_proc, static_proc)
        ), mock.patch.object(launcher, "register_shutdown_hooks"), mock.patch.object(
            launcher, "_http_ok", return_value=False
        ), mock.patch.object(
            launcher, "launch_kiosk_browser"
        ) as launch_browser, mock.patch.object(
            launcher.time, "sleep"
        ), mock.patch.object(
            launcher, "_terminate_process"
        ) as terminate:
            exit_code = launcher.main()

        self.assertEqual(exit_code, 1)
        launch_browser.assert_not_called()
        self.assertGreaterEqual(terminate.call_count, 2)

    def test_main_opens_browser_when_both_services_ready(self) -> None:
        uvicorn_proc = mock.Mock(spec=subprocess.Popen)
        static_proc = mock.Mock(spec=subprocess.Popen)
        uvicorn_proc.poll.return_value = None
        static_proc.poll.return_value = None
        browser_proc = mock.Mock(spec=subprocess.Popen)
        browser_proc.poll.side_effect = [None, 0]

        with mock.patch.object(
            launcher, "launch_background_servers", return_value=(uvicorn_proc, static_proc)
        ), mock.patch.object(launcher, "register_shutdown_hooks"), mock.patch.object(
            launcher, "_http_ok", return_value=True
        ), mock.patch.object(
            launcher, "wait_for_services", return_value=None
        ), mock.patch.object(
            launcher, "launch_kiosk_browser", return_value=browser_proc
        ) as launch_browser, mock.patch.object(
            launcher.time, "sleep"
        ), mock.patch.object(
            launcher, "_terminate_process"
        ) as terminate:
            exit_code = launcher.main()

        self.assertEqual(exit_code, 0)
        launch_browser.assert_called_once_with(launcher.FRONTEND_URL)
        self.assertGreaterEqual(terminate.call_count, 2)

    def test_main_fails_on_early_child_exit(self) -> None:
        uvicorn_proc = mock.Mock(spec=subprocess.Popen)
        static_proc = mock.Mock(spec=subprocess.Popen)
        uvicorn_proc.poll.return_value = 1
        static_proc.poll.return_value = None

        with mock.patch.object(
            launcher, "launch_background_servers", return_value=(uvicorn_proc, static_proc)
        ), mock.patch.object(launcher, "register_shutdown_hooks"), mock.patch.object(
            launcher, "launch_kiosk_browser"
        ) as launch_browser, mock.patch.object(
            launcher, "_terminate_process"
        ) as terminate:
            exit_code = launcher.main()

        self.assertEqual(exit_code, 1)
        launch_browser.assert_not_called()
        self.assertGreaterEqual(terminate.call_count, 2)

    def test_main_closes_browser_and_fails_when_server_exits_after_startup(self) -> None:
        uvicorn_proc = mock.Mock(spec=subprocess.Popen)
        static_proc = mock.Mock(spec=subprocess.Popen)
        browser_proc = mock.Mock(spec=subprocess.Popen)
        browser_proc.poll.return_value = None
        uvicorn_proc.poll.return_value = 1
        static_proc.poll.return_value = None

        with mock.patch.object(
            launcher, "launch_background_servers", return_value=(uvicorn_proc, static_proc)
        ), mock.patch.object(launcher, "register_shutdown_hooks"), mock.patch.object(
            launcher, "wait_for_services", return_value=None
        ), mock.patch.object(
            launcher, "launch_kiosk_browser", return_value=browser_proc
        ), mock.patch.object(
            launcher, "_terminate_process"
        ) as terminate:
            exit_code = launcher.main()

        self.assertEqual(exit_code, 1)
        terminate.assert_any_call(browser_proc)
        terminate.assert_any_call(uvicorn_proc)
        terminate.assert_any_call(static_proc)


if __name__ == "__main__":
    unittest.main()
