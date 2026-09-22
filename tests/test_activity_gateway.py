"""Gateway-only coverage for external activity submission."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.activity import ActivityClientRegistration
from core.activity.cloudflare import CloudflareAccessConfiguration
from core.activity.gateway import GatewayConfigurationError, GatewayOptions, create_gateway_app
import core.activity.gateway as gateway


def _registration(
    *,
    client_id: str = "codex",
    enabled: bool = True,
    principal: str = "operator",
) -> ActivityClientRegistration:
    return ActivityClientRegistration(
        id=client_id,
        display_name=client_id.title(),
        enabled=enabled,
        allowed_principals=[principal],
        permissions=["activity:submit"],
        partition="production",
    )


def _report(key: str) -> dict[str, object]:
    return {
        "submission_key": key,
        "title": "Gateway report",
        "task_status": "completed",
        "outcome": "The focused checks passed.",
    }


class GatewayOptionsTests(unittest.TestCase):
    def test_gateway_rejects_non_loopback_and_cloudflare_requires_configuration(self) -> None:
        with self.assertRaisesRegex(GatewayConfigurationError, "loopback"):
            GatewayOptions(host="0.0.0.0").validate()
        with self.assertRaisesRegex(GatewayConfigurationError, "external_activity.cloudflare"):
            create_gateway_app(GatewayOptions(mode="cloudflare"))


class GatewayHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.directory.name) / "activity.db")
        self.loaded_registrations = (_registration(),)
        self.database_patch = mock.patch.object(gateway.database, "DB_NAME", self.db_path)
        self.registration_patch = mock.patch.object(
            gateway,
            "load_activity_client_registrations",
            side_effect=lambda **_kwargs: self.loaded_registrations,
        )
        self.database_patch.start()
        self.registration_patch.start()
        self.app = create_gateway_app(GatewayOptions())
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.headers = {
            "Host": "127.0.0.1:8001",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.registration_patch.stop()
        self.database_patch.stop()
        self.directory.cleanup()

    def test_json_submission_is_narrow_and_idempotent(self) -> None:
        first = self.client.post(
            "/v1/activity/reports",
            headers=self.headers,
            json={"client_id": "codex", "report": _report("json-key")},
        )
        retry = self.client.post(
            "/v1/activity/reports",
            headers=self.headers,
            json={"client_id": "codex", "report": _report("json-key")},
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(set(first.json()), {"id", "received_at", "duplicate"})
        self.assertFalse(first.json()["duplicate"])
        self.assertTrue(retry.json()["duplicate"])
        self.assertEqual(first.json()["id"], retry.json()["id"])
        self.assertEqual(self.client.get("/api/v1/activity/reports").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/cortex/agent").status_code, 404)

    def test_custom_loopback_binding_accepts_only_its_configured_host(self) -> None:
        options = GatewayOptions(host="127.0.0.2", port=8123)
        custom = create_gateway_app(options)
        headers = {"Host": "127.0.0.2:8123", "Content-Type": "application/json"}
        with TestClient(custom) as client:
            accepted = client.post(
                "/v1/activity/reports",
                headers=headers,
                json={"client_id": "codex", "report": _report("custom-host")},
            )
            rejected = client.post(
                "/v1/activity/reports",
                headers={**headers, "Host": "127.0.0.1:8123"},
                json={"client_id": "codex", "report": _report("wrong-host")},
            )
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(rejected.status_code, 421)

    def test_json_boundary_rejects_host_origin_content_and_oversized_bodies(self) -> None:
        payload = {"client_id": "codex", "report": _report("blocked")}
        self.assertEqual(self.client.post("/v1/activity/reports", json=payload).status_code, 421)
        mcp_payload = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        }
        self.assertEqual(
            self.client.post("/mcp/", headers={"Host": "outside.example", "Content-Type": "application/json"}, json=mcp_payload).status_code,
            421,
        )
        self.assertEqual(
            self.client.post("/mcp/", headers={**self.headers, "Origin": "http://127.0.0.1:5500"}, json=mcp_payload).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/v1/activity/reports",
                headers={**self.headers, "Origin": "http://127.0.0.1:5500"},
                json=payload,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/v1/activity/reports",
                headers={"Host": "127.0.0.1:8001", "Content-Type": "text/plain"},
                content=b"not-json",
            ).status_code,
            415,
        )
        self.assertEqual(
            self.client.post(
                "/v1/activity/reports",
                headers=self.headers,
                content=b"x" * (256 * 1024 + 1),
            ).status_code,
            413,
        )

    def test_json_and_mcp_share_the_fixed_window_limit(self) -> None:
        for index in range(30):
            response = self.client.post(
                "/v1/activity/reports",
                headers=self.headers,
                json={"client_id": "codex", "report": _report(f"rate-{index}")},
            )
            self.assertEqual(response.status_code, 201)

        initialized = self._mcp_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        })
        session_id = initialized.headers["mcp-session-id"]
        self._mcp_request({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, session_id=session_id)
        limited = self._mcp_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "submit_activity", "arguments": {"client_id": "codex", "report": _report("rate-mcp")}},
        }, session_id=session_id)
        result = limited.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("rate limit", result["content"][0]["text"].lower())
        self.assertEqual(len(self.app.state.activity_service.list(partition="production")), 30)

    def _mcp_request(self, payload: dict[str, object], *, session_id: str | None = None):
        headers = self.headers if session_id is None else {**self.headers, "mcp-session-id": session_id}
        return self.client.post("/mcp/", headers=headers, json=payload)

    def test_mcp_exposes_only_submission_and_uses_same_receipts(self) -> None:
        initialized = self._mcp_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        })
        self.assertEqual(initialized.status_code, 200)
        session_id = initialized.headers["mcp-session-id"]
        self.assertEqual(
            self._mcp_request({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, session_id=session_id).status_code,
            202,
        )
        tools = self._mcp_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session_id=session_id)
        self.assertEqual([tool["name"] for tool in tools.json()["result"]["tools"]], ["submit_activity"])

        submitted = self._mcp_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "submit_activity", "arguments": {"client_id": "codex", "report": _report("mcp-key")}},
        }, session_id=session_id)
        self.assertEqual(submitted.status_code, 200)
        self.assertFalse(submitted.json()["result"]["isError"])
        reports = self.app.state.activity_service.list(partition="production")
        self.assertEqual([report.content.submission_key for report in reports], ["mcp-key"])

        self.loaded_registrations = (_registration(enabled=False),)
        disabled = self._mcp_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "submit_activity", "arguments": {"client_id": "codex", "report": _report("disabled-key")}},
        }, session_id=session_id)
        self.assertTrue(disabled.json()["result"]["isError"])
        self.loaded_registrations = ()
        removed = self._mcp_request({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "submit_activity", "arguments": {"client_id": "codex", "report": _report("removed-key")}},
        }, session_id=session_id)
        self.assertTrue(removed.json()["result"]["isError"])
        self.assertEqual(len(self.app.state.activity_service.list(partition="production")), 1)


if __name__ == "__main__":
    unittest.main()
