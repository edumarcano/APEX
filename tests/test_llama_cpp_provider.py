"""Mock-HTTP coverage for the llama.cpp Chat Completions provider."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from core.agent.capabilities import CapabilityDescriptor
from core.agent.catalog import build_concrete_agent, resolve_effort
from core.agent.model_catalog import get_model_profile
from core.agent.prompting import SECURITY_BOUNDARY_DIRECTIVE
from core.agent.providers.llama_cpp import (
    LlamaCppProvider,
    LlamaCppRequestError,
    _openai_message_to_agent_message,
    _parse_tool_call_arguments,
    _post_chat,
    _strip_thinking_tags,
)
from core.agent.types import AgentMessage, ToolCall, ToolResult

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llama_cpp"
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "</" + "think" + ">"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _llama_profile(
    *,
    model_id: str = "gemma-4-E2B-Q4_K_M.gguf",
    context_window: int = 16384,
    reasoning_mode: str | None = "none",
):
    model_profile = get_model_profile(model_id)
    assert model_profile is not None
    native = resolve_effort(model_profile, None)
    return build_concrete_agent(
        "apex",
        native_effort=native,
        local_context_window=context_window,
        local_reasoning_mode=reasoning_mode,
        model_id=model_id,
    )


def _local_profile(
    *,
    context_window: int = 16384,
    reasoning_mode: str | None = "none",
):
    return _llama_profile(
        context_window=context_window,
        reasoning_mode=reasoning_mode,
    )


def _descriptor(name: str = "get_weather_forecast") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        name=name,
        title="Weather",
        description="Forecast",
        input_schema={
            "type": "object",
            "properties": {"location": {"type": "string"}},
        },
        origin="native",
        risk="read",
        expose_to_agent=True,
        expose_to_mcp_server=False,
        expose_to_client_display=True,
    )


def _mock_response(
    *,
    status_code: int = 200,
    payload: dict | None = None,
    text: str = "",
    raise_http: bool = False,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    if payload is not None:
        response.json.return_value = payload
    else:
        response.json.side_effect = ValueError("not json")
    if raise_http:
        error = requests.HTTPError(response=response)
        response.raise_for_status.side_effect = error
    else:
        response.raise_for_status.return_value = None
    return response


class LlamaCppProviderTests(unittest.TestCase):
    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_basic_final_answer(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = _load_fixture("basic_answer.json")
        result = LlamaCppProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            _local_profile(),
        )
        self.assertEqual(result.message.content, "The local weather looks clear.")
        self.assertIn(result.resolved_model, {"gemma-4-e2b-16k", "apodemus-16k"})
        self.assertIsNone(result.message.tool_calls)
        payload = mock_post.call_args.args[0]
        self.assertEqual(payload["reasoning_effort"], "none")
        self.assertEqual(
            payload["chat_template_kwargs"],
            {"enable_thinking": False},
        )
        self.assertEqual(payload["max_tokens"], 768)
        self.assertEqual(payload["temperature"], 0.2)
        self.assertFalse(payload["stream"])
        self.assertIn(SECURITY_BOUNDARY_DIRECTIVE, payload["messages"][0]["content"])

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_empty_assistant_content(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = {
            "model": "gemma-4-e2b-16k",
            "choices": [
                {
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": "stop",
                }
            ],
        }
        result = LlamaCppProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            _local_profile(),
        )
        self.assertIsNone(result.message.content)

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_focused_reasoning_omits_reasoning_effort(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = _load_fixture("basic_answer.json")
        LlamaCppProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            _local_profile(reasoning_mode="focused"),
        )
        payload = mock_post.call_args.args[0]
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(
            payload["chat_template_kwargs"],
            {"enable_thinking": True},
        )
        self.assertEqual(payload["max_tokens"], 1536)

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_reasoning_payload_is_explicit_for_both_llama_agents(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = _load_fixture("basic_answer.json")

        model_ids = {
            "apodemus": "gemma-4-E2B-Q4_K_M.gguf",
            "neotoma": "gemma-4-E4B-Q4_K_M.gguf",
            "unnamed-experimental-agent": "Qwen3.5-4B-Q4_K_M.gguf",
        }
        for legacy_key, model_id in model_ids.items():
            for reasoning_mode, enabled in (("none", False), ("focused", True)):
                with self.subTest(model=model_id, reasoning_mode=reasoning_mode):
                    mock_post.reset_mock()
                    LlamaCppProvider().generate_turn(
                        [AgentMessage(role="user", content="Hi")],
                        [],
                        _llama_profile(
                            model_id=model_id,
                            reasoning_mode=reasoning_mode,
                        ),
                    )
                    payload = mock_post.call_args.args[0]
                    self.assertEqual(
                        payload["chat_template_kwargs"],
                        {"enable_thinking": enabled},
                    )
                    if enabled:
                        self.assertNotIn("reasoning_effort", payload)
                    else:
                        self.assertEqual(payload["reasoning_effort"], "none")

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_single_tool_call_string_arguments(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = _load_fixture("single_tool_call.json")
        result = LlamaCppProvider().generate_turn(
            [AgentMessage(role="user", content="Weather?")],
            [_descriptor()],
            _local_profile(),
        )
        assert result.message.tool_calls is not None
        self.assertEqual(len(result.message.tool_calls), 1)
        call = result.message.tool_calls[0]
        self.assertEqual(call.id, "call_weather_1")
        self.assertEqual(call.name, "get_weather_forecast")
        self.assertEqual(call.arguments, {"location": "Boston"})
        payload = mock_post.call_args.args[0]
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertTrue(payload["parallel_tool_calls"])
        self.assertEqual(payload["reasoning_effort"], "none")

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_parallel_tool_calls_mixed_argument_shapes(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = _load_fixture("parallel_tool_calls.json")
        result = LlamaCppProvider().generate_turn(
            [AgentMessage(role="user", content="Lookup")],
            [_descriptor(), _descriptor("fetch_crypto_price")],
            _local_profile(),
        )
        assert result.message.tool_calls is not None
        self.assertEqual(
            [call.name for call in result.message.tool_calls],
            ["get_weather_forecast", "fetch_crypto_price"],
        )
        self.assertEqual(result.message.tool_calls[0].arguments, {"location": "Boston"})
        self.assertEqual(result.message.tool_calls[1].arguments, {"symbol": "BTC"})

    def test_parse_tool_call_arguments_variants(self) -> None:
        self.assertEqual(
            _parse_tool_call_arguments('{"city":"Paris"}'),
            {"city": "Paris"},
        )
        self.assertEqual(
            _parse_tool_call_arguments({"city": "Paris"}),
            {"city": "Paris"},
        )
        self.assertEqual(_parse_tool_call_arguments("[1,2]"), {})
        self.assertEqual(_parse_tool_call_arguments("{not-json"), {})
        self.assertEqual(_parse_tool_call_arguments(None), {})

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_outbound_tool_history_and_security_wrappers(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = _load_fixture("tool_continuation.json")
        messages = [
            AgentMessage(role="user", content="Weather in Boston?"),
            AgentMessage(
                role="agent",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call_weather_1",
                        name="get_weather_forecast",
                        arguments={"location": "Boston"},
                    )
                ],
            ),
            AgentMessage(
                role="tool",
                tool_results=[
                    ToolResult(
                        id="call_weather_1",
                        name="get_weather_forecast",
                        output={"summary": "clear", "temp_f": 68},
                    )
                ],
            ),
        ]
        result = LlamaCppProvider().generate_turn(
            messages,
            [_descriptor()],
            _local_profile(),
        )
        self.assertEqual(result.message.content, "Boston is clear and about 68 F.")
        payload = mock_post.call_args.args[0]
        roles = [item["role"] for item in payload["messages"]]
        self.assertEqual(roles[:4], ["system", "user", "assistant", "tool"])
        assistant = payload["messages"][2]
        self.assertEqual(
            assistant["tool_calls"][0]["function"]["arguments"],
            '{"location":"Boston"}',
        )
        tool_message = payload["messages"][3]
        self.assertIn("<untrusted_tool_output", tool_message["content"])
        self.assertEqual(tool_message["tool_call_id"], "call_weather_1")

    def test_strip_thinking_tags_and_discard_reasoning_content(self) -> None:
        cleaned = _strip_thinking_tags(
            f"{_THINK_OPEN}secret plan{_THINK_CLOSE}Visible answer"
        )
        self.assertEqual(cleaned, "Visible answer")
        message = _openai_message_to_agent_message(
            {
                "role": "assistant",
                "content": f"{_THINK_OPEN}hide me{_THINK_CLOSE}Hello",
                "reasoning_content": "should never surface",
            }
        )
        self.assertEqual(message.content, "Hello")
        self.assertNotIn("hide me", message.content or "")
        self.assertNotIn("should never surface", message.content or "")

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_usage_cached_tokens_and_timings(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = _load_fixture("usage_and_timings.json")
        with self.assertLogs("core.agent.providers.llama_cpp", level="INFO") as logs:
            result = LlamaCppProvider().generate_turn(
                [AgentMessage(role="user", content="Hi")],
                [],
                _local_profile(),
            )
        assert result.usage is not None
        self.assertEqual(result.usage.input_tokens, 100)
        self.assertEqual(result.usage.output_tokens, 20)
        self.assertEqual(result.usage.total_tokens, 120)
        self.assertEqual(result.usage.cached_input_tokens, 25)
        joined = "\n".join(logs.output)
        self.assertIn("prompt_ms=12.5", joined)
        self.assertIn("tokens_per_sec=42.5", joined)
        self.assertNotIn("Usage and timings are present", joined)

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_resolved_model_falls_back_to_runtime_alias(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.return_value = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ]
        }
        profile = _local_profile()
        result = LlamaCppProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [],
            profile,
        )
        self.assertEqual(result.resolved_model, profile.runtime_model_id)

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_overflow_retries_without_prior_history(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        overflow = LlamaCppRequestError(
            "llama.cpp request failed",
            status_code=400,
            detail=_load_fixture("context_overflow_error.json")["error"]["message"],
        )
        mock_post.side_effect = [
            overflow,
            _load_fixture("basic_answer.json"),
        ]
        messages = [
            AgentMessage(role="user", content="Earlier question"),
            AgentMessage(role="agent", content="Earlier answer"),
            AgentMessage(role="user", content="Current question"),
        ]
        result = LlamaCppProvider().generate_turn(
            messages,
            [],
            _local_profile(),
        )
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(result.message.content, "The local weather looks clear.")
        retry_payload = mock_post.call_args_list[1].args[0]
        user_contents = [
            item["content"]
            for item in retry_payload["messages"]
            if item["role"] == "user"
        ]
        self.assertEqual(user_contents, ["Current question"])

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp._post_chat")
    def test_truncated_tool_turn_regenerates_without_tools(
        self, mock_post: MagicMock, _activity: MagicMock
    ) -> None:
        mock_post.side_effect = [
            {
                "model": "gemma-4-e2b-16k",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "truncated prose",
                        },
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 40,
                    "total_tokens": 120,
                },
            },
            {
                "model": "gemma-4-e2b-16k",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Final answer",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 70,
                    "completion_tokens": 25,
                    "total_tokens": 95,
                },
            },
        ]
        result = LlamaCppProvider().generate_turn(
            [AgentMessage(role="user", content="Hi")],
            [_descriptor()],
            _local_profile(),
        )
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(result.message.content, "Final answer")
        self.assertEqual(result.retry_count, 1)
        self.assertNotIn("tools", mock_post.call_args_list[1].args[0])
        assert result.usage is not None
        self.assertEqual(result.usage.input_tokens, 150)
        self.assertEqual(result.usage.output_tokens, 65)

    @patch("core.agent.providers.llama_cpp.get_auth_headers", return_value={})
    @patch("core.agent.providers.llama_cpp.get_http_session")
    def test_autoload_false_is_always_present(
        self, mock_get_session: MagicMock, _auth: MagicMock
    ) -> None:
        session = MagicMock()
        session.post.return_value = _mock_response(
            payload=_load_fixture("basic_answer.json")
        )
        mock_get_session.return_value = session
        _post_chat(
            {
                "model": "gemma-4-e2b-16k",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
                "temperature": 0.2,
                "max_tokens": 64,
                "reasoning_effort": "none",
            },
            _local_profile(),
        )
        _args, kwargs = session.post.call_args
        self.assertEqual(kwargs["params"], {"autoload": "false"})

    @patch("core.agent.providers.llama_cpp.get_auth_headers", return_value={})
    @patch("core.agent.providers.llama_cpp.get_http_session")
    def test_connection_and_timeout_failures(
        self, mock_get_session: MagicMock, _auth: MagicMock
    ) -> None:
        session = MagicMock()
        mock_get_session.return_value = session
        profile = _local_profile()
        payload = {"model": "gemma-4-e2b-16k", "messages": []}

        session.post.side_effect = requests.Timeout()
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            _post_chat(payload, profile)

        session.post.side_effect = requests.ConnectionError()
        with self.assertRaisesRegex(RuntimeError, "Failed to connect"):
            _post_chat(payload, profile)

    @patch("core.agent.providers.llama_cpp.get_auth_headers", return_value={})
    @patch("core.agent.providers.llama_cpp.get_http_session")
    def test_provider_error_is_sanitized(
        self, mock_get_session: MagicMock, _auth: MagicMock
    ) -> None:
        session = MagicMock()
        mock_get_session.return_value = session
        secret = "Bearer super-secret-key"
        prompt = "user private prompt about medical history"
        overflow = _load_fixture("context_overflow_error.json")
        session.post.return_value = _mock_response(
            status_code=400,
            payload=overflow,
            raise_http=True,
        )
        with self.assertRaises(LlamaCppRequestError) as raised:
            _post_chat(
                {
                    "model": "gemma-4-e2b-16k",
                    "messages": [{"role": "user", "content": prompt}],
                    "headers_should_not_leak": secret,
                },
                _local_profile(),
            )
        message = str(raised.exception)
        self.assertIn("context window", raised.exception.detail.lower())
        self.assertTrue(raised.exception.is_context_overflow)
        self.assertNotIn(secret, message)
        self.assertNotIn(prompt, message)
        self.assertNotIn("Authorization", message)

    @patch("core.agent.providers.llama_cpp.get_auth_headers", return_value={})
    @patch("core.agent.providers.llama_cpp.get_http_session")
    def test_non_json_and_missing_choice_errors(
        self, mock_get_session: MagicMock, _auth: MagicMock
    ) -> None:
        session = MagicMock()
        mock_get_session.return_value = session
        session.post.return_value = _mock_response(status_code=200, payload=None)
        with self.assertRaisesRegex(RuntimeError, "non-JSON"):
            _post_chat({"model": "gemma-4-e2b-16k", "messages": []}, _local_profile())

        with patch(
            "core.agent.providers.llama_cpp.register_local_activity",
            return_value=None,
        ), patch(
            "core.agent.providers.llama_cpp._post_chat",
            return_value={"choices": []},
        ):
            with self.assertRaisesRegex(RuntimeError, "missing choices"):
                LlamaCppProvider().generate_turn(
                    [AgentMessage(role="user", content="Hi")],
                    [],
                    _local_profile(),
                )


if __name__ == "__main__":
    unittest.main()
