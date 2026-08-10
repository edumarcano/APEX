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
from core.agent.types import AgentQueryRequest, AgentQueryResponse
from core.api.cortex import _execute_agent_turn


class AgentIdentityTests(unittest.TestCase):
    _IDENTITIES = {
        "acinonyx": (
            "You are Apex Acinonyx, an Apex Agent powered by "
            "Gemini 3.5 Flash Lite. You are the development-only privacy sandbox."
        ),
        "panthera": "You are Apex Panthera, an Apex Agent powered by GPT-5.6 Luna.",
        "neofelis": "You are Apex Neofelis, an Apex Agent powered by Gemini 3.6 Flash.",
        "delphinus": "You are Apex Delphinus, an Apex Agent powered by Grok 4.3.",
        "orcinus": "You are Apex Orcinus, an Apex Agent powered by Grok 4.5.",
        "sorex": "You are Apex Sorex, an Apex Agent powered by Qwen3 1.7B through Ollama.",
        "mus": "You are Apex Mus, an Apex Agent powered by Qwen3 4B Instruct through Ollama.",
        "apodemus": "You are Apex Apodemus, an Apex Agent powered by Gemma 4 E2B through llama.cpp.",
        "neotoma": "You are Apex Neotoma, an Apex Agent powered by Gemma 4 E4B through llama.cpp.",
        "unnamed-experimental-agent": (
            "You are Unnamed Experimental Agent, a technical APEX development "
            "target powered by Qwen3.5 4B through llama.cpp."
        ),
    }

    def test_every_profile_has_the_expected_immutable_identity(self) -> None:
        self.assertEqual(set(AGENT_SPECS), set(self._IDENTITIES))
        for key, identity in self._IDENTITIES.items():
            with self.subTest(agent=key):
                self.assertEqual(AGENT_SPECS[key].identity_instruction, identity)
                _apex_effort, native_effort = resolve_effort(key, None)
                profile = build_concrete_agent(key, native_effort=native_effort)
                self.assertTrue(profile.system_instruction.startswith(identity))

    def test_effective_request_prompts_preserve_identity_with_runtime_overrides(self) -> None:
        captured_instructions: dict[str, str] = {}

        def capture_loop(*_args, **kwargs):
            profile = _args[2]
            captured_instructions[profile.display_name] = kwargs[
                "system_instruction_override"
            ]
            return AgentQueryResponse(answer="ok", agent_used={}, session_id=None)

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
            for key, identity in self._IDENTITIES.items():
                _apex_effort, native_effort = resolve_effort(key, None)
                profile = build_concrete_agent(key, native_effort=native_effort)
                _execute_agent_turn(
                    AgentQueryRequest(prompt="Identify yourself.", agent=key),
                    profile,
                    agent_key=key,
                    api_key="test",
                    resolved_apex_effort=None,
                    resolved_native_effort=native_effort,
                    user_designation="Chief",
                )
                instruction = captured_instructions[profile.display_name]
                self.assertTrue(instruction.startswith(identity))
                self.assertEqual(instruction.count(identity), 1)
                self.assertNotIn("You are APEX", instruction)
                self.assertIn('Address the user as "Chief" when natural.', instruction)
                expected_runtime_prompt = (
                    "Local runtime prompt."
                    if AGENT_SPECS[key].runtime == "local"
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
