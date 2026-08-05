from __future__ import annotations

import unittest
from typing import Any

from core.agent.capabilities import CapabilityDescriptor
from core.agent.loop import run_agent_loop
from core.agent.providers.litert import (
    LiteRTProvider,
    LiteRTProviderError,
    LiteRTProviderSession,
    normalize_litert_response,
)
from core.agent.providers.litert_models import LiteRTModelProfile
from core.agent.providers.litert_protocol import LiteRTInferenceAmbiguousError
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall, ToolResult


def _profile() -> LiteRTModelProfile:
    return LiteRTModelProfile(
        display_name="Test LiteRT",
        agent_version="1.0",
        api_model="litert-test/model",
        tier="lightweight",
        stability="preview",
        max_tool_turns=3,
        max_tool_calls=4,
        system_instruction="You are a test local agent.",
        artifact_path="test.litertlm",
    )


def _descriptor(name: str = "get_current_date_time") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        title=name,
        description="test capability",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        origin="native",
        risk="read",
        expose_to_agent=True,
        expose_to_mcp_server=False,
        expose_to_client_display=True,
    )


class FakeRuntime:
    def __init__(self, responses: list[dict[str, Any] | BaseException]) -> None:
        self.responses = list(responses)
        self.opened: list[dict[str, Any]] = []
        self.sent: list[tuple[str, Any]] = []
        self.closed: list[str] = []

    def open_conversation(self, **kwargs: Any) -> dict[str, Any]:
        self.opened.append(kwargs)
        return {"conversation_id": kwargs["conversation_id"]}

    def send_message(self, conversation_id: str, message: Any, *, timeout: float) -> dict[str, Any]:
        del timeout
        self.sent.append((conversation_id, message))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def close_conversation(self, conversation_id: str) -> dict[str, Any]:
        self.closed.append(conversation_id)
        return {"closed": True}


class LiteRTNormalizationTests(unittest.TestCase):
    def test_native_structured_calls_and_synthesized_ids(self) -> None:
        text, calls = normalize_litert_response(
            {
                "content": [{"type": "text", "text": "Need time."}],
                "tool_calls": [
                    {"type": "function", "function": {"name": "get_current_date_time", "arguments": {}}},
                    {"type": "function", "function": {"name": "get_upcoming_calendar_events", "arguments": {"days": 1}}},
                ],
            },
            conversation_id="litert:test",
            turn_number=2,
        )
        self.assertEqual(text, "Need time.")
        self.assertEqual([call.name for call in calls], ["get_current_date_time", "get_upcoming_calendar_events"])
        self.assertEqual(calls[0].id, "litert:litert:test:2:0")
        self.assertEqual(calls[1].arguments, {"days": 1})

    def test_text_function_markup_is_not_parsed_and_non_object_arguments_are_rejected(self) -> None:
        text, calls = normalize_litert_response(
            {"content": "<function=get_current_date_time>", "tool_calls": []},
            conversation_id="c",
            turn_number=1,
        )
        self.assertEqual(text, "<function=get_current_date_time>")
        self.assertEqual(calls, [])
        with self.assertRaises(LiteRTProviderError):
            normalize_litert_response(
                {
                    "tool_calls": [
                        {"function": {"name": "get_current_date_time", "arguments": "{}"}}
                    ]
                },
                conversation_id="c",
                turn_number=1,
            )


