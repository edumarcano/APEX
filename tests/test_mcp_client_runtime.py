"""Regression tests for the MCP client runtime lifecycle."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from core.agent.capabilities import (
    clear_capability_registry_for_tests,
    get_capability_descriptor,
    invoke_capability,
    list_assistant_capabilities,
    unregister_capability,
    unregister_capabilities_by_origin,
)
from core.agent.tools import register_native_capabilities
from core.mcp import empty_mcp_status, set_mcp_manager
from core.mcp.config import load_mcp_config
from core.mcp.manager import MCPClientManager
from core.mcp.models import McpRuntimeConfig, McpServerConfig


def _build_demo_server() -> FastMCP:
    server = FastMCP("demo")

    @server.tool
    def echo(msg: str = "hi") -> str:
        """Echo a message back."""
        return msg

    @server.tool
    def secret_tool() -> str:
        """Should remain filtered by allowlist."""
        return "secret"

    return server


class CapabilityUnregisterTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_capability_registry_for_tests()
        register_native_capabilities()

    def tearDown(self) -> None:
        clear_capability_registry_for_tests()

    def test_unregister_capability_removes_entry(self) -> None:
        from core.agent.capabilities import CapabilityDescriptor, register_capability

        register_capability(
            CapabilityDescriptor(
                name="temp_native_probe",
                title="Temp",
                description="Temp",
                input_schema={"type": "object", "properties": {}},
                origin="native",
                risk="read",
                expose_to_assistant=False,
                expose_to_mcp_server=False,
                expose_to_client_display=False,
            ),
            lambda: {"ok": True},
        )
        self.assertIsNotNone(get_capability_descriptor("temp_native_probe"))
        self.assertTrue(unregister_capability("temp_native_probe"))
        self.assertIsNone(get_capability_descriptor("temp_native_probe"))
        self.assertFalse(unregister_capability("temp_native_probe"))

    def test_unregister_by_origin_removes_only_matching(self) -> None:
        from core.agent.capabilities import CapabilityDescriptor, register_capability

        register_capability(
            CapabilityDescriptor(
                name="demo_echo",
                title="Echo",
                description="Echo",
                input_schema={"type": "object", "properties": {}},
                origin="mcp",
                risk="read",
                expose_to_assistant=True,
                expose_to_mcp_server=False,
                expose_to_client_display=False,
            ),
            lambda: {"ok": True},
        )
        removed = unregister_capabilities_by_origin("mcp")
        self.assertEqual(removed, ["demo_echo"])
        self.assertIsNone(get_capability_descriptor("demo_echo"))
        self.assertIsNotNone(get_capability_descriptor("get_weather_forecast"))

    def test_registry_reads_wait_for_concurrent_mutation_lock(self) -> None:
        from core.agent import capabilities

        started = threading.Event()
        finished = threading.Event()

        def _list_capabilities() -> None:
            started.set()
            list_assistant_capabilities()
            finished.set()

        with capabilities._REGISTRY._lock:
            worker = threading.Thread(target=_list_capabilities)
            worker.start()
            self.assertTrue(started.wait(timeout=1.0))
            time.sleep(0.02)
            self.assertFalse(finished.is_set())

        worker.join(timeout=1.0)
        self.assertTrue(finished.is_set())


class McpConfigLoaderTests(unittest.TestCase):
    def test_missing_mcp_section_defaults_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "config.json"
            local = Path(tmp) / "config.local.json"
            base.write_text("{}", encoding="utf-8")
            config = load_mcp_config(config_path=base, local_path=local)
            self.assertFalse(config.enabled)
            self.assertEqual(config.servers, {})

    def test_local_overlay_merges_server_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "config.json"
            local = Path(tmp) / "config.local.json"
            base.write_text(
                json.dumps(
                    {
                        "mcp": {
                            "enabled": False,
                            "servers": {
                                "demo": {
                                    "enabled": False,
                                    "transport": "http",
                                    "url": "https://example.com/mcp",
                                    "tool_allowlist": ["echo"],
                                    "tool_risks": {"echo": "read"},
                                }
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            local.write_text(
                json.dumps(
                    {
                        "mcp": {
                            "enabled": True,
                            "servers": {
                                "demo": {
                                    "enabled": True,
                                    "auth_env": "DEMO_MCP_TOKEN",
                                }
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_mcp_config(config_path=base, local_path=local)
            self.assertTrue(config.enabled)
            self.assertIn("demo", config.servers)
            self.assertTrue(config.servers["demo"].enabled)
            self.assertEqual(config.servers["demo"].auth_env, "DEMO_MCP_TOKEN")
            self.assertEqual(config.servers["demo"].tool_allowlist, ["echo"])
            self.assertEqual(config.servers["demo"].tool_risks, {"echo": "read"})

    def test_non_boolean_enabled_values_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "config.json"
            local = Path(tmp) / "config.local.json"
            base.write_text(
                json.dumps(
                    {
                        "mcp": {
                            "enabled": "false",
                            "servers": {
                                "demo": {
                                    "enabled": "false",
                                    "transport": "stdio",
                                    "command": "should-not-run",
                                }
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_mcp_config(config_path=base, local_path=local)
            self.assertFalse(config.enabled)
            self.assertFalse(config.servers["demo"].enabled)


class McpClientRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        clear_capability_registry_for_tests()
        register_native_capabilities()
        set_mcp_manager(None)
        self._demo_server = _build_demo_server()
        self._manager: MCPClientManager | None = None

    async def asyncTearDown(self) -> None:
        if self._manager is not None:
            await self._manager.shutdown()
            self._manager = None
        set_mcp_manager(None)
        unregister_capabilities_by_origin("mcp")
        clear_capability_registry_for_tests()

    def _patch_inmemory_client(self):
        demo = self._demo_server

        def _build_client(config, *, auth_token=None, headers=None):
            return Client(demo)

        return patch("core.mcp.manager._build_client", side_effect=_build_client)

    async def _start_manager(self, config: McpRuntimeConfig) -> MCPClientManager:
        manager = MCPClientManager(config)
        self._manager = manager
        set_mcp_manager(manager)
        with self._patch_inmemory_client():
            await manager.start()
            if manager._discovery_tasks:
                await asyncio.gather(*manager._discovery_tasks)
        return manager

    async def test_no_mcp_config_leaves_natives_only(self) -> None:
        manager = MCPClientManager(McpRuntimeConfig(enabled=False, servers={}))
        self._manager = manager
        await manager.start()
        names = {cap.name for cap in list_assistant_capabilities()}
        self.assertTrue(names.issuperset({
            "get_weather_forecast",
            "get_f1_driver_standings",
            "get_f1_season_calendar",
            "get_upcoming_calendar_events",
            "get_active_reminders",
            "get_briefing_history",
        }))
        self.assertFalse(any(name.startswith("demo_") for name in names))
        snapshot = manager.status_snapshot()
        self.assertEqual(snapshot.status, "disabled")

    async def test_allowlist_registers_only_approved_tools(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=["echo"],
                    tool_risks={"echo": "read"},
                )
            },
        )
        await self._start_manager(config)
        self.assertIsNotNone(get_capability_descriptor("demo_echo"))
        self.assertIsNone(get_capability_descriptor("demo_secret_tool"))
        descriptor = get_capability_descriptor("demo_echo")
        assert descriptor is not None
        self.assertEqual(descriptor.origin, "mcp")
        self.assertEqual(descriptor.risk, "read")
        self.assertTrue(descriptor.expose_to_assistant)
        self.assertFalse(descriptor.expose_to_mcp_server)
        self.assertFalse(descriptor.expose_to_client_display)

    async def test_allowlisted_tool_without_explicit_risk_is_not_registered(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=["echo"],
                )
            },
        )
        manager = await self._start_manager(config)
        self.assertIsNone(get_capability_descriptor("demo_echo"))
        self.assertEqual(manager.status_snapshot().servers[0].registered_tools, [])

    async def test_explicit_write_risk_is_preserved(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=["echo"],
                    tool_risks={"echo": "write"},
                )
            },
        )
        await self._start_manager(config)
        descriptor = get_capability_descriptor("demo_echo")
        assert descriptor is not None
        self.assertEqual(descriptor.risk, "write")

    async def test_empty_allowlist_registers_nothing(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=[],
                )
            },
        )
        manager = await self._start_manager(config)
        self.assertIsNone(get_capability_descriptor("demo_echo"))
        status = manager.status_snapshot()
        self.assertEqual(status.servers[0].status, "connected")
        self.assertEqual(status.servers[0].registered_tools, [])

    async def test_missing_auth_env_is_authentication_required(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=["echo"],
                    tool_risks={"echo": "read"},
                    auth_env="APEX_TEST_MCP_TOKEN_MISSING",
                )
            },
        )
        os.environ.pop("APEX_TEST_MCP_TOKEN_MISSING", None)
        manager = await self._start_manager(config)
        snapshot = manager.status_snapshot()
        self.assertEqual(snapshot.status, "authentication-required")
        self.assertEqual(snapshot.servers[0].status, "authentication-required")
        self.assertNotIn("APEX_TEST_MCP_TOKEN_MISSING=", snapshot.servers[0].reason)
        self.assertIsNone(get_capability_descriptor("demo_echo"))

    async def test_offline_http_server_degrades_without_raising(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "offline": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="http://127.0.0.1:1/mcp",
                    tool_allowlist=["echo"],
                    tool_risks={"echo": "read"},
                    timeout_seconds=2.0,
                )
            },
        )
        manager = MCPClientManager(config)
        self._manager = manager
        await manager.start()
        if manager._discovery_tasks:
            await asyncio.gather(*manager._discovery_tasks)
        snapshot = manager.status_snapshot()
        self.assertEqual(snapshot.servers[0].status, "degraded")
        self.assertIsNone(get_capability_descriptor("offline_echo"))

    async def test_invoke_allowlisted_tool_through_capability_registry(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=["echo"],
                    tool_risks={"echo": "read"},
                )
            },
        )
        await self._start_manager(config)
        result = await asyncio.to_thread(
            invoke_capability,
            "demo_echo",
            {"msg": "chief"},
        )
        serialized = json.dumps(result, default=str)
        self.assertIn("chief", serialized)

    async def test_shutdown_unregisters_mcp_capabilities(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=["echo"],
                    tool_risks={"echo": "read"},
                )
            },
        )
        manager = await self._start_manager(config)
        self.assertIsNotNone(get_capability_descriptor("demo_echo"))
        await manager.shutdown()
        self._manager = None
        self.assertIsNone(get_capability_descriptor("demo_echo"))
        self.assertIsNotNone(get_capability_descriptor("get_weather_forecast"))

    async def test_status_payload_never_includes_secrets(self) -> None:
        config = McpRuntimeConfig(
            enabled=True,
            servers={
                "demo": McpServerConfig(
                    enabled=True,
                    transport="http",
                    url="https://example.invalid/mcp",
                    tool_allowlist=["echo"],
                    tool_risks={"echo": "read"},
                    auth_env="APEX_TEST_MCP_SECRET",
                    header_env={"Authorization": "APEX_TEST_MCP_HEADER"},
                )
            },
        )
        os.environ["APEX_TEST_MCP_SECRET"] = "super-secret-token"
        os.environ["APEX_TEST_MCP_HEADER"] = "Bearer leaked"
        try:
            manager = await self._start_manager(config)
            payload = manager.status_snapshot().model_dump()
            serialized = json.dumps(payload)
            self.assertNotIn("super-secret-token", serialized)
            self.assertNotIn("Bearer leaked", serialized)
            self.assertNotIn("Authorization", serialized)
        finally:
            os.environ.pop("APEX_TEST_MCP_SECRET", None)
            os.environ.pop("APEX_TEST_MCP_HEADER", None)


class McpStatusRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        set_mcp_manager(None)

    def tearDown(self) -> None:
        set_mcp_manager(None)

    def test_status_route_returns_disabled_without_manager(self) -> None:
        from core.api.app import app

        with patch("core.api.app.OLLAMA_ENABLED", False), patch(
            "core.api.app.load_mcp_config",
            return_value=McpRuntimeConfig(enabled=False, servers={}),
        ):
            with TestClient(app) as client:
                response = client.get("/api/v1/mcp/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["status"], "disabled")
        self.assertEqual(body["servers"], [])
        self.assertEqual(body, empty_mcp_status().model_dump())

    def test_ready_probe_does_not_require_mcp(self) -> None:
        from core.api.app import app

        with patch("core.api.app.OLLAMA_ENABLED", False), patch(
            "core.api.app.load_mcp_config",
            return_value=McpRuntimeConfig(enabled=False, servers={}),
        ):
            with TestClient(app) as client:
                response = client.get("/api/v1/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")


if __name__ == "__main__":
    unittest.main()
