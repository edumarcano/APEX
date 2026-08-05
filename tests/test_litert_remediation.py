"""Focused remediation coverage for shared local-runtime/LiteRT behavior."""

from __future__ import annotations

import importlib
import tempfile
import unittest
from unittest.mock import AsyncMock
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.agent.local_runtime import LocalRuntimeCoordinator, LOCAL_RUNTIME
from core.agent.providers import litert_lifecycle
from core.agent.providers.litert_lifecycle import LiteRTLifecycleBackend
from core.agent.providers.litert_models import LiteRTModelProfile
from core.api.app import local_idle_monitor_enabled
from core.settings.normalize import normalize_layer

app_module = importlib.import_module("core.api.app")


class _Backend:
    def __init__(self, provider: str, *, unload: bool = True, switch: bool = True) -> None:
        self.provider = provider
        self.unload_result = unload
        self.switch_result = switch
        self.unload_calls = 0
        self.switch_calls = 0
        self.shutdown_calls = 0

    def get_status_snapshot(self, *, force_refresh: bool = False) -> dict[str, object]:
        del force_refresh
        return {}

    def is_model_loaded(self, _model_name: str) -> bool:
        return False

    def is_model_resident(self, _model_name: str) -> bool:
        return False

    def switch_model(self, _profile: object) -> bool:
        self.switch_calls += 1
        return self.switch_result

    def unload_active_model(self) -> bool:
        self.unload_calls += 1
        return self.unload_result

    def unload_model(self, _model_name: str) -> bool:
        return True

    def get_idle_unload_remaining_seconds(self) -> int | None:
        return None

    def check_idle(self) -> None:
        return None

    def shutdown(self) -> bool:
        self.shutdown_calls += 1
        return True

    def reconcile_state(self) -> None:
        return None


