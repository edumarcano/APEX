from __future__ import annotations

import unittest
from pathlib import Path

from scripts.check_docs import (
    check_gemini_profiles,
    check_links,
    check_schema_versions,
)


class DocumentationCheckerTests(unittest.TestCase):
    def test_accepts_valid_relative_link_and_anchor(self) -> None:
        root = Path("virtual-valid").resolve()
        source = root / "README.md"
        target = root / "guide.md"
        contents = {
            source: "[Guide](guide.md#quick-start)\n",
            target: "# Quick Start\n",
        }

        self.assertEqual(check_links([source, target], root, contents), [])

    def test_reports_missing_file(self) -> None:
        root = Path("virtual-missing-file").resolve()
        source = root / "README.md"

        issues = check_links(
            [source], root, {source: "[Missing](missing.md)\n"}
        )

        self.assertEqual(len(issues), 1)
        self.assertIn("file does not exist", issues[0].reason)

    def test_reports_missing_anchor(self) -> None:
        root = Path("virtual-missing-anchor").resolve()
        source = root / "README.md"
        target = root / "guide.md"
        contents = {
            source: "[Guide](guide.md#missing)\n",
            target: "# Present\n",
        }

        issues = check_links([source, target], root, contents)

        self.assertEqual(len(issues), 1)
        self.assertIn("anchor does not exist", issues[0].reason)

    def test_ignores_links_inside_fenced_code(self) -> None:
        root = Path("virtual-fence").resolve()
        source = root / "README.md"
        contents = {source: "```markdown\n[Example](missing.md)\n```\n"}

        self.assertEqual(check_links([source], root, contents), [])

    def test_reports_schema_version_mismatch(self) -> None:
        source = Path("virtual-api.md")
        issues = check_schema_versions(
            [source], 5, {source: '{"schema_version": 4}\n'}
        )

        self.assertEqual(len(issues), 1)
        self.assertIn("should be 5", issues[0].reason)

    def test_reports_unknown_gemini_model(self) -> None:
        source = Path("virtual-readme.md")
        issues = check_gemini_profiles(
            [source],
            {"comet": "gemini-3.5-flash-lite"},
            {
                source: (
                    "comet uses gemini-3.5-flash-lite; "
                    "old uses gemini-3.1-flash\n"
                )
            },
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].target, "gemini-3.1-flash")


if __name__ == "__main__":
    unittest.main()
