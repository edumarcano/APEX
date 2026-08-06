"""Tests for deterministic capability routing rules."""

from __future__ import annotations

import unittest

from core.agent.routing.rules import apply_routing_rules
from core.agent.types import AgentMessage


class CapabilityRoutingRulesTests(unittest.TestCase):
    def test_schedule_entity_pattern(self) -> None:
        matches = apply_routing_rules("What is on my calendar tomorrow?", [])
        families = {item.family for item in matches}
        self.assertIn("schedule", families)

    def test_no_tool_pattern_without_entities(self) -> None:
        matches = apply_routing_rules("Explain gradient descent in simple terms.", [])
        families = {item.family for item in matches}
        self.assertIn("none", families)

    def test_ambiguous_prompt_returns_no_rule_matches(self) -> None:
        matches = apply_routing_rules("Check on that for me.", [])
        self.assertEqual(matches, [])

    def test_family_name_mention_in_synthetic_prompt(self) -> None:
        matches = apply_routing_rules(
            "Please help with search information request 76.",
            [],
        )
        families = {item.family for item in matches}
        self.assertIn("search", families)

    def test_history_context_used_for_rules(self) -> None:
        history = [
            AgentMessage(role="user", content="Show my To Do lists."),
            AgentMessage(role="agent", content="You have a Work list."),
        ]
        matches = apply_routing_rules("List tasks in that list.", history)
        families = {item.family for item in matches}
        self.assertIn("todo", families)


if __name__ == "__main__":
    unittest.main()
