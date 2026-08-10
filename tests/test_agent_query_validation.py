"""Validation and safety boundaries for Apex Agent queries."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient

from core.agent.capabilities import CapabilityDescriptor
from core.agent.tool_policies import filter_agent_capabilities, hosted_tools_for_agent
from core.agent.types import AgentMessage, AgentQueryRequest, AgentQueryResponse
from core.api.cortex import query_agent


class LocalEffortRejectionTests(unittest.TestCase):
    def test_local_agent_rejects_effort_with_400(self) -> None:
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
                        agent="sorex",
                        effort="focused",
                    )
                )
        self.assertEqual(ctx.exception.status_code, 400)


class AcinonyxPolicyTests(unittest.TestCase):
    def test_acinonyx_query_route_is_hard_dev_mode_only(self) -> None:
        from core.api.app import app

        client = TestClient(app, raise_server_exceptions=True)
        with mock.patch("core.api.routers.cortex.is_dev_mode", return_value=False):
            response = client.post(
                "/api/v1/cortex/query",
                json={"prompt": "hello", "agent": "acinonyx"},
            )
        self.assertEqual(response.status_code, 404)

    def test_acinonyx_rejects_production_history_and_uses_safe_tools(self) -> None:
        captured: dict[str, object] = {}

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

        with (
            mock.patch("core.api.cortex.DEMO_MODE", False),
            mock.patch("core.api.cortex.is_dev_mode", return_value=True),
            mock.patch("core.api.cortex.is_agent_visible", return_value=True),
            mock.patch("core.api.cortex.get_settings_store") as store_mock,
            mock.patch(
                "core.api.cortex._execute_agent_turn", side_effect=capture_execution
            ),
            mock.patch.dict(
                "os.environ", {"GEMINI_SANDBOX_API_KEY": "sandbox"}, clear=False
            ),
        ):
            store_mock.return_value.get_snapshot.return_value.ask_apex.enabled = True
            query_agent(
                AgentQueryRequest(
                    prompt="hello",
                    agent="acinonyx",
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

    def test_acinonyx_capability_policy_is_an_explicit_allowlist(self) -> None:
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
            "acinonyx",
            [
                descriptor("get_weather_forecast"),
                descriptor("get_active_reminders"),
                descriptor("brave_brave_web_search"),
                descriptor("alphavantage_quote"),
                descriptor("github_list_issues"),
            ],
        )
        self.assertEqual(
            [item.name for item in filtered],
            [
                "get_weather_forecast",
                "brave_brave_web_search",
                "alphavantage_quote",
            ],
        )

    def test_hosted_tool_policy_matches_profiles_and_toggles(self) -> None:
        self.assertEqual(
            hosted_tools_for_agent(
                "neofelis", neofelis_google_search_enabled=True
            ),
            frozenset({"google_search", "google_maps"}),
        )
        self.assertEqual(
            hosted_tools_for_agent(
                "neofelis", neofelis_google_search_enabled=False
            ),
            frozenset({"google_maps"}),
        )
        self.assertEqual(
            hosted_tools_for_agent(
                "neofelis",
                neofelis_google_search_enabled=False,
                neofelis_google_maps_enabled=False,
            ),
            frozenset(),
        )
        self.assertEqual(
            hosted_tools_for_agent(
                "delphinus", neofelis_google_search_enabled=True
            ),
            frozenset({"x_search"}),
        )
        self.assertEqual(
            hosted_tools_for_agent(
                "delphinus",
                neofelis_google_search_enabled=True,
                delphinus_x_search_enabled=False,
            ),
            frozenset(),
        )
        self.assertEqual(
            hosted_tools_for_agent(
                "orcinus",
                neofelis_google_search_enabled=True,
                orcinus_x_search_enabled=False,
            ),
            frozenset(),
        )


if __name__ == "__main__":
    unittest.main()
