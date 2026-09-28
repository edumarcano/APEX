"""Configuration coverage for archived Cortex conversation retention."""

from __future__ import annotations

import unittest

from core.config import CORTEX_CONVERSATIONS_ARCHIVED_RETENTION_DAYS
from core.settings.normalize import NormalizationIssues, normalize_layer


class ConversationRetentionConfigTests(unittest.TestCase):
    def test_default_retention_is_thirty_days(self) -> None:
        self.assertEqual(CORTEX_CONVERSATIONS_ARCHIVED_RETENTION_DAYS, 30)

    def test_retention_config_is_not_treated_as_an_unknown_editable_setting(self) -> None:
        issues = NormalizationIssues()

        normalized = normalize_layer(
            {"cortex_conversations": {"archived_retention_days": 30}},
            layer_name="config.json",
            issues=issues,
        )

        self.assertEqual(normalized, {})
        self.assertEqual(issues.warnings, [])


if __name__ == "__main__":
    unittest.main()
