"""Apex Agent tool policy, grounding, and sandbox privacy coverage."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from core.agent.loop import run_agent_loop
from core.agent.capabilities import CapabilityDescriptor, get_capability_descriptor
from core.agent.model_catalog import get_model_profile
from core.agent.prompting import build_tool_access_instruction
from core.agent.providers.contract import ProviderTurnResult
from core.agent.providers.gemini import _parse_grounding
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
    build_cloud_profile,
)


class HostedGroundingTests(unittest.TestCase):
    def test_hosted_grounding_stays_outside_apex_tool_schema_profiles(self) -> None:
        expected = {
            GEMINI_FLASH_MODEL: {"google_search", "google_maps"},
        }
        for model_id, hosted_names in expected.items():
            profile = build_cloud_profile(model=model_id)
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

        profile = build_cloud_profile(model=GEMINI_FLASH_MODEL)
        response = run_agent_loop(
            AgentQueryRequest(prompt="Find current information", agent="apex"),
            Provider(),
            profile,
        )

        self.assertEqual(response.answer, "Grounded answer.")
        self.assertEqual(
            response.grounding.search_suggestions_html,
            "<div>Search suggestions</div>",
        )


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
                    agent="apex",
                    snapshot_id="current-snapshot",
                    history_partition="sandbox",
                ),
                agent_key="apex",
            )
            stale = _build_hud_context(
                AgentQueryRequest(
                    prompt="Summarize",
                    agent="apex",
                    snapshot_id="stale-snapshot",
                    history_partition="sandbox",
                ),
                agent_key="apex",
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

        profile = build_cloud_profile(model="gemini-3.7-flash")
        response = run_agent_loop(
            AgentQueryRequest(
                prompt="Read reminders",
                agent="apex",
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

    def test_multi_step_tool_loop_compacts_earlier_tool_outputs(self) -> None:
        turn_history_snapshots: list[list[AgentMessage]] = []

        class MultiTurnProvider:
            def __init__(self) -> None:
                self.calls = 0

            def generate_turn(
                self,
                messages: list[AgentMessage],
                _tools: list[object],
                _profile: object,
                system_instruction_override: str | None = None,
            ) -> ProviderTurnResult:
                del system_instruction_override
                self.calls += 1
                tool_msgs = [m for m in messages if m.role == "tool"]
                turn_history_snapshots.append(
                    [m.model_copy(deep=True) for m in tool_msgs]
                )
                if self.calls == 1:
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="agent",
                            tool_calls=[
                                ToolCall(id="call-1", name="get_weather_forecast", arguments={})
                            ],
                        )
                    )
                elif self.calls == 2:
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="agent",
                            tool_calls=[
                                ToolCall(id="call-2", name="get_f1_driver_standings", arguments={})
                            ],
                        )
                    )
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="Final answer.")
                )

        tool_a_desc = get_capability_descriptor("get_weather_forecast")
        tool_b_desc = get_capability_descriptor("get_f1_driver_standings")

        large_payload = {"data": "x" * 1000}

        def dispatcher(name: str, _args: dict[str, object]) -> object:
            if name == "get_weather_forecast":
                return large_payload
            return {"result": "step_2_done"}

        profile = build_cloud_profile(model="gemini-3.7-flash")
        response = run_agent_loop(
            AgentQueryRequest(prompt="Run multi-step", agent="apex"),
            MultiTurnProvider(),
            profile,
            tools_dispatcher=dispatcher,
            selected_tools=[tool_a_desc, tool_b_desc],
        )

        self.assertEqual(response.answer, "Final answer.")
        self.assertEqual(len(turn_history_snapshots[0]), 0)
        self.assertEqual(len(turn_history_snapshots[1]), 1)
        self.assertEqual(turn_history_snapshots[1][0].tool_results[0].output, large_payload)
        self.assertEqual(len(turn_history_snapshots[2]), 2)
        step_1_res = turn_history_snapshots[2][0].tool_results[0].output
        self.assertIn("compacted", str(step_1_res))
        self.assertEqual(turn_history_snapshots[2][1].tool_results[0].output, {"result": "step_2_done"})
        self.assertEqual(response.tool_outputs[0]["output"], large_payload)

    def test_multi_step_turn_tool_compaction_is_idempotent(self) -> None:
        from core.agent.loop import _compact_tool_result_output

        large_payload = {"data": "x" * 1000}
        compacted = _compact_tool_result_output(large_payload)
        self.assertTrue(isinstance(compacted, dict) and compacted.get("compacted") is True)

        # Re-compacting already compacted output must be idempotent (no nested wrapping)
        recompacted = _compact_tool_result_output(compacted)
        self.assertEqual(recompacted, compacted)

        # String compaction idempotency
        large_str = "x" * 1000
        compacted_str = _compact_tool_result_output(large_str)
        self.assertTrue(compacted_str.endswith("... [prior step output compacted]"))
        recompacted_str = _compact_tool_result_output(compacted_str)
        self.assertEqual(recompacted_str, compacted_str)


if __name__ == "__main__":
    unittest.main()
