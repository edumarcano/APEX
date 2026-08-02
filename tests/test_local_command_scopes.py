"""Regression coverage for bounded local assistant command scopes."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core.agent.capabilities import CapabilityDescriptor
from core.agent.local_commands import (
    ResolvedLocalCommand,
    _estimate_schema_tokens,
    _project_local_descriptor,
    list_local_command_statuses,
)
from core.agent.loop import run_agent_loop
from core.agent.providers.contract import ProviderTurnResult
from core.agent.profiles import build_concrete_profile, resolve_effort
from core.agent.profiles import build_concrete_profile, resolve_effort
from core.agent.providers.ollama import (
    OllamaProvider,
    _budget_payload,
    _build_payload,
    _estimate_payload_tokens,
)
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES


def _cloud_profile(key: str = "neofelis"):
    _apex, native = resolve_effort(key, None)
    return build_concrete_profile(key, native_effort=native)
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall


class _CapturingProvider:
    def __init__(self, responses: list[AgentMessage]) -> None:
        self.responses = responses
        self.tool_names: list[list[str]] = []
        self.system_instructions: list[str | None] = []

    def generate_turn(
        self,
        _messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        _profile: object,
        system_instruction_override: str | None = None,
    ) -> ProviderTurnResult:
        self.tool_names.append([tool.name for tool in tools])
        self.system_instructions.append(system_instruction_override)
        return ProviderTurnResult(message=self.responses.pop(0))


class LocalCommandScopeTests(unittest.TestCase):
    def test_catalog_has_approved_commands_without_github_or_auto(self) -> None:
        statuses = list_local_command_statuses()
        commands = {status.command for status in statuses}

        self.assertEqual(
            commands,
            {
                "/schedule",
                "/weather",
                "/f1",
                "/mail",
                "/search",
                "/market",
                "/briefings",
                "/todo",
            },
        )
        self.assertNotIn("/github", commands)
        self.assertNotIn("/auto", commands)

    def test_local_query_without_scope_receives_no_tools(self) -> None:
        provider = _CapturingProvider(
            [AgentMessage(role="model", content="No live lookup performed.")]
        )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Hello", profile="sorex"),
            provider,
            OLLAMA_MODEL_PROFILES["sorex"],
        )

        self.assertEqual(provider.tool_names, [[]])
        self.assertIsNone(response.tool_scope_used)
        self.assertIsNotNone(response.local_context_usage)

    def test_search_projection_replaces_verbose_schema_without_mutating_source(
        self,
    ) -> None:
        verbose_descriptor = CapabilityDescriptor(
            name="brave_brave_web_search",
            title="Brave Web Search",
            description="Verbose remote description " * 200,
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    **{
                        f"remote_option_{index}": {
                            "type": "string",
                            "description": "Verbose option " * 30,
                        }
                        for index in range(20)
                    },
                },
                "required": ["query"],
            },
            origin="mcp",
            risk="read",
            expose_to_assistant=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )

        projected = _project_local_descriptor("search", verbose_descriptor)

        self.assertEqual(
            set(projected.input_schema["properties"]),
            {"query", "count"},
        )
        self.assertLess(_estimate_schema_tokens([projected]), 250)
        self.assertIn("remote_option_0", verbose_descriptor.input_schema["properties"])

    def test_non_search_projection_preserves_descriptor(self) -> None:
        descriptor = CapabilityDescriptor(
            name="get_weather_forecast",
            title="Weather",
            description="Weather forecast.",
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_assistant=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )

        self.assertIs(_project_local_descriptor("weather", descriptor), descriptor)

    def test_weather_scope_exposes_only_weather_and_rejects_other_calls(self) -> None:
        provider = _CapturingProvider(
            [
                AgentMessage(
                    role="model",
                    tool_calls=[
                        ToolCall(
                            id="bad-call",
                            name="get_active_reminders",
                            arguments={},
                        )
                    ],
                ),
                AgentMessage(role="model", content="Done."),
            ]
        )
        dispatched: list[str] = []

        resolution = ResolvedLocalCommand(
            scope="weather",
            descriptors=(
                CapabilityDescriptor(
                    name="get_weather_forecast",
                    title="Weather",
                    description="Weather forecast.",
                    input_schema={"type": "object", "properties": {}},
                    origin="native",
                    risk="read",
                    expose_to_assistant=True,
                    expose_to_mcp_server=False,
                    expose_to_client_display=True,
                ),
            ),
            missing_tool_names=(),
        )
        with patch("core.agent.loop.resolve_local_command") as resolver:
            response = run_agent_loop(
                AgentQueryRequest(
                    prompt="Forecast",
                    profile="sorex",
                    tool_scope="weather",
                ),
                provider,
                OLLAMA_MODEL_PROFILES["sorex"],
                tools_dispatcher=lambda name, _arguments: dispatched.append(name),
                resolved_local_command=resolution,
            )

        resolver.assert_not_called()
        self.assertEqual(provider.tool_names[0], ["get_weather_forecast"])
        self.assertEqual(dispatched, [])
        self.assertEqual(
            response.tool_outputs[0]["output"]["error_category"],
            "unavailable",
        )

    def test_cloud_query_retains_automatic_tools(self) -> None:
        provider = _CapturingProvider([AgentMessage(role="model", content="Done.")])

        response = run_agent_loop(
            AgentQueryRequest(prompt="Hello", profile="neofelis"),
            provider,
            _cloud_profile("neofelis"),
        )

        self.assertGreater(len(provider.tool_names[0]), 0)
        self.assertIsNone(response.local_context_usage)

    def test_cloud_final_turn_withholds_tools_for_answer(self) -> None:
        provider = _CapturingProvider(
            [
                AgentMessage(
                    role="model",
                    tool_calls=[
                        ToolCall(
                            id="weather-call",
                            name="get_weather_forecast",
                            arguments={"days": 1},
                        )
                    ],
                ),
                AgentMessage(role="model", content="Forecast ready."),
            ]
        )
        profile = _cloud_profile("neofelis").model_copy(
            update={"max_tool_turns": 2}
        )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Forecast", profile="neofelis"),
            provider,
            profile,
            tools_dispatcher=lambda _name, _arguments: {"forecast": "clear"},
        )

        self.assertGreater(len(provider.tool_names[0]), 0)
        self.assertEqual(provider.tool_names[1], [])
        self.assertNotIn("FINAL ANSWER PHASE", provider.system_instructions[0] or "")
        self.assertIn("FINAL ANSWER PHASE", provider.system_instructions[1] or "")
        self.assertEqual(response.answer, "Forecast ready.")
        self.assertIsNone(response.error)

    def test_budget_trims_oldest_complete_interaction(self) -> None:
        profile = OLLAMA_MODEL_PROFILES["sorex"].model_copy(
            update={"context_window": 1400, "final_answer_max_tokens": 128}
        )
        history = [
            AgentMessage(role="user", content="old " * 700),
            AgentMessage(role="model", content="old answer"),
            AgentMessage(role="user", content="current question"),
        ]

        payload, _estimated, dropped = _budget_payload(
            history,
            [],
            profile,
            "Short system instruction.",
            num_predict=profile.final_answer_max_tokens,
        )

        contents = [message["content"] for message in payload["messages"]]
        self.assertEqual(dropped, 2)
        self.assertNotIn("old answer", contents)
        self.assertIn("current question", contents)

    def test_security_directive_does_not_claim_tools_are_available(self) -> None:
        profile = OLLAMA_MODEL_PROFILES["sorex"]
        payload = _build_payload(
            [AgentMessage(role="user", content="Hello")],
            [],
            profile,
            "Short system instruction.",
            num_predict=profile.final_answer_max_tokens,
        )

        system_content = payload["messages"][0]["content"]
        self.assertIn("when present", system_content)
        self.assertNotIn("You have access to external tools", system_content)

    def test_truncated_tool_turn_rebudgets_for_larger_final_answer(self) -> None:
        profile = OLLAMA_MODEL_PROFILES["mus"].model_copy(
            update={
                "context_window": 2200,
                "tool_select_max_tokens": 64,
                "final_answer_max_tokens": 512,
            }
        )
        descriptor = CapabilityDescriptor(
            name="get_weather_forecast",
            title="Weather",
            description="Weather forecast.",
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_assistant=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )
        messages: list[AgentMessage] | None = None
        for word_count in range(100, 1200, 25):
            candidate = [
                AgentMessage(role="user", content="old " * word_count),
                AgentMessage(role="model", content="old answer"),
                AgentMessage(role="user", content="current question"),
            ]
            try:
                _tool_payload, _tool_estimate, tool_dropped = _budget_payload(
                    candidate,
                    [descriptor],
                    profile,
                    "Short system instruction.",
                    num_predict=profile.tool_select_max_tokens,
                )
                _final_payload, _final_estimate, final_dropped = _budget_payload(
                    candidate,
                    [],
                    profile,
                    "Short system instruction.",
                    num_predict=profile.final_answer_max_tokens,
                )
            except RuntimeError:
                continue
            if tool_dropped == 0 and final_dropped > 0:
                messages = candidate
                break
        self.assertIsNotNone(messages)

        responses = [
            {
                "message": {"role": "assistant", "content": "partial"},
                "done_reason": "length",
                "prompt_eval_count": 900,
            },
            {
                "message": {"role": "assistant", "content": "Final answer."},
                "done_reason": "stop",
                "prompt_eval_count": 600,
            },
        ]
        payloads: list[dict[str, object]] = []

        def fake_post(payload: dict[str, object], _profile: object) -> dict[str, object]:
            payloads.append(payload)
            return responses.pop(0)

        with patch("core.agent.providers.ollama._post_chat", side_effect=fake_post):
            result = OllamaProvider().generate_turn(
                messages or [],
                [descriptor],
                profile,
                system_instruction_override="Short system instruction.",
            )

        self.assertEqual(result.message.content, "Final answer.")
        self.assertEqual(len(payloads), 2)
        retry_payload = payloads[1]
        self.assertNotIn("tools", retry_payload)
        self.assertEqual(
            retry_payload["options"]["num_predict"],  # type: ignore[index]
            profile.final_answer_max_tokens,
        )
        retry_target = (
            profile.context_window
            - profile.final_answer_max_tokens
            - 512
        )
        self.assertLessEqual(_estimate_payload_tokens(retry_payload), retry_target)
        self.assertGreater(result.history_messages_dropped, 0)


if __name__ == "__main__":
    unittest.main()
