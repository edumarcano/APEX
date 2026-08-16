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


def _lynx_settings_mock(*, context_window: int = 16384) -> mock.Mock:
    settings = mock.Mock()
    settings.ask_apex.agent = "lynx"
    settings.ask_apex.lynx.runtime = "llama_cpp"
    settings.ask_apex.lynx.model = "gemma-4-E2B-Q4_K_M.gguf"
    settings.ask_apex.lynx.context_window = context_window
    settings.ask_apex.panthera.hosted_tools.google_search = True
    settings.ask_apex.panthera.hosted_tools.google_maps = True
    settings.ask_apex.panthera.hosted_tools.x_search = True
    settings.ask_apex.panthera.model = "gpt-5.6-luna"
    return settings

def _ollama_snapshot(*installed: str) -> dict:
    return {
        "provider": "ollama",
        "reachable": True,
        "installed_models": list(installed),
        "loaded_models": [],
        "sampled_at": 0.0,
    }


class LocalModelLifecycleControlTests(unittest.TestCase):
    def test_load_prewarms_only_after_gate_and_runtime_verification(self) -> None:
        backend = mock.Mock()
        backend.enabled = True
        backend.is_model_resident.side_effect = [False, True]
        settings = _lynx_settings_mock()
        settings.ask_apex.lynx.runtime = "ollama"
        settings.ask_apex.lynx.model = "qwen3:4b-instruct"
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch("core.api.cortex.check_resource_gate", return_value=(True, None)) as gate,
            mock.patch("core.api.cortex.switch_local_model", return_value=True) as switch,
            mock.patch(
                "core.api.cortex.get_provider_snapshot",
                return_value=_ollama_snapshot("qwen3:4b-instruct"),
            ) as snapshot,
            mock.patch(
                "core.settings.get_settings_store",
                return_value=mock.Mock(get_snapshot=mock.Mock(return_value=settings)),
            ),
        ):
            response = load_local_model_endpoint("lynx")

        self.assertEqual(response.agent, "lynx")
        gate.assert_called_once()
        switch.assert_called_once()
        self.assertGreaterEqual(snapshot.call_count, 2)
        snapshot.assert_any_call("ollama", force_refresh=True)
        end_execution.assert_called_once()

    def test_load_rejects_demo_mode_without_touching_ollama(self) -> None:
        with mock.patch("core.api.cortex.DEMO_MODE", True), mock.patch(
            "core.api.cortex.try_begin_local_execution"
        ) as begin:
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("lynx")

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
                load_local_model_endpoint("lynx")

        self.assertEqual(raised.exception.status_code, 409)

    def test_load_rejects_missing_configured_alias(self) -> None:
        backend = mock.Mock()
        backend.enabled = True
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch(
                "core.api.cortex.get_provider_snapshot",
                return_value=_ollama_snapshot("qwen3:1.7b"),
            ),
            mock.patch("core.api.cortex.switch_local_model") as switch,
        ):
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("lynx")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("not configured", raised.exception.detail)
        switch.assert_not_called()
        end_execution.assert_called_once()

    def test_load_rejects_unreachable_provider_before_switch(self) -> None:
        backend = mock.Mock()
        backend.enabled = True
        unreachable = {
            "provider": "ollama",
            "reachable": False,
            "installed_models": [],
            "loaded_models": [],
            "sampled_at": 0.0,
        }
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution"),
            mock.patch("core.api.cortex.get_provider_snapshot", return_value=unreachable),
            mock.patch("core.api.cortex.switch_local_model") as switch,
        ):
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("lynx")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("unreachable", raised.exception.detail)
        switch.assert_not_called()

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
            mock.patch(
                "core.api.cortex.get_provider_snapshot",
                return_value=_ollama_snapshot("qwen3:1.7b"),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                load_local_model_endpoint("lynx")

        self.assertEqual(raised.exception.status_code, 503)

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

    def test_lynx_status_reports_missing_selected_alias(self) -> None:
        snapshot = {
            "provider": "llama_cpp",
            "reachable": True,
            "installed_models": ["apodemus-4k"],
            "loaded_models": [],
            "sampled_at": 0.0,
        }
        ollama_backend = mock.Mock()
        ollama_backend.provider = "ollama"
        ollama_backend.enabled = False
        llama_backend = mock.Mock()
        llama_backend.provider = "llama_cpp"
        llama_backend.enabled = True
        llama_backend.get_status_snapshot.return_value = snapshot

        settings = _lynx_settings_mock()

        with (
            mock.patch(
                "core.api.cortex.iter_local_runtime_backends",
                return_value=(llama_backend,),
            ),
            mock.patch(
                "core.api.cortex.get_local_runtime_backend",
                side_effect=lambda provider: (
                    llama_backend if provider == "llama_cpp" else ollama_backend
                ),
            ),
            mock.patch(
                "core.api.cortex.get_system_vitals",
                return_value={"cpu": 10.0, "ram": 10.0},
            ),
            mock.patch("core.api.cortex.get_active_local_model", return_value=None),
            mock.patch("core.api.cortex.get_loading_local_model", return_value=None),
            mock.patch(
                "core.api.cortex.get_idle_unload_remaining_seconds", return_value=None
            ),
            mock.patch("core.api.cortex.is_local_execution_active", return_value=False),
            mock.patch(
                "core.settings.get_settings_store",
                return_value=mock.Mock(get_snapshot=mock.Mock(return_value=settings)),
            ),
            mock.patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "test-key", "GEMINI_API_KEY": "test-key"},
            ),
        ):
            profiles = {profile.key: profile for profile in build_agent_statuses()}

        self.assertEqual(profiles["lynx"].status, "model_not_installed")
        self.assertIn("not installed or configured", profiles["lynx"].reason or "")

    def test_lynx_status_reports_router_load_failure(self) -> None:
        snapshot = {
            "provider": "llama_cpp",
            "reachable": True,
            "installed_models": ["gemma-4-e2b-16k"],
            "loaded_models": [
                {
                    "provider": "llama_cpp",
                    "name": "gemma-4-e2b-16k",
                    "model": "gemma-4-e2b-16k",
                    "state": "failed",
                    "context_window": None,
                    "size_bytes": None,
                    "size_vram_bytes": None,
                    "processor": None,
                    "context": None,
                    "expires_at": None,
                }
            ],
            "sampled_at": 0.0,
        }
        ollama_backend = mock.Mock()
        ollama_backend.provider = "ollama"
        ollama_backend.enabled = False
        llama_backend = mock.Mock()
        llama_backend.provider = "llama_cpp"
        llama_backend.enabled = True
        llama_backend.get_status_snapshot.return_value = snapshot

        settings = _lynx_settings_mock()

        with (
            mock.patch(
                "core.api.cortex.iter_local_runtime_backends",
                return_value=(llama_backend,),
            ),
            mock.patch(
                "core.api.cortex.get_local_runtime_backend",
                side_effect=lambda provider: (
                    llama_backend if provider == "llama_cpp" else ollama_backend
                ),
            ),
            mock.patch(
                "core.api.cortex.get_system_vitals",
                return_value={"cpu": 10.0, "ram": 10.0},
            ),
            mock.patch("core.api.cortex.get_active_local_model", return_value=None),
            mock.patch("core.api.cortex.get_loading_local_model", return_value=None),
            mock.patch(
                "core.api.cortex.get_idle_unload_remaining_seconds", return_value=None
            ),
            mock.patch("core.api.cortex.is_local_execution_active", return_value=False),
            mock.patch(
                "core.settings.get_settings_store",
                return_value=mock.Mock(get_snapshot=mock.Mock(return_value=settings)),
            ),
            mock.patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "test-key", "GEMINI_API_KEY": "test-key"},
            ),
        ):
            profiles = {profile.key: profile for profile in build_agent_statuses()}

        apodemus = profiles["lynx"]
        self.assertNotEqual(apodemus.status, "available")
        self.assertEqual(apodemus.status, "provider_error")
        self.assertFalse(apodemus.active)
        self.assertEqual(
            apodemus.reason,
            "llama.cpp reported that the selected model preset failed to load.",
        )
        self.assertIsNotNone(apodemus.loaded_model)
        assert apodemus.loaded_model is not None
        self.assertEqual(apodemus.loaded_model.state, "failed")

    def test_query_rejects_missing_local_alias_with_provider_label(self) -> None:
        from core.agent.types import AgentQueryRequest
        from core.api.cortex import query_agent

        backend = mock.Mock()
        backend.enabled = True
        settings = mock.Mock()
        settings = _lynx_settings_mock()
        settings.ask_apex.enabled = True
        settings.user_designation = ""
        missing = {
            "provider": "llama_cpp",
            "reachable": True,
            "installed_models": ["apodemus-4k"],
            "loaded_models": [],
            "sampled_at": 0.0,
        }
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution") as end_execution,
            mock.patch("core.api.cortex.get_provider_snapshot", return_value=missing),
            mock.patch("core.api.cortex.switch_local_model") as switch,
            mock.patch(
                "core.settings.get_settings_store",
                return_value=mock.Mock(get_snapshot=mock.Mock(return_value=settings)),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                query_agent(AgentQueryRequest(prompt="hello", agent="lynx"))

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("gemma-4-e2b-16k", raised.exception.detail)
        self.assertIn("llama.cpp", raised.exception.detail)
        self.assertNotIn("Ollama", raised.exception.detail)
        switch.assert_not_called()
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
            mock.patch("core.api.cortex.is_dev_mode", return_value=True),
            mock.patch("core.agent.catalog.is_dev_mode", return_value=True),
            mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key", "GEMINI_API_KEY": "test-key"}),
        ):
            profiles = {profile.key: profile for profile in build_agent_statuses()}

        self.assertFalse(profiles["lynx"].active)
        self.assertIsNone(profiles["lynx"].idle_unload_remaining_seconds)


if __name__ == "__main__":
    unittest.main()
