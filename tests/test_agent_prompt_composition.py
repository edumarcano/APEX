"""Apex Agent prompt identity coverage."""

from __future__ import annotations

import unittest

from core.agent.catalog import (
    AGENT_SPECS,
    build_concrete_agent,
    compose_agent_system_instruction,
    resolve_agent_display_name,
)


class ApexAgentPromptTests(unittest.TestCase):
    def test_cloud_and_local_models_share_the_apex_identity(self) -> None:
        identity = AGENT_SPECS["apex"].identity_instruction
        for model_id in ("gpt-5.6-luna", "gemma-4-E2B-Q4_K_M.gguf"):
            with self.subTest(model_id=model_id):
                profile = build_concrete_agent("apex", native_effort=None, model_id=model_id)
                self.assertTrue(profile.system_instruction.startswith(identity))

    def test_default_identity_sentence_matches_catalog(self) -> None:
        instruction = compose_agent_system_instruction("apex", "Behavior instructions.")
        self.assertTrue(
            instruction.startswith(AGENT_SPECS["apex"].identity_instruction)
        )
        self.assertEqual(resolve_agent_display_name(""), "Apex Agent")
        self.assertEqual(resolve_agent_display_name("  "), "Apex Agent")

    def test_custom_display_name_and_user_designation_are_composed(self) -> None:
        instruction = compose_agent_system_instruction(
            "apex",
            "Behavior instructions.",
            model_profile=None,
            user_designation="Chief",
            agent_display_name="Nova",
        )
        self.assertTrue(
            instruction.startswith(
                "You are Nova, APEX's built-in personal operations assistant."
            )
        )
        self.assertIn('Address the user as "Chief" when natural.', instruction)
        self.assertEqual(instruction.count("Nova"), 1)
        self.assertNotIn("Apex Agent", instruction)

    def test_model_name_and_user_designation_are_composed_once(self) -> None:
        instruction = compose_agent_system_instruction(
            "apex", "Behavior instructions.", model_profile=None, user_designation="Chief"
        )
        self.assertIn('Address the user as "Chief" when natural.', instruction)
        self.assertEqual(instruction.count("Apex Agent"), 1)


if __name__ == "__main__":
    unittest.main()