class LiteRTSessionTests(unittest.TestCase):
    def test_structured_tool_results_match_outstanding_calls(self) -> None:
        runtime = FakeRuntime(
            [
                {
                    "tool_calls": [
                        {"function": {"name": "get_current_date_time", "arguments": {}}},
                        {"function": {"name": "get_upcoming_calendar_events", "arguments": {}}},
                    ]
                },
                {"content": [{"type": "text", "text": "Done."}]},
            ]
        )
        provider = LiteRTProvider(runtime)  # type: ignore[arg-type]
        profile = _profile()
        session = provider.create_session(profile, [_descriptor(), _descriptor("get_upcoming_calendar_events")])
        first = session.generate_turn([AgentMessage(role="user", content="Schedule?")], [], profile)
        calls = first.message.tool_calls
        assert calls is not None
        results = [
            ToolResult(id=call.id, name=call.name, output={"ok": call.name}) for call in calls
        ]
        second = session.generate_turn(
            [
                AgentMessage(role="user", content="Schedule?"),
                first.message,
                AgentMessage(role="tool", tool_results=results),
            ],
            [],
            profile,
        )
        self.assertEqual(second.message.content, "Done.")
        native_tool_message = runtime.sent[1][1]
        self.assertEqual(native_tool_message["role"], "tool")
        self.assertEqual(len(native_tool_message["content"]), 2)
        self.assertIn("untrusted_tool_output", native_tool_message["content"][0]["response"])
        session.close()
        session.close()
        self.assertEqual(len(runtime.closed), 1)

    def test_mismatched_tool_result_is_rejected_without_submission(self) -> None:
        runtime = FakeRuntime(
            [{"tool_calls": [{"function": {"name": "get_current_date_time", "arguments": {}}}]}]
        )
        session = LiteRTProvider(runtime).create_session(_profile(), [_descriptor()])  # type: ignore[arg-type]
        first = session.generate_turn([AgentMessage(role="user", content="Time?")], [], _profile())
        assert first.message.tool_calls is not None
        with self.assertRaises(LiteRTProviderError):
            session.generate_turn(
                [
                    AgentMessage(role="user", content="Time?"),
                    first.message,
                    AgentMessage(
                        role="tool",
                        tool_results=[ToolResult(id="wrong", name="get_current_date_time", output={})],
                    ),
                ],
                [],
                _profile(),
            )
        self.assertEqual(len(runtime.sent), 1)

    def test_ambiguous_inference_poisons_session_and_never_closes_or_replays(self) -> None:
        runtime = FakeRuntime([LiteRTInferenceAmbiguousError("ambiguous")])
        session = LiteRTProvider(runtime).create_session(_profile(), [_descriptor()])  # type: ignore[arg-type]
        with self.assertRaises(LiteRTInferenceAmbiguousError):
            session.generate_turn([AgentMessage(role="user", content="Time?")], [], _profile())
        session.close()
        self.assertEqual(len(runtime.sent), 1)
        self.assertEqual(runtime.closed, [])

    def test_independent_sessions_have_distinct_conversations(self) -> None:
        runtime = FakeRuntime([
            {"content": [{"type": "text", "text": "one"}]},
            {"content": [{"type": "text", "text": "two"}]},
        ])
        provider = LiteRTProvider(runtime)  # type: ignore[arg-type]
        profile = _profile()
        first = provider.create_session(profile, [])
        second = provider.create_session(profile, [])
        first.generate_turn([AgentMessage(role="user", content="one")], [], profile)
        second.generate_turn([AgentMessage(role="user", content="two")], [], profile)
        self.assertNotEqual(first.conversation_id, second.conversation_id)
        first.close()
        second.close()
        self.assertEqual(len(runtime.opened), 2)
        self.assertEqual(len(runtime.closed), 2)


class LiteRTLoopIntegrationTests(unittest.TestCase):
    def test_existing_loop_dispatches_litert_tools_and_keeps_usage_null_cost_zero(self) -> None:
        runtime = FakeRuntime(
            [
                {"tool_calls": [{"function": {"name": "get_current_date_time", "arguments": {}}}]},
                {"content": [{"type": "text", "text": "The time is confirmed."}]},
            ]
        )
        profile = _profile()
        response = run_agent_loop(
            AgentQueryRequest(prompt="What time is it?", agent="microtus", tool_scope="schedule"),
            LiteRTProvider(runtime),  # type: ignore[arg-type]
            profile,
            tools_dispatcher=lambda name, _args: {"tool": name},
        )
        self.assertEqual(response.answer, "The time is confirmed.")
        self.assertIsNone(response.usage)
        assert response.cost_estimate is not None
        self.assertEqual(response.cost_estimate.total_cost, 0.0)
        self.assertEqual(response.tool_trace[0]["name"], "get_current_date_time")
        self.assertIsNotNone(response.local_context_usage)


if __name__ == "__main__":
    unittest.main()
