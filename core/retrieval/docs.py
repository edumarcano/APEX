"""Bounded local indexing and search for APEX repository documentation."""

from __future__ import annotations

import bisect
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
from typing import TYPE_CHECKING

from core.config import PROJECT_ROOT
from core.retrieval.models import RetrievalItem

if TYPE_CHECKING:
    from core.retrieval.service import RetrievalService


DOCS_NAMESPACE = "apex_docs"
DOCS_SOURCE_TYPE = "markdown_chunk"
_TARGET_CHARS = 2_000
_OVERLAP_CHARS = 160
_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+\s*)?$")
_SETEXT_HEADING = re.compile(r"^\s*(=+|-+)\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass(frozen=True)
class _Section:
    heading: str | None
    start_line: int
    lines: list[str]


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def documentation_paths(root: Path = PROJECT_ROOT) -> list[Path]:
    root = root.resolve()
    candidates = [root / "README.md"]
    docs_root = root / "docs"
    if docs_root.is_dir():
        candidates.extend(docs_root.rglob("*.md"))
    return sorted(
        {path.resolve() for path in candidates if path.is_file() and _within(path, root)},
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _heading_boundaries(lines: list[str]) -> list[tuple[int, int, str]]:
    boundaries: list[tuple[int, int, str]] = []
    fenced: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if fenced is None:
                fenced = marker[0]
            elif marker[0] == fenced:
                fenced = None
            index += 1
            continue
        if fenced is None:
            atx = _ATX_HEADING.match(line.rstrip("\n"))
            if atx:
                boundaries.append((index, len(atx.group(1)), atx.group(2).strip()))
            elif index + 1 < len(lines) and line.strip() and _SETEXT_HEADING.match(lines[index + 1]):
                underline = lines[index + 1].lstrip()[0]
                boundaries.append((index, 1 if underline == "=" else 2, line.strip()))
        index += 1
    return boundaries


def _sections(lines: list[str]) -> list[_Section]:
    boundaries = _heading_boundaries(lines)
    sections: list[_Section] = []
    if boundaries and boundaries[0][0] > 0:
        sections.append(_Section(None, 1, lines[: boundaries[0][0]]))
    elif not boundaries and lines:
        sections.append(_Section(None, 1, lines))
    stack: list[str] = []
    for number, (start, level, title) in enumerate(boundaries):
        stack = stack[: level - 1]
        stack.append(title)
        end = boundaries[number + 1][0] if number + 1 < len(boundaries) else len(lines)
        sections.append(_Section(" > ".join(stack), start + 1, lines[start:end]))
    return sections


def _chunk_section(section: _Section) -> list[tuple[int, int, str]]:
    text = "".join(section.lines)
    if not text.strip():
        return []
    line_offsets: list[int] = []
    offset = 0
    for line in section.lines:
        line_offsets.append(offset)
        offset += len(line)
    chunks: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + _TARGET_CHARS, len(text))
        if end < len(text):
            newline = text.rfind("\n", start, end)
            if newline > start:
                end = newline + 1
        excerpt = text[start:end].strip()
        if excerpt:
            start_line = section.start_line + bisect.bisect_right(line_offsets, start) - 1
            end_line = section.start_line + bisect.bisect_right(line_offsets, max(start, end - 1)) - 1
            chunks.append((start_line, end_line, excerpt))
        if end >= len(text):
            break
        start = max(end - _OVERLAP_CHARS, start + 1)
    return chunks


def build_documentation_items(root: Path = PROJECT_ROOT) -> list[RetrievalItem]:
    root = root.resolve()
    items: list[RetrievalItem] = []
    for path in documentation_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root).as_posix()
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        for section_number, section in enumerate(_sections(text.splitlines(keepends=True))):
            for chunk_number, (start_line, end_line, excerpt) in enumerate(_chunk_section(section)):
                source_id = f"{relative}:{section_number}:{chunk_number}"
                locator = f"{relative}:L{start_line}-L{end_line}"
                items.append(
                    RetrievalItem(
                        namespace=DOCS_NAMESPACE,
                        source_type=DOCS_SOURCE_TYPE,
                        source_id=source_id,
                        partition="shared",
                        conversation_id=None,
                        message_id=None,
                        role=None,
                        timestamp=timestamp,
                        locator=locator,
                        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                        text=excerpt,
                        title=relative,
                        heading=section.heading,
                        metadata={"path": relative, "line_start": start_line, "line_end": end_line},
                    )
                )
    return items


def search_documentation(query: str, service: "RetrievalService", *, root: Path = PROJECT_ROOT) -> dict[str, object]:
    service.sync_namespace(DOCS_NAMESPACE, build_documentation_items(root))
    hits = service.search(query, namespace=DOCS_NAMESPACE, source_type=DOCS_SOURCE_TYPE, partition="shared", limit=5)
    return {
        "query": query,
        "trust": "untrusted_reference",
        "retrieval_mode": service.status().mode,
        "results": [
            {
                "path": hit.metadata["path"],
                "heading": hit.heading,
                "line_start": hit.metadata["line_start"],
                "line_end": hit.metadata["line_end"],
                "text": hit.text,
                "score": hit.score,
            }
            for hit in hits
        ],
    }
