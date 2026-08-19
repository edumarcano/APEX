"""Validate public APEX documentation links and versioned contracts."""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
EXPLICIT_ANCHOR_PATTERN = re.compile(
    r"<a\s+(?:[^>]*?\s)?id=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE
)
ROUTE_ROW_PATTERN = re.compile(
    r"^\|\s*(GET|POST|PATCH|PUT|DELETE)\s*\|\s*`([^`]+)`\s*\|",
    re.IGNORECASE,
)
ROUTE_HEADING_PATTERN = re.compile(
    r"^#{2,6}\s+(GET|POST|PATCH|PUT|DELETE)\s+`([^`]+)`\s*$",
    re.IGNORECASE,
)
SCHEMA_VERSION_PATTERN = re.compile(r'"schema_version"\s*:\s*(\d+)')
API_CONTRACT_VERSION_PATTERN = re.compile(
    r"\bcontract\s+version\s+(?:is\s+)?`?(\d+)`?", re.IGNORECASE
)
RELEASE_HEADING_PATTERN = re.compile(r"^##\s+v(\d+\.\d+\.\d+)\b", re.MULTILINE)


@dataclass(frozen=True)
class DocumentationIssue:
    path: Path
    line: int
    target: str
    reason: str

    def format(self, root: Path = ROOT) -> str:
        try:
            display = self.path.resolve().relative_to(root.resolve())
        except ValueError:
            display = self.path
        return f"{display}:{self.line}: {self.reason}: {self.target}"


def public_document_paths(root: Path) -> list[Path]:
    paths = [
        root / "README.md",
        root / "CHANGELOG.md",
        root / ".env.example",
        root / "frontend" / "README.md",
        root / "benchmarks" / "README.md",
    ]
    paths.extend(sorted((root / "docs").rglob("*.md")))
    return [path for path in paths if path.is_file()]


def lines_outside_fences(text: str) -> Iterable[tuple[int, str]]:
    in_fence = False
    fence_marker = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if not in_fence:
            yield line_number, line


