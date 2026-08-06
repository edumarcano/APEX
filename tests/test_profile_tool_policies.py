"""Apex Agent tool policy, grounding, and Acinonyx privacy coverage."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from core.agent.catalog import build_concrete_agent, resolve_effort
from core.agent.loop import run_agent_loop
from core.agent.capabilities import CapabilityDescriptor
from core.agent.prompting import build_tool_access_instruction
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.gemini import _parse_grounding
from core.agent.providers.xai_provider import XAIProvider
from core.agent.sandbox_context import (
    clear_masked_briefing_for_tests,
    publish_masked_briefing,
)
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall
from core.api.cortex import _build_hud_context
from core.api.briefing import _mask_dev_personal_results
from core.connectors.models import ConnectorResult


class HostedGroundingTests(unittest.TestCase):
    def test_hosted_grounding_stays_outside_apex_tool_schema_profiles(self) -> None:
        expected = {
            "neofelis": {"google_search", "google_maps"},
            "delphinus": {"x_search"},
            "orcinus": {"x_search"},
        }
        for agent_key, hosted_names in expected.items():
            _apex, native = resolve_effort(agent_key, None)
            profile = build_concrete_agent(agent_key, native_effort=native)
            instruction = build_tool_access_instruction(
                [],
                hosted_tool_names=tuple(profile.hosted_tools),
            )

            self.assertEqual(set(profile.hosted_tools), hosted_names)
            self.assertIn("No APEX-managed or MCP tool schemas", instruction)
            self.assertIn("Provider-hosted grounding is enabled separately", instruction)
            self.assertNotIn("No live tools are attached", instruction)

    def test_gemini_grounding_normalizes_search_and_maps(self) -> None:
        metadata = SimpleNamespace(
            grounding_chunks=[
                SimpleNamespace(
                    web=SimpleNamespace(uri="https://example.com", title="Example"),
                    maps=None,
                ),
                SimpleNamespace(
                    web=None,
                    maps=SimpleNamespace(
                        uri="https://maps.google.com/place", title="A Place"
                    ),
                ),
            ]
        )
        response = SimpleNamespace(
            candidates=[SimpleNamespace(grounding_metadata=metadata)]
        )

        citations, events = _parse_grounding(response)

        self.assertEqual([item.source for item in citations], ["google_search", "google_maps"])
        self.assertEqual([item.name for item in events], ["google_search", "google_maps"])
        self.assertTrue(all(item.status == "ok" for item in events))
        self.assertTrue(all(item.billable_units == 1 for item in events))

    @mock.patch("core.agent.providers.responses_api.OpenAI")
    def test_xai_profiles_attach_x_search_without_web_search(
        self, openai_cls: mock.MagicMock
    ) -> None:
        client = mock.MagicMock()
        openai_cls.return_value = client
        client.responses.create.return_value = SimpleNamespace(
            output=[], model="grok-4.3", usage=None
        )
        _apex, native = resolve_effort("delphinus", None)
        profile = build_concrete_agent("delphinus", native_effort=native)

        XAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="What is happening on X?")],
            [],
            profile,
        )

        tools = client.responses.create.call_args.kwargs["tools"]
        self.assertEqual(tools, [{"type": "x_search"}])
        self.assertFalse(any(item.get("type") == "web_search" for item in tools))


class AcinonyxContextTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_masked_briefing_for_tests()

    def test_only_process_current_masked_briefing_is_attached(self) -> None:
        publish_masked_briefing(
            snapshot_id="current-snapshot",
            briefing="Two unread emails; personal details were masked.",
            insights=["Review the masked summary."],
        )

        current = _build_hud_context(
            AgentQueryRequest(
                prompt="Summarize",
                agent="acinonyx",
                snapshot_id="current-snapshot",
                history_partition="acinonyx",
            ),
            agent_key="acinonyx",
        )
        stale = _build_hud_context(
            AgentQueryRequest(
                prompt="Summarize",
                agent="acinonyx",
                snapshot_id="stale-snapshot",
                history_partition="acinonyx",
            ),
            agent_key="acinonyx",
        )

        self.assertIn("CURRENT MASKED DEV BRIEFING", current)
        self.assertNotIn("CURRENT TELEMETRY SNAPSHOT", current)
        self.assertEqual(stale, "")

    def test_dev_masking_removes_personal_text_but_preserves_counts(self) -> None:
        results = {
            "email": ConnectorResult(
                name="email",
                status="healthy",
                data={"count": 2, "emails": [{"subject": "Secret subject"}]},
                display_text="Secret subject",
            ),
            "calendar": ConnectorResult(
                name="calendar",
                status="healthy",
                data={
                    "total_count": 1,
                    "events": [{"summary": "Private appointment"}],
                },
                display_text="Private appointment",
            ),
            "reminders": ConnectorResult(
                name="reminders",
                status="healthy",
                data={"count": 1, "notes": ["Call Alice"]},
                display_text="Call Alice",
            ),
        }

        masked = _mask_dev_personal_results(results)
        serialized = str(masked)

        self.assertNotIn("Secret subject", serialized)
        self.assertNotIn("Private appointment", serialized)
        self.assertNotIn("Call Alice", serialized)
        self.assertEqual(masked["email"].data["count"], 2)  # type: ignore[union-attr]
        self.assertEqual(masked["calendar"].data["total_count"], 1)  # type: ignore[union-attr]
        self.assertEqual(masked["reminders"].data["count"], 1)  # type: ignore[union-attr]

    def test_disallowed_hallucinated_tool_call_is_not_executed(self) -> None:
        weather = CapabilityDescriptor(
            name="get_weather_forecast",
            title="Weather",
            description="Weather",
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )

        class Provider:
            def __init__(self) -> None:
                self.calls = 0

            def generate_turn(self, *_args, **_kwargs) -> ProviderTurnResult:
                self.calls += 1
                if self.calls == 1:
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="agent",
                            tool_calls=[
                                ToolCall(
                                    id="forbidden",
                                    name="get_active_reminders",
                                    arguments={},
                                )
                            ],
                        )
                    )
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="Cannot access that tool.")
                )

        _apex, native = resolve_effort("acinonyx", None)
        response = run_agent_loop(
            AgentQueryRequest(
                prompt="Read reminders",
                agent="acinonyx",
                history_partition="acinonyx",
            ),
            Provider(),
            build_concrete_agent("acinonyx", native_effort=native),
            tools_dispatcher=mock.Mock(side_effect=AssertionError("must not execute")),
            selected_tools=[weather],
        )

        self.assertEqual(response.tool_trace[0]["status"], "error")
        self.assertEqual(
            response.tool_outputs[0]["output"]["error_category"], "unavailable"
        )


if __name__ == "__main__":
    unittest.main()
