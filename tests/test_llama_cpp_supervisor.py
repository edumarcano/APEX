"""Tests for optional APEX-managed llama.cpp server supervision."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.agent.providers import llama_cpp_supervisor as supervisor_mod
from core.agent.providers.llama_cpp_supervisor import (
    LlamaCppServerSupervisor,
    build_llama_server_args,
    parse_loopback_bind,
    reset_llama_cpp_server_supervisor_for_tests,
    sanitize_process_text,
    windows_creationflags,
)
from core.settings.models import LlamaCppPatch, SettingsPatch
from core.settings.store import RuntimeSettingsStore, reset_settings_store_for_tests


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class LlamaCppSupervisorHelpersTests(unittest.TestCase):
    def test_bind_derives_host_and_port(self) -> None:
        bind = parse_loopback_bind("http://127.0.0.1:8080")
        self.assertEqual(bind.host, "127.0.0.1")
        self.assertEqual(bind.port, 8080)

    def test_bind_rejects_malformed_port(self) -> None:
        with self.assertRaises(supervisor_mod.LlamaCppManagedServerError):
            parse_loopback_bind("http://localhost:notaport")

    def test_args_include_expected_sequence_with_spaces(self) -> None:
        bind = parse_loopback_bind("http://127.0.0.1:9090")
        args = build_llama_server_args(
            executable_path=r"C:\Program Files\llama\llama-server.exe",
            preset_path=r"C:\Users\Test User\preset.ini",
            bind=bind,
        )
        self.assertEqual(
            args,
            [
                r"C:\Program Files\llama\llama-server.exe",
                "--host",
                "127.0.0.1",
                "--port",
                "9090",
                "--models-preset",
                r"C:\Users\Test User\preset.ini",
                "--models-max",
                "1",
                "--no-models-autoload",
            ],
        )

    def test_sanitize_strips_filesystem_paths(self) -> None:
        cleaned = sanitize_process_text(
            r"failed reading C:\Users\eduma\secret\model.gguf details"
        )
        self.assertNotIn(r"C:\Users\eduma", cleaned)
        self.assertNotIn("model.gguf", cleaned)
        self.assertIn("<path>", cleaned)

    def test_windows_creationflags_hide_console(self) -> None:
        with mock.patch.object(supervisor_mod.sys, "platform", "win32"):
            flags = windows_creationflags()
        self.assertEqual(flags, 0x08000000)


class LlamaCppSupervisorBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_llama_sup_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        self.exe = self._dir / "llama-server.exe"
        self.preset = self._dir / "preset.ini"
        self.exe.write_text("fake", encoding="utf-8")
        self.preset.write_text("[*]\n", encoding="utf-8")
        _write_json(
            self.config_path,
            {
                "llama_cpp": {
                    "enabled": False,
                    "managed": False,
                    "host": "http://127.0.0.1:8080",
                    "executable_path": "",
                    "preset_path": "",
                }
            },
        )
        reset_settings_store_for_tests()
        reset_llama_cpp_server_supervisor_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._runtime_patch = mock.patch(
            "core.agent.providers.llama_cpp_supervisor.get_llama_cpp_runtime_settings",
            side_effect=lambda: self.store.get_snapshot().llama_cpp,
        )
        self._runtime_patch.start()
        self.addCleanup(self._runtime_patch.stop)
        self.addCleanup(reset_settings_store_for_tests)
        self.addCleanup(reset_llama_cpp_server_supervisor_for_tests)
        self.supervisor = LlamaCppServerSupervisor()

    def tearDown(self) -> None:
        self.supervisor.shutdown_owned()

    def _enable(
        self,
        *,
        managed: bool,
        executable: str | None = None,
        preset: str | None = None,
    ) -> None:
        self.store.apply_patch(
            SettingsPatch(
                llama_cpp=LlamaCppPatch(
                    enabled=True,
                    managed=managed,
                    host="http://127.0.0.1:8080",
                    executable_path=executable if executable is not None else str(self.exe),
                    preset_path=preset if preset is not None else str(self.preset),
                )
            )
        )

    def test_disabled_does_not_spawn(self) -> None:
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=False
        ), mock.patch.object(supervisor_mod.subprocess, "Popen") as popen:
            status = self.supervisor.ensure_ready()
        popen.assert_not_called()
        self.assertEqual(status.state, "disabled")

    def test_reachable_external_is_not_duplicated(self) -> None:
        self._enable(managed=True)
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=True
        ), mock.patch.object(supervisor_mod.subprocess, "Popen") as popen:
            status = self.supervisor.ensure_ready()
        popen.assert_not_called()
        self.assertEqual(status.state, "external_connected")
        self.assertEqual(status.ownership, "external")

    def test_managed_unreachable_starts_with_expected_args(self) -> None:
        self._enable(managed=True)
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        fake_proc.stdout = iter(())
        fake_proc.stderr = iter(())
        fake_proc.pid = 4242

        probe = mock.Mock(side_effect=[False, True])
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", probe
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ) as popen, mock.patch.object(
            supervisor_mod.time, "sleep", return_value=None
        ):
            status = self.supervisor.ensure_ready()

        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(
            args[0],
            build_llama_server_args(
                executable_path=str(self.exe),
                preset_path=str(self.preset),
                bind=parse_loopback_bind("http://127.0.0.1:8080"),
            ),
        )
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(status.state, "managed_running")
        self.assertEqual(status.ownership, "apex")

    def test_paths_with_spaces_passed_as_sequence(self) -> None:
        spaced_dir = self._dir / "Program Files" / "llama cpp"
        spaced_dir.mkdir(parents=True)
        exe = spaced_dir / "llama-server.exe"
        preset = spaced_dir / "my preset.ini"
        exe.write_text("x", encoding="utf-8")
        preset.write_text("[*]\n", encoding="utf-8")
        self._enable(managed=True, executable=str(exe), preset=str(preset))
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        fake_proc.stdout = iter(())
        fake_proc.stderr = iter(())
        fake_proc.pid = 1
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", side_effect=[False, True]
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ) as popen, mock.patch.object(supervisor_mod.time, "sleep"):
            self.supervisor.ensure_ready()
        launched = popen.call_args[0][0]
        self.assertEqual(launched[0], str(exe))
        self.assertEqual(launched[6], str(preset))
        self.assertIsInstance(launched, list)

    def test_missing_executable_returns_clear_error(self) -> None:
        self._enable(managed=True, executable=str(self._dir / "missing.exe"))
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=False
        ), mock.patch.object(supervisor_mod.subprocess, "Popen") as popen:
            status = self.supervisor.ensure_ready()
        popen.assert_not_called()
        self.assertEqual(status.state, "startup_failed")
        self.assertIn("executable_path", status.last_error or "")

    def test_missing_preset_returns_clear_error(self) -> None:
        self._enable(managed=True, preset=str(self._dir / "missing.ini"))
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=False
        ):
            status = self.supervisor.ensure_ready()
        self.assertEqual(status.state, "startup_failed")
        self.assertIn("preset_path", status.last_error or "")

    def test_startup_timeout_leaves_unavailable_without_crash(self) -> None:
        self._enable(managed=True)
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        fake_proc.stdout = iter(())
        fake_proc.stderr = iter(())
        fake_proc.pid = 7
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=False
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ), mock.patch.object(
            supervisor_mod, "_STARTUP_TIMEOUT_SECONDS", 0.01
        ), mock.patch.object(
            supervisor_mod, "_STARTUP_POLL_SECONDS", 0.001
        ), mock.patch.object(supervisor_mod.time, "sleep"):
            status = self.supervisor.ensure_ready()
        self.assertEqual(status.state, "startup_failed")
        self.assertIn("timeout", (status.last_error or "").lower())

    def test_concurrent_probes_launch_at_most_one_child(self) -> None:
        self._enable(managed=True)
        started = threading.Event()
        release = threading.Event()
        launch_count = 0
        lock = threading.Lock()

        def fake_popen(*_args, **_kwargs):
            nonlocal launch_count
            with lock:
                launch_count += 1
            started.set()
            release.wait(timeout=2)
            proc = mock.Mock()
            proc.poll.return_value = None
            proc.stdout = iter(())
            proc.stderr = iter(())
            proc.pid = 99
            return proc

        probe_calls = {"n": 0}

        def fake_probe(_host: str, *, timeout: float = 2.0) -> bool:
            del timeout
            probe_calls["n"] += 1
            # Become healthy after the first launch has begun.
            return started.is_set() and release.is_set()

        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", side_effect=fake_probe
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", side_effect=fake_popen
        ), mock.patch.object(supervisor_mod.time, "sleep"):
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    self.supervisor.ensure_ready()
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            self.assertTrue(started.wait(timeout=2))
            release.set()
            for thread in threads:
                thread.join(timeout=3)
        self.assertEqual(errors, [])
        self.assertEqual(launch_count, 1)

    def test_shutdown_only_owned_process(self) -> None:
        self._enable(managed=True)
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        fake_proc.stdout = iter(())
        fake_proc.stderr = iter(())
        fake_proc.pid = 11
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", side_effect=[False, True]
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ), mock.patch.object(supervisor_mod.time, "sleep"):
            self.supervisor.ensure_ready()
        self.supervisor.shutdown_owned()
        fake_proc.terminate.assert_called_once()

    def test_external_servers_never_terminated(self) -> None:
        self._enable(managed=False)
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=True
        ), mock.patch.object(supervisor_mod.subprocess, "Popen") as popen:
            status = self.supervisor.ensure_ready()
            self.supervisor.shutdown_owned()
        popen.assert_not_called()
        self.assertEqual(status.ownership, "external")

    def test_managed_process_exit_reflected_in_status(self) -> None:
        self._enable(managed=True)
        fake_proc = mock.Mock()
        fake_proc.poll.side_effect = [None, None, 1]
        fake_proc.stdout = iter(())
        fake_proc.stderr = iter(())
        fake_proc.pid = 12
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", side_effect=[False, True, False]
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ), mock.patch.object(supervisor_mod.time, "sleep"):
            running = self.supervisor.ensure_ready()
            self.assertEqual(running.state, "managed_running")
            stopped = self.supervisor.status_snapshot()
        self.assertEqual(stopped.state, "managed_stopped")

    def test_no_endless_automatic_restart_loop(self) -> None:
        self._enable(managed=True)
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = 1
        fake_proc.stdout = iter(())
        fake_proc.stderr = iter(())
        fake_proc.pid = 13

        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=False
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ) as popen, mock.patch.object(
            supervisor_mod, "_STARTUP_TIMEOUT_SECONDS", 0.01
        ), mock.patch.object(
            supervisor_mod, "_STARTUP_POLL_SECONDS", 0.001
        ), mock.patch.object(supervisor_mod.time, "sleep"):
            first = self.supervisor.ensure_ready()
            # Simulate unexpected-exit restart budget then consume it.
            self.supervisor._state = "managed_stopped"  # noqa: SLF001
            self.supervisor._last_error = "exited"  # noqa: SLF001
            self.supervisor._restart_allowed = True  # noqa: SLF001
            second = self.supervisor.ensure_ready(allow_restart=True)
            third = self.supervisor.ensure_ready(allow_restart=True)
        self.assertEqual(first.state, "startup_failed")
        self.assertLessEqual(popen.call_count, 2)
        self.assertEqual(popen.call_count, 2)
        self.assertIn(third.state, {"startup_failed", "managed_stopped"})
        # A fourth call must not launch again.
        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", return_value=False
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ) as popen2, mock.patch.object(supervisor_mod.time, "sleep"):
            self.supervisor.ensure_ready(allow_restart=True)
        popen2.assert_not_called()
        self.assertIsNotNone(second)


class LlamaCppSettingsTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_llama_sup_trans_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        self.exe = self._dir / "llama-server.exe"
        self.preset = self._dir / "preset.ini"
        self.exe.write_text("fake", encoding="utf-8")
        self.preset.write_text("[*]\n", encoding="utf-8")
        _write_json(
            self.config_path,
            {
                "llama_cpp": {
                    "enabled": False,
                    "managed": False,
                    "host": "http://127.0.0.1:8080",
                    "executable_path": "",
                    "preset_path": "",
                }
            },
        )
        reset_settings_store_for_tests()
        reset_llama_cpp_server_supervisor_for_tests()
        self.store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        self._runtime_patch = mock.patch(
            "core.agent.providers.llama_cpp_supervisor.get_llama_cpp_runtime_settings",
            side_effect=lambda: self.store.get_snapshot().llama_cpp,
        )
        self._runtime_patch.start()
        self.addCleanup(self._runtime_patch.stop)
        self.addCleanup(reset_settings_store_for_tests)
        self.addCleanup(reset_llama_cpp_server_supervisor_for_tests)
        self.supervisor = LlamaCppServerSupervisor()

    def tearDown(self) -> None:
        self.supervisor.shutdown_owned()

    def _enable_managed(self) -> None:
        self.store.apply_patch(
            SettingsPatch(
                llama_cpp=LlamaCppPatch(
                    enabled=True,
                    managed=True,
                    executable_path=str(self.exe),
                    preset_path=str(self.preset),
                )
            )
        )

    def test_validate_rejects_identity_change_during_local_execution(self) -> None:
        self._enable_managed()
        previous = self.store.get_snapshot().llama_cpp
        proposed = previous.model_copy(update={"host": "http://127.0.0.1:9090"})
        with mock.patch.object(
            supervisor_mod, "is_local_execution_active", return_value=True
        ):
            with self.assertRaises(supervisor_mod.LlamaCppManagedServerError):
                self.supervisor.validate_settings_transition(previous, proposed)

    def test_validate_rejects_changes_while_starting(self) -> None:
        self._enable_managed()
        previous = self.store.get_snapshot().llama_cpp
        proposed = previous.model_copy(update={"managed": False})
        self.supervisor._state = "starting"  # noqa: SLF001
        with self.assertRaises(supervisor_mod.LlamaCppManagedServerError):
            self.supervisor.validate_settings_transition(previous, proposed)

    def test_deferred_shutdown_runs_after_local_execution_ends(self) -> None:
        self._enable_managed()
        fake_proc = mock.Mock()
        fake_proc.poll.return_value = None
        fake_proc.stdout = iter(())
        fake_proc.stderr = iter(())
        fake_proc.pid = 21
        previous = self.store.get_snapshot().llama_cpp
        current = previous.model_copy(update={"enabled": False})
        from core.agent.local_runtime import coordinator as coord

        with mock.patch.object(
            supervisor_mod, "probe_router_reachable", side_effect=[False, True]
        ), mock.patch.object(
            supervisor_mod.subprocess, "Popen", return_value=fake_proc
        ), mock.patch.object(supervisor_mod.time, "sleep"):
            self.supervisor.ensure_ready()
            self.assertTrue(coord.try_begin_local_execution())
            self.supervisor.on_settings_changed(previous, current)
            self.assertTrue(self.supervisor._stop_after_idle)  # noqa: SLF001
            with mock.patch.object(
                supervisor_mod,
                "get_llama_cpp_server_supervisor",
                return_value=self.supervisor,
            ):
                coord.end_local_execution()
        fake_proc.terminate.assert_called_once()

    def test_settings_patch_conflict_does_not_persist(self) -> None:
        self._enable_managed()
        store_patches = [
            mock.patch(
                "core.api.routers.system.get_settings_store",
                return_value=self.store,
            ),
            mock.patch("core.speaker.get_settings_store", return_value=self.store),
        ]
        for patcher in store_patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        from core.api import app

        client = TestClient(app)
        host_before = self.store.get_snapshot().llama_cpp.host
        self.supervisor._state = "starting"  # noqa: SLF001
        with mock.patch(
            "core.api.routers.system.get_llama_cpp_server_supervisor",
            return_value=self.supervisor,
        ):
            response = client.patch(
                "/api/v1/settings",
                json={"llama_cpp": {"host": "http://127.0.0.1:9191"}},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.get_snapshot().llama_cpp.host, host_before)


class LlamaCppManagedSettingsPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_llama_persist_")
        self.addCleanup(self._temp_dir.cleanup)
        self._dir = Path(self._temp_dir.name)
        self.config_path = self._dir / "config.json"
        self.local_path = self._dir / "config.local.json"
        _write_json(
            self.config_path,
            {
                "llama_cpp": {
                    "enabled": False,
                    "managed": False,
                    "host": "http://127.0.0.1:8080",
                    "executable_path": "",
                    "preset_path": "",
                }
            },
        )

    def test_paths_persist_only_to_local_config(self) -> None:
        store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        store.apply_patch(
            SettingsPatch(
                llama_cpp=LlamaCppPatch(
                    enabled=True,
                    managed=True,
                    executable_path=r"C:\Tools\llama-server.exe",
                    preset_path=r"C:\Tools\preset.ini",
                )
            )
        )
        local = json.loads(self.local_path.read_text(encoding="utf-8"))
        tracked = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(local["llama_cpp"]["executable_path"], r"C:\Tools\llama-server.exe")
        self.assertEqual(local["llama_cpp"]["preset_path"], r"C:\Tools\preset.ini")
        self.assertEqual(tracked["llama_cpp"]["executable_path"], "")
        self.assertFalse(tracked["llama_cpp"]["managed"])

    def test_managed_requires_paths(self) -> None:
        store = RuntimeSettingsStore(
            config_path=self.config_path,
            local_config_path=self.local_path,
        )
        with self.assertRaises(Exception):
            store.apply_patch(SettingsPatch(llama_cpp=LlamaCppPatch(managed=True)))


class LlamaCppStatusApiPrivacyTests(unittest.TestCase):
    def test_public_agent_status_omits_local_paths(self) -> None:
        from core.api.app import app

        reset_settings_store_for_tests()
        reset_llama_cpp_server_supervisor_for_tests()
        client = TestClient(app)
        agents = client.get("/api/v1/agents")
        self.assertEqual(agents.status_code, 200)
        blob = agents.text
        self.assertNotIn("executable_path", blob)
        self.assertNotIn("preset_path", blob)
        status = client.get("/api/v1/llama-cpp/status")
        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertNotIn("executable_path", payload)
        self.assertNotIn("preset_path", payload)


if __name__ == "__main__":
    unittest.main()