def github_slug(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[`*_~]", "", value).strip().lower()
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    return value.replace(" ", "-")


def anchors_for_text(text: str) -> set[str]:
    anchors: set[str] = set()
    slug_counts: dict[str, int] = {}
    for _, line in lines_outside_fences(text):
        anchors.update(EXPLICIT_ANCHOR_PATTERN.findall(line))
        heading = HEADING_PATTERN.match(line)
        if heading is None:
            continue
        base = github_slug(heading.group(2))
        count = slug_counts.get(base, 0)
        slug_counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def _split_link_target(raw_target: str) -> tuple[str, str | None]:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if "#" not in target:
        return unquote(target), None
    file_part, anchor = target.split("#", 1)
    return unquote(file_part), unquote(anchor)


def check_links(
    paths: Iterable[Path],
    root: Path,
    contents: Mapping[Path, str] | None = None,
) -> list[DocumentationIssue]:
    issues: list[DocumentationIssue] = []
    anchor_cache: dict[Path, set[str]] = {}
    virtual_contents = (
        {path.resolve(): text for path, text in contents.items()}
        if contents is not None
        else {}
    )

    for source in paths:
        resolved_source = source.resolve()
        text = virtual_contents.get(resolved_source)
        if text is None:
            text = source.read_text(encoding="utf-8")
        for line_number, line in lines_outside_fences(text):
            for match in LINK_PATTERN.finditer(line):
                raw_target = match.group(1)
                if re.match(r"^(?:https?://|mailto:|data:)", raw_target, re.IGNORECASE):
                    continue
                file_part, anchor = _split_link_target(raw_target)
                target_file = source if not file_part else (source.parent / file_part)
                target_file = target_file.resolve()

                if target_file not in virtual_contents and not target_file.is_file():
                    issues.append(
                        DocumentationIssue(
                            source,
                            line_number,
                            raw_target,
                            "linked file does not exist",
                        )
                    )
                    continue

                if anchor is None:
                    continue
                if target_file not in anchor_cache:
                    target_text = virtual_contents.get(target_file)
                    if target_text is None:
                        target_text = target_file.read_text(encoding="utf-8")
                    anchor_cache[target_file] = anchors_for_text(target_text)
                if anchor not in anchor_cache[target_file]:
                    issues.append(
                        DocumentationIssue(
                            source,
                            line_number,
                            raw_target,
                            "linked anchor does not exist",
                        )
                    )
    return issues


def documented_routes(api_text: str) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for _, line in lines_outside_fences(api_text):
        match = ROUTE_ROW_PATTERN.match(line)
        if match is not None:
            routes.add((match.group(1).upper(), match.group(2)))
    return routes


def duplicate_route_headings(api_text: str) -> list[tuple[str, str, int]]:
    """Return duplicate route-detail headings with their first duplicate line."""
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str, int]] = []
    for line_number, line in lines_outside_fences(api_text):
        match = ROUTE_HEADING_PATTERN.match(line)
        if match is not None:
            route = (match.group(1).upper(), match.group(2))
            if route in seen:
                duplicates.append((*route, line_number))
            else:
                seen.add(route)
    return duplicates


def check_routes(
    api_path: Path,
    expected: set[tuple[str, str]],
) -> list[DocumentationIssue]:
    api_text = api_path.read_text(encoding="utf-8")
    actual = documented_routes(api_text)
    issues: list[DocumentationIssue] = []
    for method, path in sorted(expected - actual):
        issues.append(
            DocumentationIssue(api_path, 1, f"{method} {path}", "public route is undocumented")
        )
    for method, path in sorted(actual - expected):
        issues.append(
            DocumentationIssue(api_path, 1, f"{method} {path}", "documented route is not public")
        )
    for method, path, line in duplicate_route_headings(api_text):
        issues.append(
            DocumentationIssue(
                api_path,
                line,
                f"{method} {path}",
                "route detail heading is duplicated",
            )
        )
    return issues


def check_schema_versions(
    paths: Iterable[Path],
    expected_version: int,
    contents: Mapping[Path, str] | None = None,
) -> list[DocumentationIssue]:
    issues: list[DocumentationIssue] = []
    for path in paths:
        text = contents.get(path, "") if contents is not None else path.read_text(encoding="utf-8")
        for line_number, line in enumerate(
            text.splitlines(), start=1
        ):
            for match in SCHEMA_VERSION_PATTERN.finditer(line):
                found = int(match.group(1))
                if found != expected_version:
                    issues.append(
                        DocumentationIssue(
                            path,
                            line_number,
                            str(found),
                            f"settings schema version should be {expected_version}",
                        )
                    )
    return issues


def check_api_contract_version(
    api_path: Path,
    expected_version: int,
    contents: Mapping[Path, str] | None = None,
) -> list[DocumentationIssue]:
    """Keep the human-readable API contract version aligned with settings."""
    text = contents.get(api_path, "") if contents is not None else api_path.read_text(
        encoding="utf-8"
    )
    matches = [
        (line_number, match)
        for line_number, line in lines_outside_fences(text)
        for match in API_CONTRACT_VERSION_PATTERN.finditer(line)
    ]
    if not matches:
        return [
            DocumentationIssue(
                api_path,
                1,
                "contract version",
                f"API contract version statement should be {expected_version}",
            )
        ]

    issues: list[DocumentationIssue] = []
    for line_number, match in matches:
        found = int(match.group(1))
        if found != expected_version:
            issues.append(
                DocumentationIssue(
                    api_path,
                    line_number,
                    str(found),
                    f"API contract version should be {expected_version}",
                )
            )
    return issues


def check_agent_profiles(
    paths: Iterable[Path],
    expected_profiles: Mapping[str, str],
    contents: Mapping[Path, str] | None = None,
) -> list[DocumentationIssue]:
    issues: list[DocumentationIssue] = []
    texts = {
        path: contents.get(path, "") if contents is not None else path.read_text(encoding="utf-8")
        for path in paths
    }
    for key, model in sorted(expected_profiles.items()):
        mapping_patterns = (
            re.compile(
                rf"\b`?{re.escape(key)}`?\s*->\s*`?{re.escape(model)}`?(?=\s|$|[,;])",
                re.IGNORECASE,
            ),
            re.compile(
                rf"^\|\s*`{re.escape(key)}`[^|]*\|[^|]*`{re.escape(model)}`",
                re.IGNORECASE | re.MULTILINE,
            ),
        )
        if not any(pattern.search(text) for pattern in mapping_patterns for text in texts.values()):
            issues.append(
                DocumentationIssue(
                    ROOT / "docs" / "configuration.md",
                    1,
                    f"{key} -> {model}",
                    "current Agent model mapping is missing",
                )
            )

    known_models = registered_model_ids()
    model_pattern = re.compile(
        r"(?:gemini|gpt|grok)-\d+(?:\.\d+)*(?:-[a-z0-9-]+)?|"
        r"qwen\d+(?:\.\d+)?:[a-z0-9.-]+|"
        r"[a-z0-9][a-z0-9._-]*\.gguf",
        re.IGNORECASE,
    )
    for path in paths:
        for line_number, line in enumerate(
            texts[path].splitlines(), start=1
        ):
            for model in model_pattern.findall(line):
                model = model.lower()
                if model not in known_models:
                    issues.append(
                        DocumentationIssue(
                            path,
                            line_number,
                            model,
                            "model ID is not used by a current Agent",
                        )
                    )
    return issues


def check_gemini_profiles(
    paths: Iterable[Path],
    expected_profiles: Mapping[str, str],
    contents: Mapping[Path, str] | None = None,
) -> list[DocumentationIssue]:
    """Compatibility wrapper for callers of the former Gemini-only check."""
    return check_agent_profiles(paths, expected_profiles, contents)


def check_cors_example(root: Path) -> list[DocumentationIssue]:
    """Prevent .env.example from narrowing the tested localhost defaults."""
    from core.api.app import DEFAULT_ALLOWED_ORIGINS

    env_path = root / ".env.example"
    text = env_path.read_text(encoding="utf-8")
    assignments = re.findall(r"^APEX_ALLOWED_ORIGINS=(.+)$", text, re.MULTILINE)
    issues: list[DocumentationIssue] = []
    if assignments:
        configured = {
            item.strip() for item in assignments[-1].split(",") if item.strip()
        }
        if configured != set(DEFAULT_ALLOWED_ORIGINS):
            issues.append(
                DocumentationIssue(
                    env_path,
                    1,
                    assignments[-1],
                    "active CORS example must match all tested defaults",
                )
            )
    for required in ("http://127.0.0.1:5173", "http://localhost:5173"):
        if required not in DEFAULT_ALLOWED_ORIGINS:
            issues.append(
                DocumentationIssue(
                    root / "core" / "api" / "app.py",
                    1,
                    required,
                    "Vite workflow origin is missing from CORS defaults",
                )
            )
    return issues


def check_release_version(root: Path) -> list[DocumentationIssue]:
    """Require Python metadata to match the latest released changelog entry."""
    pyproject_path = root / "pyproject.toml"
    changelog_path = root / "CHANGELOG.md"
    project_version = tomllib.loads(
        pyproject_path.read_text(encoding="utf-8")
    )["project"]["version"]
    match = RELEASE_HEADING_PATTERN.search(changelog_path.read_text(encoding="utf-8"))
    if match is None:
        return [
            DocumentationIssue(
                changelog_path,
                1,
                "latest release heading",
                "released changelog version could not be determined",
            )
        ]
    if project_version == match.group(1):
        return []
    return [
        DocumentationIssue(
            pyproject_path,
            1,
            project_version,
            f"project version should match latest release {match.group(1)}",
        )
    ]


def check_frontend_owner_names(root: Path) -> list[DocumentationIssue]:
    """Keep the frontend state-ownership table on current hook names."""
    frontend_readme = root / "frontend" / "README.md"
    text = frontend_readme.read_text(encoding="utf-8")
    issues: list[DocumentationIssue] = []
    if "useApexAssistant" in text:
        issues.append(
            DocumentationIssue(
                frontend_readme,
                1,
                "useApexAssistant",
                "removed frontend owner is still documented",
            )
        )
    if "useCortex" not in text:
        issues.append(
            DocumentationIssue(
                frontend_readme,
                1,
                "useCortex",
                "current Cortex owner is missing",
            )
        )
    return issues


PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "gemini": "Google",
    "xai": "SpaceXAI",
    "ollama": "Ollama",
    "llama_cpp": "llama.cpp",
}


def check_default_briefing_provider(
    root: Path,
    *,
    readme_text: str | None = None,
) -> list[DocumentationIssue]:
    """Keep README briefing paths aligned with the current synthesis contract."""
    import json

    from core.agent.model_catalog import (
        DEFAULT_FELIS_MODEL,
        PANTHERA_BRIEFING_MODEL,
        get_model_profile,
    )
    from core.synthesis.models import VALID_BRIEFING_MODES

    def provider_for_mode(mode: str) -> str:
        model_id = {
            "panthera": PANTHERA_BRIEFING_MODEL,
            "felis": DEFAULT_FELIS_MODEL,
        }.get(mode)
        profile = get_model_profile(model_id) if model_id is not None else None
        if profile is None:
            raise ValueError(f"Fixed briefing route selects an unknown {mode} model: {model_id!r}")
        return profile.provider

    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    default_mode = config.get("briefing", {}).get("default_mode", "panthera")
    if default_mode in {"panthera", "felis"}:
        provider = provider_for_mode(default_mode)
        expected = PROVIDER_DISPLAY_NAMES[provider]
    else:
        expected = "Structured Digest"

    readme_path = root / "README.md"
    readme = (
        readme_text
        if readme_text is not None
        else readme_path.read_text(encoding="utf-8")
    )
    diagram = re.search(
        r'^\s*B\s+-->\s+M\["([^"]+)"\]\s*$', readme, re.MULTILINE
    )
    issues: list[DocumentationIssue] = []
    if diagram is None:
        issues.append(
            DocumentationIssue(
                readme_path,
                1,
                "briefing diagram",
                "briefing diagram is missing its synthesis path label",
            )
        )
    else:
        diagram_label = diagram.group(1)
        diagram_line = readme.count("\n", 0, diagram.start()) + 1
        if expected not in diagram_label:
            issues.append(
                DocumentationIssue(
                    readme_path,
                    diagram_line,
                    expected,
                    "briefing diagram omits the configured default provider",
                )
            )

        expected_paths = {
            "Structured Digest"
            if mode == "structured_digest"
            else PROVIDER_DISPLAY_NAMES[provider_for_mode(mode)]
            for mode in VALID_BRIEFING_MODES
        }
        for provider in sorted(expected_paths):
            if provider not in diagram_label:
                issues.append(
                    DocumentationIssue(
                        readme_path,
                        diagram_line,
                        provider,
                        "briefing diagram omits a supported synthesis path",
                    )
                )
        if re.search(r"\bollama\b", diagram_label, re.IGNORECASE):
            issues.append(
                DocumentationIssue(
                    readme_path,
                    diagram_line,
                    "Ollama",
                    "obsolete Ollama briefing provider is documented",
                )
            )

    briefing_section_match = re.search(
        r"(?ms)^###\s+Produces briefings on user-defined terms\s*$.*?(?=^###\s|\Z)",
        readme,
    )
    if briefing_section_match is not None:
        section = briefing_section_match.group(0)
        section_start_line = readme.count("\n", 0, briefing_section_match.start()) + 1
        for line_number, line in enumerate(section.splitlines(), start=1):
            if re.search(r"\bollama\b", line, re.IGNORECASE):
                issues.append(
                    DocumentationIssue(
                        readme_path,
                        section_start_line + line_number - 1,
                        "Ollama",
                        "obsolete Ollama briefing provider is documented",
                    )
                )
    return issues


def public_openapi_routes() -> set[tuple[str, str]]:
    from core.api.app import app

    routes: set[tuple[str, str]] = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            routes.add((method.upper(), path))
    return routes


def current_agent_profiles() -> dict[str, str]:
    from core.agent.model_catalog import DEFAULT_FELIS_MODEL, DEFAULT_PANTHERA_MODEL

    return {
        "panthera": DEFAULT_PANTHERA_MODEL,
        "felis": DEFAULT_FELIS_MODEL,
    }


def registered_model_ids() -> set[str]:
    from core.agent.model_catalog import ALL_MODEL_PROFILES

    return {model_id.lower() for model_id in ALL_MODEL_PROFILES}


def run(root: Path = ROOT) -> list[DocumentationIssue]:
    from core.settings.models import SETTINGS_SCHEMA_VERSION

    paths = public_document_paths(root)
    contract_paths = [
        root / "README.md",
        root / "frontend" / "README.md",
        root / "docs" / "api.md",
        root / "docs" / "architecture.md",
        root / "docs" / "configuration.md",
        root / "docs" / "identity-and-naming.md",
    ]
    api_path = root / "docs" / "api.md"
    issues: list[DocumentationIssue] = []
    issues.extend(check_links(paths, root))
    issues.extend(check_routes(api_path, public_openapi_routes()))
    issues.extend(check_schema_versions(contract_paths, SETTINGS_SCHEMA_VERSION))
    issues.extend(check_api_contract_version(api_path, SETTINGS_SCHEMA_VERSION))
    issues.extend(check_agent_profiles(contract_paths, current_agent_profiles()))
    issues.extend(check_cors_example(root))
    issues.extend(check_release_version(root))
    issues.extend(check_frontend_owner_names(root))
    issues.extend(check_default_briefing_provider(root))
    return issues


def main() -> int:
    issues = run()
    if issues:
        for issue in issues:
            print(issue.format(), file=sys.stderr)
        print(f"Documentation check failed with {len(issues)} issue(s).", file=sys.stderr)
        return 1
    print("Documentation check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
