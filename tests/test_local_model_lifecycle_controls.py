"""Regression coverage for verified manual local-model lifecycle controls."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException

from core.agent.local_runtime.contract import LocalModelRef
from core.api.cortex import (
    build_agent_statuses,
    load_local_model_endpoint,
    unload_active_local_model_endpoint,
)


class LocalModelLifecycleControlTests(unittest.TestCase):
    def test_load_prewarms_only_after_gate_and_runtime_verification(self) -> None:
        backend = mock.Mock()
        backend.enabled = True
        backend.is_model_resident.side_effect = [False, True]
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch("core.api.cortex.check_resource_gate", return_value=(True, None)) as gate,
            mock.patch("core.api.cortex.switch_local_model", return_value=True) as switch,
            mock.patch("core.api.cortex.get_provider_snapshot") as snapshot,
        ):
            response = load_local_model_endpoint("mus")

        self.assertEqual(response.agent, "mus")
        gate.assert_called_once()
        switch.assert_called_once()
        snapshot.assert_called_once_with("ollama", force_refresh=True)
        end_execution.assert_called_once()

    def test_load_rejects_demo_mode_without_touching_ollama(self) -> None:
        with mock.patch("core.api.cortex.DEMO_MODE", True), mock.patch(
            "core.api.cortex.try_begin_local_execution"
        ) as begin:
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("mus")

        self.assertEqual(raised.exception.status_code, 403)
        begin.assert_not_called()

    def test_load_rejects_competing_local_work(self) -> None:
        backend = mock.Mock()
        backend.enabled = True
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("mus")

        self.assertEqual(raised.exception.status_code, 409)

    def test_load_never_reports_success_without_runtime_residency(self) -> None:
        backend = mock.Mock()
        backend.enabled = True
        backend.is_model_resident.side_effect = [False, False]
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution"),
            mock.patch("core.api.cortex.check_resource_gate", return_value=(True, None)),
            mock.patch("core.api.cortex.switch_local_model", return_value=True),
        ):
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("sorex")

        self.assertEqual(raised.exception.status_code, 503)

    def test_load_with_stale_tracker_still_gates_and_switches(self) -> None:
        backend = mock.Mock()
        backend.enabled = True
        backend.is_model_resident.side_effect = [False, True]
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution"),
            mock.patch(
                "core.api.cortex.check_resource_gate", return_value=(True, None)
            ) as gate,
            mock.patch("core.api.cortex.switch_local_model", return_value=True) as switch,
            mock.patch("core.api.cortex.get_provider_snapshot"),
        ):
            response = load_local_model_endpoint("mus")

        self.assertEqual(response.agent, "mus")
        gate.assert_called_once()
        switch.assert_called_once()

    def test_unload_claims_the_execution_slot_before_requesting_release(self) -> None:
        backend = mock.Mock()
        backend.manual_unload_enabled = True
        with (
            mock.patch(
                "core.api.cortex.get_active_local_model",
                return_value=LocalModelRef(provider="ollama", model="qwen3:4b-instruct"),
            ),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch(
                "core.api.cortex.get_provider_snapshot",
                return_value={"reachable": True},
            ),
            mock.patch("core.api.cortex.unload_active_local_model", return_value=True),
        ):
            response = unload_active_local_model_endpoint()

        self.assertEqual(response.status, "success")
        end_execution.assert_called_once()

    def test_unload_noop_without_active_model_claims_slot_and_skips_probe(self) -> None:
        backend = mock.Mock()
        backend.manual_unload_enabled = True
        with (
            mock.patch("core.api.cortex.get_active_local_model", return_value=None),
            mock.patch(
                "core.api.cortex.iter_local_runtime_backends",
                return_value=(backend,),
            ),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch("core.api.cortex.get_provider_snapshot") as snapshot,
            mock.patch("core.api.cortex.unload_active_local_model") as unload,
        ):
            response = unload_active_local_model_endpoint()

        self.assertEqual(response.status, "success")
        end_execution.assert_called_once()
        snapshot.assert_not_called()
        unload.assert_not_called()

    def test_unload_noop_rejects_when_cold_load_holds_slot(self) -> None:
        backend = mock.Mock()
        backend.manual_unload_enabled = True
        with (
            mock.patch("core.api.cortex.get_active_local_model", return_value=None),
            mock.patch(
                "core.api.cortex.iter_local_runtime_backends",
                return_value=(backend,),
            ),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=False),
            mock.patch("core.api.cortex.get_provider_snapshot") as snapshot,
            mock.patch("core.api.cortex.unload_active_local_model") as unload,
        ):
            with self.assertRaises(HTTPException) as raised:
                unload_active_local_model_endpoint()

        self.assertEqual(raised.exception.status_code, 409)
        snapshot.assert_not_called()
        unload.assert_not_called()

    def test_unload_noop_rejects_when_switch_is_loading(self) -> None:
        backend = mock.Mock()
        backend.manual_unload_enabled = True
        with (
            mock.patch("core.api.cortex.get_active_local_model", return_value=None),
            mock.patch(
                "core.api.cortex.get_loading_local_model",
                return_value=LocalModelRef(provider="ollama", model="qwen3:4b-instruct"),
            ),
            mock.patch(
                "core.api.cortex.iter_local_runtime_backends",
                return_value=(backend,),
            ),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=False),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch("core.api.cortex.get_provider_snapshot") as snapshot,
            mock.patch("core.api.cortex.unload_active_local_model") as unload,
        ):
            with self.assertRaises(HTTPException) as raised:
                unload_active_local_model_endpoint()

        self.assertEqual(raised.exception.status_code, 409)
        end_execution.assert_not_called()
        snapshot.assert_not_called()
        unload.assert_not_called()

    def test_unload_propagates_failed_runtime_verification(self) -> None:
        backend = mock.Mock()
        backend.manual_unload_enabled = True
        with (
            mock.patch(
                "core.api.cortex.get_active_local_model",
                return_value=LocalModelRef(provider="ollama", model="qwen3:4b-instruct"),
            ),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch(
                "core.api.cortex.get_provider_snapshot",
                return_value={"reachable": True},
            ),
            mock.patch("core.api.cortex.unload_active_local_model", return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                unload_active_local_model_endpoint()

        self.assertEqual(raised.exception.status_code, 503)
        end_execution.assert_called_once()

    def test_profile_status_uses_ollama_residency_not_only_the_tracker(self) -> None:
        snapshot = {
            "provider": "ollama",
            "reachable": True,
            "installed_models": ["qwen3:1.7b", "qwen3:4b-instruct"],
            "loaded_models": [],
            "sampled_at": 0.0,
        }
        backend = mock.Mock()
        backend.provider = "ollama"
        backend.enabled = True
        backend.get_status_snapshot.return_value = snapshot
        with (
            mock.patch(
                "core.api.cortex.iter_local_runtime_backends",
                return_value=(backend,),
            ),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.get_system_vitals", return_value={"cpu": 10.0, "ram": 10.0}),
            mock.patch(
                "core.api.cortex.get_active_local_model",
                return_value=LocalModelRef(provider="ollama", model="qwen3:4b-instruct"),
            ),
            mock.patch("core.api.cortex.get_loading_local_model", return_value=None),
            mock.patch("core.api.cortex.get_idle_unload_remaining_seconds", return_value=60),
            mock.patch("core.api.cortex.is_local_execution_active", return_value=False),
            mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "GEMINI_API_KEY": "test-key"}),
        ):
            profiles = {profile.key: profile for profile in build_agent_statuses()}

        self.assertFalse(profiles["mus"].active)
        self.assertIsNone(profiles["mus"].idle_unload_remaining_seconds)


if __name__ == "__main__":
    unittest.main()
