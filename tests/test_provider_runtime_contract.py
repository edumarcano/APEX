"""Provider runtime contract, pricing, retries, and Responses adapter coverage."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from google.genai.errors import APIError
from openai import APIStatusError

from core.agent.capabilities import CapabilityDescriptor
from core.agent.catalog import (
    AGENT_SPECS,
    agent_key_for_local_model_ref,
    build_concrete_agent,
    known_local_model_refs,
    local_model_ref_for_agent,
    local_model_refs_for_agent,
    resolve_effort,
)
from core.agent.local_runtime.contract import LocalModelProfile, LocalModelRef
from core.agent.loop import is_local_profile, run_agent_loop
from core.agent.pricing import (
    PRICING_VERSION,
    _MODEL_RATES,
    agent_pricing,
    estimate_inference_cost,
)
from core.agent.providers.contract import (
    ProviderToolEvent,
    ProviderTurnResult,
    is_local_inference_provider,
    merge_token_usage,
    resolve_inference_provider,
)
from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.ollama import OllamaProvider
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


from core.agent.model_catalog import get_model_profile

def _concrete_profile(key_or_model: str = "gpt-5.6-luna"):
    if key_or_model == "panthera":
        model_id = "gpt-5.6-luna"
    elif key_or_model == "felis":
        model_id = "gemma-4-E2B-Q4_K_M.gguf"
    else:
        model_id = key_or_model
    model_profile = get_model_profile(model_id)
    assert model_profile is not None
    native = resolve_effort(model_profile, None)
    agent_key = "felis" if model_profile.runtime == "local" else "panthera"
    return build_concrete_agent(
        agent_key,
        native_effort=native,
        local_reasoning_mode=(
            "none"
            if model_profile.runtime == "local"
            else None
        ),
        model_id=model_id,
    )


class ProviderContractTests(unittest.TestCase):
    def test_resolve_inference_provider_for_existing_profiles(self) -> None:
        self.assertEqual(
            resolve_inference_provider(_concrete_profile("gemini-3.6-flash")), "gemini"
        )
        self.assertEqual(
            resolve_inference_provider(_concrete_profile("gpt-5.6-luna")), "openai"
        )
        self.assertEqual(
            resolve_inference_provider(_concrete_profile("qwen3:1.7b")), "ollama"
        )
        self.assertEqual(
            resolve_inference_provider(_concrete_profile("gemma-4-E2B-Q4_K_M.gguf")), "llama_cpp"
        )
        self.assertEqual(
            resolve_inference_provider(OPENAI_INTERNAL_PROFILES["openai_default"]),
            "openai",
        )
        self.assertEqual(
            resolve_inference_provider(XAI_INTERNAL_PROFILES["xai_default"]), "xai"
        )

    def test_local_profile_markers_and_runtime_ids(self) -> None:
        local_keys = [
            key for key, spec in AGENT_SPECS.items() if spec.runtime == "local"
        ]
        self.assertTrue(local_keys)

        for agent_key in local_keys:
            with self.subTest(agent=agent_key):
                profile = _concrete_profile(agent_key)
                self.assertIsInstance(profile, LocalModelProfile)
                self.assertTrue(is_local_inference_provider(profile.provider))
                self.assertTrue(profile.runtime_model_id)
                self.assertTrue(profile.api_model)

                if profile.provider != "llama_cpp":
                    continue

                self.assertIn(
                    profile.default_context_window,
                    profile.allowed_context_windows,
                )
                self.assertGreaterEqual(
                    profile.maximum_context_window,
                    max(profile.allowed_context_windows),
                )
                self.assertTrue(
                    set(profile.high_resource_context_options).issubset(
                        profile.allowed_context_windows
                    )
                )
                self.assertIn(profile.reasoning_mode, profile.supported_reasoning_modes)
                for context_window in profile.allowed_context_windows:
                    selected = build_concrete_agent(
                        agent_key,
                        native_effort=None,
                        local_context_window=context_window,
                        local_reasoning_mode=profile.reasoning_mode,
                        model_id=profile.api_model,
                    )
                    self.assertEqual(selected.context_window, context_window)
                    self.assertEqual(
                        selected.high_resource,
                        context_window in profile.high_resource_context_options,
                    )

        self.assertTrue(is_local_inference_provider("ollama"))
        self.assertTrue(is_local_inference_provider("llama_cpp"))
        self.assertFalse(is_local_inference_provider("openai"))
    def test_local_model_refs_derive_from_concrete_profiles(self) -> None:
        from core.agent.catalog import local_model_refs_for_model

        for model_id in (
            "qwen3:1.7b",
            "qwen3:4b-instruct",
            "gemma-4-E2B-Q4_K_M.gguf",
            "gemma-4-E4B-Q4_K_M.gguf",
            "Qwen3.5-4B-Q4_K_M.gguf",
        ):
            profile = _concrete_profile(model_id)
            self.assertTrue(is_local_profile(profile))
            refs = local_model_refs_for_model(model_id)
            self.assertTrue(refs)
            selected = next(iter(refs))
            self.assertEqual(selected.provider, profile.provider)
            self.assertEqual(agent_key_for_local_model_ref(selected), "felis")

        known = known_local_model_refs()
        self.assertTrue(known)
        self.assertIsNone(
            agent_key_for_local_model_ref(
                LocalModelRef(provider="ollama", model="unknown-model")
            )
        )

    def test_local_reasoning_mode_reaches_llama_cpp_profile(self) -> None:
        focused = build_concrete_agent(
            "felis",
            native_effort=None,
            local_reasoning_mode="focused",
            model_id="gemma-4-E2B-Q4_K_M.gguf",
        )
        self.assertEqual(focused.reasoning_mode, "focused")

    def test_focused_llama_profiles_reserve_completion_headroom(self) -> None:
        for model_id in ("gemma-4-E2B-Q4_K_M.gguf", "gemma-4-E4B-Q4_K_M.gguf", "Qwen3.5-4B-Q4_K_M.gguf"):
            with self.subTest(model=model_id):
                profile = build_concrete_agent(
                    "felis",
                    native_effort=None,
                    local_reasoning_mode="focused",
                    model_id=model_id,
                )
                self.assertEqual(
                    (profile.tool_select_max_tokens, profile.final_answer_max_tokens),
                    (1536, 1536),
                )

    def test_agent_loop_follows_local_policy_for_non_ollama_local_profile(self) -> None:
        class FakeLocalProfile:
            provider = "ollama"
            runtime = "local"
            display_name = "Fake Local"
            agent_version = "1.0"
            api_model = "fake-local"
            runtime_model_id = "fake-local"
            max_tool_turns = 1
            max_tool_calls = 1
            context_window = 1024
            generation_timeout = 10
            ram_limit = 90.0
            cpu_limit = 90.0
            high_resource = False
            system_instruction = "test"

            def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
                return {"api_model": self.api_model}

        profile = FakeLocalProfile()
        self.assertTrue(is_local_profile(profile))

        class Provider:
            def generate_turn(self, messages, tools, _profile, system_instruction_override=None):
                self.tools = tools
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="ok"),
                    usage=TokenUsage(input_tokens=1, output_tokens=1),
                    provider_ms=1.0,
                )

        provider = Provider()
        response = run_agent_loop(
            AgentQueryRequest(prompt="hello", agent="felis"),
            provider,
            profile,  # type: ignore[arg-type]
        )
        self.assertEqual(provider.tools, [])
        self.assertEqual(response.answer, "ok")
        self.assertIsNone(response.error)
        self.assertIsNotNone(response.local_context_usage)

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
        profile = _concrete_profile("gemini-3.6-flash")

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
                            role="agent",
                            tool_calls=[
                                ToolCall(
                                    id="call-1",
                                    name="get_weather_forecast",
                                    arguments={"days": 1},
                                )
                            ],
                        ),
                        resolved_model="gemini-3.6-flash-rev",
                        usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
                        provider_ms=12.5,
                    )
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="Clear skies."),
                    resolved_model="gemini-3.6-flash-rev",
                    usage=TokenUsage(input_tokens=140, output_tokens=30, total_tokens=170),
                    provider_ms=8.0,
                )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Weather?", agent="panthera"),
            Provider(),
            profile,
            tools_dispatcher=lambda _name, _args: {"summary": "clear"},
        )

        self.assertEqual(response.answer, "Clear skies.")
        self.assertEqual(response.resolved_model, "gemini-3.6-flash-rev")
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
        gemini_keys = {
            key
            for key in AGENT_SPECS
            if key == "panthera"
        }
        self.assertEqual(gemini_keys, {"panthera"})

    def test_provider_tool_events_reach_the_trace_with_numeric_durations(self) -> None:
        class Provider:
            def generate_turn(
                self,
                _messages: list[AgentMessage],
                _tools: list[CapabilityDescriptor],
                _profile: object,
                system_instruction_override: str | None = None,
            ) -> ProviderTurnResult:
                del system_instruction_override
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content="Grounded."),
                    provider_tool_events=[
                        ProviderToolEvent(
                            name="google_search",
                            status="ok",
                            duration_ms=41.5,
                            billable_units=1,
                        )
                    ],
                )

        response = run_agent_loop(
            AgentQueryRequest(prompt="Search?", agent="panthera"),
            Provider(),
            _concrete_profile("gemini-3.6-flash"),
        )

        trace = response.tool_trace[0]
        self.assertEqual(trace["origin"], "provider")
        self.assertIsInstance(trace["duration_ms"], float)


class OllamaContractTests(unittest.TestCase):
    @staticmethod
    def _descriptor() -> CapabilityDescriptor:
        return CapabilityDescriptor(
            name="get_weather_forecast",
            title="Weather",
            description="Forecast",
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )

    @patch("core.agent.providers.ollama.register_local_activity", return_value=None)
    @patch("core.agent.providers.ollama._post_chat")
    def test_usage_and_resolved_model_come_from_response_body(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = {
            "model": "qwen3:1.7b-q4",
            "message": {"role": "model", "content": "Local answer"},
            "prompt_eval_count": 90,
            "eval_count": 15,
        }

        result = OllamaProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            _concrete_profile("qwen3:1.7b"),
        )

        self.assertEqual(result.message.content, "Local answer")
        self.assertEqual(result.resolved_model, "qwen3:1.7b-q4")
        assert result.usage is not None
        self.assertEqual(result.usage.input_tokens, 90)
        self.assertEqual(result.usage.output_tokens, 15)
        self.assertEqual(result.usage.total_tokens, 105)
        self.assertEqual(result.retry_count, 0)
        self.assertIsNotNone(result.provider_ms)

    @patch("core.agent.providers.ollama.register_local_activity", return_value=None)
    @patch("core.agent.providers.ollama._post_chat")
    def test_resolved_model_falls_back_to_configured_tag(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = {
            "message": {"role": "model", "content": "Local answer"},
        }

        result = OllamaProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            _concrete_profile("qwen3:1.7b"),
        )

        self.assertEqual(result.resolved_model, _concrete_profile("qwen3:1.7b").api_model)
        self.assertIsNone(result.usage)

    @patch("core.agent.providers.ollama.register_local_activity", return_value=None)
    @patch("core.agent.providers.ollama._post_chat")
    def test_truncated_tool_turn_regenerates_and_sums_usage(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.side_effect = [
            {
                "model": "qwen3:1.7b",
                "message": {"role": "model", "content": "truncated prose"},
                "done_reason": "length",
                "prompt_eval_count": 80,
                "eval_count": 40,
            },
            {
                "model": "qwen3:1.7b",
                "message": {"role": "model", "content": "Final answer"},
                "prompt_eval_count": 70,
                "eval_count": 25,
            },
        ]

        result = OllamaProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [self._descriptor()],
            _concrete_profile("qwen3:1.7b"),
        )

        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(result.message.content, "Final answer")
        self.assertEqual(result.retry_count, 1)
        assert result.usage is not None
        self.assertEqual(result.usage.input_tokens, 150)
        self.assertEqual(result.usage.output_tokens, 65)
        self.assertEqual(result.usage.total_tokens, 215)


class PricingRegistryTests(unittest.TestCase):
    def test_paid_model_rates_match_the_active_paid_cloud_agents(self) -> None:
        from core.agent.model_catalog import CLOUD_MODEL_PROFILES

        self.assertEqual(set(_MODEL_RATES), set(CLOUD_MODEL_PROFILES))

    def test_luna_uses_the_current_standard_rates(self) -> None:
        standard = _MODEL_RATES["gpt-5.6-luna"]
        self.assertEqual(standard.input_per_million, 0.20)
        self.assertEqual(standard.output_per_million, 1.20)
        self.assertEqual(standard.cached_input_per_million, 0.02)

        standard_estimate = estimate_inference_cost(
            model="gpt-5.6-luna",
            usage=TokenUsage(input_tokens=1_000, output_tokens=1_000),
        )
        self.assertAlmostEqual(standard_estimate.token_cost or 0.0, 0.0014, places=6)

        estimate = estimate_inference_cost(
            model="gpt-5.6-luna",
            usage=TokenUsage(
                input_tokens=1_000_000,
                cached_input_tokens=400_000,
                output_tokens=1_000_000,
            ),
        )

        # Above Luna's long-context threshold: 0.6M uncached at $0.40, 0.4M
        # cached at $0.04, and 1M output at $1.80.
        self.assertAlmostEqual(estimate.token_cost or 0.0, 2.056, places=4)

    def test_gemini_flash_lite_uses_free_tier_billing(self) -> None:
        pricing = agent_pricing(
            "panthera",
            model="gemini-3.5-flash-lite",
            provider="gemini",
        )

        self.assertEqual(pricing.billing_basis, "free_tier")
        self.assertEqual(pricing.rates.input_per_million, 0.0)
        self.assertEqual(pricing.rates.output_per_million, 0.0)
        self.assertEqual(pricing.rates.cached_input_per_million, 0.0)

    def test_token_cost_excludes_mcp_and_marks_unknown_hosted_partial(self) -> None:
        estimate = estimate_inference_cost(
            model="gemini-3.6-flash",
            usage=TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000),
            hosted_tool_events=[
                ProviderToolEvent(name="google_search", status="ok", billable_units=2),
                ProviderToolEvent(name="unknown_hosted", status="ok", billable_units=1),
            ],
        )
        self.assertAlmostEqual(estimate.token_cost or 0.0, 4.5, places=4)
        self.assertAlmostEqual(estimate.hosted_tool_cost or 0.0, 0.028, places=4)
        self.assertEqual(estimate.completeness, "partial")
        self.assertEqual(estimate.pricing_version, PRICING_VERSION)

    def test_local_ollama_models_are_zero_cost(self) -> None:
        estimate = estimate_inference_cost(
            model="qwen3:1.7b",
            usage=TokenUsage(input_tokens=1000, output_tokens=200, total_tokens=1200),
            provider="ollama",
        )
        self.assertEqual(estimate.token_cost, 0.0)
        self.assertEqual(estimate.hosted_tool_cost, 0.0)
        self.assertEqual(estimate.total_cost, 0.0)
        self.assertEqual(estimate.completeness, "complete")

    def test_local_llama_cpp_models_are_zero_cost(self) -> None:
        estimate = estimate_inference_cost(
            model="gemma-4-E2B-Q4_K_M.gguf",
            usage=TokenUsage(input_tokens=1000, output_tokens=200, total_tokens=1200),
            provider="llama_cpp",
        )
        self.assertEqual(estimate.token_cost, 0.0)
        self.assertEqual(estimate.hosted_tool_cost, 0.0)
        self.assertEqual(estimate.total_cost, 0.0)
        self.assertEqual(estimate.completeness, "complete")

    def test_cached_and_reasoning_tokens_are_not_charged_twice(self) -> None:
        estimate = estimate_inference_cost(
            model="gemini-3.6-flash",
            usage=TokenUsage(
                input_tokens=1_000_000,
                cached_input_tokens=400_000,
                reasoning_tokens=1_000_000,
                output_tokens=1_000_000,
            ),
        )
        # 0.6M uncached at 0.75 + 0.4M cached at 0.075 + 1M reasoning and 1M
        # output at the 3.75 output rate.
        self.assertAlmostEqual(estimate.token_cost or 0.0, 7.98, places=4)

    def test_experimental_gemini_model_pricing_uses_free_tier(self) -> None:
        estimate = estimate_inference_cost(
            model="gemini-3.5-flash-lite",
            configured_model="gemini-3.5-flash-lite",
            provider="gemini",
            agent_key="panthera",
            usage=TokenUsage(input_tokens=1000, output_tokens=200),
        )
        self.assertEqual(estimate.token_cost, 0.0)
        self.assertEqual(estimate.completeness, "complete")

    def test_long_context_rates_apply_after_the_provider_threshold(self) -> None:
        estimate = estimate_inference_cost(
            model="grok-4.5",
            usage=TokenUsage(input_tokens=200_001, output_tokens=1_000_000),
        )
        self.assertAlmostEqual(estimate.token_cost or 0.0, 12.800004, places=6)

    def test_unknown_cloud_model_reports_unavailable_instead_of_guessing(self) -> None:
        estimate = estimate_inference_cost(
            model="mistral-large:latest",
            usage=TokenUsage(input_tokens=1000, output_tokens=200),
        )
        self.assertIsNone(estimate.token_cost)
        self.assertEqual(estimate.completeness, "unavailable")


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
        mock_response.model_version = "gemini-3.6-flash"
        mock_client.models.generate_content.side_effect = [
            APIError(429, {"error": {"message": "rate limited"}}),
            mock_response,
        ]

        result = GeminiProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hello")],
            [],
            _concrete_profile("gemini-3.6-flash"),
        )
        self.assertEqual(result.message.content, "Recovered")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.resolved_model, "gemini-3.6-flash")
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
                role="agent",
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

    def test_usage_parser_separates_reasoning_from_visible_output(self) -> None:
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
        # The Responses API nests reasoning inside output_tokens.
        self.assertEqual(usage.output_tokens, 30)

    def test_forbidden_native_web_search_tools_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_no_forbidden_native_tools([{"type": "web_search"}])

    def test_apex_function_tool_named_web_search_is_allowed(self) -> None:
        assert_no_forbidden_native_tools([{"type": "function", "name": "web_search"}])

    def test_descriptor_to_responses_tool_is_flat_function_schema(self) -> None:
        tool = descriptor_to_responses_tool(
            CapabilityDescriptor(
                name="get_weather_forecast",
                title="Weather",
                description="Forecast",
                input_schema={"type": "object", "properties": {}},
                origin="native",
                risk="read",
                expose_to_agent=True,
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
        mock_response.model = "gpt-5.6-luna"
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
        self.assertEqual(kwargs["include"], ["reasoning.encrypted_content"])
        self.assertEqual(result.message.content, "Hello from OpenAI")
        self.assertEqual(result.resolved_model, "gpt-5.6-luna")

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_non_reasoning_profile_omits_reasoning_request_fields(
        self, mock_openai_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.output = []
        mock_response.model = "grok-4"
        mock_response.usage = None
        mock_client.responses.create.return_value = mock_response

        XAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            XAI_INTERNAL_PROFILES["xai_default"],
        )
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertNotIn("reasoning", kwargs)
        self.assertNotIn("include", kwargs)

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_hosted_tool_events_carry_attributed_durations(
        self, mock_openai_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.output = [
            {"type": "x_search_call", "status": "completed"},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Done"}],
            },
        ]
        mock_response.model = "grok-4"
        mock_response.usage = None
        mock_client.responses.create.return_value = mock_response

        result = XAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            XAI_INTERNAL_PROFILES["xai_default"],
        )
        self.assertEqual(len(result.provider_tool_events), 1)
        event = result.provider_tool_events[0]
        self.assertEqual(event.name, "x_search")
        self.assertEqual(event.status, "ok")
        self.assertIsNotNone(event.duration_ms)

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

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_grok_4_3_delphinus_omits_encrypted_reasoning_include(
        self, mock_openai_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.output = []
        mock_response.model = "grok-4.3"
        mock_response.usage = None
        mock_client.responses.create.return_value = mock_response

        delphinus_profile = _concrete_profile("grok-4.3")
        XAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            delphinus_profile,  # type: ignore[arg-type]
        )
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["reasoning"], {"effort": "medium"})
        self.assertNotIn("include", kwargs)

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_grok_4_5_orcinus_includes_encrypted_reasoning_include(
        self, mock_openai_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.output = []
        mock_response.model = "grok-4.5"
        mock_response.usage = None
        mock_client.responses.create.return_value = mock_response

        orcinus_profile = _concrete_profile("grok-4.5")
        XAIProvider(api_key="test").generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            orcinus_profile,  # type: ignore[arg-type]
        )
        kwargs = mock_client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["reasoning"], {"effort": "high"})
        self.assertNotIn("include", kwargs)

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_responses_api_logs_structured_warning_on_400_bad_request(
        self, mock_openai_cls: MagicMock
    ) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        error_response = MagicMock()
        error_response.status_code = 400
        mock_client.responses.create.side_effect = APIStatusError(
            message="Invalid parameter: 'include'",
            response=error_response,
            body={
                "error": {
                    "message": "Invalid parameter: 'include'",
                    "param": "include",
                    "code": "invalid_parameter",
                }
            },
        )

        delphinus_profile = _concrete_profile("grok-4.3")
        with self.assertLogs("core.agent.providers.responses_api", level="WARNING") as log_cm:
            with self.assertRaises(APIStatusError):
                XAIProvider(api_key="test").generate_turn(
                    [AgentMessage(role="user", content="Hi")],
                    [],
                    delphinus_profile,  # type: ignore[arg-type]
                )

        self.assertTrue(
            any(
                "xai Responses API 400 Bad Request for model grok-4.3" in log and "invalid_parameter" in log
                for log in log_cm.output
            )
        )


class PublicRosterTests(unittest.TestCase):
    def test_unified_registry_exposes_panthera_and_felis(self) -> None:
        self.assertEqual(set(AGENT_SPECS), {"panthera", "felis"})
        self.assertEqual(AGENT_SPECS["panthera"].runtime, "cloud")
        self.assertEqual(AGENT_SPECS["felis"].runtime, "local")


if __name__ == "__main__":
    unittest.main()
