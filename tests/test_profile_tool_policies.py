"""Apex Agent tool policy, grounding, and sandbox privacy coverage."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from core.agent.loop import run_agent_loop
from core.agent.capabilities import CapabilityDescriptor
from core.agent.model_catalog import get_model_profile
from core.agent.prompting import build_tool_access_instruction
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.gemini import _parse_grounding
from core.agent.providers.xai_provider import XAIProvider
from core.agent.sandbox_context import (
    clear_masked_briefing_for_tests,
    publish_masked_briefing,
)
from core.agent.types import (
    AgentMessage,
    AgentQueryRequest,
    GroundingPresentation,
    ToolCall,
)
from core.api.cortex import _build_hud_context
from core.api.briefing import _mask_dev_personal_results
from core.connectors.models import ConnectorResult
from tests.support.agent_fixtures import (
    GEMINI_FLASH_MODEL,
    GROK_43_MODEL,
    GROK_45_MODEL,
    build_panthera_profile,
)


class HostedGroundingTests(unittest.TestCase):
    def test_hosted_grounding_stays_outside_apex_tool_schema_profiles(self) -> None:
        expected = {
            GEMINI_FLASH_MODEL: {"google_search", "google_maps"},
            GROK_43_MODEL: {"x_search"},
            GROK_45_MODEL: {"x_search"},
        }
        for model_id, hosted_names in expected.items():
            profile = build_panthera_profile(model=model_id)
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
            ],
            grounding_supports=[
                SimpleNamespace(
                    segment=SimpleNamespace(end_index=12),
                    grounding_chunk_indices=[0, 1],
                )
            ],
            search_entry_point=SimpleNamespace(
                rendered_content="<a href='https://www.google.com/search'>Search</a>"
            ),
        )
        response = SimpleNamespace(
            candidates=[SimpleNamespace(grounding_metadata=metadata)]
        )

        citations, events, grounding, rendered = _parse_grounding(
            response, "Grounded text."
        )

        self.assertEqual([item.source for item in citations], ["google_search", "google_maps"])
        self.assertEqual([item.name for item in events], ["google_search", "google_maps"])
        self.assertTrue(all(item.status == "ok" for item in events))
        self.assertTrue(all(item.billable_units == 1 for item in events))
        self.assertEqual(
            grounding.search_suggestions_html,
            "<a href='https://www.google.com/search'>Search</a>",
        )
        self.assertEqual(
            rendered,
            "Grounded tex [1](https://example.com) [Google Maps: A Place](https://maps.google.com/place)t.",
        )

    def test_gemini_grounding_ignores_unsafe_source_uris(self) -> None:
        metadata = SimpleNamespace(
            grounding_chunks=[
                SimpleNamespace(
                    web=SimpleNamespace(uri="javascript:alert(1)", title="Unsafe"),
                    maps=None,
                )
            ]
        )
        response = SimpleNamespace(
            candidates=[SimpleNamespace(grounding_metadata=metadata)]
        )

        citations, _events, _grounding, rendered = _parse_grounding(
            response, "Grounded text."
        )

        self.assertIsNone(citations[0].uri)
        self.assertEqual(rendered, "Grounded text.")

    def test_agent_loop_returns_grounding_presentation_to_the_client(self) -> None:
        class Provider:
            def generate_turn(self, *_args, **_kwargs) -> ProviderTurnResult:
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="Grounded answer."),
                    grounding=GroundingPresentation(
                        search_suggestions_html="<div>Search suggestions</div>"
                    ),
                )

        profile = build_panthera_profile(model=GEMINI_FLASH_MODEL)
        response = run_agent_loop(
            AgentQueryRequest(prompt="Find current information", agent="panthera"),
            Provider(),
            profile,
        )

        self.assertEqual(response.answer, "Grounded answer.")
        self.assertEqual(
            response.grounding.search_suggestions_html,
            "<div>Search suggestions</div>",
        )

    @mock.patch("core.agent.providers.responses_api.OpenAI")
    def test_xai_profiles_attach_x_search_without_web_search(
        self, openai_cls: mock.MagicMock
    ) -> None:
        client = mock.MagicMock()
        openai_cls.return_value = client
        client.responses.create.return_value = SimpleNamespace(
            output=[], model="grok-4.3", usage=None
        )
        profile = build_panthera_profile(model=GROK_43_MODEL)

        XAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="What is happening on X?")],
            [],
            profile,
        )

        tools = client.responses.create.call_args.kwargs["tools"]
        self.assertEqual(tools, [{"type": "x_search"}])
        self.assertFalse(any(item.get("type") == "web_search" for item in tools))


class ToolAccessInstructionTests(unittest.TestCase):
    def test_attached_apex_tools_distinguish_reads_from_approval_gated_writes(self) -> None:
        instruction = build_tool_access_instruction(
            ["get_weather_forecast"],
            hosted_tool_names=["google_search"],
        )

        self.assertIn(
            "Attached read tools may be used directly when needed.",
            instruction,
        )
        self.assertIn(
            "native write tool creates a durable proposal only",
            instruction,
        )
        self.assertIn(
            "requires separate local operator approval",
            instruction,
        )
        self.assertIn(
            "Provider-hosted grounding is enabled separately",
            instruction,
        )
        self.assertNotIn("No APEX-managed or MCP tool schemas", instruction)

    def test_no_attached_apex_tools_do_not_claim_read_only_authority(self) -> None:
        instruction = build_tool_access_instruction([])

        self.assertIn("No APEX-managed or MCP tool schemas", instruction)
        self.assertNotIn(
            "Attached read tools may be used directly when needed.",
            instruction,
        )
        self.assertNotIn(
            "requires separate local operator approval",
            instruction,
        )


class SandboxContextTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_masked_briefing_for_tests()

    def test_only_process_current_masked_briefing_is_attached(self) -> None:
        publish_masked_briefing(
            snapshot_id="current-snapshot",
            briefing="Two unread emails; personal details were masked.",
            insights=["Review the masked summary."],
        )

        ask_apex = mock.Mock()
        ask_apex.sandbox_mode = True
        with mock.patch("core.api.cortex.get_settings_store") as store, mock.patch(
            "core.api.cortex.is_dev_mode", return_value=True
        ):
            store.return_value.get_snapshot.return_value.ask_apex = ask_apex
            current = _build_hud_context(
                AgentQueryRequest(
                    prompt="Summarize",
                    agent="panthera",
                    snapshot_id="current-snapshot",
                    history_partition="sandbox",
                ),
                agent_key="panthera",
            )
            stale = _build_hud_context(
                AgentQueryRequest(
                    prompt="Summarize",
                    agent="panthera",
                    snapshot_id="stale-snapshot",
                    history_partition="sandbox",
                ),
                agent_key="panthera",
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

        profile = build_panthera_profile(model="gemini-3.5-flash-lite")
        response = run_agent_loop(
            AgentQueryRequest(
                prompt="Read reminders",
                agent="panthera",
                history_partition="sandbox",
            ),
            Provider(),
            profile,
            tools_dispatcher=mock.Mock(side_effect=AssertionError("must not execute")),
            selected_tools=[weather],
        )

        self.assertEqual(response.tool_trace[0]["status"], "error")
        self.assertEqual(
            response.tool_outputs[0]["output"]["error_category"], "unavailable"
        )


if __name__ == "__main__":
    unittest.main()
