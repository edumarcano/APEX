"""Provider runtime contract, pricing, retries, and Responses adapter coverage."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from google.genai.errors import APIError

from core.agent.capabilities import CapabilityDescriptor
from core.agent.loop import run_agent_loop
from core.agent.pricing import PRICING_VERSION, estimate_inference_cost
from core.agent.providers.contract import (
    ProviderToolEvent,
    ProviderTurnResult,
    merge_token_usage,
    resolve_inference_provider,
)
from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.gemini_models import GEMINI_MODEL_PROFILES
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES
from core.agent.providers.openai_provider import OPENAI_INTERNAL_PROFILES, OpenAIProvider
from core.agent.providers.responses_api import (
    assert_no_forbidden_native_tools,
    _messages_to_responses_input,
    _parse_usage,
)
from core.agent.providers.retries import call_with_bounded_retries
from core.agent.providers.xai_provider import XAI_INTERNAL_PROFILES, XAIProvider
from core.agent.tool_schemas import descriptor_to_responses_tool
from core.agent.types import AgentMessage, AgentQueryRequest, TokenUsage, ToolCall, ToolResult


class ProviderContractTests(unittest.TestCase):
    def test_resolve_inference_provider_for_existing_profiles(self) -> None:
        self.assertEqual(
            resolve_inference_provider(GEMINI_MODEL_PROFILES["comet"]), "gemini"
        )
        self.assertEqual(
            resolve_inference_provider(OLLAMA_MODEL_PROFILES["lynx"]), "ollama"
        )
        self.assertEqual(
            resolve_inference_provider(OPENAI_INTERNAL_PROFILES["openai_default"]),
            "openai",
        )
        self.assertEqual(
            resolve_inference_provider(XAI_INTERNAL_PROFILES["xai_default"]), "xai"
        )

    def test_merge_token_usage_sums_nullable_fields(self) -> None:
        merged = merge_token_usage(
            TokenUsage(input_tokens=10, output_tokens=4),
            TokenUsage(input_tokens=5, reasoning_tokens=2, output_tokens=1),
        )
        assert merged is not None
        self.assertEqual(merged.input_tokens, 15)
        self.assertEqual(merged.output_tokens, 5)
        self.assertEqual(merged.reasoning_tokens, 2)
        self.assertEqual(merged.total_tokens, 22)

    def test_loop_aggregates_usage_timing_cost_and_apex_origin(self) -> None:
        class Provider:
            def __init__(self) -> None:
                self.calls = 0

            def generate_turn(
                self,
                _messages: list[AgentMessage],
                _tools: list[CapabilityDescriptor],
                _profile: object,
                system_instruction_override: str | None = None,
            ) -> ProviderTurnResult:
                del system_instruction_override
                self.calls += 1
                if self.calls == 1:
                    return ProviderTurnResult(
                        message=AgentMessage(
                            role="model",
                            tool_calls=[
                                ToolCall(
                                    id="call-1",
                                    name="get_weather_forecast",
                                    arguments={"days": 1},
                                )
                            ],
                        ),
                        resolved_model="gemini-3.5-flash-lite-rev",
                        usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
                        provider_ms=12.5,
                    )
                return ProviderTurnResult(
                    message=AgentMessage(role="model", content="Clear skies."),
                    resolved_model="gemini-3.5-flash-lite-rev",
                    usage=TokenUsage(input_tokens=140, output_tokens=30, total_tokens=170),
                    provider_ms=8.0,
                )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Weather?", profile="comet"),
            Provider(),
            GEMINI_MODEL_PROFILES["comet"],
            tools_dispatcher=lambda _name, _args: {"summary": "clear"},
        )

        self.assertEqual(response.answer, "Clear skies.")
        self.assertEqual(response.resolved_model, "gemini-3.5-flash-lite-rev")
        assert response.usage is not None
        self.assertEqual(response.usage.input_tokens, 240)
        self.assertEqual(response.usage.output_tokens, 50)
        assert response.timing is not None
        self.assertGreaterEqual(response.timing.provider_ms or 0, 20.5)
        self.assertGreaterEqual(response.timing.apex_tool_ms or 0, 0)
        assert response.cost_estimate is not None
        self.assertEqual(response.cost_estimate.pricing_version, PRICING_VERSION)
        self.assertEqual(response.cost_estimate.completeness, "complete")
        self.assertEqual(response.tool_trace[0]["origin"], "apex")
        self.assertEqual(
            {key for key in GEMINI_MODEL_PROFILES},
            {"comet", "nova", "pulsar"},
        )


class PricingRegistryTests(unittest.TestCase):
    def test_token_cost_excludes_mcp_and_marks_unknown_hosted_partial(self) -> None:
        estimate = estimate_inference_cost(
            model="gemini-3.5-flash",
            usage=TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000),
            hosted_tool_events=[
                ProviderToolEvent(name="google_search", status="ok", billable_units=2),
                ProviderToolEvent(name="unknown_hosted", status="ok", billable_units=1),
            ],
        )
        self.assertAlmostEqual(estimate.token_cost or 0.0, 2.80, places=4)
        self.assertAlmostEqual(estimate.hosted_tool_cost or 0.0, 0.07, places=4)
        self.assertEqual(estimate.completeness, "partial")
        self.assertEqual(estimate.pricing_version, PRICING_VERSION)

    def test_local_ollama_models_are_zero_cost(self) -> None:
        estimate = estimate_inference_cost(
            model="qwen3:1.7b",
            usage=TokenUsage(input_tokens=1000, output_tokens=200, total_tokens=1200),
        )
        self.assertEqual(estimate.token_cost, 0.0)
        self.assertEqual(estimate.hosted_tool_cost, 0.0)
        self.assertEqual(estimate.total_cost, 0.0)
        self.assertEqual(estimate.completeness, "complete")


class RetryHelperTests(unittest.TestCase):
    def test_bounded_retries_succeed_after_transient_failure(self) -> None:
        attempts = {"count": 0}

        def operation() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("transient")
            return "ok"

        result, retry_count = call_with_bounded_retries(
            operation,
            is_retryable=lambda exc: isinstance(exc, RuntimeError),
            wait_seconds=lambda _attempt, _exc: 0.0,
            max_attempts=3,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(retry_count, 2)

    @patch("core.agent.providers.gemini.genai.Client")
    @patch("core.agent.providers.gemini.time.sleep", return_value=None)
    def test_gemini_retries_429_then_succeeds(
        self, _sleep: MagicMock, mock_client_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_part = MagicMock()
        mock_part.text = "Recovered"
        mock_part.function_call = None
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.usage_metadata = MagicMock(
            prompt_token_count=11,
            candidates_token_count=3,
            total_token_count=14,
            cached_content_token_count=None,
            thoughts_token_count=None,
        )
        mock_response.model_version = "gemini-3.5-flash"
        mock_client.models.generate_content.side_effect = [
            APIError(429, {"error": {"message": "rate limited"}}),
            mock_response,
        ]

        result = GeminiProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hello")],
            [],
            GEMINI_MODEL_PROFILES["nova"],
        )
        self.assertEqual(result.message.content, "Recovered")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.resolved_model, "gemini-3.5-flash")
        assert result.usage is not None
        self.assertEqual(result.usage.input_tokens, 11)
        self.assertEqual(result.usage.output_tokens, 3)


class ResponsesAdapterTests(unittest.TestCase):
    def test_message_conversion_preserves_tool_loop_and_store_false_contract(
        self,
    ) -> None:
        history = [
            AgentMessage(role="user", content="Check weather"),
            AgentMessage(
                role="model",
                content=None,
                tool_calls=[
                    ToolCall(id="call_1", name="get_weather_forecast", arguments={"days": 1})
                ],
                provider_output_items=[
                    {
                        "type": "reasoning",
                        "encrypted_content": "opaque",
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "get_weather_forecast",
                        "arguments": '{"days":1}',
                    },
                ],
            ),
            AgentMessage(
                role="tool",
                tool_results=[
                    ToolResult(
                        id="call_1",
                        name="get_weather_forecast",
                        output={"summary": "clear"},
                    )
                ],
            ),
        ]
        items = _messages_to_responses_input(history)
        self.assertEqual(items[0]["role"], "user")
        self.assertEqual(items[1]["type"], "reasoning")
        self.assertEqual(items[2]["type"], "function_call")
        self.assertEqual(items[3]["type"], "function_call_output")
        self.assertIn("untrusted_tool_output", items[3]["output"])

    def test_usage_parser_reads_cached_and_reasoning_details(self) -> None:
        usage = _parse_usage(
            {
                "input_tokens": 100,
                "output_tokens": 40,
                "total_tokens": 150,
                "input_tokens_details": {"cached_tokens": 20},
                "output_tokens_details": {"reasoning_tokens": 10},
            }
        )
        assert usage is not None
        self.assertEqual(usage.cached_input_tokens, 20)
        self.assertEqual(usage.reasoning_tokens, 10)

    def test_forbidden_native_web_search_tools_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_no_forbidden_native_tools([{"type": "web_search"}])

    def test_descriptor_to_responses_tool_is_flat_function_schema(self) -> None:
        tool = descriptor_to_responses_tool(
            CapabilityDescriptor(
                name="get_weather_forecast",
                title="Weather",
                description="Forecast",
                input_schema={"type": "object", "properties": {}},
                origin="native",
                risk="read",
                expose_to_assistant=True,
                expose_to_mcp_server=False,
                expose_to_client_display=True,
            )
        )
        self.assertEqual(tool["type"], "function")
        self.assertEqual(tool["name"], "get_weather_forecast")
        self.assertNotIn("function", tool)

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_openai_provider_uses_store_false_and_no_web_search(
        self, mock_openai_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.output = [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello from OpenAI"}],
            }
        ]
        mock_response.model = "gpt-4.1-mini"
        mock_response.usage = {
            "input_tokens": 12,
            "output_tokens": 4,
            "total_tokens": 16,
        }
        mock_client.responses.create.return_value = mock_response

        result = OpenAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            OPENAI_INTERNAL_PROFILES["openai_default"],
        )
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertNotIn("previous_response_id", kwargs)
        self.assertNotIn("tools", kwargs)
        self.assertEqual(result.message.content, "Hello from OpenAI")
        self.assertEqual(result.resolved_model, "gpt-4.1-mini")

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_xai_provider_uses_xai_base_url(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.output = [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello from xAI"}],
            }
        ]
        mock_response.model = "grok-4"
        mock_response.usage = None
        mock_client.responses.create.return_value = mock_response

        result = XAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            XAI_INTERNAL_PROFILES["xai_default"],
        )
        self.assertEqual(
            mock_openai_cls.call_args.kwargs["base_url"], "https://api.x.ai/v1"
        )
        self.assertFalse(mock_client.responses.create.call_args.kwargs["store"])
        self.assertEqual(result.message.content, "Hello from xAI")
        # Unavailable usage remains None rather than inventing zeros.
        self.assertIsNone(result.usage)


class PublicRosterUnchangedTests(unittest.TestCase):
    def test_openai_and_xai_profiles_are_not_in_public_registries(self) -> None:
        self.assertNotIn("openai_default", GEMINI_MODEL_PROFILES)
        self.assertNotIn("xai_default", OLLAMA_MODEL_PROFILES)
        self.assertEqual(
            set(OLLAMA_MODEL_PROFILES),
            {"lynx", "acinonyx", "neofelis"},
        )


if __name__ == "__main__":
    unittest.main()
