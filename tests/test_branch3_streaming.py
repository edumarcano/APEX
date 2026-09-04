"""Focused production-path coverage for beta.2 provider streaming seams."""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.agent.model_catalog import ALL_MODEL_PROFILES
from core.agent.providers.contract import ProviderStreamEvent
from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.gemini_models import GeminiModelProfile
from core.agent.providers.openrouter import OpenRouterModelProfile, OpenRouterProvider
from core.agent.providers.openai_provider import OpenAIProvider, OPENAI_INTERNAL_PROFILES
from core.agent.providers.llama_cpp import LlamaCppProvider
from core.agent.providers.llama_cpp_models import build_llama_cpp_profile
from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.retries import call_with_bounded_retries
from core.agent.types import AgentMessage
from core.api.cortex import _profile_to_catalog_entry
from core.runs.coordinator import ExecutionCancelled, ExecutionLimitReached, RunExecutionControl
from tests.support.agent_fixtures import build_local_profile


class _Stream:
    def __init__(self, items):
        self.items = iter(items)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.items)

    def close(self):
        self.closed = True


class _Control:
    def __init__(self, remaining=10.0):
        self.cancel_event = threading.Event()
        self.remaining = remaining
        self.retries = 0

    def before_provider_attempt(self):
        if self.cancel_event.is_set():
            raise ExecutionCancelled()

    def before_retry(self, _number=0):
        self.retries += 1

    def remaining_seconds(self):
        return self.remaining

    def wait_retry(self, delay):
        if delay >= self.remaining:
            raise ExecutionLimitReached("max_elapsed_seconds")


