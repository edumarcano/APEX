from __future__ import annotations

import unittest
from pathlib import Path

from scripts.check_docs import (
    ROOT,
    check_agent_profiles,
    check_briefing_profiles,
    check_frontend_owner_names,
    check_links,
    check_release_version,
    duplicate_route_headings,
)


class DocumentationCheckerTests(unittest.TestCase):
    def make_version_root(self, version: str, *, uv_version: str | None = None) -> Path:
        from tempfile import TemporaryDirectory

        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "frontend" / "src-tauri").mkdir(parents=True)
        (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
        (root / "uv.lock").write_text(
            f'[[package]]\nname = "apex"\nversion = "{uv_version or version}"\n', encoding="utf-8"
        )
        (root / "frontend" / "src-tauri" / "Cargo.toml").write_text(
            f'[package]\nname = "apex-desktop"\nversion = "{version}"\n', encoding="utf-8"
        )
        (root / "frontend" / "src-tauri" / "Cargo.lock").write_text(
            f'[[package]]\nname = "apex-desktop"\nversion = "{version}"\n', encoding="utf-8"
        )
        (root / "frontend" / "src-tauri" / "tauri.conf.json").write_text(
            f'{{"version":"{version}"}}', encoding="utf-8"
        )
        (root / "CHANGELOG.md").write_text("## v2.0.0 - APEX 2.0\n", encoding="utf-8")
        return root

    def test_release_version_accepts_matching_and_forward_versions(self) -> None:
        for version in ("2.0.0", "2.1.0", "2.1.0b1"):
            with self.subTest(version=version):
                self.assertEqual(check_release_version(self.make_version_root(version)), [])

    def test_release_version_rejects_older_metadata(self) -> None:
        issues = check_release_version(self.make_version_root("1.9.9"))

        self.assertTrue(any("older than latest release" in issue.reason for issue in issues))

    def test_release_version_rejects_malformed_metadata(self) -> None:
        issues = check_release_version(self.make_version_root("2.1"))

        self.assertTrue(any("malformed" in issue.reason for issue in issues))

    def test_release_version_reports_malformed_metadata_structure(self) -> None:
        root = self.make_version_root("2.1.0")
        (root / "uv.lock").write_text("[]", encoding="utf-8")

        issues = check_release_version(root)

        self.assertTrue(any("could not read version metadata" in issue.reason for issue in issues))

    def test_release_version_rejects_split_metadata(self) -> None:
        issues = check_release_version(self.make_version_root("2.1.0", uv_version="2.0.0"))

        self.assertTrue(any("differs from" in issue.reason for issue in issues))

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

    def test_reports_unknown_gemini_model(self) -> None:
        source = Path("virtual-readme.md")
        issues = check_agent_profiles(
            [source],
            {"catalog-one": "gemini-3.7-flash"},
            {
                source: (
                    "| `catalog-one` | Gemini `gemini-3.7-flash` |\n"
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
                "catalog-one": "openai/gpt-6-luna",
                "catalog-two": "gemini-3.7-flash",
            },
            {
                source: (
                    "| `catalog-one` | Gemini `gemini-3.7-flash` |\n"
                    "| `catalog-two` | OpenRouter `openai/gpt-6-luna` |\n"
                )
            },
        )

        self.assertEqual({issue.target for issue in issues}, {
            "catalog-one -> openai/gpt-6-luna",
            "catalog-two -> gemini-3.7-flash",
        })

    def test_reports_unknown_suffixless_grok_model(self) -> None:
        source = Path("virtual-readme.md")
        issues = check_agent_profiles(
            [source],
            {"catalog-one": "openai/gpt-6-luna"},
            {source: "catalog-one -> openai/gpt-6-luna; retired model grok-4.2\n"},
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].target, "grok-4.2")

    def test_reports_duplicate_route_detail_heading(self) -> None:
        duplicates = duplicate_route_headings(
            "### POST `/api/v1/example`\n\n### POST `/api/v1/example`\n"
        )

        self.assertEqual(duplicates, [("POST", "/api/v1/example", 3)])

    def test_readme_briefing_check_requires_current_profiles(self) -> None:
        issues = check_briefing_profiles(
            ROOT,
            readme_text=(
                "```mermaid\n"
                'B --> M["Daily"]\n'
                "```\n"
            ),
        )

        missing_profiles = {issue.target for issue in issues}
        self.assertEqual(missing_profiles, {"Catch Up", "Deep"})

    def test_frontend_owner_names_reports_missing_cortex_runs(self) -> None:
        root = Path("virtual-frontend").resolve()
        source = root / "frontend" / "README.md"
        contents = {source: "| `useCortex` | Browser conversation |\n"}
        issues = check_frontend_owner_names(root, contents=contents)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].target, "useCortexRuns")
        self.assertIn("current Cortex runs owner is missing", issues[0].reason)

    def test_frontend_owner_names_accepts_valid_current_owners(self) -> None:
        root = Path("virtual-frontend").resolve()
        source = root / "frontend" / "README.md"
        contents = {
            source: (
                "| `useCortex` | Browser conversation |\n"
                "| `useCortexRuns` | Recent runs |\n"
            )
        }
        issues = check_frontend_owner_names(root, contents=contents)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
