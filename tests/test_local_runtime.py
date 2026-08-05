"""Characterization coverage for provider-neutral local coordination."""

from __future__ import annotations

import unittest

from core.agent.local_runtime import LocalRuntimeCoordinator
from core.agent.providers.ollama_lifecycle import LOCAL_RUNTIME


class _IdleBackend:
    provider = "fake"

    def __init__(self) -> None:
        self.checks = 0

    def check_idle(self) -> None:
        self.checks += 1


class LocalRuntimeCoordinatorTests(unittest.TestCase):
    def test_execution_slot_records_owner_and_excludes_other_providers(self) -> None:
        coordinator = LocalRuntimeCoordinator()

        self.assertTrue(coordinator.try_begin_execution("ollama"))
        self.assertFalse(coordinator.try_begin_execution("litert"))
        self.assertTrue(coordinator.is_execution_active())
        self.assertEqual(coordinator.execution_provider(), "ollama")

        coordinator.end_execution()

        self.assertFalse(coordinator.is_execution_active())
        self.assertIsNone(coordinator.execution_provider())
        self.assertTrue(coordinator.try_begin_execution("litert"))
        coordinator.end_execution()

    def test_active_and_loading_identity_are_provider_scoped(self) -> None:
        coordinator = LocalRuntimeCoordinator()

        coordinator.mark_loading("ollama", "qwen3:4b-instruct")
        self.assertEqual(
            coordinator.get_loading_model("ollama"), "qwen3:4b-instruct"
        )
        self.assertIsNone(coordinator.get_loading_model("litert"))

        coordinator.mark_active("ollama", "qwen3:4b-instruct")
        self.assertEqual(
            coordinator.get_active_model("ollama"), "qwen3:4b-instruct"
        )
        self.assertIsNone(coordinator.get_active_model("litert"))

        coordinator.clear_loading("ollama", "qwen3:4b-instruct")
        self.assertIsNone(coordinator.get_loading_model("ollama"))

    def test_idle_candidate_is_cleared_only_when_activity_is_unchanged(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        coordinator.mark_active("ollama", "qwen3:1.7b")

        candidate = coordinator.idle_candidate("ollama", 0)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        model, activity_snapshot = candidate
        coordinator.register_activity("ollama", model)
        self.assertFalse(
            coordinator.clear_active_if_unchanged(
                "ollama", model, activity_snapshot
            )
        )
        self.assertEqual(coordinator.get_active_model("ollama"), model)

    def test_ollama_lifecycle_registers_a_provider_backend(self) -> None:
        self.assertIsNotNone(LOCAL_RUNTIME.get_backend("ollama"))

    def test_backend_registration_replaces_by_provider_name(self) -> None:
        coordinator = LocalRuntimeCoordinator()
        first = _IdleBackend()
        second = _IdleBackend()

        coordinator.register_backend(first)
        coordinator.register_backend(second)

        self.assertIs(coordinator.get_backend("fake"), second)


if __name__ == "__main__":
    unittest.main()