class Branch3StreamingTests(unittest.TestCase):
    def test_retry_charges_before_wait_and_honors_cancellation_without_sleep(self):
        control = _Control()
        attempts = 0

        def operation():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                control.cancel_event.set()
                raise RuntimeError("transient")
            return "ok"

        with self.assertRaises(ExecutionCancelled):
            call_with_bounded_retries(
                operation,
                is_retryable=lambda _exc: True,
                wait_seconds=lambda _attempt, _exc: 0,
                execution_control=control,
                sleep_fn=lambda _delay: None,
            )
        self.assertEqual(control.retries, 0)
        self.assertEqual(attempts, 1)

    def test_retry_deadline_uses_run_limit_error(self):
        control = _Control(remaining=0.1)
        with self.assertRaises(ExecutionLimitReached) as raised:
            call_with_bounded_retries(
                lambda: (_ for _ in ()).throw(RuntimeError("transient")),
                is_retryable=lambda _exc: True,
                wait_seconds=lambda _attempt, _exc: 1,
                execution_control=control,
            )
        self.assertEqual(raised.exception.reason, "max_elapsed_seconds")

    @patch("core.agent.providers.openrouter.OpenAI")
    def test_openrouter_stream_assembles_calls_and_preserves_privacy(self, client_cls):
        stream = _Stream([
            {"choices": [{"delta": {"content": "pro"}}]},
            {"choices": [{"delta": {"content": "visional"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 2, "id": "c2", "function": {"name": "weather", "arguments": "{\"city\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 2, "function": {"arguments": "\"NYC\"}"}}]}}]},
            {"usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}},
        ])
        client = Mock()
        client_cls.return_value = client
        profile = OpenRouterModelProfile(display_name="Apex", api_model="m", max_tool_turns=1, max_tool_calls=2, system_instruction="", reasoning_effort=None)
        events: list[ProviderStreamEvent] = []
        client.chat.completions.create.side_effect = [stream]
        result = OpenRouterProvider("secret").generate_turn([AgentMessage(role="user", content="x")], [], profile, stream_observer=events.append)
        self.assertEqual(result.message.content, "provisional")
        self.assertEqual(result.message.tool_calls[0].arguments, {"city": "NYC"})
        self.assertIn("reset", [event.kind for event in events])
        self.assertNotIn("NYC", repr(events))
        self.assertTrue(stream.closed)
        request = client.chat.completions.create.call_args.kwargs
        self.assertTrue(request["extra_body"]["provider"]["zdr"])
        self.assertEqual(result.usage.total_tokens, 7)

    @patch("core.agent.providers.gemini.genai.Client")
    def test_gemini_stream_merges_same_index_and_sets_timeout(self, client_cls):
        part1 = SimpleNamespace(text="hel", function_call=None)
        part2 = SimpleNamespace(text="lo", function_call=None)
        fc1 = SimpleNamespace(id="call-1", name="weather", args={"city": ""})
        fc2 = SimpleNamespace(id="call-1", name="weather", args={"city": "NYC"})
        chunks = [SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part1]))]), SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part2, SimpleNamespace(text=None, function_call=fc1), SimpleNamespace(text=None, function_call=fc2)]))], usage_metadata=SimpleNamespace(prompt_token_count=2, candidates_token_count=3, total_token_count=5))]
        client = Mock()
        client.models.generate_content_stream.return_value = _Stream(chunks)
        client_cls.return_value = client
        profile = GeminiModelProfile(display_name="Gemini", api_model="gemini", stability="stable", thinking_level="low", system_instruction="")
        control = _Control()
        result = GeminiProvider("key").generate_turn([AgentMessage(role="user", content="x")], [], profile, execution_control=control)
        self.assertEqual(result.message.content, "hello")
        self.assertEqual(len(result.message.tool_calls), 1)
        self.assertEqual(result.message.tool_calls[0].arguments, {"city": "NYC"})
        self.assertEqual(result.usage.total_tokens, 5)
        config = client.models.generate_content_stream.call_args.kwargs["config"]
        self.assertIsNotNone(config.http_options)

    def test_catalog_capabilities_are_provider_truthful(self):
        self.assertEqual(_profile_to_catalog_entry(ALL_MODEL_PROFILES["gemini-3.7-flash"]).streaming, "native")
        self.assertEqual(_profile_to_catalog_entry(ALL_MODEL_PROFILES["qwen3:1.7b"]).streaming, "completed_turn")
        self.assertEqual(_profile_to_catalog_entry(ALL_MODEL_PROFILES["deepseek/deepseek-v4-flash-0731"]).structured_output, "unavailable")

    @patch("core.agent.providers.responses_api.OpenAI")
    def test_openai_responses_stream_preserves_final_output_metadata(self, client_cls):
        stream = _Stream([
            {"type": "response.output_text.delta", "delta": "hel"},
            {"type": "response.output_text.delta", "delta": "lo"},
            {"type": "response.output_item.added", "output_index": 0, "item": {"type": "function_call", "call_id": "c", "name": "weather"}},
            {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": "{\"city\":\"NYC\"}"},
            {"type": "response.completed", "response": {"model": "served", "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}, "output": [{"type": "mcp_call", "name": "weather", "status": "completed"}]}},
        ])
        client = Mock()
        client.responses.create.return_value = stream
        client_cls.return_value = client
        events: list[ProviderStreamEvent] = []
        result = OpenAIProvider("key").generate_turn([AgentMessage(role="user", content="x")], [], OPENAI_INTERNAL_PROFILES["openai_default"], stream_observer=events.append)
        self.assertEqual(result.message.content, "hello")
        self.assertEqual(result.resolved_model, "served")
        self.assertEqual(result.usage.total_tokens, 5)
        self.assertTrue(result.provider_tool_events)
        self.assertTrue(stream.closed)
        self.assertIn("reset", [event.kind for event in events])

    @patch("core.agent.providers.llama_cpp.register_local_activity", return_value=None)
    @patch("core.agent.providers.llama_cpp.get_http_session")
    def test_llama_cpp_sse_assembles_indexed_fragments_and_closes(self, session_factory, _activity):
        response = Mock()
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo","tool_calls":[{"index":1,"id":"c","function":{"name":"weather","arguments":"{\\"city\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"arguments":"\\"NYC\\"}"}}]}}]}',
            'data: {"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5},"choices":[{"finish_reason":"tool_calls"}]}',
            'data: [DONE]',
        ]
        session_factory.return_value.post.return_value = response
        profile = build_llama_cpp_profile("gemma-4-E2B-Q4_K_M.gguf", display_name="Gemma", api_model="gemma", stability="stable", max_tool_turns=1, max_tool_calls=2, system_instruction="")
        events: list[ProviderStreamEvent] = []
        result = LlamaCppProvider().generate_turn([AgentMessage(role="user", content="x")], [], profile, stream_observer=events.append)
        self.assertEqual(result.message.content, "hello")
        self.assertEqual(result.usage.total_tokens, 5)
        self.assertTrue(response.close.called)
        self.assertEqual(len([event for event in events if event.kind == "text"]), 2)

    @patch("core.agent.providers.openrouter.OpenAI")
    def test_openrouter_retries_stream_with_privacy_each_attempt(self, client_cls):
        from httpx import Request
        from openai import APIConnectionError
        stream = _Stream([{"choices": [{"delta": {"content": "ok"}}]}])
        client = Mock()
        client.chat.completions.create.side_effect = [APIConnectionError(request=Request("POST", "https://openrouter.ai")), stream]
        client_cls.return_value = client
        profile = OpenRouterModelProfile(display_name="Apex", api_model="m", max_tool_turns=1, max_tool_calls=1, system_instruction="", reasoning_effort=None)
        with patch("core.agent.providers.openrouter.time.sleep"):
            OpenRouterProvider("secret").generate_turn([AgentMessage(role="user", content="x")], [], profile)
        self.assertEqual(len(client.chat.completions.create.call_args_list), 2)
        for call in client.chat.completions.create.call_args_list:
            self.assertTrue(call.kwargs["extra_body"]["provider"]["zdr"])

    def test_native_schema_is_only_applied_to_tool_free_turns(self):
        from core.agent.providers.responses_api import ResponsesApiProvider
        provider = ResponsesApiProvider.__new__(ResponsesApiProvider)
        provider.provider_kind = "openai"
        provider.client = Mock()
        response = Mock(output=[{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}], model="m", usage=None)
        provider.client.responses.create.return_value = response
        result = provider.generate_turn([AgentMessage(role="user", content="x")], [], OPENAI_INTERNAL_PROFILES["openai_default"], output_schema={"type": "object"})
        request = provider.client.responses.create.call_args.kwargs
        self.assertEqual(request["text"]["format"]["type"], "json_schema")
        self.assertTrue(result.output_schema_applied)

    @patch("core.agent.providers.ollama.register_local_activity", return_value=None)
    @patch("core.agent.providers.ollama._post_chat")
    def test_ollama_completed_turn_observer_has_one_safe_sequence(self, post_chat, _activity):
        post_chat.return_value = {"model": "qwen", "message": {"role": "assistant", "content": "done"}, "done": True}
        events: list[ProviderStreamEvent] = []
        OllamaProvider().generate_turn([AgentMessage(role="user", content="x")], [], build_local_profile(model="qwen3:1.7b"), stream_observer=events.append)
        self.assertEqual([event.kind for event in events], ["text", "completed"])

    def test_runtime_measurements_are_strict_and_persisted(self):
        from core.agent.providers.contract import ProviderRuntimeMeasurements, ProviderTurnResult
        from core.runs.models import RunLimitSnapshot
        updates = []
        record = SimpleNamespace(limit_snapshot=RunLimitSnapshot(max_elapsed_seconds=600, max_total_tokens=100, max_retries=2, max_model_turns=2, max_tool_calls=2))
        handle = Mock()
        handle.get_record.return_value = record
        handle.update_progress.side_effect = lambda **kwargs: updates.append(kwargs)
        control = RunExecutionControl(handle, threading.Event())
        with self.assertRaises(Exception):
            ProviderRuntimeMeasurements(unexpected=1)
        control.after_model_turn(ProviderTurnResult(message=AgentMessage(role="agent", content="ok"), runtime_measurements={"ttft_ms": 4.5, "eval_count": 3}))
        measurements = updates[-1]["runtime_measurements"]
        self.assertEqual(measurements.ttft_ms, 4.5)
        self.assertEqual(measurements.eval_count, 3)

    @patch("core.agent.providers.llama_cpp.get_http_session")
    def test_llama_stream_translates_http_failure_and_closes_response(self, session_factory):
        import requests
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        response.status_code = 502
        response.json.return_value = {"error": {"message": "upstream server error"}}
        session_factory.return_value.post.return_value = response
        profile = build_llama_cpp_profile("gemma-4-E2B-Q4_K_M.gguf", display_name="Gemma", api_model="gemma", stability="stable", max_tool_turns=1, max_tool_calls=1, system_instruction="")
        from core.agent.providers.llama_cpp import LlamaCppRequestError
        with self.assertRaises(LlamaCppRequestError) as raised:
            LlamaCppProvider().generate_turn([AgentMessage(role="user", content="x")], [], profile, stream_observer=lambda _event: None)
        self.assertIn("HTTP 502", str(raised.exception))
        self.assertNotIn("response", str(raised.exception))
        self.assertTrue(response.close.called)

    @patch("core.agent.providers.llama_cpp.get_http_session")
    def test_llama_stream_cancellation_closes_active_response(self, session_factory):
        response = Mock()
        response.iter_lines.return_value = ['data: {"choices":[{"delta":{"content":"one"}}]}']
        session_factory.return_value.post.return_value = response
        profile = build_llama_cpp_profile("gemma-4-E2B-Q4_K_M.gguf", display_name="Gemma", api_model="gemma", stability="stable", max_tool_turns=1, max_tool_calls=1, system_instruction="")

        class CancelAfterFirst(_Control):
            checks = 0
            def before_provider_attempt(self):
                self.checks += 1
                if self.checks > 0:
                    self.cancel_event.set()
                super().before_provider_attempt()

        with self.assertRaises(ExecutionCancelled):
            LlamaCppProvider().generate_turn([AgentMessage(role="user", content="x")], [], profile, execution_control=CancelAfterFirst())
        self.assertTrue(response.close.called)


if __name__ == "__main__":
    unittest.main()
