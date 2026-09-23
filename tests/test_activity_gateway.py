"""Gateway-only coverage for external activity submission."""

from __future__ import annotations

import asyncio
import json
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.requests import Request

from core.activity import ActivityReportContent, ActivityService, ActivityStore
from core.activity.gateway import GatewayConfigurationError, GatewayOptions, create_gateway_app
from core.settings.store import RuntimeSettingsStore
import core.activity.gateway as gateway


def _report(key: str) -> dict[str, object]:
    return {
        "submission_key": key,
        "title": "Gateway report",
        "task_status": "completed",
        "outcome": "The focused checks passed.",
    }


def _gateway_request(payload: dict[str, object]) -> Request:
    body = json.dumps(payload).encode("utf-8")
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http", "http_version": "1.1", "method": "POST",
            "scheme": "http", "path": "/v1/activity/reports",
            "raw_path": b"/v1/activity/reports", "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:8001"), (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8001),
        },
        receive,
    )


class GatewayOptionsTests(unittest.TestCase):
    def test_gateway_rejects_non_loopback(self) -> None:
        with self.assertRaisesRegex(GatewayConfigurationError, "loopback"):
            GatewayOptions(host="0.0.0.0").validate()


class GatewayPartitionTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        prefix = f".gateway-settings-test-{uuid4().hex}"
        self.config_path = root / f"{prefix}.json"
        self.local_config_path = root / f"{prefix}.local.json"
        self.addCleanup(self.config_path.unlink, missing_ok=True)
        self.addCleanup(self.local_config_path.unlink, missing_ok=True)
        self.store = ActivityStore(None)
        self.store.initialize()
        self.addCleanup(self.store.close)
        self.activity_service = ActivityService(self.store)
        self.service = gateway.GatewaySubmissionService(self.activity_service)

        def fresh_settings_store(*, force_new: bool = False):
            self.assertTrue(force_new, "gateway must not reuse its cached settings snapshot")
            return RuntimeSettingsStore(
                config_path=self.config_path,
                local_config_path=self.local_config_path,
            )

        self.settings_store_factory = fresh_settings_store

    def _write_persisted_settings(self, *, base_sandbox: bool, local_sandbox: bool) -> None:
        self.config_path.write_text(
            json.dumps({"ask_apex": {"sandbox_mode": base_sandbox}}),
            encoding="utf-8",
        )
        self.local_config_path.write_text(
            json.dumps({"ask_apex": {"sandbox_mode": local_sandbox}}),
            encoding="utf-8",
        )

    def _submit(self, key: str) -> None:
        self.service.submit(
            client_id="codex",
            report=ActivityReportContent.model_validate(_report(key)),
        )

    def test_submissions_follow_persisted_sandbox_switches(self) -> None:
        # The local layer takes precedence over tracked config.json, as it does
        # for settings changes written by the API.
        self._write_persisted_settings(base_sandbox=True, local_sandbox=False)
        with mock.patch.object(gateway, "is_dev_mode", return_value=True), mock.patch.object(
            gateway, "get_settings_store", side_effect=self.settings_store_factory,
        ):
            self._submit("before-sandbox")
            self._write_persisted_settings(base_sandbox=False, local_sandbox=True)
            self._submit("in-sandbox")
            self._write_persisted_settings(base_sandbox=True, local_sandbox=False)
            self._submit("after-sandbox")

        self.assertCountEqual(
            [item.content.submission_key for item in self.activity_service.list(partition="production")],
            ["before-sandbox", "after-sandbox"],
        )
        self.assertCountEqual(
            [item.content.submission_key for item in self.activity_service.list(partition="sandbox")],
            ["in-sandbox"],
        )

    def test_disabled_dev_mode_stays_in_production_without_reading_settings(self) -> None:
        self._write_persisted_settings(base_sandbox=True, local_sandbox=True)
        with mock.patch.object(gateway, "is_dev_mode", return_value=False), mock.patch.object(
            gateway, "get_settings_store",
        ) as settings_store:
            self._submit("dev-mode-disabled")

        settings_store.assert_not_called()
        self.assertEqual(len(self.activity_service.list(partition="production")), 1)
        self.assertEqual(self.activity_service.list(partition="sandbox"), [])


class GatewayHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.directory.name) / "activity.db")
        self.database_patch = mock.patch.object(gateway.database, "DB_NAME", self.db_path)
        self.database_patch.start()
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
        self.assertEqual(self.client.get("/api/v1/activity/mailbox/status").status_code, 404)
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
                json={"client_id": f"source-{index}", "report": _report(f"rate-{index}")},
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
            "params": {"name": "submit_activity", "arguments": {"client_id": "different-source", "report": _report("rate-mcp")}},
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

        invalid_id = self._mcp_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "submit_activity", "arguments": {"client_id": "Bad ID", "report": _report("invalid-key")}},
        }, session_id=session_id)
        self.assertTrue(invalid_id.json()["result"]["isError"])
        self.assertEqual(len(self.app.state.activity_service.list(partition="production")), 1)


class GatewayAsyncSubmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = create_gateway_app(GatewayOptions())
        self.endpoint = next(
            route.endpoint for route in self.app.routes
            if getattr(route, "path", None) == "/v1/activity/reports"
        )

    async def test_json_submission_keeps_event_loop_responsive_during_storage(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def blocking_submit(*, client_id: str, report) -> dict[str, object]:
            entered.set()
            release.wait(3)
            finished.set()
            return {"id": "report-id", "received_at": "2026-09-23T00:00:00+00:00", "duplicate": False}

        request = _gateway_request({"client_id": "codex", "report": _report("async-gateway")})
        with mock.patch.object(self.app.state.submission_service, "submit", side_effect=blocking_submit):
            submission = asyncio.create_task(self.endpoint(request))
            self.assertTrue(await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), timeout=4))
            loop_progress = asyncio.Event()
            asyncio.get_running_loop().call_soon(loop_progress.set)
            try:
                await asyncio.wait_for(loop_progress.wait(), timeout=1)
                self.assertFalse(finished.is_set(), "storage completed before the event loop could progress")
            finally:
                release.set()
            response = await submission

        self.assertEqual(response.status_code, 201)
        self.assertFalse(json.loads(response.body)["duplicate"])


if __name__ == "__main__":
    unittest.main()
