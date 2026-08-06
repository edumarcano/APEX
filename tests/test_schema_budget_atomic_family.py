"""Regression coverage for atomic family schema budgeting."""

from __future__ import annotations

import unittest

from core.agent.capabilities import list_agent_capabilities
from core.agent.local_commands import estimate_schema_tokens
from core.agent.routing.service import _apply_schema_budget, _order_descriptors_for_family


class SchemaBudgetAtomicFamilyTests(unittest.TestCase):
    def test_mail_family_not_partially_offered_when_only_search_fits(self) -> None:
        mail_descriptors = _order_descriptors_for_family(
            "mail",
            tuple(
                descriptor
                for descriptor in list_agent_capabilities()
                if descriptor.routing_family == "mail"
            ),
        )
        self.assertGreaterEqual(len(mail_descriptors), 2)
        search_tokens = estimate_schema_tokens([mail_descriptors[0]])
        total_tokens = estimate_schema_tokens(mail_descriptors)
        self.assertLess(search_tokens, total_tokens)

        budget = search_tokens + max(1, (total_tokens - search_tokens) // 2)
        offered, fully_truncated, partially_truncated = _apply_schema_budget(
            ["mail"],
            [
                descriptor
                for descriptor in list_agent_capabilities()
                if descriptor.routing_family == "mail"
            ],
            budget,
        )
        offered_names = [descriptor.name for descriptor in offered]
        self.assertNotIn("search_gmail", offered_names)
        self.assertNotIn("get_gmail_message", offered_names)
        self.assertIn("mail", partially_truncated + fully_truncated)

    def test_first_descriptor_not_added_when_it_exceeds_budget(self) -> None:
        descriptors = _order_descriptors_for_family(
            "weather",
            tuple(
                descriptor
                for descriptor in list_agent_capabilities()
                if descriptor.routing_family == "weather"
            ),
        )
        self.assertTrue(descriptors)
        single_token_budget = max(1, estimate_schema_tokens([descriptors[0]]) - 1)
        offered, fully_truncated, partially_truncated = _apply_schema_budget(
            ["weather"],
            [
                descriptor
                for descriptor in list_agent_capabilities()
                if descriptor.routing_family == "weather"
            ],
            single_token_budget,
        )
        self.assertEqual(offered, [])
        self.assertTrue(fully_truncated or partially_truncated)


if __name__ == "__main__":
    unittest.main()
