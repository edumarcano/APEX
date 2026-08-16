"""Provider-authoritative local context budgeting coverage."""

from __future__ import annotations

import unittest

from tests.support.agent_fixtures import build_felis_profile
from core.agent.loop import build_agent_failure_details
from core.agent.providers.llama_cpp import (
    _budget_payload as llama_cpp_budget_payload,
    _estimate_payload_tokens as llama_cpp_estimate_payload_tokens,
)
from core.agent.providers.ollama import (
    _budget_payload as ollama_budget_payload,
    _estimate_payload_tokens as ollama_estimate_payload_tokens,
)
from core.agent.types import AgentMessage
from core.agent.tool_schemas import estimate_json_tokens


def _history_with_large_prior_interactions() -> list[AgentMessage]:
    large_answer = "Prior answer " * 1_500
    return [
        AgentMessage(role="user", content="Prior question one"),
        AgentMessage(role="agent", content=large_answer),
        AgentMessage(role="user", content="Prior question two"),
        AgentMessage(role="agent", content=large_answer),
        AgentMessage(role="user", content="Prior question three"),
        AgentMessage(role="agent", content=large_answer),
        AgentMessage(role="user", content="Current question"),
    ]


class LocalProviderBudgetTests(unittest.TestCase):
    def test_ollama_trims_complete_history_and_applies_allowance_and_margin(self) -> None:
        profile = build_felis_profile(model="qwen3:4b-instruct")
        payload, estimated, dropped = ollama_budget_payload(
            _history_with_large_prior_interactions(),
            [],
            profile,
            profile.system_instruction,
            num_predict=profile.final_answer_max_tokens,
        )

        self.assertGreater(dropped, 0)
        self.assertLessEqual(
            estimated,
            profile.context_window - profile.final_answer_max_tokens - 512,
        )
        self.assertEqual(
            estimated,
            estimate_json_tokens(payload, bytes_per_token=3) + 128,
        )
        self.assertEqual(payload["options"]["num_ctx"], profile.context_window)
        self.assertEqual(
            payload["options"]["num_predict"],
            profile.final_answer_max_tokens,
        )

    def test_llama_cpp_trims_complete_history_and_applies_allowance_and_margin(
        self,
    ) -> None:
        profile = build_felis_profile()
        payload, estimated, dropped = llama_cpp_budget_payload(
            _history_with_large_prior_interactions(),
            [],
            profile,
            profile.system_instruction,
            max_tokens=profile.final_answer_max_tokens,
        )

        self.assertGreater(dropped, 0)
        self.assertLessEqual(
            estimated,
            profile.context_window - profile.final_answer_max_tokens - 512,
        )
        self.assertEqual(
            estimated,
            estimate_json_tokens(payload, bytes_per_token=3) + 128,
        )
        self.assertEqual(payload["max_tokens"], profile.final_answer_max_tokens)

    def test_current_interaction_is_rejected_after_history_is_exhausted(self) -> None:
        ollama_profile = build_felis_profile(model="qwen3:4b-instruct").model_copy(
            update={"context_window": 2048, "final_answer_max_tokens": 128}
        )
        llama_profile = build_felis_profile().model_copy(
            update={"context_window": 4096, "final_answer_max_tokens": 128}
        )
        current = [
            AgentMessage(
                role="user",
                content="Current interaction " * 20_000,
            )
        ]

        with self.assertRaisesRegex(RuntimeError, "Local prompt budget exceeded"):
            ollama_budget_payload(
                current,
                [],
                ollama_profile,
                ollama_profile.system_instruction,
                num_predict=ollama_profile.final_answer_max_tokens,
            )
        with self.assertRaisesRegex(RuntimeError, "Local prompt budget exceeded"):
            llama_cpp_budget_payload(
                current,
                [],
                llama_profile,
                llama_profile.system_instruction,
                max_tokens=llama_profile.final_answer_max_tokens,
            )

    def test_provider_overflow_error_is_actionable(self) -> None:
        profile = build_felis_profile(model="qwen3:4b-instruct")
        answer, detail = build_agent_failure_details(
            profile,
            RuntimeError(
                "Local prompt budget exceeded after removing prior history "
                "(estimated=5000, budget=3456, context_window=4096)."
            ),
        )

        self.assertIn("current interaction is too large", answer)
        self.assertIn("Shorten the prompt", answer)
        self.assertIn("provider-authoritative history trimming", detail)

    def test_provider_estimates_include_the_same_template_allowance(self) -> None:
        profile = build_felis_profile(model="qwen3:4b-instruct")
        payload, estimated, _dropped = ollama_budget_payload(
            [AgentMessage(role="user", content="Current question")],
            [],
            profile,
            profile.system_instruction,
            num_predict=profile.final_answer_max_tokens,
        )
        self.assertEqual(
            estimated,
            ollama_estimate_payload_tokens(payload),
        )
        llama_profile = build_felis_profile()
        llama_payload, llama_estimated, _llama_dropped = llama_cpp_budget_payload(
            [AgentMessage(role="user", content="Current question")],
            [],
            llama_profile,
            llama_profile.system_instruction,
            max_tokens=llama_profile.final_answer_max_tokens,
        )
        self.assertEqual(
            llama_estimated,
            llama_cpp_estimate_payload_tokens(llama_payload),
        )


if __name__ == "__main__":
    unittest.main()
