"""Cloud catalog, non-generative verification, and sanitized status coverage."""

from __future__ import annotations

import unittest
from threading import Event, Thread
from unittest import mock

import requests
from fastapi import HTTPException

from core.agent.providers.cloud_verification import (
    classify_provider_failure,
    clear_cloud_status_cache,
    cloud_status,
    record_cloud_request_failure,
    verify_cloud_agent,
)
from core.agent.model_catalog import get_model_profile
from core.api.cortex import verify_cloud_agent_endpoint
from core.settings.models import AgentSettings, CloudSettings


class _ProviderError(Exception):
    def __init__(self, status_code: int, code: str = "") -> None:
        self.status_code = status_code
        self.code = code


class CloudAgentVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cloud_status_cache()

    def tearDown(self) -> None:
        clear_cloud_status_cache()

    def test_non_generative_probe_is_cached_as_verified(self) -> None:
        with (
            mock.patch("core.agent.providers.cloud_verification.os.getenv", return_value="secret"),
            mock.patch("core.agent.providers.cloud_verification._probe_model", return_value=("verified", None)) as probe,
        ):
            result = verify_cloud_agent("gpt-5.6-luna")

        self.assertEqual(result.status, "verified")
        self.assertEqual(cloud_status("gpt-5.6-luna").status, "verified")
        probe.assert_called_once_with("openai", "gpt-5.6-luna", "secret")

    def test_explicit_verification_forces_a_fresh_probe(self) -> None:
        with (
            mock.patch("core.agent.providers.cloud_verification.os.getenv", return_value="secret"),
            mock.patch("core.agent.providers.cloud_verification._probe_model", return_value=("verified", None)) as probe,
        ):
            verify_cloud_agent("gpt-5.6-luna")
            verify_cloud_agent("gpt-5.6-luna")

        self.assertEqual(probe.call_count, 2)

    def test_explicit_verification_records_the_route_it_captured(self) -> None:
        with (
            mock.patch("core.agent.providers.cloud_verification.os.getenv", return_value="secret"),
            mock.patch(
                "core.agent.providers.cloud_verification._probe_model",
                return_value=("verified", None),
            ) as probe,
        ):
            result = verify_cloud_agent("gpt-5.6-luna")

        self.assertEqual(result.status, "verified")
        probe.assert_called_once_with("openai", "gpt-5.6-luna", "secret")
        self.assertEqual(cloud_status("gpt-5.6-luna").status, "verified")

    def test_concurrent_verification_is_rejected(self) -> None:
        probe_started = Event()
        release_probe = Event()
        first_result: list[object] = []

        def slow_probe(*_args: object) -> tuple[str, None]:
            probe_started.set()
            release_probe.wait(timeout=1)
            return "verified", None

        with (
            mock.patch("core.agent.providers.cloud_verification.os.getenv", return_value="secret"),
            mock.patch("core.agent.providers.cloud_verification._probe_model", side_effect=slow_probe),
        ):
            worker = Thread(target=lambda: first_result.append(verify_cloud_agent("gpt-5.6-luna")))
            worker.start()
            self.assertTrue(probe_started.wait(timeout=1))
            with self.assertRaises(RuntimeError):
                verify_cloud_agent("gpt-5.6-luna")
            release_probe.set()
            worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(first_result), 1)

    def test_probe_uses_a_bounded_metadata_request(self) -> None:
        response = mock.Mock(ok=True)
        with mock.patch("core.agent.providers.cloud_verification.requests.get", return_value=response) as get:
            from core.agent.providers.cloud_verification import _probe_model

            status, reason = _probe_model("openai", "gpt-5.6-luna", "secret")

        self.assertEqual((status, reason), ("verified", None))
        get.assert_called_once_with(
            "https://api.openai.com/v1/models/gpt-5.6-luna",
            headers={"Authorization": "Bearer secret"},
            timeout=5,
        )

    def test_openrouter_probe_requires_a_zdr_route_for_the_selected_model(self) -> None:
        response = mock.Mock(ok=True)
        response.json.return_value = {
            "data": [{"model_id": "deepseek/deepseek-v4-flash-0731"}]
        }
        with mock.patch("core.agent.providers.cloud_verification.requests.get", return_value=response) as get:
            from core.agent.providers.cloud_verification import _probe_model

            status, reason = _probe_model("openrouter", "deepseek/deepseek-v4-flash-0731", "secret")

        self.assertEqual((status, reason), ("verified", None))
        get.assert_called_once_with(
            "https://openrouter.ai/api/v1/endpoints/zdr",
            headers={"Authorization": "Bearer secret"},
            timeout=5,
        )

    def test_openrouter_probe_fails_closed_for_invalid_or_unavailable_zdr_responses(self) -> None:
        from core.agent.providers.cloud_verification import _probe_model

        cases = (
            ({"data": []}, "model_unavailable"),
            ({"unexpected": []}, "provider_error"),
        )
        for payload, expected_status in cases:
            with self.subTest(payload=payload):
                response = mock.Mock(ok=True)
                response.json.return_value = payload
                with mock.patch(
                    "core.agent.providers.cloud_verification.requests.get",
                    return_value=response,
                ):
                    status, _reason = _probe_model(
                        "openrouter", "deepseek/deepseek-v4-flash-0731", "secret"
                    )
                self.assertEqual(status, expected_status)

        for response, expected_status in (
            (mock.Mock(ok=False, status_code=401), "unauthorized"),
            (mock.Mock(ok=False, status_code=503), "provider_unreachable"),
        ):
            with self.subTest(status=response.status_code):
                with mock.patch(
                    "core.agent.providers.cloud_verification.requests.get",
                    return_value=response,
                ):
                    status, _reason = _probe_model(
                        "openrouter", "deepseek/deepseek-v4-flash-0731", "secret"
                    )
                self.assertEqual(status, expected_status)

        with mock.patch(
            "core.agent.providers.cloud_verification.requests.get",
            side_effect=requests.Timeout,
        ):
            status, _reason = _probe_model(
                "openrouter", "deepseek/deepseek-v4-flash-0731", "secret"
            )
        self.assertEqual(status, "provider_unreachable")

    def test_metadata_probe_does_not_clear_recent_account_failure(self) -> None:
        record_cloud_request_failure(
            "apex",
            _ProviderError(429, "insufficient_quota"),
            provider="openai",
            model="gpt-5.6-luna",
        )
        with (
            mock.patch("core.agent.providers.cloud_verification.os.getenv", return_value="secret"),
            mock.patch("core.agent.providers.cloud_verification._probe_model", return_value=("verified", None)),
        ):
            result = verify_cloud_agent("gpt-5.6-luna")

        self.assertEqual(result.status, "quota_exhausted")
        self.assertEqual(result.source, "request")

    def test_failure_classification_is_conservative_and_sanitized(self) -> None:
        self.assertEqual(classify_provider_failure(_ProviderError(401))[0], "unauthorized")
        self.assertEqual(classify_provider_failure(_ProviderError(429))[0], "rate_limited")
        self.assertEqual(classify_provider_failure(_ProviderError(429, "insufficient_quota"))[0], "quota_exhausted")
        self.assertEqual(classify_provider_failure(_ProviderError(400, "billing_required"))[0], "billing_blocked")
        self.assertEqual(classify_provider_failure(_ProviderError(404))[0], "model_unavailable")
        self.assertEqual(classify_provider_failure(_ProviderError(500))[0], "provider_unreachable")

        openai_profile = get_model_profile("gpt-5.6-luna")
        record_cloud_request_failure(
            "apex",
            _ProviderError(429, "insufficient_quota"),
            provider="openai",
            model="gpt-5.6-luna",
        )
        self.assertEqual(
            cloud_status("gpt-5.6-luna").reason,
            "Provider reported exhausted quota or credits.",
        )

    def test_endpoint_rejects_demo_and_local_agents_without_probe(self) -> None:
        with mock.patch("core.api.cortex.DEMO_MODE", True), mock.patch(
            "core.api.cortex.verify_cloud_agent"
        ) as verify:
            with self.assertRaises(HTTPException) as demo_error:
                verify_cloud_agent_endpoint("gpt-5.6-luna")
        self.assertEqual(demo_error.exception.status_code, 403)
        verify.assert_not_called()

        with mock.patch("core.api.cortex.DEMO_MODE", False), mock.patch(
            "core.api.cortex.is_dev_mode", return_value=True
        ), mock.patch(
            "core.agent.catalog.is_dev_mode", return_value=True
        ), mock.patch("core.api.cortex.verify_cloud_agent") as verify:
            with self.assertRaises(HTTPException) as local_error:
                verify_cloud_agent_endpoint("gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(local_error.exception.status_code, 400)
        verify.assert_not_called()

    def test_verification_requires_configured_credentials(self) -> None:
        with mock.patch("core.agent.providers.cloud_verification.os.getenv", return_value=None):
            with self.assertRaises(ValueError):
                verify_cloud_agent("gpt-5.6-luna")

    def test_verification_cache_is_scoped_to_provider_and_model(self) -> None:
        with (
            mock.patch("core.agent.providers.cloud_verification.os.getenv", return_value="secret"),
            mock.patch(
                "core.agent.providers.cloud_verification._probe_model",
                return_value=("verified", None),
            ),
        ):
            verify_cloud_agent("gpt-5.6-luna")
            self.assertEqual(cloud_status("gpt-5.6-luna").status, "verified")
            self.assertEqual(cloud_status("gemini-3.6-flash").status, "configured")

    def test_request_cache_records_the_route_that_actually_ran(self) -> None:
        from core.agent.providers.cloud_verification import record_cloud_request_success

        record_cloud_request_success(
            "apex",
            provider="openai",
            model="gpt-5.6-luna",
        )
        self.assertEqual(cloud_status("gpt-5.6-luna").status, "verified")
        self.assertEqual(cloud_status("gemini-3.6-flash").status, "configured")

    def test_endpoint_returns_sanitized_result(self) -> None:
        result = mock.Mock(status="verified", reason=None)
        result.checked_at = cloud_status("gpt-5.6-luna").checked_at
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.agent_has_credentials", return_value=True),
            mock.patch("core.api.cortex.verify_cloud_agent", return_value=result),
        ):
            response = verify_cloud_agent_endpoint("gpt-5.6-luna")
        self.assertEqual(response.status, "verified")
        self.assertIsNone(response.reason)
