"""Cloudflare Access verification and gateway binding coverage."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from core import config
from core.activity import ActivityClientRegistration
from core.activity.cloudflare import (
    CloudflareAccessAuthorizationError,
    CloudflareAccessConfiguration,
    CloudflareAccessVerificationError,
    CloudflareAccessVerifier,
)
from core.activity.gateway import GatewayOptions, create_gateway_app
import core.activity.gateway as gateway


ISSUER = "https://apex.cloudflareaccess.com"
JWKS_URL = f"{ISSUER}/cdn-cgi/access/certs"


def _configuration() -> CloudflareAccessConfiguration:
    return CloudflareAccessConfiguration.model_validate({
        "issuer": ISSUER,
        "jwks_url": JWKS_URL,
        "key_cache_seconds": 60,
        "bindings": [
            {"client_id": "spark", "audience": "spark-audience", "allowed_subjects": ["operator-subject"]},
            {"client_id": "codex", "audience": "codex-audience", "allowed_subjects": ["operator-subject"]},
        ],
    })


def _registration(client_id: str, *, enabled: bool = True) -> ActivityClientRegistration:
    return ActivityClientRegistration(
        id=client_id,
        display_name=client_id.title(),
        enabled=enabled,
        allowed_principals=[f"client:{client_id}"],
        permissions=["activity:submit"],
        partition="production",
    )


def _report(key: str) -> dict[str, object]:
    return {
        "submission_key": key,
        "title": "Cloudflare report",
        "task_status": "completed",
        "outcome": "The assertion was accepted at the gateway boundary.",
    }


class _ClaimsVerifier:
    def verify(self, assertion: str):
        if not assertion:
            raise CloudflareAccessVerificationError("missing assertion")
        return {
            "sub": "operator-subject",
            "aud": {
                "spark": "spark-audience",
                "codex": "codex-audience",
            }.get(assertion, "unknown-audience"),
        }


class CloudflareVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.now = int(time.time())
        self.jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        self.jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
        self.configuration = _configuration()

    def _assertion(self, **overrides: object) -> str:
        claims = {
            "iss": ISSUER,
            "aud": "spark-audience",
            "sub": "operator-subject",
            "exp": self.now + 300,
            **overrides,
        }
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "test-key"})

    def test_verifies_signature_issuer_expiry_and_bounded_key_cache(self) -> None:
        calls = 0

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"keys": [self_jwk]}

        self_jwk = self.jwk

        def get(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return Response()

        verifier = CloudflareAccessVerifier(self.configuration, get=get)
        claims = verifier.verify(self._assertion())
        self.assertEqual(claims["sub"], "operator-subject")
        verifier.verify(self._assertion())
        self.assertEqual(calls, 1)

        for assertion in (
            self._assertion(iss="https://other.cloudflareaccess.com"),
            self._assertion(exp=self.now - 1),
            jwt.encode(
                {"iss": ISSUER, "aud": "spark-audience", "sub": "operator-subject", "exp": self.now + 300},
                rsa.generate_private_key(public_exponent=65537, key_size=2048),
                algorithm="RS256",
                headers={"kid": "test-key"},
            ),
        ):
            with self.assertRaises(CloudflareAccessVerificationError):
                verifier.verify(assertion)

    def test_rejects_ambiguous_audience_bindings(self) -> None:
        with self.assertRaisesRegex(CloudflareAccessAuthorizationError, "one permitted registration"):
            self.configuration.resolve_binding({
                "sub": "operator-subject",
                "aud": ["spark-audience", "codex-audience"],
            })

    def test_fails_closed_when_an_expired_key_cache_cannot_refresh(self) -> None:
        clock = [0.0]

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"keys": [self_jwk]}

        self_jwk = self.jwk
        calls = 0

        def get(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return Response()
            raise requests.ConnectionError("offline")

        verifier = CloudflareAccessVerifier(self.configuration, now=lambda: clock[0], get=get)
        verifier.verify(self._assertion())
        clock[0] = 61.0
        with self.assertRaises(CloudflareAccessVerificationError):
            verifier.verify(self._assertion())
        with self.assertRaises(CloudflareAccessVerificationError):
            verifier.verify(self._assertion())
        self.assertEqual(calls, 2)
        clock[0] = 92.0
        with self.assertRaises(CloudflareAccessVerificationError):
            verifier.verify(self._assertion())
        self.assertEqual(calls, 3)

    def test_unknown_signing_key_refreshes_only_once_per_cache_interval(self) -> None:
        calls = 0

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"keys": [self_jwk]}

        self_jwk = self.jwk

        def get(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return Response()

        verifier = CloudflareAccessVerifier(self.configuration, get=get)
        verifier.verify(self._assertion())
        unknown_key_assertion = jwt.encode(
            {"iss": ISSUER, "aud": "spark-audience", "sub": "operator-subject", "exp": self.now + 300},
            self.private_key,
            algorithm="RS256",
            headers={"kid": "unknown-key"},
        )
        for _ in range(3):
            with self.assertRaises(CloudflareAccessVerificationError):
                verifier.verify(unknown_key_assertion)
        self.assertEqual(calls, 2)

    def test_unknown_signing_key_does_not_retry_a_failed_forced_refresh(self) -> None:
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"keys": [self_jwk]}

        self_jwk = self.jwk
        calls = 0

        def get(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return Response()
            raise requests.ConnectionError("offline")

        verifier = CloudflareAccessVerifier(self.configuration, get=get)
        verifier.verify(self._assertion())
        unknown_key_assertion = jwt.encode(
            {"iss": ISSUER, "aud": "spark-audience", "sub": "operator-subject", "exp": self.now + 300},
            self.private_key,
            algorithm="RS256",
            headers={"kid": "unknown-key"},
        )
        for _ in range(3):
            with self.assertRaises(CloudflareAccessVerificationError):
                verifier.verify(unknown_key_assertion)
        self.assertEqual(calls, 2)


class CloudflareConfigurationTests(unittest.TestCase):
    def test_loads_only_a_valid_optional_gateway_configuration(self) -> None:
        with mock.patch.object(config, "_CONFIG_DATA", {
            "external_activity": {
                "cloudflare": _configuration().model_dump(),
            },
        }):
            loaded = config.load_cloudflare_access_configuration()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.bindings[0].principal, "client:spark")

        with mock.patch.object(config, "_CONFIG_DATA", {"external_activity": {"cloudflare": {}}}):
            self.assertIsNone(config.load_cloudflare_access_configuration())


class CloudflareGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.directory.name) / "activity.db")
        self.loaded_registrations = (_registration("spark"), _registration("codex"))
        self.database_patch = mock.patch.object(gateway.database, "DB_NAME", self.db_path)
        self.registration_patch = mock.patch.object(
            gateway,
            "load_activity_client_registrations",
            side_effect=lambda **_kwargs: self.loaded_registrations,
        )
        self.database_patch.start()
        self.registration_patch.start()
        self.app = create_gateway_app(
            GatewayOptions(mode="cloudflare"),
            cloudflare=_configuration(),
            verifier=_ClaimsVerifier(),
        )
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Cf-Access-Jwt-Assertion": "spark",
        }

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.registration_patch.stop()
        self.database_patch.stop()
        self.directory.cleanup()

    def test_remote_binding_derives_client_and_rechecks_enabled_registration(self) -> None:
        with mock.patch.object(gateway.ConversationService, "partition", return_value="sandbox"):
            accepted = self.client.post(
                "/v1/activity/reports",
                headers=self.headers,
                json={"client_id": "spark", "report": _report("spark-key")},
            )
        self.assertEqual(accepted.status_code, 201)
        report = self.app.state.activity_service.list(partition="production")[0]
        self.assertEqual((report.client_id, report.principal), ("spark", "client:spark"))
        self.assertNotIn("operator-subject", str(report))
        self.assertNotIn("cloudflare", report.principal)

        mismatched = self.client.post(
            "/v1/activity/reports",
            headers=self.headers,
            json={"client_id": "codex", "report": _report("mismatched-key")},
        )
        self.assertEqual(mismatched.status_code, 403)
        missing = self.client.post(
            "/v1/activity/reports",
            headers={"Content-Type": "application/json"},
            json={"client_id": "spark", "report": _report("missing-key")},
        )
        self.assertEqual(missing.status_code, 401)
        wrong_audience = self.client.post(
            "/v1/activity/reports",
            headers={**self.headers, "Cf-Access-Jwt-Assertion": "wrong"},
            json={"client_id": "spark", "report": _report("wrong-audience-key")},
        )
        self.assertEqual(wrong_audience.status_code, 401)

        self.loaded_registrations = (_registration("spark", enabled=False), _registration("codex"))
        disabled = self.client.post(
            "/v1/activity/reports",
            headers=self.headers,
            json={"client_id": "spark", "report": _report("disabled-key")},
        )
        self.assertEqual(disabled.status_code, 403)
        separate = self.client.post(
            "/v1/activity/reports",
            headers={**self.headers, "Cf-Access-Jwt-Assertion": "codex"},
            json={"client_id": "codex", "report": _report("codex-key")},
        )
        self.assertEqual(separate.status_code, 201)

    def test_cloudflare_mcp_checks_the_assertion_for_each_tool_call(self) -> None:
        initialized = self.client.post("/mcp/", headers=self.headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        })
        self.assertEqual(initialized.status_code, 200)
        session_id = initialized.headers["mcp-session-id"]
        tool_headers = {**self.headers, "mcp-session-id": session_id}
        self.client.post("/mcp/", headers=tool_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        submitted = self.client.post("/mcp/", headers=tool_headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "submit_activity", "arguments": {"client_id": "spark", "report": _report("mcp-key")}},
        })
        self.assertFalse(submitted.json()["result"]["isError"])
        rejected = self.client.post("/mcp/", headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id}, json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "submit_activity", "arguments": {"client_id": "spark", "report": _report("missing-mcp-key")}},
        })
        self.assertTrue(rejected.json()["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
