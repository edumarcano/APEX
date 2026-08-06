"""Integration coverage for Cortex routing and offered-tool propagation."""

from __future__ import annotations

import unittest
from unittest import mock

from core.agent.capabilities import CapabilityDescriptor
from core.agent.routing.models import CapabilityRoutingRequest, RankedCapabilityFamily
from core.agent.routing.ranker import RankerResult
from core.agent.routing.service import resolve_capabilities
from core.agent.types import AgentQueryRequest, AgentQueryResponse
from core.api.cortex import _execute_agent_turn, query_agent


def _descriptor(name: str, family: str) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        title=name,
        description=name,
        input_schema={"type": "object", "properties": {}},
        origin="native",
        risk="read",
        expose_to_agent=True,
        expose_to_mcp_server=False,
        expose_to_client_display=True,
        routing_family=family,
    )


class CapabilityRoutingIntegrationTests(unittest.TestCase):
    def test_execute_agent_turn_passes_offered_tools_to_loop(self) -> None:
        offered = [_descriptor("get_weather_forecast", "weather")]
        captured: dict[str, object] = {}

        def capture_loop(*_args, **kwargs):
            captured["offered_tools"] = kwargs.get("offered_tools")
            return AgentQueryResponse(answer="ok", agent_used={}, session_id=None)

        profile = mock.Mock()
        profile.display_name = "Apex Panthera"
        profile.api_model = "gpt-test"
        profile.provider = "openai"

        with (
            mock.patch("core.api.cortex._create_provider", return_value=mock.Mock()),
            mock.patch("core.api.cortex.run_agent_loop", side_effect=capture_loop),
            mock.patch("core.api.cortex._build_hud_context", return_value=""),
        ):
            _execute_agent_turn(
                AgentQueryRequest(prompt="Forecast", agent="panthera"),
                profile,
                agent_key="panthera",
                api_key="test",
                resolved_apex_effort=None,
                resolved_native_effort=None,
                user_designation="",
                offered_tools=offered,
                routing_diagnostics=None,
            )

        self.assertEqual(captured["offered_tools"], offered)

    @mock.patch("core.api.cortex.resolve_capabilities")
    @mock.patch("core.api.cortex.filter_agent_capabilities")
    @mock.patch("core.api.cortex.run_agent_loop")
    @mock.patch("core.api.cortex._create_provider")
    @mock.patch("core.api.cortex.get_settings_store")
    @mock.patch("core.api.cortex.DEMO_MODE", False)
    def test_query_agent_attaches_routing_diagnostics_in_shadow_mode(
        self,
        store_mock,
        provider_mock,
        loop_mock,
        filter_mock,
        resolve_mock,
    ) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        mail = _descriptor("search_gmail", "mail")
        filter_mock.return_value = [weather, mail]
        decision = resolve_capabilities(
            CapabilityRoutingRequest(
                prompt="Forecast",
                history=(),
                capabilities=(weather, mail),
                agent_key="neofelis",
                runtime="cloud",
                mode="shadow",
                explicit_scope=None,
            )
        )
        resolve_mock.return_value = decision
        loop_mock.return_value = AgentQueryResponse(
            answer="ok",
            agent_used={"key": "neofelis"},
            session_id=None,
        )
        store = store_mock.return_value
        store.get_snapshot.return_value.ask_apex.enabled = True
        store.get_snapshot.return_value.ask_apex.tool_routing_mode = "shadow"
        store.get_snapshot.return_value.ask_apex.neofelis_google_search_enabled = False
        store.get_snapshot.return_value.ask_apex.neofelis_google_maps_enabled = False
        store.get_snapshot.return_value.ask_apex.delphinus_x_search_enabled = False
        store.get_snapshot.return_value.ask_apex.orcinus_x_search_enabled = False
        provider_mock.return_value = mock.Mock()

        with mock.patch("core.api.cortex._build_hud_context", return_value=""):
            response = query_agent(
                AgentQueryRequest(prompt="Forecast", agent="neofelis"),
            )

        self.assertIsNotNone(response.routing)
        self.assertEqual(response.routing.mode, "shadow")
        self.assertFalse(response.routing.enforced)
        loop_kwargs = loop_mock.call_args.kwargs
        self.assertEqual(len(loop_kwargs["offered_tools"]), 2)

    @mock.patch("core.agent.routing.service.rank_capability_families")
    def test_enabled_cloud_routing_reduces_offered_tools(self, rank_mock) -> None:
        weather = _descriptor("get_weather_forecast", "weather")
        mail = _descriptor("search_gmail", "mail")
        rank_mock.return_value = RankerResult(
            rankings=(
                RankedCapabilityFamily(key="weather", score=0.92),
                RankedCapabilityFamily(key="none", score=0.08),
            ),
            model_key="all-minilm-l6-v2",
            latency_ms=2.0,
        )
        decision = resolve_capabilities(
            CapabilityRoutingRequest(
                prompt="Forecast",
                history=(),
                capabilities=(weather, mail),
                agent_key="neofelis",
                runtime="cloud",
                mode="enabled",
                explicit_scope=None,
            )
        )
        self.assertTrue(decision.enforced)
        self.assertEqual(
            [tool.name for tool in decision.offered_capabilities],
            ["get_weather_forecast"],
        )

    @mock.patch("core.agent.routing.service.rank_capability_families")
    def test_explicit_none_bypasses_ranker(self, rank_mock) -> None:
        decision = resolve_capabilities(
            CapabilityRoutingRequest(
                prompt="Hello",
                history=(),
                capabilities=(_descriptor("get_weather_forecast", "weather"),),
                agent_key="sorex",
                runtime="local",
                mode="enabled",
                explicit_scope="none",
            )
        )
        rank_mock.assert_not_called()
        self.assertEqual(decision.kind, "explicit_none")
        self.assertEqual(decision.offered_capabilities, ())


if __name__ == "__main__":
    unittest.main()
