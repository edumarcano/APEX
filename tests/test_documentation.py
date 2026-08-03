from __future__ import annotations

import unittest
from pathlib import Path

from scripts.check_docs import (
    ROOT,
    check_agent_profiles,
    check_cors_example,
    check_default_briefing_provider,
    check_frontend_owner_names,
    check_links,
    check_release_version,
    check_schema_versions,
    duplicate_route_headings,
    run,
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
        issues = check_agent_profiles(
            [source],
            {"neofelis": "gemini-3.6-flash"},
            {
                source: (
                    "| `neofelis` | Gemini `gemini-3.6-flash` |\n"
                    "old uses gemini-3.1-flash\n"
                )
            },
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].target, "gemini-3.1-flash")

    def test_reports_swapped_agent_model_mapping(self) -> None:
        source = Path("virtual-configuration.md")
        issues = check_agent_profiles(
            [source],
            {
                "panthera": "gpt-5.6-luna",
                "neofelis": "gemini-3.6-flash",
            },
            {
                source: (
                    "| `panthera` | Gemini `gemini-3.6-flash` |\n"
                    "| `neofelis` | OpenAI `gpt-5.6-luna` |\n"
                )
            },
        )

        self.assertEqual({issue.target for issue in issues}, {
            "panthera -> gpt-5.6-luna",
            "neofelis -> gemini-3.6-flash",
        })

    def test_reports_unknown_suffixless_grok_model(self) -> None:
        source = Path("virtual-readme.md")
        issues = check_agent_profiles(
            [source],
            {"delphinus": "grok-4.3"},
            {source: "delphinus -> grok-4.3; retired model grok-4.2\n"},
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].target, "grok-4.2")

    def test_reports_duplicate_route_detail_heading(self) -> None:
        duplicates = duplicate_route_headings(
            "### POST `/api/v1/example`\n\n### POST `/api/v1/example`\n"
        )

        self.assertEqual(duplicates, [("POST", "/api/v1/example", 3)])

    def test_repository_cors_example_preserves_defaults(self) -> None:
        self.assertEqual(check_cors_example(ROOT), [])

    def test_repository_release_version_matches_changelog(self) -> None:
        self.assertEqual(check_release_version(ROOT), [])

    def test_frontend_state_owners_use_current_names(self) -> None:
        self.assertEqual(check_frontend_owner_names(ROOT), [])

    def test_readme_names_the_default_briefing_provider(self) -> None:
        self.assertEqual(check_default_briefing_provider(ROOT), [])

    def test_complete_documentation_contract(self) -> None:
        self.assertEqual(run(ROOT), [])


if __name__ == "__main__":
    unittest.main()
