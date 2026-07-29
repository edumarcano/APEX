"""Regression coverage for bounded local assistant command scopes."""

from __future__ import annotations

import unittest

from core.agent.capabilities import CapabilityDescriptor
from core.agent.local_commands import list_local_command_statuses
from core.agent.loop import run_agent_loop
from core.agent.providers.gemini_models import GEMINI_MODEL_PROFILES
from core.agent.providers.ollama import _budget_payload
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall


class _CapturingProvider:
    def __init__(self, responses: list[AgentMessage]) -> None:
        self.responses = responses
        self.tool_names: list[list[str]] = []

    def generate_turn(
        self,
        _messages: list[AgentMessage],
        tools: list[CapabilityDescriptor],
        _profile: object,
        system_instruction_override: str | None = None,
    ) -> AgentMessage:
        del system_instruction_override
        self.tool_names.append([tool.name for tool in tools])
        return self.responses.pop(0)


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
            },
        )
        self.assertNotIn("/github", commands)
        self.assertNotIn("/auto", commands)

    def test_local_query_without_scope_receives_no_tools(self) -> None:
        provider = _CapturingProvider(
            [AgentMessage(role="model", content="No live lookup performed.")]
        )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Hello", profile="lynx"),
            provider,
            OLLAMA_MODEL_PROFILES["lynx"],
        )

        self.assertEqual(provider.tool_names, [[]])
        self.assertIsNone(response.tool_scope_used)
        self.assertIsNotNone(response.local_context_usage)

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

        response = run_agent_loop(
            AgentQueryRequest(
                prompt="Forecast",
                profile="lynx",
                tool_scope="weather",
            ),
            provider,
            OLLAMA_MODEL_PROFILES["lynx"],
            tools_dispatcher=lambda name, _arguments: dispatched.append(name),
        )

        self.assertEqual(provider.tool_names[0], ["get_weather_forecast"])
        self.assertEqual(dispatched, [])
        self.assertEqual(
            response.tool_outputs[0]["output"]["error_category"],
            "unavailable",
        )

    def test_cloud_query_retains_automatic_tools(self) -> None:
        provider = _CapturingProvider([AgentMessage(role="model", content="Done.")])

        response = run_agent_loop(
            AgentQueryRequest(prompt="Hello", profile="comet"),
            provider,
            GEMINI_MODEL_PROFILES["comet"],
        )

        self.assertGreater(len(provider.tool_names[0]), 0)
        self.assertIsNone(response.local_context_usage)

    def test_budget_trims_oldest_complete_interaction(self) -> None:
        profile = OLLAMA_MODEL_PROFILES["lynx"].model_copy(
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


if __name__ == "__main__":
    unittest.main()
