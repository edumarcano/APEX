from __future__ import annotations

import unittest

from core.agent.local_context import is_local_profile
from core.agent.providers.contract import resolve_inference_provider
from core.agent.providers.litert_models import LiteRTModelProfile
from core.agent.types import AgentMessage, AgentQueryRequest


class LiteRTIntegrationContractTests(unittest.TestCase):
    def test_litert_profile_is_provider_neutral_to_the_loop(self) -> None:
        profile = LiteRTModelProfile(
            display_name="Injected LiteRT",
            agent_version="1.0",
            api_model="test/model",
            tier="balanced",
            stability="preview",
            system_instruction="test",
        )
        self.assertEqual(resolve_inference_provider(profile), "litert")
        self.assertTrue(is_local_profile(profile))

    def test_request_history_contract_accepts_litert_agent_keys(self) -> None:
        request = AgentQueryRequest(
            prompt="Continue",
            agent="mustela",
            history=[AgentMessage(role="user", content="Earlier")],
        )
        self.assertEqual(request.agent, "mustela")

if __name__ == "__main__":
    unittest.main()
