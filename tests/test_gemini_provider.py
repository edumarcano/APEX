"""Unit tests verifying Gemini provider temperature omission and Ollama temperature retention."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.agent.providers.gemini import GeminiProvider
from core.agent.providers.gemini_models import GEMINI_MODEL_PROFILES, GeminiModelProfile
from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES, OllamaModelProfile
from core.agent.types import AgentMessage


class GeminiProviderTemperatureTests(unittest.TestCase):
    def test_gemini_model_profile_omits_default_temperature(self) -> None:
        """Verify GeminiModelProfile schema has no default_temperature field."""
        profile = GEMINI_MODEL_PROFILES["comet"]
        self.assertFalse(hasattr(profile, "default_temperature"))
        self.assertNotIn("default_temperature", profile.model_dump())
        self.assertNotIn("default_temperature", GeminiModelProfile.model_fields)

    def test_ollama_model_profile_retains_default_temperature(self) -> None:
        """Verify OllamaModelProfile schema retains default_temperature field."""
        profile = OLLAMA_MODEL_PROFILES["lynx"]
        self.assertTrue(hasattr(profile, "default_temperature"))
        self.assertIn("default_temperature", profile.model_dump())
        self.assertIn("default_temperature", OllamaModelProfile.model_fields)
        self.assertEqual(profile.default_temperature, 0.2)

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
        profile = GEMINI_MODEL_PROFILES["nova"]
        messages = [AgentMessage(role="user", content="Hello")]

        provider.generate_turn(messages=messages, tools=[], profile=profile)

        mock_client.models.generate_content.assert_called_once()
        _args, kwargs = mock_client.models.generate_content.call_args
        config = kwargs["config"]
        self.assertFalse(hasattr(config, "temperature") and config.temperature is not None)
        self.assertEqual(kwargs["model"], "gemini-3.5-flash")

    @patch("core.agent.providers.ollama.get_http_session")
    def test_ollama_provider_retains_temperature(
        self, mock_get_session: MagicMock
    ) -> None:
        """Verify OllamaProvider continues sending temperature under options."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {"role": "assistant", "content": "Local response"}
        }
        mock_session.post.return_value = mock_response
        mock_get_session.return_value = mock_session

        provider = OllamaProvider()
        profile = OLLAMA_MODEL_PROFILES["acinonyx"]
        messages = [AgentMessage(role="user", content="Hello")]

        provider.generate_turn(messages=messages, tools=[], profile=profile)

        mock_session.post.assert_called_once()
        _args, kwargs = mock_session.post.call_args
        payload = kwargs["json"]
        self.assertIn("options", payload)
        self.assertIn("temperature", payload["options"])
        self.assertEqual(payload["options"]["temperature"], 0.2)
