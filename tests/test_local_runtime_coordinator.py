"""Unit coverage for the provider-neutral local runtime coordinator."""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import ClassVar, Literal
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
    provider: ClassVar[Literal["ollama"]] = "ollama"
    runtime: ClassVar[Literal["local"]] = "local"
    api_model: str
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
    provider = "ollama"

    def __init__(self) -> None:
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

    def get_status_snapshot(
        self, *, force_refresh: bool = False
    ) -> LocalRuntimeSnapshot:
        if coord.is_local_execution_active():
            self.lock_held_during_io = True
        loaded: list[LocalRuntimeModel] = [
            {
                "provider": "ollama",
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
            "provider": "ollama",
            "reachable": True,
            "installed_models": list(self.installed),
            "loaded_models": loaded,
            "sampled_at": 0.0,
        }

    def is_model_resident(self, model: str) -> bool:
        return model in self.resident

    def load_model(self, profile: LocalModelProfile) -> bool:
        model = profile.runtime_model_id
        self.load_calls.append(model)
        if model in self.fail_load:
            return False
        self.resident.add(model)
        return True

    def unload_model(self, model: str) -> bool:
        self.unload_calls.append(model)
        if model in self.fail_unload:
            return False
        self.resident.discard(model)
        return True

    def invalidate_status_snapshot(self) -> None:
        return None


class LocalRuntimeCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _FakeBackend()
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
                return_value=self.backend,
            ),
            mock.patch(
                "core.agent.local_runtime.coordinator.iter_local_runtime_backends",
                return_value=(self.backend,),
            ),
            mock.patch(
                "core.agent.local_runtime.coordinator._known_local_model_refs",
                return_value=frozenset(
                    {
                        LocalModelRef(provider="ollama", model="sorex-model"),
                        LocalModelRef(provider="ollama", model="mus-model"),
                    }
                ),
            ),
        ]
        for patched in self._patches:
            patched.start()
            self.addCleanup(patched.stop)
        # Ensure execution lock is released between tests.
        while coord.is_local_execution_active():
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
        profile = _FakeProfile(api_model="mus-model")
        self.backend.resident.add("mus-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(profile))
        self.backend.load_calls.clear()
        self.assertTrue(coord.switch_local_model(profile))
        self.assertEqual(self.backend.load_calls, [])
        coord.end_local_execution()

    def test_cold_target_load(self) -> None:
        profile = _FakeProfile(api_model="mus-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(profile))
        self.assertEqual(self.backend.load_calls, ["mus-model"])
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="mus-model"),
        )
        coord.end_local_execution()

    def test_target_already_resident_bypasses_reload_path(self) -> None:
        profile = _FakeProfile(api_model="sorex-model")
        self.backend.resident.add("sorex-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(profile))
        self.assertEqual(self.backend.load_calls, ["sorex-model"])
        coord.end_local_execution()

    def test_switch_unloads_competing_known_model(self) -> None:
        self.backend.resident.add("sorex-model")
        coord.register_local_activity(
            LocalModelRef(provider="ollama", model="sorex-model")
        )
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(_FakeProfile(api_model="mus-model")))
        self.assertEqual(self.backend.unload_calls, ["sorex-model"])
        self.assertEqual(self.backend.load_calls, ["mus-model"])
        self.assertNotIn("sorex-model", self.backend.resident)
        coord.end_local_execution()

    def test_unknown_external_model_is_not_auto_unloaded(self) -> None:
        self.backend.resident.add("external-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertTrue(coord.switch_local_model(_FakeProfile(api_model="mus-model")))
        self.assertEqual(self.backend.unload_calls, [])
        self.assertIn("external-model", self.backend.resident)
        coord.end_local_execution()

    def test_failed_unload_aborts_switch(self) -> None:
        self.backend.resident.add("sorex-model")
        self.backend.fail_unload.add("sorex-model")
        coord.register_local_activity(
            LocalModelRef(provider="ollama", model="sorex-model")
        )
        self.assertTrue(coord.try_begin_local_execution())
        self.assertFalse(coord.switch_local_model(_FakeProfile(api_model="mus-model")))
        self.assertEqual(self.backend.load_calls, [])
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="sorex-model"),
        )
        coord.end_local_execution()

    def test_failed_load_leaves_no_false_active_state(self) -> None:
        self.backend.fail_load.add("mus-model")
        self.assertTrue(coord.try_begin_local_execution())
        self.assertFalse(coord.switch_local_model(_FakeProfile(api_model="mus-model")))
        self.assertIsNone(coord.get_active_local_model())
        self.assertIsNone(coord.get_loading_local_model())
        coord.end_local_execution()

    def test_activity_resets_idle_countdown(self) -> None:
        ref = LocalModelRef(provider="ollama", model="mus-model")
        self.backend.resident.add("mus-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 1030.0
        self.assertEqual(coord.get_idle_unload_remaining_seconds(), 30)
        coord.register_local_activity(ref)
        self.assertEqual(coord.get_idle_unload_remaining_seconds(), 60)

    def test_idle_worker_skips_active_execution(self) -> None:
        ref = LocalModelRef(provider="ollama", model="mus-model")
        self.backend.resident.add("mus-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        self.assertTrue(coord.try_begin_local_execution())
        coord._maybe_unload_idle_model()
        self.assertEqual(self.backend.unload_calls, [])
        self.assertEqual(coord.get_active_local_model(), ref)
        coord.end_local_execution()

    def test_idle_unload_success(self) -> None:
        ref = LocalModelRef(provider="ollama", model="mus-model")
        self.backend.resident.add("mus-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        coord._maybe_unload_idle_model()
        self.assertEqual(self.backend.unload_calls, ["mus-model"])
        self.assertIsNone(coord.get_active_local_model())

    def test_idle_unload_failed_verification_keeps_active(self) -> None:
        ref = LocalModelRef(provider="ollama", model="mus-model")
        self.backend.resident.add("mus-model")
        self.backend.fail_unload.add("mus-model")
        coord.register_local_activity(ref)
        self.clock["now"] = 2000.0
        coord._maybe_unload_idle_model()
        self.assertEqual(coord.get_active_local_model(), ref)

    def test_restart_reconciliation_adopts_single_resident(self) -> None:
        self.backend.resident.add("mus-model")
        self.assertEqual(
            coord.get_active_local_model(),
            LocalModelRef(provider="ollama", model="mus-model"),
        )

    def test_restart_reconciliation_leaves_multiple_untracked(self) -> None:
        self.backend.resident.update({"mus-model", "sorex-model"})
        self.assertIsNone(coord.get_active_local_model())

    def test_profile_protocol_compliance(self) -> None:
        profile = _FakeProfile(api_model="mus-model", high_resource=True)
        self.assertIsInstance(profile, LocalModelProfile)
        sorex = _FakeProfile(api_model="sorex-model", high_resource=False)
        self.assertFalse(sorex.high_resource)
        self.assertTrue(profile.high_resource)


if __name__ == "__main__":
    unittest.main()
