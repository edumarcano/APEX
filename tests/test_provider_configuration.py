"""Unit tests verifying Gemini provider temperature omission and Ollama temperature retention."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.agent.catalog import build_provider_profile, resolve_effort
from core.agent.capabilities import CapabilityDescriptor
from core.agent.loop import run_agent_loop
from core.agent.model_catalog import get_model_profile
from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage, AgentQueryRequest, ToolCall
from core.config import CORTEX_RUNS_MAX_TOOL_CALLS, CORTEX_RUNS_MAX_MODEL_TURNS

def _concrete_profile(model_id: str):
    model_profile = get_model_profile(model_id)
    assert model_profile is not None
    native = resolve_effort(model_profile, None)
    return build_provider_profile(
        native_effort=native,
        model_id=model_id,
    )


class GeminiProviderTemperatureTests(unittest.TestCase):
    def test_cloud_agents_apply_quota_aware_loop_caps(self) -> None:
        for model_id in ("gpt-5.6-luna", "deepseek/deepseek-v4-flash-0731", "gemini-3.7-flash"):
            with self.subTest(model=model_id):
                profile = get_model_profile(model_id)
                assert profile is not None
                self.assertGreaterEqual(profile.max_tool_turns, 2)
                self.assertGreaterEqual(profile.max_tool_calls, profile.max_tool_turns)
                self.assertLessEqual(profile.max_tool_turns, CORTEX_RUNS_MAX_MODEL_TURNS)
                self.assertLessEqual(profile.max_tool_calls, CORTEX_RUNS_MAX_TOOL_CALLS)

    def test_local_models_respect_loop_caps_and_leave_a_final_answer_turn(self) -> None:
        local_model_ids = (
            "qwen3:1.7b",
            "qwen3:4b-instruct",
            "gemma-4-E2B-Q4_K_M.gguf",
            "gemma-4-E4B-Q4_K_M.gguf",
            "Qwen3.5-4B-Q4_K_M.gguf",
        )
        for model_id in local_model_ids:
            with self.subTest(model=model_id):
                profile = get_model_profile(model_id)
                assert profile is not None
                self.assertGreaterEqual(profile.max_tool_turns, 2)
                self.assertGreaterEqual(profile.max_tool_calls, profile.max_tool_turns)
                self.assertLessEqual(profile.max_tool_turns, CORTEX_RUNS_MAX_MODEL_TURNS)
                self.assertLessEqual(profile.max_tool_calls, CORTEX_RUNS_MAX_TOOL_CALLS)

        profile = build_provider_profile(
            native_effort=None,
            local_reasoning_mode="none",
            model_id="qwen3:1.7b",
        ).model_copy(update={"max_tool_turns": 2, "max_tool_calls": 1})
        descriptor = CapabilityDescriptor(
            name="get_weather_forecast",
            title="Weather",
            description="Read a forecast",
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )

        class Provider:
            def __init__(self) -> None:
                self.offered_tools: list[list[CapabilityDescriptor]] = []

            def generate_turn(
                self,
                _messages: list[AgentMessage],
                tools: list[CapabilityDescriptor],
                _profile: object,
                system_instruction_override: str | None = None,
                *,
                execution_control: object | None = None,
                stream_observer: object | None = None,
                output_schema: dict[str, object] | None = None,
            ) -> ProviderTurnResult:
                del system_instruction_override, execution_control, stream_observer, output_schema
                self.offered_tools.append(tools)
                if tools:
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="agent",
                            tool_calls=[
                                ToolCall(
                                    id="weather-1",
                                    name="get_weather_forecast",
                                    arguments={},
                                )
                            ],
                        )
                    )
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="It will be sunny.")
                )

        provider = Provider()
        dispatched: list[str] = []
        response = run_agent_loop(
            AgentQueryRequest(prompt="What is the weather?", agent="apex"),
            provider,
            profile,
            tools_dispatcher=lambda name, _arguments: dispatched.append(name) or "Sunny",
            selected_tools=[descriptor],
        )

        self.assertEqual(response.answer, "It will be sunny.")
        self.assertIsNone(response.error)
        self.assertEqual(dispatched, ["get_weather_forecast"])
        self.assertEqual(provider.offered_tools, [[descriptor], []])

    @patch("core.agent.providers.gemini.genai.Client")
    def test_gemini_provider_config_omits_temperature(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Verify GeminiProvider does not pass temperature to GenerateContentConfig."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_part = MagicMock()
        mock_part.text = "Test response"
        mock_part.thought = False
        mock_part.function_call = None
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_chunk = MagicMock()
        mock_chunk.candidates = [mock_candidate]
        mock_client.models.generate_content_stream.return_value = [mock_chunk]

        provider = GeminiProvider(api_key="test-api-key")
        profile = _concrete_profile("gemini-3.7-flash")
        messages = [AgentMessage(role="user", content="Hello")]

        provider.generate_turn(messages=messages, tools=[], profile=profile)

        mock_client.models.generate_content_stream.assert_called_once()
        _args, kwargs = mock_client.models.generate_content_stream.call_args
        config = kwargs["config"]
        self.assertFalse(hasattr(config, "temperature") and config.temperature is not None)
        self.assertEqual(kwargs["model"], "gemini-3.7-flash")

    @patch("core.agent.providers.ollama.get_http_session")
    def test_ollama_provider_retains_temperature(
        self, mock_get_session: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Done."},
            "done": True,
        }
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_get_session.return_value = mock_session

        provider = OllamaProvider()
        profile = _concrete_profile("qwen3:1.7b")
        provider.generate_turn(
            [AgentMessage(role="user", content="Hello")],
            [],
            profile,
        )

        payload = mock_session.post.call_args.kwargs["json"]
        self.assertIn("temperature", payload["options"])


if __name__ == "__main__":
    unittest.main()
