"""Focused resource-lifecycle tests for the shared local admission seam."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.agent.local_runtime import execution as local_execution


class LocalModelAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = SimpleNamespace(
            provider="ollama",
            runtime="local",
            api_model="alias-for-api",
            runtime_model_id="runtime-model:latest",
            context_window=8192,
            generation_timeout=30,
            ram_limit=80.0,
            cpu_limit=90.0,
            high_resource=False,
        )
        self.backend = SimpleNamespace(enabled=True)
        self.patches = [
            patch.object(
                local_execution,
                "get_local_runtime_backend",
                return_value=self.backend,
            ),
            patch.object(local_execution, "try_begin_local_execution", return_value=True),
            patch.object(local_execution, "end_local_execution"),
            patch.object(
                local_execution,
                "get_provider_snapshot",
                return_value={"reachable": True, "installed_models": ["runtime-model:latest"]},
            ),
            patch.object(local_execution, "is_local_model_ready", return_value=True),
            patch.object(local_execution, "check_resource_gate", return_value=(True, None)),
            patch.object(local_execution, "switch_local_model", return_value=True),
        ]
        self.mocks = [item.start() for item in self.patches]
        (
            self.backend_lookup,
            self.begin,
            self.end,
            self.snapshot,
            self.ready,
            self.resource_gate,
            self.switch,
        ) = self.mocks

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()

    def test_occupied_slot_rejects_without_releasing_another_execution(self) -> None:
        self.begin.return_value = False

        with self.assertRaisesRegex(
            local_execution.LocalModelAdmissionError, "already in progress"
        ):
            with local_execution.admit_local_model(self.profile):
                self.fail("occupied execution slot must not enter")

        self.end.assert_not_called()
        self.snapshot.assert_not_called()

    def test_unreachable_runtime_releases_the_claimed_slot(self) -> None:
        self.snapshot.return_value = {"reachable": False, "installed_models": []}

        with self.assertRaisesRegex(
            local_execution.LocalModelAdmissionError, "unreachable"
        ):
            with local_execution.admit_local_model(self.profile):
                self.fail("unreachable runtime must not enter")

        self.end.assert_called_once_with()

    def test_missing_runtime_alias_releases_the_claimed_slot(self) -> None:
        self.snapshot.return_value = {"reachable": True, "installed_models": ["other-model"]}

        with self.assertRaisesRegex(
            local_execution.LocalModelAdmissionError, "not installed"
        ):
            with local_execution.admit_local_model(self.profile):
                self.fail("missing model must not enter")

        self.end.assert_called_once_with()

    def test_failed_model_load_releases_the_claimed_slot(self) -> None:
        self.switch.return_value = False

        with self.assertRaisesRegex(
            local_execution.LocalModelAdmissionError, "could not be loaded"
        ):
            with local_execution.admit_local_model(self.profile):
                self.fail("failed load must not enter")

        self.end.assert_called_once_with()

    def test_successful_admission_holds_then_releases_the_slot(self) -> None:
        entered = False
        with local_execution.admit_local_model(self.profile):
            entered = True
            self.begin.assert_called_once_with()
            self.end.assert_not_called()
        self.assertTrue(entered)
        self.end.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
