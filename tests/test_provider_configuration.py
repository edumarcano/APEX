"""Unit tests verifying Gemini provider temperature omission and Ollama temperature retention."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.agent.catalog import build_concrete_agent, resolve_effort
from core.agent.model_catalog import get_model_profile
from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.ollama import OllamaProvider
from core.agent.types import AgentMessage
from core.config import GEMINI_AGENT_MAX_TOOL_CALLS, GEMINI_AGENT_MAX_TURNS

def _concrete_profile(model_id: str):
    model_profile = get_model_profile(model_id)
    assert model_profile is not None
    native = resolve_effort(model_profile, None)
    return build_concrete_agent(
        "apex",
        native_effort=native,
        model_id=model_id,
    )


class GeminiProviderTemperatureTests(unittest.TestCase):
    def test_cloud_agents_apply_quota_aware_loop_caps(self) -> None:
        for model_id in ("gpt-5.6-luna", "gemini-3.6-flash", "gemini-3.5-flash-lite"):
            with self.subTest(model=model_id):
                profile = get_model_profile(model_id)
                assert profile is not None
                self.assertGreater(profile.max_tool_turns, 0)
                self.assertGreaterEqual(profile.max_tool_calls, profile.max_tool_turns)
                self.assertLessEqual(profile.max_tool_turns, GEMINI_AGENT_MAX_TURNS)
                self.assertLessEqual(profile.max_tool_calls, GEMINI_AGENT_MAX_TOOL_CALLS)

    def test_local_models_leave_a_final_answer_turn_after_tool_work(self) -> None:
        for model_id in (
            "qwen3:1.7b",
            "qwen3:4b-instruct",
            "gemma-4-E2B-Q4_K_M.gguf",
            "gemma-4-E4B-Q4_K_M.gguf",
            "Qwen3.5-4B-Q4_K_M.gguf",
        ):
            with self.subTest(model=model_id):
                profile = get_model_profile(model_id)
                assert profile is not None
                self.assertGreater(profile.max_tool_turns, 0)
                self.assertGreaterEqual(profile.max_tool_calls, profile.max_tool_turns)
        for model_id in (
            "qwen3:4b-instruct",
            "gemma-4-E2B-Q4_K_M.gguf",
            "gemma-4-E4B-Q4_K_M.gguf",
            "Qwen3.5-4B-Q4_K_M.gguf",
        ):
            with self.subTest(model=model_id):
                self.assertEqual(get_model_profile(model_id).max_tool_turns, 4)

    @patch("core.agent.providers.gemini.genai.Client")
    def test_gemini_provider_config_omits_temperature(
        self, mock_client_cls: MagicMock
    ) -> None:
        """Verify GeminiProvider does not pass temperature to GenerateContentConfig."""
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_candidate = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "Test response"
        mock_part.function_call = None
        mock_candidate.content.parts = [mock_part]
        mock_response.candidates = [mock_candidate]
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(api_key="test-api-key")
        profile = _concrete_profile("gemini-3.6-flash")
        messages = [AgentMessage(role="user", content="Hello")]

        provider.generate_turn(messages=messages, tools=[], profile=profile)

        mock_client.models.generate_content.assert_called_once()
        _args, kwargs = mock_client.models.generate_content.call_args
        config = kwargs["config"]
        self.assertFalse(hasattr(config, "temperature") and config.temperature is not None)
        self.assertEqual(kwargs["model"], "gemini-3.6-flash")

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
