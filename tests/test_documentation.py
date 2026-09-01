from __future__ import annotations

import unittest
from pathlib import Path

from scripts.check_docs import (
    ROOT,
    check_agent_profiles,
    check_api_contract_version,
    check_default_briefing_provider,
    check_links,
    check_schema_versions,
    duplicate_route_headings,
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

    def test_reports_prose_api_contract_version_mismatch(self) -> None:
        source = Path("virtual-api.md")
        issues = check_api_contract_version(
            source, 13, {source: "The current contract version is `12`.\n"}
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].target, "12")
        self.assertIn("should be 13", issues[0].reason)

    def test_reports_unknown_gemini_model(self) -> None:
        source = Path("virtual-readme.md")
        issues = check_agent_profiles(
            [source],
            {"catalog-one": "gemini-3.6-flash"},
            {
                source: (
                    "| `catalog-one` | Gemini `gemini-3.6-flash` |\n"
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
                "catalog-one": "gpt-5.6-luna",
                "catalog-two": "gemini-3.6-flash",
            },
            {
                source: (
                    "| `catalog-one` | Gemini `gemini-3.6-flash` |\n"
                    "| `catalog-two` | OpenAI `gpt-5.6-luna` |\n"
                )
            },
        )

        self.assertEqual({issue.target for issue in issues}, {
            "catalog-one -> gpt-5.6-luna",
            "catalog-two -> gemini-3.6-flash",
        })

    def test_reports_unknown_suffixless_grok_model(self) -> None:
        source = Path("virtual-readme.md")
        issues = check_agent_profiles(
            [source],
            {"catalog-one": "grok-4.3"},
            {source: "catalog-one -> grok-4.3; retired model grok-4.2\n"},
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].target, "grok-4.2")

    def test_reports_duplicate_route_detail_heading(self) -> None:
        duplicates = duplicate_route_headings(
            "### POST `/api/v1/example`\n\n### POST `/api/v1/example`\n"
        )

        self.assertEqual(duplicates, [("POST", "/api/v1/example", 3)])

    def test_readme_briefing_check_rejects_ollama_and_missing_paths(self) -> None:
        issues = check_default_briefing_provider(
            ROOT,
            readme_text=(
                "### Produces briefings on user-defined terms\n"
                "A briefing can use a local model through Ollama.\n\n"
                "```mermaid\n"
                'B --> M["OpenRouter · Ollama"]\n'
                "```\n"
            ),
        )

        reasons = {issue.reason for issue in issues}
        self.assertIn("obsolete Ollama briefing provider is documented", reasons)
        self.assertIn("briefing diagram omits a supported synthesis path", reasons)

if __name__ == "__main__":
    unittest.main()
