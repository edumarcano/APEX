"""Regression coverage for verified manual local-model lifecycle controls."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException

from core.api.assistant import (
    build_agent_profile_statuses,
    load_local_model_endpoint,
    unload_active_local_model_endpoint,
)


class LocalModelLifecycleControlTests(unittest.TestCase):
    def test_load_prewarms_only_after_gate_and_runtime_verification(self) -> None:
        with (
            mock.patch("core.api.assistant.DEMO_MODE", False),
            mock.patch("core.api.assistant.OLLAMA_ENABLED", True),
            mock.patch("core.api.assistant.try_begin_local_execution", return_value=True),
            mock.patch("core.api.assistant.end_local_execution") as end_execution,
            mock.patch("core.api.assistant.is_local_model_resident", side_effect=[False, True]),
            mock.patch("core.api.assistant.check_resource_gate", return_value=(True, None)) as gate,
            mock.patch("core.api.assistant.switch_local_model", return_value=True) as switch,
            mock.patch("core.api.assistant.get_status_snapshot") as snapshot,
        ):
            response = load_local_model_endpoint("mus")

        self.assertEqual(response.profile, "mus")
        gate.assert_called_once()
        switch.assert_called_once()
        snapshot.assert_called_once_with(force_refresh=True)
        end_execution.assert_called_once()

    def test_load_rejects_demo_mode_without_touching_ollama(self) -> None:
        with mock.patch("core.api.assistant.DEMO_MODE", True), mock.patch(
            "core.api.assistant.try_begin_local_execution"
        ) as begin:
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("mus")

        self.assertEqual(raised.exception.status_code, 403)
        begin.assert_not_called()

    def test_load_rejects_competing_local_work(self) -> None:
        with (
            mock.patch("core.api.assistant.DEMO_MODE", False),
            mock.patch("core.api.assistant.OLLAMA_ENABLED", True),
            mock.patch("core.api.assistant.try_begin_local_execution", return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("mus")

        self.assertEqual(raised.exception.status_code, 409)

    def test_load_never_reports_success_without_runtime_residency(self) -> None:
        with (
            mock.patch("core.api.assistant.DEMO_MODE", False),
            mock.patch("core.api.assistant.OLLAMA_ENABLED", True),
            mock.patch("core.api.assistant.try_begin_local_execution", return_value=True),
            mock.patch("core.api.assistant.end_local_execution"),
            mock.patch("core.api.assistant.is_local_model_resident", side_effect=[False, False]),
            mock.patch("core.api.assistant.check_resource_gate", return_value=(True, None)),
            mock.patch("core.api.assistant.switch_local_model", return_value=True),
        ):
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("sorex")

        self.assertEqual(raised.exception.status_code, 503)

    def test_unload_claims_the_execution_slot_before_requesting_release(self) -> None:
        with (
            mock.patch("core.api.assistant.OLLAMA_MANUAL_UNLOAD_ENABLED", True),
            mock.patch("core.api.assistant.try_begin_local_execution", return_value=True),
            mock.patch("core.api.assistant.end_local_execution") as end_execution,
            mock.patch("core.api.assistant.get_status_snapshot", return_value={"reachable": True}),
            mock.patch("core.api.assistant.unload_active_local_model", return_value=True),
        ):
            response = unload_active_local_model_endpoint()

        self.assertEqual(response.status, "success")
        end_execution.assert_called_once()

    def test_unload_propagates_failed_runtime_verification(self) -> None:
        with (
            mock.patch("core.api.assistant.OLLAMA_MANUAL_UNLOAD_ENABLED", True),
            mock.patch("core.api.assistant.try_begin_local_execution", return_value=True),
            mock.patch("core.api.assistant.end_local_execution") as end_execution,
            mock.patch("core.api.assistant.get_status_snapshot", return_value={"reachable": True}),
            mock.patch("core.api.assistant.unload_active_local_model", return_value=False),
        ):
            with self.assertRaises(HTTPException) as raised:
                unload_active_local_model_endpoint()

        self.assertEqual(raised.exception.status_code, 503)
        end_execution.assert_called_once()

    def test_profile_status_uses_ollama_residency_not_only_the_tracker(self) -> None:
        snapshot = {
            "reachable": True,
            "installed_tags": ["qwen3:1.7b", "qwen3:4b-instruct"],
            "loaded_models": [],
            "vitals": {"cpu": 10.0, "ram": 10.0},
        }
        with (
            mock.patch("core.api.assistant.OLLAMA_ENABLED", True),
            mock.patch("core.api.assistant.get_status_snapshot", return_value=snapshot),
            mock.patch("core.api.assistant.get_active_loaded_model", return_value="qwen3:4b-instruct"),
            mock.patch("core.api.assistant.get_loading_model", return_value=None),
            mock.patch("core.api.assistant.get_idle_unload_remaining_seconds", return_value=60),
            mock.patch("core.api.assistant.is_local_execution_active", return_value=False),
            mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "GEMINI_API_KEY": "test-key"}),
        ):
            profiles = {profile.key: profile for profile in build_agent_profile_statuses()}

        self.assertFalse(profiles["mus"].active)
        self.assertIsNone(profiles["mus"].idle_unload_remaining_seconds)


if __name__ == "__main__":
    unittest.main()
