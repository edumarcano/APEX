"""Regression coverage for routing context construction."""

from __future__ import annotations

import unittest

from core.agent.routing.context import build_routing_document
from core.agent.types import AgentMessage


class CapabilityRoutingContextTests(unittest.TestCase):
    def test_includes_prompt_and_recent_history(self) -> None:
        document = build_routing_document(
            "Open that message.",
            [
                AgentMessage(role="user", content="Find Sarah's note."),
                AgentMessage(role="agent", content="I found a Gmail message."),
            ],
        )
        self.assertIn("CURRENT REQUEST:\nOpen that message.", document)
        self.assertIn("USER: Find Sarah's note.", document)
        self.assertIn("APEX: I found a Gmail message.", document)

    def test_drops_older_history_beyond_limit(self) -> None:
        history = [
            AgentMessage(role="user", content=f"old-{index}")
            for index in range(10)
        ]
        document = build_routing_document("Current", history)
        self.assertNotIn("old-0", document)
        self.assertIn("old-9", document)

    def test_unicode_preserved(self) -> None:
        document = build_routing_document("Résumé demain ?", [])
        self.assertIn("Résumé demain ?", document)


if __name__ == "__main__":
    unittest.main()
