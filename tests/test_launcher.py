"""Characterization coverage for launcher orchestration helpers."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import launcher


class LauncherHelperTests(unittest.TestCase):
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

    def test_launch_background_servers_sets_pythonpath_and_commands(self) -> None:
        created: list[dict[str, object]] = []
        real_popen = subprocess.Popen

        def _fake_popen(cmd: list[str], **kwargs: object) -> mock.Mock:
            created.append({"cmd": cmd, "kwargs": kwargs})
            handle = mock.Mock(spec=real_popen)
            handle.poll.return_value = None
            return handle

        with mock.patch.object(launcher.subprocess, "Popen", side_effect=_fake_popen):
            uvicorn_proc, static_proc = launcher.launch_background_servers()

        self.assertEqual(len(created), 2)
        uvicorn_cmd = created[0]["cmd"]
        static_cmd = created[1]["cmd"]
        self.assertEqual(
            uvicorn_cmd[-6:],
            ["uvicorn", "core.api:app", "--host", "127.0.0.1", "--port", "8000"],
        )
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


if __name__ == "__main__":
    unittest.main()
