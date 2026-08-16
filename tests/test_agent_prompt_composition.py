"""Documented Apex Agent identity and prompt-composition coverage."""

from __future__ import annotations

import unittest
from unittest import mock

from core import config
from core.agent.catalog import (
    AGENT_SPECS,
    build_concrete_agent,
    compose_agent_system_instruction,
    resolve_effort,
)
from core.agent.model_catalog import get_model_profile
from core.agent.types import AgentQueryRequest, AgentQueryResponse
from core.api.cortex import _execute_agent_turn
from tests.support.agent_fixtures import (
    ACINONYX_MODEL,
    APODEMUS_MODEL,
    DELPHINUS_MODEL,
    EXPERIMENTAL_MODEL,
    MUS_MODEL,
    NEOFELIS_MODEL,
    NEOTOMA_MODEL,
    ORCINUS_MODEL,
    SOREX_MODEL,
    build_lynx_profile,
    build_panthera_profile,
)


class AgentIdentityTests(unittest.TestCase):
    _IDENTITIES = {
        "panthera": (
            "You are Apex Panthera, the cloud Apex Agent. "
            "You run through the operator's selected cloud provider and model."
        ),
        "lynx": (
            "You are Apex Lynx, the local Apex Agent. "
            "You run through the operator's selected local runtime and model."
        ),
    }

    _MODEL_POWERED_PREFIXES = {
        "gpt-5.6-luna": "You are currently powered by GPT-5.6 Luna.",
        "gemini-3.6-flash": "You are currently powered by Gemini 3.6 Flash.",
        "grok-4.3": "You are currently powered by Grok 4.3.",
        "grok-4.5": "You are currently powered by Grok 4.5.",
        "gemini-3.5-flash-lite": "You are currently powered by Gemini 3.5 Flash Lite.",
        "qwen3:1.7b": "You are currently powered by Qwen3 1.7B.",
        "qwen3:4b-instruct": "You are currently powered by Qwen3 4B Instruct.",
        APODEMUS_MODEL: "You are currently powered by Gemma 4 E2B.",
        NEOTOMA_MODEL: "You are currently powered by Gemma 4 E4B.",
        EXPERIMENTAL_MODEL: "You are currently powered by Qwen3.5 4B.",
    }

    def test_every_profile_has_the_expected_immutable_identity(self) -> None:
        self.assertEqual(set(AGENT_SPECS), set(self._IDENTITIES))
        for key, identity in self._IDENTITIES.items():
            with self.subTest(agent=key):
                self.assertEqual(AGENT_SPECS[key].identity_instruction, identity)

    def test_switching_model_preserves_agent_identity(self) -> None:
        cases = (
            ("panthera", NEOFELIS_MODEL),
            ("panthera", DELPHINUS_MODEL),
            ("panthera", ORCINUS_MODEL),
            ("panthera", ACINONYX_MODEL),
            ("lynx", SOREX_MODEL),
            ("lynx", MUS_MODEL),
            ("lynx", APODEMUS_MODEL),
            ("lynx", NEOTOMA_MODEL),
            ("lynx", EXPERIMENTAL_MODEL),
        )
        for agent_key, model_id in cases:
            with self.subTest(agent=agent_key, model=model_id):
                identity = self._IDENTITIES[agent_key]
                if agent_key == "panthera":
                    profile = build_panthera_profile(model=model_id)
                else:
                    profile = build_lynx_profile(model=model_id)
                self.assertTrue(profile.system_instruction.startswith(identity))
                self.assertIn(self._MODEL_POWERED_PREFIXES[model_id], profile.system_instruction)

    def test_effective_request_prompts_preserve_identity_with_runtime_overrides(self) -> None:
        captured_instructions: dict[str, str] = {}

        def capture_loop(*_args, **kwargs):
            profile = _args[2]
            captured_instructions[profile.display_name] = kwargs[
                "system_instruction_override"
            ]
            return AgentQueryResponse(answer="ok", agent_used={}, session_id=None)

        cases = (
            ("panthera", "gpt-5.6-luna"),
            ("lynx", APODEMUS_MODEL),
        )
        with (
            mock.patch("core.api.cortex._create_provider", return_value=mock.Mock()),
            mock.patch("core.api.cortex.run_agent_loop", side_effect=capture_loop),
            mock.patch(
                "core.api.cortex.config.AGENT_SYSTEM_PROMPT", "Cloud runtime prompt."
            ),
            mock.patch(
                "core.api.cortex.config.LOCAL_AGENT_SYSTEM_PROMPT", "Local runtime prompt."
            ),
        ):
            for agent_key, model_id in cases:
                if agent_key == "panthera":
                    profile = build_panthera_profile(model=model_id)
                else:
                    profile = build_lynx_profile(model=model_id)
                model_profile = get_model_profile(model_id)
                assert model_profile is not None
                _apex_effort, native_effort = resolve_effort(model_profile, None)
                _execute_agent_turn(
                    AgentQueryRequest(prompt="Identify yourself.", agent=agent_key),
                    profile,
                    agent_key=agent_key,
                    api_key="test",
                    resolved_apex_effort=None,
                    resolved_native_effort=native_effort,
                    user_designation="Chief",
                )
                instruction = captured_instructions[profile.display_name]
                self.assertTrue(
                    instruction.startswith(self._IDENTITIES[agent_key])
                )
                self.assertEqual(instruction.count(self._IDENTITIES[agent_key]), 1)
                self.assertNotIn("You are APEX", instruction)
                self.assertIn('Address the user as "Chief" when natural.', instruction)
                expected_runtime_prompt = (
                    "Local runtime prompt."
                    if AGENT_SPECS[agent_key].runtime == "local"
                    else "Cloud runtime prompt."
                )
                self.assertIn(expected_runtime_prompt, instruction)

    def test_identity_composition_keeps_identity_when_base_prompt_is_empty(self) -> None:
        identity = AGENT_SPECS["panthera"].identity_instruction
        self.assertEqual(compose_agent_system_instruction("panthera", "  "), identity)

    def test_user_designation_is_optional_and_added_once(self) -> None:
        identity = AGENT_SPECS["panthera"].identity_instruction
        instruction = compose_agent_system_instruction(
            "panthera",
            "Behavior instructions.",
            user_designation="  Chief\n ",
        )
        self.assertTrue(instruction.startswith(identity))
        self.assertIn('Address the user as "Chief" when natural.', instruction)
        self.assertEqual(instruction.count('Address the user as "Chief"'), 1)
        self.assertEqual(
            compose_agent_system_instruction(
                "panthera", "Behavior instructions.", user_designation=""
            ),
            f"{identity}\n\nBehavior instructions.",
        )


class PromptConfigurationTests(unittest.TestCase):
    def test_missing_prompt_configuration_is_not_replaced_by_embedded_text(self) -> None:
        with self.assertRaises(RuntimeError):
            config._required_prompt("", key="agent_system_prompt")


if __name__ == "__main__":
    unittest.main()
