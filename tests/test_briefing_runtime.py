"""Shared-model resolution and bounded one-call execution tests."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from core.agent.types import AgentMessage, ToolCall
from core.briefings.execution import (
    BriefingModelOutputError,
    InvalidBriefingModelOutputError,
    execute_single_call,
)
from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingModelConfiguration,
    MAX_PROMPT_BYTES,
)
from core.briefings.runtime import (
    BriefingModelConfigurationError,
    resolve_briefing_configuration,
)
from core.agent.providers.contract import ProviderTurnResult


class BriefingModelResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ask_apex = SimpleNamespace(
            enabled=True,
            local=SimpleNamespace(
                last_model="gemma-4-E2B-Q4_K_M.gguf",
                context_window=8192,
                reasoning_mode="none",
            ),
        )
        self.settings = SimpleNamespace(ask_apex=self.ask_apex)

    def test_valid_catalog_context_above_previous_universal_cap_is_preserved(self) -> None:
        request = BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="deep",
            model_id="deepseek/deepseek-v4-flash-0731",
            reasoning="high",
            context_window=1_310_720,
        )
        with (
            patch("core.briefings.runtime.get_settings_store", return_value=SimpleNamespace(get_snapshot=lambda: self.settings)),
            patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
        ):
            configuration = resolve_briefing_configuration(request)

        self.assertEqual(configuration.model.context_window, 1_310_720)
        self.assertEqual(configuration.model.reasoning, "high")
        self.assertEqual(configuration.profile.id, "deep")

    def test_unknown_or_hidden_model_is_rejected_without_substitution(self) -> None:
        unknown = BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="missing-model",
        )
        hidden = BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="gpt-5.6-luna",
        )
        for request in (unknown, hidden):
            with self.subTest(model=request.model_id), self.assertRaises(
                BriefingModelConfigurationError
            ):
                resolve_briefing_configuration(request)

    def test_unsupported_reasoning_and_context_are_rejected(self) -> None:
        invalid_reasoning = BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="deepseek/deepseek-v4-flash-0731",
            reasoning="medium",
        )
        excessive_context = BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="deepseek/deepseek-v4-flash-0731",
            context_window=1_310_721,
        )
        with patch("core.briefings.runtime.get_settings_store", return_value=SimpleNamespace(get_snapshot=lambda: self.settings)):
            with self.assertRaises(BriefingModelConfigurationError):
                resolve_briefing_configuration(invalid_reasoning)
            with self.assertRaises(BriefingModelConfigurationError):
                resolve_briefing_configuration(excessive_context)


class _ExecutionControl:
    def __init__(self) -> None:
        self.before = 0
        self.after = 0

    def before_model_turn(self) -> None:
        self.before += 1

    def after_model_turn(self, _result: ProviderTurnResult) -> None:
        self.after += 1


class _SingleCallProvider:
    def __init__(self) -> None:
        self.calls = []

    def generate_turn(self, messages, tools, profile, **kwargs):
        self.calls.append((messages, tools, profile, kwargs))
        return ProviderTurnResult(
            message=AgentMessage(role="agent", content='{"sections":[]}'),
            usage={"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
        )


class BriefingSingleCallTests(unittest.TestCase):
    @staticmethod
    def _configuration(*, context_window: int | None = None):
        profile = BUILTIN_BRIEFING_PROFILES["daily"]
        return BriefingGenerationConfiguration(
            profile=profile,
            model=BriefingModelConfiguration(
                model_id="deepseek/deepseek-v4-flash-0731",
                provider="openrouter",
                runtime="cloud",
                reasoning="high",
                context_window=context_window,
                max_elapsed_seconds=30,
                max_retries=1,
                max_model_turns=1,
                max_tool_calls=1,
                output_token_limit=48,
            ),
            origin="hud",
        )

    def test_single_call_is_tool_free_explicit_and_bounded(self) -> None:
        provider = _SingleCallProvider()
        control = _ExecutionControl()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            result = execute_single_call(
                configuration=self._configuration(),
                prompt="Create a structured briefing from the supplied evidence.",
                output_schema={"type": "object"},
                control=control,  # type: ignore[arg-type]
                provider_factory=lambda _profile, _key: provider,
            )

        self.assertEqual(result.message.content, '{"sections":[]}')
        self.assertEqual(len(provider.calls), 1)
        messages, tools, model_profile, kwargs = provider.calls[0]
        self.assertEqual(len(messages), 1)
        self.assertEqual(tools, [])
        self.assertEqual(model_profile.api_model, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(model_profile.reasoning_effort, "high")
        self.assertEqual(model_profile.hosted_tools, frozenset())
        self.assertEqual(kwargs["output_token_limit"], 48)
        self.assertEqual(kwargs["output_schema"], {"type": "object"})
        self.assertIs(kwargs["execution_control"], control)
        self.assertEqual((control.before, control.after), (1, 1))

    def test_prompt_and_context_bounds_reject_before_provider_call(self) -> None:
        provider_calls = []
        control = _ExecutionControl()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            with self.assertRaises(BriefingModelOutputError):
                execute_single_call(
                    configuration=self._configuration(),
                    prompt="x" * (MAX_PROMPT_BYTES + 1),
                    output_schema={"type": "object"},
                    control=control,  # type: ignore[arg-type]
                    provider_factory=lambda *_args: provider_calls.append(True),
                )
            with self.assertRaises(BriefingModelOutputError):
                execute_single_call(
                    configuration=self._configuration(context_window=48),
                    prompt="x" * 100,
                    output_schema={"type": "object"},
                    control=control,  # type: ignore[arg-type]
                    provider_factory=lambda *_args: provider_calls.append(True),
                )
        self.assertEqual(provider_calls, [])

    def test_rejected_provider_response_still_counts_the_completed_turn(self) -> None:
        class ToolReturningProvider(_SingleCallProvider):
            def generate_turn(self, messages, tools, profile, **kwargs):
                self.calls.append((messages, tools, profile, kwargs))
                return ProviderTurnResult(
                    message=AgentMessage(
                        role="agent",
                        content="not a supported briefing result",
                        tool_calls=[ToolCall(id="call-1", name="search", arguments={})],
                    ),
                    usage={"input_tokens": 7, "output_tokens": 4, "total_tokens": 11},
                )

        provider = ToolReturningProvider()
        control = _ExecutionControl()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            with self.assertRaisesRegex(InvalidBriefingModelOutputError, "tool"):
                execute_single_call(
                    configuration=self._configuration(),
                    prompt="Make one structured call.",
                    output_schema={"type": "object"},
                    control=control,  # type: ignore[arg-type]
                    provider_factory=lambda _profile, _key: provider,
                )
        self.assertEqual((control.before, control.after), (1, 1))

    def test_empty_and_oversized_provider_responses_are_repairable_output_errors(self) -> None:
        class ContentReturningProvider(_SingleCallProvider):
            def __init__(self, content: str) -> None:
                super().__init__()
                self.content = content

            def generate_turn(self, messages, tools, profile, **kwargs):
                self.calls.append((messages, tools, profile, kwargs))
                return ProviderTurnResult(
                    message=AgentMessage(role="agent", content=self.content),
                )

        for content, feedback in (("", "No response content"), ("x" * 769, "output bound")):
            with self.subTest(feedback=feedback), patch.dict(
                os.environ, {"OPENROUTER_API_KEY": "test-key"}
            ):
                with self.assertRaises(InvalidBriefingModelOutputError) as raised:
                    execute_single_call(
                        configuration=self._configuration(),
                        prompt="Make one structured call.",
                        output_schema={"type": "object"},
                        control=_ExecutionControl(),  # type: ignore[arg-type]
                        provider_factory=lambda _profile, _key: ContentReturningProvider(content),
                    )

            self.assertIn(feedback, raised.exception.repair_feedback)


if __name__ == "__main__":
    unittest.main()
