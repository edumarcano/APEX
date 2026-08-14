"""Unit tests verifying Gemini provider temperature omission and Ollama temperature retention."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.agent.catalog import AGENT_SPECS, build_concrete_agent, resolve_effort
from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.ollama import OllamaProvider
from core.agent.types import AgentMessage
from core.config import GEMINI_AGENT_MAX_TOOL_CALLS, GEMINI_AGENT_MAX_TURNS


def _concrete_profile(key: str):
    _apex, native = resolve_effort(key, None)
    return build_concrete_agent(key, native_effort=native)


class GeminiProviderTemperatureTests(unittest.TestCase):
    def test_cloud_agents_apply_quota_aware_loop_caps(self) -> None:
        for key in ("panthera", "neofelis", "acinonyx"):
            with self.subTest(agent=key):
                spec = AGENT_SPECS[key]
                self.assertGreater(spec.max_tool_turns, 0)
                self.assertGreaterEqual(spec.max_tool_calls, spec.max_tool_turns)
                self.assertLessEqual(spec.max_tool_turns, GEMINI_AGENT_MAX_TURNS)
                self.assertLessEqual(spec.max_tool_calls, GEMINI_AGENT_MAX_TOOL_CALLS)

    def test_agent_versions_use_product_version_format(self) -> None:
        for spec in AGENT_SPECS.values():
            self.assertRegex(spec.agent_version, r"^[1-9]\d*\.\d+$")

    def test_concrete_profiles_inherit_catalog_versions(self) -> None:
        for key, spec in AGENT_SPECS.items():
            profile = _concrete_profile(key)
            self.assertEqual(profile.agent_version, spec.agent_version)

    def test_local_agents_leave_a_final_answer_turn_after_tool_work(self) -> None:
        for key in ("sorex", "mus", "apodemus", "neotoma", "unnamed-experimental-agent"):
            with self.subTest(agent=key):
                spec = AGENT_SPECS[key]
                self.assertGreater(spec.max_tool_turns, 0)
                self.assertGreaterEqual(spec.max_tool_calls, spec.max_tool_turns)
        for key in ("mus", "apodemus", "neotoma", "unnamed-experimental-agent"):
            with self.subTest(agent=key):
                self.assertEqual(AGENT_SPECS[key].max_tool_turns, 4)

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
        profile = _concrete_profile("neofelis")
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
        """Verify OllamaProvider continues sending temperature under options."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "model", "content": "Local response"}
        }
        mock_session.post.return_value = mock_response
        mock_get_session.return_value = mock_session

        provider = OllamaProvider()
        profile = _concrete_profile("mus")
        messages = [AgentMessage(role="user", content="Hello")]

        provider.generate_turn(messages=messages, tools=[], profile=profile)

        mock_session.post.assert_called_once()
        _args, kwargs = mock_session.post.call_args
        payload = kwargs["json"]
        self.assertIn("options", payload)
        self.assertIn("temperature", payload["options"])
        self.assertEqual(payload["options"]["temperature"], 0.2)


if __name__ == "__main__":
    unittest.main()
