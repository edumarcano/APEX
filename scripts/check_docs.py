"""Validate public APEX documentation links and versioned contracts."""

from __future__ import annotations

import os
import re
import sys
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
SCHEMA_VERSION_PATTERN = re.compile(r'"schema_version"\s*:\s*(\d+)')


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
    paths = [root / "README.md", root / "frontend" / "README.md"]
    paths.extend(sorted((root / "docs").glob("*.md")))
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
    return re.sub(r"[ ]+", "-", value)


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


def check_routes(
    api_path: Path,
    expected: set[tuple[str, str]],
) -> list[DocumentationIssue]:
    actual = documented_routes(api_path.read_text(encoding="utf-8"))
    issues: list[DocumentationIssue] = []
    for method, path in sorted(expected - actual):
        issues.append(
            DocumentationIssue(api_path, 1, f"{method} {path}", "public route is undocumented")
        )
    for method, path in sorted(actual - expected):
        issues.append(
            DocumentationIssue(api_path, 1, f"{method} {path}", "documented route is not public")
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


def check_gemini_profiles(
    paths: Iterable[Path],
    expected_profiles: Mapping[str, str],
    contents: Mapping[Path, str] | None = None,
) -> list[DocumentationIssue]:
    issues: list[DocumentationIssue] = []
    texts = {
        path: contents.get(path, "") if contents is not None else path.read_text(encoding="utf-8")
        for path in paths
    }
    combined = "\n".join(texts.values())
    for key, model in sorted(expected_profiles.items()):
        if key not in combined or model not in combined:
            issues.append(
                DocumentationIssue(
                    ROOT / "docs" / "configuration.md",
                    1,
                    f"{key} -> {model}",
                    "current Gemini profile mapping is missing",
                )
            )

    known_models = set(expected_profiles.values())
    model_pattern = re.compile(r"gemini-\d+(?:\.\d+)*-[a-z0-9-]+")
    for path in paths:
        for line_number, line in enumerate(
            texts[path].splitlines(), start=1
        ):
            for model in model_pattern.findall(line):
                if model not in known_models:
                    issues.append(
                        DocumentationIssue(
                            path,
                            line_number,
                            model,
                            "Gemini model ID is not used by a current profile",
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


def current_gemini_profiles() -> dict[str, str]:
    from core.agent.profiles import PROFILE_SPECS

    return {
        key: spec.api_model
        for key, spec in PROFILE_SPECS.items()
        if spec.provider == "gemini"
    }


def run(root: Path = ROOT) -> list[DocumentationIssue]:
    from core.settings.models import SETTINGS_SCHEMA_VERSION

    paths = public_document_paths(root)
    api_path = root / "docs" / "api.md"
    issues: list[DocumentationIssue] = []
    issues.extend(check_links(paths, root))
    issues.extend(check_routes(api_path, public_openapi_routes()))
    issues.extend(check_schema_versions(paths, SETTINGS_SCHEMA_VERSION))
    issues.extend(check_gemini_profiles(paths, current_gemini_profiles()))
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
