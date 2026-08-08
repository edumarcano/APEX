"""Mock-HTTP coverage for the llama.cpp local-runtime backend."""

from __future__ import annotations

import json
import os
import threading
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import requests

from core.agent.catalog import agent_key_for_local_model_ref
from core.agent.local_runtime.contract import LocalModelRef
from core.agent.providers import llama_cpp_lifecycle as lifecycle
from core.agent.providers.llama_cpp_lifecycle import (
    LlamaCppRuntimeBackend,
    get_auth_headers,
)
from core.agent.providers.llama_cpp_models import build_llama_cpp_profile

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llama_cpp"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _apodemus_profile(*, context_window: int = 16384):
    return build_llama_cpp_profile(
        "apodemus",
        display_name="Apex Apodemus",
        agent_version="1.0",
        api_model="gemma-4-E2B-Q4_K_M.gguf",
        tier="balanced",
        stability="stable",
        max_tool_turns=3,
        max_tool_calls=4,
        system_instruction="test",
        context_window=context_window,
    )


class LlamaCppAuthHeaderTests(unittest.TestCase):
    def test_auth_header_absent_without_api_key(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLAMA_CPP_API_KEY", None)
            self.assertEqual(get_auth_headers(), {})

    def test_auth_header_present_when_api_key_set(self) -> None:
        with mock.patch.dict(
            os.environ, {"LLAMA_CPP_API_KEY": " test-key-value "}, clear=False
        ):
            self.assertEqual(
                get_auth_headers(),
                {"Authorization": "Bearer test-key-value"},
            )


class LlamaCppLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = LlamaCppRuntimeBackend()
        self.backend.invalidate_status_snapshot()
        self._enabled_patch = mock.patch.object(
            lifecycle, "is_llama_cpp_enabled", return_value=False
        )
        self._enabled_patch.start()
        self.addCleanup(self._enabled_patch.stop)
        self._runtime_settings_patch = mock.patch.object(
            lifecycle,
            "get_llama_cpp_runtime_settings",
            return_value=mock.Mock(managed=False),
        )
        self._runtime_settings_patch.start()
        self.addCleanup(self._runtime_settings_patch.stop)
        self._poll_patch = mock.patch.object(
            lifecycle, "_POLL_INTERVAL_SECONDS", 0.01
        )
        self._poll_patch.start()
        self.addCleanup(self._poll_patch.stop)

    def _session_get_models(
        self,
        payload: dict | list | None = None,
        *,
        side_effect: Exception | None = None,
    ) -> MagicMock:
        session = MagicMock()
        if side_effect is not None:
            session.get.side_effect = side_effect
            return session
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload if payload is not None else _load_fixture(
            "model_list.json"
        )
        session.get.return_value = response
        return session

    def test_models_list_parses_object_status_and_context_args(self) -> None:
        session = self._session_get_models()
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)

        self.assertTrue(snapshot["reachable"])
        self.assertEqual(
            snapshot["installed_models"],
            ["apodemus-132k", "apodemus-4k", "apodemus-16k", "apodemus-32k"],
        )
        states = {row["model"]: row["state"] for row in snapshot["loaded_models"]}
        self.assertEqual(states["apodemus-132k"], "loaded")
        self.assertEqual(states["apodemus-16k"], "sleeping")
        self.assertEqual(states["apodemus-32k"], "loading")
        self.assertNotIn("apodemus-4k", states)

        windows = {
            row["model"]: row["context_window"] for row in snapshot["loaded_models"]
        }
        self.assertEqual(windows["apodemus-132k"], 131072)
        self.assertEqual(windows["apodemus-16k"], 16384)
        self.assertEqual(windows["apodemus-32k"], 32768)

        _args, kwargs = session.get.call_args
        self.assertTrue(str(_args[0]).endswith("/models"))
        self.assertIn("headers", kwargs)

    def test_flat_string_status_remains_supported(self) -> None:
        payload = {
            "data": [
                {
                    "id": "apodemus-132k",
                    "status": "loaded",
                    "n_ctx": 131072,
                }
            ]
        }
        session = self._session_get_models(payload)
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)
        self.assertEqual(
            [row["state"] for row in snapshot["loaded_models"]],
            ["loaded"],
        )
        self.assertEqual(snapshot["loaded_models"][0]["context_window"], 131072)

    def test_failed_status_object_with_unloaded_value(self) -> None:
        payload = {
            "data": [
                {
                    "id": "apodemus-132k",
                    "status": {
                        "value": "unloaded",
                        "failed": True,
                        "exit_code": 1,
                        "args": [],
                    },
                }
            ]
        }
        session = self._session_get_models(payload)
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)
            self.assertEqual(snapshot["loaded_models"][0]["state"], "failed")
            self.assertFalse(self.backend.is_model_resident("apodemus-132k"))

    def test_missing_alias_is_not_fabricated_as_installed(self) -> None:
        payload = {
            "data": [
                {
                    "id": "apodemus-4k",
                    "status": {"value": "unloaded", "args": []},
                }
            ]
        }
        session = self._session_get_models(payload)
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)

        self.assertEqual(snapshot["installed_models"], ["apodemus-4k"])
        self.assertNotIn("apodemus-132k", snapshot["installed_models"])
        self.assertNotIn("apodemus-16k", snapshot["installed_models"])
        self.assertNotIn("apodemus-32k", snapshot["installed_models"])

    def test_unloaded_configured_alias_still_appears_installed(self) -> None:
        payload = {
            "data": [
                {
                    "id": "apodemus-132k",
                    "status": {"value": "unloaded", "args": []},
                }
            ]
        }
        session = self._session_get_models(payload)
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)
        self.assertIn("apodemus-132k", snapshot["installed_models"])
        self.assertEqual(snapshot["loaded_models"], [])

    def test_unknown_external_alias_is_not_an_apex_agent(self) -> None:
        payload = {
            "data": [
                {
                    "id": "other-gguf-alias",
                    "status": {"value": "loaded", "args": ["-ctx", "2048"]},
                }
            ]
        }
        session = self._session_get_models(payload)
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)
        self.assertEqual(snapshot["installed_models"], ["other-gguf-alias"])
        self.assertIsNone(
            agent_key_for_local_model_ref(
                LocalModelRef(provider="llama_cpp", model="other-gguf-alias")
            )
        )

    def test_malformed_models_payload_fails_closed(self) -> None:
        for payload in ({}, {"unexpected": []}, {"data": "not-a-list"}):
            with self.subTest(payload=payload):
                session = self._session_get_models(payload)
                with mock.patch.object(lifecycle, "_SESSION", session), self.assertLogs(
                    "core.agent.providers.llama_cpp_lifecycle", level="WARNING"
                ) as logs:
                    snapshot = self.backend.get_status_snapshot(force_refresh=True)
                self.assertFalse(snapshot["reachable"])
                self.assertEqual(snapshot["installed_models"], [])
                self.assertEqual(snapshot["loaded_models"], [])
                self.assertIn("missing recognized model array", "\n".join(logs.output))

    def test_empty_data_array_is_reachable_with_no_models(self) -> None:
        session = self._session_get_models({"object": "list", "data": []})
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)
        self.assertTrue(snapshot["reachable"])
        self.assertEqual(snapshot["installed_models"], [])
        self.assertEqual(snapshot["loaded_models"], [])

    def test_sleeping_model_is_not_resident(self) -> None:
        payload = {
            "data": [
                {
                    "id": "apodemus-132k",
                    "status": {"value": "sleeping", "args": ["-ctx", "131072"]},
                }
            ]
        }
        session = self._session_get_models(payload)
        with mock.patch.object(lifecycle, "_SESSION", session):
            self.assertFalse(self.backend.is_model_resident("apodemus-132k"))

    def test_unreachable_router(self) -> None:
        session = self._session_get_models(
            side_effect=requests.ConnectionError("refused")
        )
        with mock.patch.object(lifecycle, "_SESSION", session):
            snapshot = self.backend.get_status_snapshot(force_refresh=True)
        self.assertFalse(snapshot["reachable"])
        self.assertEqual(snapshot["loaded_models"], [])

    def test_auth_header_forwarded_only_when_configured(self) -> None:
        session = self._session_get_models()
        with mock.patch.object(lifecycle, "_SESSION", session), mock.patch.dict(
            os.environ, {"LLAMA_CPP_API_KEY": "router-secret"}, clear=False
        ):
            self.backend.get_status_snapshot(force_refresh=True)
        headers = session.get.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Authorization"), "Bearer router-secret")

        session_no_auth = self._session_get_models()
        with mock.patch.object(lifecycle, "_SESSION", session_no_auth), mock.patch.dict(
            os.environ, {}, clear=False
        ):
            os.environ.pop("LLAMA_CPP_API_KEY", None)
            self.backend.invalidate_status_snapshot()
            self.backend.get_status_snapshot(force_refresh=True)
        self.assertEqual(session_no_auth.get.call_args.kwargs["headers"], {})

    def test_load_model_posts_and_verifies_residency(self) -> None:
        get_payloads = [
            {
                "data": [
                    {"id": "apodemus-16k", "status": {"value": "unloaded", "args": []}}
                ]
            },
            {
                "data": [
                    {
                        "id": "apodemus-16k",
                        "status": {
                            "value": "loaded",
                            "args": ["llama-server", "-ctx", "16384"],
                        },
                    }
                ]
            },
            {
                "data": [
                    {
                        "id": "apodemus-16k",
                        "status": {
                            "value": "loaded",
                            "args": ["llama-server", "-ctx", "16384"],
                        },
                    }
                ]
            },
        ]
        get_calls = {"n": 0}

        def fake_get(*_args, **_kwargs):
            response = MagicMock()
            response.raise_for_status.return_value = None
            idx = min(get_calls["n"], len(get_payloads) - 1)
            response.json.return_value = get_payloads[idx]
            get_calls["n"] += 1
            return response

        session = MagicMock()
        session.get.side_effect = fake_get
        post_response = MagicMock()
        post_response.raise_for_status.return_value = None
        session.post.return_value = post_response

        mock_sup = MagicMock()
        with mock.patch.object(lifecycle, "_SESSION", session), mock.patch.object(
            lifecycle, "_probe_props", return_value={"default_model": "apodemus-16k"}
        ), mock.patch(
            "core.agent.providers.llama_cpp_supervisor.get_llama_cpp_server_supervisor",
            return_value=mock_sup,
        ):
            self.assertTrue(self.backend.load_model(_apodemus_profile()))

        self.assertTrue(
            any(
                str(call.args[0]).endswith("/models/load")
                for call in session.post.call_args_list
            )
        )
        load_json = next(
            call.kwargs["json"]
            for call in session.post.call_args_list
            if str(call.args[0]).endswith("/models/load")
        )
        self.assertEqual(load_json, {"model": "apodemus-16k"})

    def test_unload_model_posts_and_accepts_sleeping(self) -> None:
        get_payloads = [
            {
                "data": [
                    {
                        "id": "apodemus-16k",
                        "status": {
                            "value": "loaded",
                            "args": ["llama-server", "-ctx", "16384"],
                        },
                    }
                ]
            },
            {
                "data": [
                    {
                        "id": "apodemus-16k",
                        "status": {
                            "value": "sleeping",
                            "args": ["llama-server", "-ctx", "16384"],
                        },
                    }
                ]
            },
        ]
        get_calls = {"n": 0}

        def fake_get(*_args, **_kwargs):
            response = MagicMock()
            response.raise_for_status.return_value = None
            idx = min(get_calls["n"], len(get_payloads) - 1)
            response.json.return_value = get_payloads[idx]
            get_calls["n"] += 1
            return response

        session = MagicMock()
        session.get.side_effect = fake_get
        post_response = MagicMock()
        post_response.raise_for_status.return_value = None
        session.post.return_value = post_response

        with mock.patch.object(lifecycle, "_SESSION", session):
            self.assertTrue(self.backend.unload_model("apodemus-16k"))

        unload_json = next(
            call.kwargs["json"]
            for call in session.post.call_args_list
            if str(call.args[0]).endswith("/models/unload")
        )
        self.assertEqual(unload_json, {"model": "apodemus-16k"})

    def test_props_probe_uses_autoload_false(self) -> None:
        session = MagicMock()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"default_generation_settings": {}}
        session.get.return_value = response
        with mock.patch.object(lifecycle, "_SESSION", session):
            props = lifecycle._probe_props("apodemus-16k")
        self.assertIsNotNone(props)
        self.assertEqual(
            session.get.call_args.kwargs["params"],
            {"model": "apodemus-16k", "autoload": "false"},
        )

    def test_cache_invalidation_epoch_drops_stale_probe(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        probe_calls = 0

        def probe_models() -> tuple[bool, list[str], list]:
            nonlocal probe_calls
            probe_calls += 1
            if probe_calls == 1:
                entered.set()
                self.assertTrue(release.wait(timeout=2.0))
                return True, ["stale-alias"], []
            return True, ["fresh-alias"], []

        def run_probe() -> None:
            with mock.patch.object(lifecycle, "_probe_models", side_effect=probe_models):
                self.backend.get_status_snapshot(force_refresh=True)

        worker = threading.Thread(target=run_probe)
        worker.start()
        self.assertTrue(entered.wait(timeout=2.0))
        self.backend.invalidate_status_snapshot()
        release.set()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive())

        with self.backend._status_lock:
            cached = self.backend._status_snapshot
        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached["installed_models"], ["fresh-alias"])
        self.assertNotIn("stale-alias", cached["installed_models"])
        self.assertGreaterEqual(probe_calls, 2)

    def test_errors_do_not_embed_filesystem_paths(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.RequestException(
            "failed reading C:\\Users\\eduma\\secret\\model.gguf"
        )
        with mock.patch.object(lifecycle, "_SESSION", session), self.assertLogs(
            "core.agent.providers.llama_cpp_lifecycle", level="WARNING"
        ) as logs:
            snapshot = self.backend.get_status_snapshot(force_refresh=True)
        self.assertFalse(snapshot["reachable"])
        joined = "\n".join(logs.output)
        self.assertNotIn("C:\\Users\\eduma", joined)
        self.assertNotIn("model.gguf", joined)
        self.assertIn("RequestException", joined)


if __name__ == "__main__":
    unittest.main()
