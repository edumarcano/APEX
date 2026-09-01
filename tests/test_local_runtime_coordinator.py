"""Unit coverage for the provider-neutral local runtime coordinator."""

from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass
from typing import Literal
from unittest import mock

from core.agent.local_runtime import coordinator as coord
from core.agent.local_runtime.contract import (
    LocalModelProfile,
    LocalModelRef,
    LocalRuntimeModel,
    LocalRuntimeSnapshot,
)


@dataclass
class _FakeProfile:
    api_model: str
    provider: Literal["ollama", "llama_cpp"] = "ollama"
    runtime: Literal["local"] = "local"
    context_window: int = 4096
    generation_timeout: int = 30
    ram_limit: float = 90.0
    cpu_limit: float = 90.0
    high_resource: bool = False
    default_temperature: float = 0.2
    num_thread: int = 4
    think: bool = False

    @property
    def runtime_model_id(self) -> str:
        return self.api_model


class _FakeBackend:
    def __init__(self, provider: Literal["ollama", "llama_cpp"] = "ollama") -> None:
        self.provider = provider
        self.enabled = True
        self.idle_unload_seconds = 60
        self.manual_unload_enabled = True
        self.resident: set[str] = set()
        self.installed: list[str] = []
        self.load_calls: list[str] = []
        self.unload_calls: list[str] = []
        self.fail_unload: set[str] = set()
        self.fail_load: set[str] = set()
        self.lock_held_during_io = False
        self.unload_gate: threading.Event | None = None
        self.unload_entered: threading.Event | None = None
        self.load_gate: threading.Event | None = None
        self.load_entered: threading.Event | None = None

    def get_status_snapshot(
        self, *, force_refresh: bool = False
    ) -> LocalRuntimeSnapshot:
        if coord.is_local_execution_active():
            self.lock_held_during_io = True
        loaded: list[LocalRuntimeModel] = [
            {
                "provider": self.provider,
                "name": model,
                "model": model,
                "state": "loaded",
                "size_bytes": None,
                "size_vram_bytes": None,
                "processor": None,
                "context": None,
                "context_window": None,
                "expires_at": None,
            }
            for model in sorted(self.resident)
        ]
        return {
            "provider": self.provider,
            "reachable": True,
            "installed_models": list(self.installed),
            "loaded_models": loaded,
            "sampled_at": 0.0,
        }

    def is_model_resident(self, model: str) -> bool:
        return model in self.resident

    def load_model(self, profile: LocalModelProfile) -> bool:
        model = profile.runtime_model_id
        if self.load_entered is not None:
            self.load_entered.set()
        if self.load_gate is not None:
            self.load_gate.wait(timeout=2.0)
        self.load_calls.append(model)
        if model in self.fail_load:
            return False
        self.resident.add(model)
        return True

    def unload_model(self, model: str) -> bool:
        if self.unload_entered is not None:
            self.unload_entered.set()
        if self.unload_gate is not None:
            self.unload_gate.wait(timeout=2.0)
        self.unload_calls.append(model)
        if model in self.fail_unload:
            return False
        self.resident.discard(model)
        return True

    def invalidate_status_snapshot(self) -> None:
        return None


class LocalRuntimeCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _FakeBackend("ollama")
        self.llama_backend = _FakeBackend("llama_cpp")
        self.backends = {
            "ollama": self.backend,
            "llama_cpp": self.llama_backend,
        }
        self.clock = {"now": 1000.0}
        self._patches = [
            mock.patch.object(coord, "_active_local_model", None),
            mock.patch.object(coord, "_loading_local_model", None),
            mock.patch.object(coord, "_last_activity_time", 1000.0),
            mock.patch.object(
                coord,
                "_monotonic",
                side_effect=lambda: self.clock["now"],
            ),
            mock.patch(
                "core.agent.local_runtime.coordinator.get_local_runtime_backend",
                side_effect=lambda provider: self.backends[provider],
            ),
            mock.patch(
                "core.agent.local_runtime.coordinator.iter_local_runtime_backends",
                side_effect=lambda enabled_only=False: tuple(self.backends.values()),
            ),
            mock.patch(
                "core.agent.local_runtime.coordinator._known_local_model_refs",
                return_value=frozenset(
                    {
                        LocalModelRef(provider="ollama", model="qwen-17b-model"),
                        LocalModelRef(provider="ollama", model="qwen-4b-model"),
                        LocalModelRef(provider="llama_cpp", model="gemma-e2b-16k"),
                        LocalModelRef(provider="llama_cpp", model="gemma-e2b-4k"),
                    }
                ),
            ),
        ]
        for patched in self._patches:
            patched.start()
            self.addCleanup(patched.stop)
        # Ensure execution and transition locks are released between tests.
        while coord.is_local_runtime_transition_active():
            coord.end_local_runtime_transition()
        while coord.is_local_execution_active():
            coord.end_local_execution()

    def test_transition_lock_blocks_local_execution(self) -> None:
        self.assertTrue(coord.try_begin_local_runtime_transition())
        self.assertFalse(coord.try_begin_local_execution())
        coord.end_local_runtime_transition()
        self.assertTrue(coord.try_begin_local_execution())
        coord.end_local_execution()

    def test_transition_lock_rejects_when_execution_active(self) -> None:
        self.assertTrue(coord.try_begin_local_execution())
        self.assertFalse(coord.try_begin_local_runtime_transition())
        coord.end_local_execution()

    def test_lock_is_non_blocking(self) -> None:
        self.assertTrue(coord.try_begin_local_execution())
        self.assertFalse(coord.try_begin_local_execution())
        coord.end_local_execution()
        self.assertTrue(coord.try_begin_local_execution())
        coord.end_local_execution()

    def test_resource_gate_ram_precedence(self) -> None:
        allowed, reason = coord.check_resource_gate(
            50.0, 90.0, vitals={"cpu": 10.0, "ram": 55.0}
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "insufficient_ram")

        allowed, reason = coord.check_resource_gate(
            90.0, 50.0, vitals={"cpu": 55.0, "ram": 10.0}
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "cpu_overloaded")

    def test_same_target_already_active_is_noop(self) -> None:
        profile = _FakeProfile(api_model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(profile))
        self.backend.load_calls.clear()
        self.assertTrue(coord.switch_local_model(profile))
        self.assertEqual(self.backend.load_calls, [])
        coord.end_local_execution()

    def test_cold_target_load(self) -> None:
        profile = _FakeProfile(api_model="qwen-4b-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(profile))
        self.assertEqual(self.backend.load_calls, ["qwen-4b-model"])
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="qwen-4b-model"),
        )
        coord.end_local_execution()

    def test_target_already_resident_bypasses_reload_path(self) -> None:
        profile = _FakeProfile(api_model="qwen-17b-model")
        self.backend.resident.add("qwen-17b-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(profile))
        self.assertEqual(self.backend.load_calls, ["qwen-17b-model"])
        coord.end_local_execution()

    def test_switch_unloads_competing_known_model(self) -> None:
        self.backend.resident.add("qwen-17b-model")
        coord.register_local_activity(
            LocalModelRef(provider="ollama", model="qwen-17b-model")
        )
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(_FakeProfile(api_model="qwen-4b-model")))
        self.assertEqual(self.backend.unload_calls, ["qwen-17b-model"])
        self.assertEqual(self.backend.load_calls, ["qwen-4b-model"])
        self.assertNotIn("qwen-17b-model", self.backend.resident)
        coord.end_local_execution()

    def test_unknown_external_model_is_not_auto_unloaded(self) -> None:
        self.backend.resident.add("external-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(_FakeProfile(api_model="qwen-4b-model")))
        self.assertEqual(self.backend.unload_calls, [])
        self.assertIn("external-model", self.backend.resident)
        coord.end_local_execution()

    def test_failed_unload_aborts_switch(self) -> None:
        self.backend.resident.add("qwen-17b-model")
        self.backend.fail_unload.add("qwen-17b-model")
        coord.register_local_activity(
            LocalModelRef(provider="ollama", model="qwen-17b-model")
        )
        self.assertTrue(coord.try_begin_local_execution())
        self.assertFalse(coord.switch_local_model(_FakeProfile(api_model="qwen-4b-model")))
        self.assertEqual(self.backend.load_calls, [])
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="qwen-17b-model"),
        )
        coord.end_local_execution()

    def test_failed_load_leaves_no_false_active_state(self) -> None:
        self.backend.fail_load.add("qwen-4b-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertFalse(coord.switch_local_model(_FakeProfile(api_model="qwen-4b-model")))
        self.assertIsNone(coord.get_active_local_model())
        self.assertIsNone(coord.get_loading_local_model())
        coord.end_local_execution()

    def test_activity_resets_idle_countdown(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 1030.0
        self.assertEqual(coord.get_idle_unload_remaining_seconds(), 30)
        coord.register_local_activity(ref)
        self.assertEqual(coord.get_idle_unload_remaining_seconds(), 60)

    def test_idle_worker_skips_active_execution(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        self.assertTrue(coord.try_begin_local_execution())
        coord._maybe_unload_idle_model()
        self.assertEqual(self.backend.unload_calls, [])
        self.assertEqual(coord.get_active_local_model(), ref)
        coord.end_local_execution()

    def test_idle_unload_holds_execution_slot_through_unload(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        self.backend.unload_entered = threading.Event()
        self.backend.unload_gate = threading.Event()

        worker = threading.Thread(target=coord._maybe_unload_idle_model)
        worker.start()
        self.assertTrue(self.backend.unload_entered.wait(timeout=2.0))
        self.assertTrue(coord.is_local_execution_active())
        self.assertFalse(coord.try_begin_local_execution())
        self.backend.unload_gate.set()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())
        self.assertFalse(coord.is_local_execution_active())
        self.assertIsNone(coord.get_active_local_model())

    def test_idle_unload_success(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        coord._maybe_unload_idle_model()
        self.assertEqual(self.backend.unload_calls, ["qwen-4b-model"])
        self.assertIsNone(coord.get_active_local_model())

    def test_idle_unload_failed_verification_keeps_active(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        self.backend.fail_unload.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        coord._maybe_unload_idle_model()
        self.assertEqual(coord.get_active_local_model(), ref)

    def test_provider_restart_clears_stale_ready_state(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.assertTrue(coord.is_local_model_ready(ref))
        self.backend.resident.clear()
        self.assertFalse(coord.is_local_model_ready(ref))
        self.assertIsNone(coord.get_active_local_model())

    def test_external_unload_clears_stale_ready_state(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.backend.resident.discard("qwen-4b-model")
        self.assertFalse(coord.is_local_model_ready(ref))
        with coord._state_lock:
            self.assertIsNone(coord._active_local_model)

    def test_stale_tracked_target_forces_verified_reload(self) -> None:
        profile = _FakeProfile(api_model="qwen-4b-model")
        self.backend.resident.add("qwen-4b-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(profile))
        self.backend.load_calls.clear()
        self.backend.resident.discard("qwen-4b-model")
        self.assertTrue(coord.switch_local_model(profile))
        self.assertEqual(self.backend.load_calls, ["qwen-4b-model"])
        self.assertIn("qwen-4b-model", self.backend.resident)
        coord.end_local_execution()

    def test_stale_ready_miss_exposes_cold_load_gate(self) -> None:
        ref = LocalModelRef(provider="ollama", model="qwen-4b-model")
        profile = _FakeProfile(api_model="qwen-4b-model", ram_limit=40.0, cpu_limit=40.0)
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(ref)
        self.backend.resident.clear()

        self.assertFalse(coord.is_local_model_ready(ref))
        allowed, reason = coord.check_resource_gate(
            profile.ram_limit,
            profile.cpu_limit,
            vitals={"cpu": 10.0, "ram": 80.0},
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "insufficient_ram")

    def test_restart_reconciliation_adopts_single_resident(self) -> None:
        self.backend.resident.add("qwen-4b-model")
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="qwen-4b-model"),
        )

    def test_restart_reconciliation_leaves_multiple_untracked(self) -> None:
        self.backend.resident.update({"qwen-4b-model", "qwen-17b-model"})
        self.assertIsNone(coord.get_active_local_model())

    def test_restart_reconciliation_skips_during_switch(self) -> None:
        self.backend.resident.add("qwen-17b-model")
        coord.register_local_activity(
            LocalModelRef(provider="ollama", model="qwen-17b-model")
        )
        self.backend.unload_entered = threading.Event()
        self.backend.unload_gate = threading.Event()
        results: list[bool] = []

        def run_switch() -> None:
            self.assertTrue(coord.try_begin_local_execution())
            try:
                results.append(
                    coord.switch_local_model(_FakeProfile(api_model="qwen-4b-model"))
                )
            finally:
                coord.end_local_execution()

        switcher = threading.Thread(target=run_switch)
        switcher.start()
        self.assertTrue(self.backend.unload_entered.wait(timeout=2.0))
        # Old resident is still present while unload is paused; reconciliation
        # must not re-adopt it after the switch cleared the tracker.
        self.assertIsNone(coord.get_active_local_model())
        self.assertEqual(
            coord.get_loading_local_model(),
            LocalModelRef(provider="ollama", model="qwen-4b-model"),
        )
        self.backend.unload_gate.set()
        switcher.join(timeout=2.0)
        self.assertFalse(switcher.is_alive())
        self.assertEqual(results, [True])
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="qwen-4b-model"),
        )

    def test_profile_protocol_compliance(self) -> None:
        profile = _FakeProfile(api_model="qwen-4b-model", high_resource=True)
        self.assertIsInstance(profile, LocalModelProfile)
        small_qwen = _FakeProfile(api_model="qwen-17b-model", high_resource=False)
        self.assertFalse(small_qwen.high_resource)
        self.assertTrue(profile.high_resource)

    def test_ollama_to_llama_cpp_unloads_ollama_first(self) -> None:
        self.backend.resident.add("qwen-4b-model")
        coord.register_local_activity(
            LocalModelRef(provider="ollama", model="qwen-4b-model")
        )
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(
            coord.switch_local_model(
                _FakeProfile(api_model="gemma-e2b-16k", provider="llama_cpp")
            )
        )
        self.assertEqual(self.backend.unload_calls, ["qwen-4b-model"])
        self.assertEqual(self.llama_backend.load_calls, ["gemma-e2b-16k"])
        self.assertNotIn("qwen-4b-model", self.backend.resident)
        self.assertIn("gemma-e2b-16k", self.llama_backend.resident)
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="llama_cpp", model="gemma-e2b-16k"),
        )
        coord.end_local_execution()

    def test_llama_cpp_to_ollama_unloads_llama_cpp_first(self) -> None:
        self.llama_backend.resident.add("gemma-e2b-16k")
        coord.register_local_activity(
            LocalModelRef(provider="llama_cpp", model="gemma-e2b-16k")
        )
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(
            coord.switch_local_model(
                _FakeProfile(api_model="qwen-17b-model", provider="ollama")
            )
        )
        self.assertEqual(self.llama_backend.unload_calls, ["gemma-e2b-16k"])
        self.assertEqual(self.backend.load_calls, ["qwen-17b-model"])
        self.assertNotIn("gemma-e2b-16k", self.llama_backend.resident)
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="qwen-17b-model"),
        )
        coord.end_local_execution()

    def test_failed_cross_provider_unload_blocks_target_load(self) -> None:
        self.backend.resident.add("qwen-4b-model")
        self.backend.fail_unload.add("qwen-4b-model")
        coord.register_local_activity(
            LocalModelRef(provider="ollama", model="qwen-4b-model")
        )
        self.assertTrue(coord.try_begin_local_execution())
        self.assertFalse(
            coord.switch_local_model(
                _FakeProfile(api_model="gemma-e2b-16k", provider="llama_cpp")
            )
        )
        self.assertEqual(self.llama_backend.load_calls, [])
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="qwen-4b-model"),
        )
        coord.end_local_execution()

    def test_idle_unload_targets_active_provider(self) -> None:
        ref = LocalModelRef(provider="llama_cpp", model="gemma-e2b-16k")
        self.llama_backend.resident.add("gemma-e2b-16k")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        coord._maybe_unload_idle_model()
        self.assertEqual(self.llama_backend.unload_calls, ["gemma-e2b-16k"])
        self.assertEqual(self.backend.unload_calls, [])
        self.assertIsNone(coord.get_active_local_model())


if __name__ == "__main__":
    unittest.main()
