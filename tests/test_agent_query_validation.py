"""Validation and safety boundaries for Apex Agent queries."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.agent.capabilities import CapabilityDescriptor
from core.agent.model_catalog import get_model_profile
from core.agent.tool_policies import filter_agent_capabilities, hosted_tools_for_agent
from core.agent.types import (
    AgentMessage,
    AgentQueryRequest,
    AgentQueryResponse,
    ToolSelectionDiagnostics,
)
from core.api.models import ToolPreflightRequest
from core.api.cortex import query_agent


class LocalEffortRejectionTests(unittest.TestCase):
    def test_tool_preflight_rejects_removed_history_fields(self) -> None:
        with self.assertRaises(ValueError):
            ToolPreflightRequest.model_validate({"history": [], "prompt": "status"})

    def test_local_model_rejects_effort_with_400(self) -> None:
        with mock.patch("core.api.cortex.DEMO_MODE", False), mock.patch(
            "core.api.cortex.is_dev_mode", return_value=True
        ), mock.patch(
            "core.agent.catalog.is_dev_mode", return_value=True
        ), mock.patch("core.api.cortex.get_settings_store") as store_mock:
            store_mock.return_value.get_snapshot.return_value.ask_apex.enabled = True
            with self.assertRaises(HTTPException) as ctx:
                query_agent(
                    AgentQueryRequest(
                        prompt="hello",
                        agent="apex",
                        model_id="gemma-4-E2B-Q4_K_M.gguf",
                        effort="medium",
                    )
                )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_demo_metadata_uses_explicit_local_model_not_saved_cloud_model(self) -> None:
        saved_cloud_model = get_model_profile("gpt-5.6-luna")
        assert saved_cloud_model is not None
        settings = mock.Mock()
        settings.ask_apex.enabled = True
        with (
            mock.patch("core.api.cortex.DEMO_MODE", True),
            mock.patch("core.api.cortex.get_settings_store") as store_mock,
            mock.patch(
                "core.agent.catalog.resolve_selected_model_profile",
                return_value=saved_cloud_model,
            ),
            mock.patch(
                "core.api.cortex.resolve_selected_tools",
                return_value=mock.Mock(
                    failures=[],
                    descriptors=[],
                    diagnostics=ToolSelectionDiagnostics(),
                ),
            ),
        ):
            store_mock.return_value.get_snapshot.return_value = settings
            response = query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    agent="apex",
                    model_id="gemma-4-E2B-Q4_K_M.gguf",
                    context_window=4096,
                    local_reasoning_mode="none",
                )
            )

        self.assertEqual(response.agent_used["configured_model"], "gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(response.agent_used["resolved_model"], "gemma-4-E2B-Q4_K_M.gguf")
        self.assertEqual(response.agent_used["runtime"], "local")


class SandboxPolicyTests(unittest.TestCase):
    def test_unknown_agent_key_is_rejected(self) -> None:
        from core.api.app import app

        client = TestClient(app, raise_server_exceptions=True)
        with mock.patch("core.api.cortex.is_dev_mode", return_value=False):
            response = client.post(
                "/api/v1/cortex/query",
                json={"prompt": "hello", "agent": "unknown"},
            )
            self.assertEqual(response.status_code, 404)

    def test_sandbox_cloud_model_rejects_production_history_and_uses_safe_tools(self) -> None:
        captured: dict[str, object] = {}
        selected_model = get_model_profile("gpt-5.6-luna")
        assert selected_model is not None

        def capture_execution(payload, *_args, **kwargs):
            captured.update(
                {
                    "snapshot_id": payload.snapshot_id,
                    "briefing_id": payload.briefing_id,
                    "history": list(payload.history),
                    "disable_tools": kwargs.get("disable_tools"),
                    "disable_hud_context": kwargs.get("disable_hud_context"),
                }
            )
            return AgentQueryResponse(answer="ok", agent_used={}, session_id=None)

        ask_apex = mock.Mock()
        ask_apex.enabled = True
        ask_apex.sandbox_mode = True
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.is_dev_mode", return_value=True),
            mock.patch("core.api.cortex.is_agent_visible", return_value=True),
            mock.patch("core.api.cortex.get_settings_store") as store_mock,
            mock.patch(
                "core.api.cortex._execute_agent_turn", side_effect=capture_execution
            ),
            mock.patch(
                "core.api.cortex.resolve_selected_model_profile",
                return_value=selected_model,
            ),
            mock.patch(
                "core.agent.catalog.resolve_selected_model_profile",
                return_value=selected_model,
            ),
            mock.patch(
                "core.api.cortex.resolve_selected_tools",
                return_value=mock.Mock(failures=[], descriptors=[], diagnostics=mock.Mock()),
            ),
            mock.patch("core.api.cortex.agent_has_credentials", return_value=True),
        ):
            store_mock.return_value.get_snapshot.return_value.ask_apex = ask_apex
            query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    agent="apex",
                    model_id="gpt-5.6-luna",
                    snapshot_id="snap-1",
                    history=[
                        AgentMessage(role="user", content="prior production turn")
                    ],
                )
            )

        self.assertEqual(captured["snapshot_id"], "snap-1")
        self.assertIsNone(captured["briefing_id"])
        self.assertEqual(captured.get("history"), [])
        self.assertFalse(captured["disable_tools"])
        self.assertFalse(captured["disable_hud_context"])

    def test_sandbox_local_model_rejects_production_history(self) -> None:
        captured: dict[str, object] = {}

        def capture_execution(payload, *_args, **kwargs):
            captured.update(
                {
                    "history": list(payload.history),
                    "disable_hud_context": kwargs.get("disable_hud_context"),
                }
            )
            return AgentQueryResponse(answer="ok", agent_used={}, session_id=None)

        ask_apex = mock.Mock()
        ask_apex.enabled = True
        ask_apex.sandbox_mode = True
        backend = mock.Mock()
        backend.enabled = True
        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.is_dev_mode", return_value=True),
            mock.patch("core.api.cortex.is_agent_visible", return_value=True),
            mock.patch("core.api.cortex.get_settings_store") as store_mock,
            mock.patch("core.api.cortex.get_local_runtime_backend", return_value=backend),
            mock.patch("core.api.cortex._ensure_local_alias_configured"),
            mock.patch("core.api.cortex.switch_local_model", return_value=True),
            mock.patch("core.api.cortex.is_local_model_ready", return_value=True),
            mock.patch(
                "core.api.cortex.resolve_selected_tools",
                return_value=mock.Mock(failures=[], descriptors=[], diagnostics=mock.Mock()),
            ),
            mock.patch(
                "core.api.cortex._execute_agent_turn", side_effect=capture_execution
            ),
            mock.patch("core.api.cortex.try_begin_local_execution", return_value=True),
            mock.patch("core.api.cortex.end_local_execution"),
        ):
            store_mock.return_value.get_snapshot.return_value.ask_apex = ask_apex
            query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    agent="apex",
                    model_id="gemma-4-E2B-Q4_K_M.gguf",
                    history=[
                        AgentMessage(role="user", content="prior production turn")
                    ],
                )
            )

        self.assertEqual(captured.get("history"), [])
        self.assertFalse(captured["disable_hud_context"])

    def test_sandbox_capability_policy_is_an_explicit_allowlist(self) -> None:
        def descriptor(name: str) -> CapabilityDescriptor:
            return CapabilityDescriptor(
                name=name,
                title=name,
                description=name,
                input_schema={"type": "object", "properties": {}},
                origin=(
                    "mcp"
                    if name.startswith(("brave", "github", "alphavantage"))
                    else "native"
                ),
                risk="read",
                expose_to_agent=True,
                expose_to_mcp_server=False,
                expose_to_client_display=True,
            )

        filtered = filter_agent_capabilities(
            "apex",
            [
                descriptor("get_weather_forecast"),
                descriptor("get_active_reminders"),
                descriptor("brave_brave_web_search"),
                descriptor("alphavantage_quote"),
                descriptor("github_list_issues"),
            ],
            sandbox_mode=True,
            dev_mode=True,
        )
        self.assertEqual(
            [item.name for item in filtered],
            [
                "get_weather_forecast",
                "brave_brave_web_search",
                "alphavantage_quote",
            ],
        )

    def test_hosted_tool_policy_matches_selected_models_and_toggles(self) -> None:
        with mock.patch(
            "core.agent.catalog.resolve_selected_model_profile"
        ) as resolve_profile:
            resolve_profile.return_value = get_model_profile("gemini-3.7-flash")
            self.assertEqual(
                hosted_tools_for_agent(
                    "apex", google_search_enabled=True
                ),
                frozenset({"google_search", "google_maps"}),
            )
            self.assertEqual(
                hosted_tools_for_agent(
                    "apex", google_search_enabled=False
                ),
                frozenset({"google_maps"}),
            )
            self.assertEqual(
                hosted_tools_for_agent(
                    "apex",
                    google_search_enabled=False,
                    google_maps_enabled=False,
                ),
                frozenset(),
            )


if __name__ == "__main__":
    unittest.main()