class LocalRuntimeRemediationTests(unittest.TestCase):
    def test_switch_asks_untracked_external_backend_to_unload(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        ollama = _Backend("ollama")
        litert = _Backend("litert")
        coordinator.register_backend(ollama)
        coordinator.register_backend(litert)

        self.assertTrue(coordinator.switch_model("litert", object()))
        self.assertEqual(ollama.unload_calls, 1)
        self.assertEqual(litert.switch_calls, 1)

    def test_failed_non_target_unload_aborts_switch(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        ollama = _Backend("ollama", unload=False)
        litert = _Backend("litert")
        coordinator.register_backend(ollama)
        coordinator.register_backend(litert)

        self.assertFalse(coordinator.switch_model("litert", object()))
        self.assertEqual(litert.switch_calls, 0)

    def test_switching_back_to_ollama_evicts_litert(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        ollama = _Backend("ollama")
        litert = _Backend("litert")
        coordinator.register_backend(ollama)
        coordinator.register_backend(litert)

        self.assertTrue(coordinator.switch_model("ollama", object()))
        self.assertEqual(litert.unload_calls, 1)
        self.assertEqual(ollama.switch_calls, 1)

    def test_briefing_style_ollama_switch_uses_same_exclusion_path(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        ollama = _Backend("ollama")
        litert = _Backend("litert")
        coordinator.register_backend(ollama)
        coordinator.register_backend(litert)

        # Synthesis warmups use the same target-provider switch entry point.
        self.assertTrue(coordinator.switch_model("ollama", object()))
        self.assertEqual(litert.unload_calls, 1)

    def test_shutdown_calls_every_registered_backend(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        ollama = _Backend("ollama")
        litert = _Backend("litert")
        coordinator.register_backend(ollama)
        coordinator.register_backend(litert)

        self.assertTrue(coordinator.shutdown())
        self.assertEqual(ollama.shutdown_calls, 1)
        self.assertEqual(litert.shutdown_calls, 1)
        self.assertIsNone(coordinator.execution_provider())

    def test_lease_rejects_release_by_wrong_provider(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        self.assertTrue(coordinator.try_begin_execution("litert"))
        with self.assertRaises(RuntimeError):
            coordinator.end_execution("ollama")
        self.assertEqual(coordinator.execution_provider(), "litert")
        coordinator.end_execution("litert")

    def test_litert_only_starts_idle_monitor(self) -> None:
        with (
            mock.patch("core.api.app.OLLAMA_ENABLED", False),
            mock.patch("core.api.app.LITERT_ENABLED", True),
        ):
            self.assertTrue(local_idle_monitor_enabled())

    def test_shared_settings_fall_back_to_legacy_ollama_keys(self) -> None:
        normalized = normalize_layer(
            {
                "ollama": {
                    "idle_unload_timeout_minutes": 9,
                    "manual_unload_enabled": False,
                    "single_loaded_model": False,
                }
            },
            layer_name="config.local.json",
        )
        self.assertEqual(
            normalized["local_runtime"],
            {
                "idle_unload_timeout_minutes": 9,
                "manual_unload_enabled": False,
                "single_loaded_model": False,
            },
        )

        overridden = normalize_layer(
            {
                "ollama": {"idle_unload_timeout_minutes": 9},
                "local_runtime": {"idle_unload_timeout_minutes": 3},
            },
            layer_name="config.local.json",
        )
        self.assertEqual(overridden["local_runtime"]["idle_unload_timeout_minutes"], 3)

    def test_artifact_ignore_rules_are_present(self) -> None:
        ignore = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn(".venv-litert/", ignore)
        self.assertIn("models/litert/", ignore)
        self.assertIn("*.litertlm", ignore)

    def test_litert_percentage_gates_are_configurable(self) -> None:
        profile = LiteRTModelProfile(
            display_name="Test",
            agent_version="1",
            api_model="model",
            tier="lightweight",
            stability="preview",
            system_instruction="test",
            minimum_free_ram_mb=1,
            ram_limit=50.0,
            cpu_limit=90.0,
        )
        with mock.patch(
            "core.agent.providers.litert_lifecycle.psutil.virtual_memory",
            return_value=SimpleNamespace(available=10_000_000, percent=60.0),
        ), mock.patch(
            "core.agent.providers.litert_lifecycle.psutil.cpu_percent",
            return_value=10.0,
        ):
            allowed, reason = litert_lifecycle.check_litert_resource_gate(profile)
        self.assertFalse(allowed)
        self.assertEqual(reason, "insufficient_ram")


class LiteRTLifecycleRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._active = LOCAL_RUNTIME.get_active_model("litert")
        self._loading = LOCAL_RUNTIME.get_loading_model("litert")
        LOCAL_RUNTIME.clear_active("litert")
        LOCAL_RUNTIME.clear_loading("litert")

    def tearDown(self) -> None:
        LOCAL_RUNTIME.clear_active("litert")
        LOCAL_RUNTIME.clear_loading("litert")
        if self._active:
            LOCAL_RUNTIME.mark_active("litert", self._active)
        if self._loading:
            LOCAL_RUNTIME.mark_loading("litert", self._loading)

    def _backend_with_runtime(self, runtime: object) -> LiteRTLifecycleBackend:
        backend = object.__new__(LiteRTLifecycleBackend)
        backend._loaded_model = "model-a"
        backend._loaded_artifact = "artifact-a.litertlm"
        backend.runtime = runtime  # type: ignore[assignment]
        return backend

    def test_idle_unload_is_blocked_by_active_inference(self) -> None:
        runtime = SimpleNamespace(is_running=True, engine_model="artifact-a.litertlm")
        backend = self._backend_with_runtime(runtime)
        LOCAL_RUNTIME.mark_active("litert", "model-a")
        self.assertTrue(LOCAL_RUNTIME.try_begin_execution("litert"))
        try:
            with (
                mock.patch.object(
                    LOCAL_RUNTIME,
                    "idle_candidate",
                    return_value=("model-a", 0.0),
                ),
                mock.patch.object(backend, "unload_active_model") as unload,
            ):
                backend.check_idle()
            unload.assert_not_called()
        finally:
            LOCAL_RUNTIME.end_execution("litert")

    def test_failed_switch_clears_lifecycle_and_coordinator_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "model.litertlm"
            artifact.write_bytes(b"model")
            runtime = mock.Mock()
            runtime.load_engine.side_effect = RuntimeError("load failed")
            runtime.shutdown.return_value = True
            runtime.is_running = False
            runtime.engine_model = None
            backend = self._backend_with_runtime(runtime)
            profile = LiteRTModelProfile(
                display_name="Test",
                agent_version="1",
                api_model="model-b",
                tier="lightweight",
                stability="preview",
                system_instruction="test",
                artifact_path=str(artifact),
            )
            LOCAL_RUNTIME.mark_active("litert", "model-a")

            self.assertFalse(backend.switch_model(profile))
            self.assertIsNone(backend._loaded_model)
            self.assertIsNone(backend._loaded_artifact)
            self.assertIsNone(LOCAL_RUNTIME.get_active_model("litert"))
            self.assertIsNone(LOCAL_RUNTIME.get_loading_model("litert"))

    def test_worker_failure_requires_fresh_reload(self) -> None:
        runtime = mock.Mock()
        runtime.is_running = False
        runtime.engine_model = "artifact-a.litertlm"
        runtime.load_engine.side_effect = lambda artifact, **_kwargs: setattr(
            runtime, "is_running", True
        ) or setattr(runtime, "engine_model", str(artifact)) or {}
        backend = self._backend_with_runtime(runtime)
        self.assertFalse(backend.is_model_loaded("model-a"))
        with tempfile.TemporaryDirectory() as temp:
            artifact = Path(temp) / "model.litertlm"
            artifact.write_bytes(b"model")
            profile = LiteRTModelProfile(
                display_name="Test",
                agent_version="1",
                api_model="model-a",
                tier="lightweight",
                stability="preview",
                system_instruction="test",
                artifact_path=str(artifact),
            )
            self.assertTrue(backend.switch_model(profile))
        runtime.load_engine.assert_called_once()

    def test_shutdown_clears_state_and_closes_runtime(self) -> None:
        runtime = mock.Mock()
        runtime.shutdown.return_value = True
        runtime.is_running = True
        runtime.engine_model = "artifact-a.litertlm"
        backend = self._backend_with_runtime(runtime)
        LOCAL_RUNTIME.mark_active("litert", "model-a")

        self.assertTrue(backend.shutdown())
        runtime.shutdown.assert_called_once()
        self.assertIsNone(backend._loaded_model)
        self.assertIsNone(backend._loaded_artifact)
        self.assertIsNone(LOCAL_RUNTIME.get_active_model("litert"))


class ApplicationLifespanRemediationTests(unittest.IsolatedAsyncioTestCase):
    async def test_application_shutdown_closes_registered_local_backends(self) -> None:
        mcp_config = SimpleNamespace(enabled=False)
        mcp_manager = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock())
        auth = SimpleNamespace(shutdown=AsyncMock())
        todo = SimpleNamespace(close=mock.Mock())
        with (
            mock.patch.object(app_module, "local_idle_monitor_enabled", return_value=False),
            mock.patch.object(app_module.database, "initialize_db"),
            mock.patch.object(app_module, "load_mcp_config", return_value=mcp_config),
            mock.patch.object(app_module, "MCPClientManager", return_value=mcp_manager),
            mock.patch.object(app_module, "MicrosoftTodoAuthenticationService", return_value=auth),
            mock.patch.object(app_module, "MicrosoftTodoClient", return_value=todo),
            mock.patch.object(app_module, "LOCAL_RUNTIME") as runtime,
        ):
            async with app_module._app_lifespan(SimpleNamespace()):
                pass

        runtime.shutdown.assert_called_once()
        mcp_manager.shutdown.assert_called_once()
        auth.shutdown.assert_called_once()
        todo.close.assert_called_once()


class LiteRTDependencyCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        litert_lifecycle.clear_litert_dependency_cache()

    def test_dependency_probe_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            interpreter = Path(temp) / "python.exe"
            interpreter.write_bytes(b"fake")
            result = SimpleNamespace(returncode=0, stdout="0.15.0\n")
            with (
                mock.patch.object(litert_lifecycle, "LITERT_PYTHON_EXECUTABLE", str(interpreter)),
                mock.patch.object(litert_lifecycle.subprocess, "run", return_value=result) as run,
            ):
                litert_lifecycle.clear_litert_dependency_cache()
                self.assertEqual(litert_lifecycle._dependency_available(), (True, None))
                self.assertEqual(litert_lifecycle._dependency_available(), (True, None))
            run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
