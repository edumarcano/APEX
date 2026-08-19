"""OpenRouter privacy-routing and Chat Completions adapter coverage."""

from __future__ import annotations

import unittest
from unittest import mock

from core.agent.providers.openrouter import (
    OPENROUTER_API_BASE_URL,
    OPENROUTER_REQUEST_TIMEOUT_SECONDS,
    OPENROUTER_PRIVACY_POLICY,
    OpenRouterModelProfile,
    OpenRouterProvider,
    _messages_to_chat,
)
from core.agent.types import AgentMessage, ToolCall, ToolResult


class OpenRouterProviderTests(unittest.TestCase):
    def _profile(self, effort: str = "high") -> OpenRouterModelProfile:
        return OpenRouterModelProfile(
            display_name="Apex Panthera",
            api_model="deepseek/deepseek-v4-flash-0731",
            max_tool_turns=6,
            max_tool_calls=10,
            system_instruction="System instruction.",
            reasoning_effort=effort,
        )

    @mock.patch("core.agent.providers.openrouter.OpenAI")
    def test_request_enforces_privacy_policy_and_normalizes_usage(self, client_cls: mock.Mock) -> None:
        response = mock.Mock()
        response.model_dump.return_value = {
            "model": "deepseek/deepseek-v4-flash-0731",
            "choices": [{"message": {"content": "done"}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 12,
                "total_tokens": 32,
                "prompt_tokens_details": {"cached_tokens": 4},
                "completion_tokens_details": {"reasoning_tokens": 7},
            },
        }
        client_cls.return_value.chat.completions.create.return_value = response

        result = OpenRouterProvider("secret").generate_turn(
            [AgentMessage(role="user", content="hello")], [], self._profile("none")
        )

        client_cls.assert_called_once_with(
            api_key="secret",
            base_url=OPENROUTER_API_BASE_URL,
            max_retries=0,
            timeout=OPENROUTER_REQUEST_TIMEOUT_SECONDS,
        )
        request = client_cls.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request["model"], "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(
            request["extra_body"],
            {**OPENROUTER_PRIVACY_POLICY, "reasoning": {"effort": "none"}},
        )
        self.assertNotIn("reasoning", request)
        self.assertIn("SECURITY BOUNDARY", request["messages"][0]["content"])
        self.assertEqual(result.message.content, "done")
        self.assertEqual(result.usage.input_tokens, 20)
        self.assertEqual(result.usage.cached_input_tokens, 4)
        self.assertEqual(result.usage.reasoning_tokens, 7)
        self.assertEqual(result.usage.output_tokens, 5)

    @mock.patch("core.agent.providers.openrouter.OpenAI")
    def test_all_reasoning_efforts_are_sent_inside_extra_body(self, client_cls: mock.Mock) -> None:
        response = mock.Mock()
        response.model_dump.return_value = {
            "model": "deepseek/deepseek-v4-flash-0731",
            "choices": [{"message": {"content": "done"}}],
        }
        client_cls.return_value.chat.completions.create.return_value = response

        for effort in ("none", "low", "high", "max"):
            with self.subTest(effort=effort):
                OpenRouterProvider("secret").generate_turn(
                    [AgentMessage(role="user", content="hello")],
                    [],
                    self._profile(effort),
                )
                request = client_cls.return_value.chat.completions.create.call_args.kwargs
                self.assertEqual(request["extra_body"]["reasoning"], {"effort": effort})
                self.assertEqual(
                    request["extra_body"]["provider"],
                    OPENROUTER_PRIVACY_POLICY["provider"],
                )

    @mock.patch("core.agent.providers.openrouter.time.sleep")
    @mock.patch("core.agent.providers.openrouter.OpenAI")
    def test_retry_reuses_the_complete_privacy_policy(
        self,
        client_cls: mock.Mock,
        sleep: mock.Mock,
    ) -> None:
        from httpx import Request
        from openai import APIConnectionError

        response = mock.Mock()
        response.model_dump.return_value = {
            "model": "deepseek/deepseek-v4-flash-0731",
            "choices": [{"message": {"content": "done"}}],
        }
        client_cls.return_value.chat.completions.create.side_effect = [
            APIConnectionError(request=Request("POST", OPENROUTER_API_BASE_URL)),
            response,
        ]

        OpenRouterProvider("secret").generate_turn(
            [AgentMessage(role="user", content="hello")], [], self._profile("high")
        )

        calls = client_cls.return_value.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(
                call.kwargs["extra_body"],
                {**OPENROUTER_PRIVACY_POLICY, "reasoning": {"effort": "high"}},
            )
        sleep.assert_called_once()

    def test_tool_continuation_preserves_reasoning_details_and_wraps_output(self) -> None:
        details = [{"type": "reasoning.encrypted", "data": "opaque"}]
        messages = [
            AgentMessage(
                role="agent",
                tool_calls=[ToolCall(id="call_1", name="weather", arguments={"city": "NYC"})],
                provider_reasoning_details=details,
            ),
            AgentMessage(
                role="tool",
                tool_results=[ToolResult(id="call_1", name="weather", output={"temp": 72})],
            ),
        ]

        chat = _messages_to_chat(messages, "system")

        self.assertEqual(chat[1]["reasoning_details"], details)
        self.assertEqual(chat[1]["tool_calls"][0]["function"]["name"], "weather")
        self.assertEqual(chat[2]["role"], "tool")
        self.assertIn("<untrusted_tool_output", chat[2]["content"])
        self.assertNotIn("provider_reasoning_details", AgentMessage(role="agent", provider_reasoning_details=details).model_dump())


if __name__ == "__main__":
    unittest.main()
