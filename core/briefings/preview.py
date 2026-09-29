"""Bounded extraction of validated, provisional briefing sections from JSON streams."""

from __future__ import annotations

import json
from typing import Any

from core.briefings.models import BriefingEvidence, BriefingItemDraft, BriefingSectionDraft

MAX_PREVIEW_SECTIONS = 12
MAX_PREVIEW_CHARS = 12_000
MAX_PREVIEW_INPUT_BYTES = 64 * 1024


class BriefingPreviewParser:
    """Expose only complete validated section objects from a streamed JSON draft."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._buffer = ""
        self._cursor = 0
        self._root_started = False
        self._sections_started = False
        self._done = False
        self._sections: list[dict[str, Any]] = []
        self._characters = 0

    @property
    def sections(self) -> list[dict[str, Any]]:
        return [dict(section, items=[dict(item) for item in section["items"]]) for section in self._sections]

    def feed(
        self,
        fragment: str,
        evidence: list[BriefingEvidence],
    ) -> list[dict[str, Any]] | None:
        """Return a fresh cumulative preview when a complete section arrives."""
        if self._done or not fragment:
            return None
        if len((self._buffer + fragment).encode("utf-8")) > MAX_PREVIEW_INPUT_BYTES:
            self._done = True
            return None
        self._buffer += fragment
        changed = False
        while not self._done:
            if not self._root_started:
                self._skip_space()
                if self._cursor >= len(self._buffer):
                    break
                if self._buffer[self._cursor] != "{":
                    self._done = True
                    break
                self._root_started = True
                self._cursor += 1
            if self._sections_started:
                self._skip_space()
                if self._cursor >= len(self._buffer):
                    break
                if self._buffer[self._cursor] == "]":
                    self._done = True
                    break
                if self._buffer[self._cursor] == ",":
                    self._cursor += 1
                    continue
                try:
                    value, end = json.JSONDecoder().raw_decode(self._buffer, self._cursor)
                except (json.JSONDecodeError, ValueError):
                    break
                self._cursor = end
                if len(self._sections) >= MAX_PREVIEW_SECTIONS or not isinstance(value, dict):
                    self._done = True
                    break
                try:
                    section = BriefingSectionDraft.model_validate(value)
                except Exception:
                    continue
                evidence_by_id = {item.id: item for item in evidence}
                safe_items = [item for item in section.items if _item_has_permitted_evidence(item, evidence_by_id)]
                if section.items and not safe_items:
                    continue
                section_data = {
                    "title": section.title,
                    "items": [
                        {"category": item.category, "title": item.title, "body": item.body}
                        for item in safe_items
                    ],
                }
                section_characters = len(section.title) + sum(
                    len(item["title"]) + len(item["body"]) for item in section_data["items"]
                )
                if self._characters + section_characters > MAX_PREVIEW_CHARS:
                    self._done = True
                    break
                self._characters += section_characters
                self._sections.append(section_data)
                changed = True
                continue

            self._skip_space()
            if self._cursor >= len(self._buffer):
                break
            if self._buffer[self._cursor] == ",":
                self._cursor += 1
                continue
            if self._buffer[self._cursor] == "}":
                self._done = True
                break
            try:
                key, end = json.JSONDecoder().raw_decode(self._buffer, self._cursor)
            except (json.JSONDecodeError, ValueError):
                break
            if not isinstance(key, str):
                self._done = True
                break
            self._cursor = end
            self._skip_space()
            if self._cursor >= len(self._buffer) or self._buffer[self._cursor] != ":":
                break
            self._cursor += 1
            self._skip_space()
            if self._cursor >= len(self._buffer):
                break
            if key == "sections":
                if self._buffer[self._cursor] != "[":
                    self._done = True
                    break
                self._sections_started = True
                self._cursor += 1
            else:
                try:
                    _value, end = json.JSONDecoder().raw_decode(self._buffer, self._cursor)
                except (json.JSONDecodeError, ValueError):
                    break
                self._cursor = end
        return self.sections if changed else None

    def _skip_space(self) -> None:
        while self._cursor < len(self._buffer) and self._buffer[self._cursor] in " \r\n\t":
            self._cursor += 1


def _item_has_permitted_evidence(
    item: BriefingItemDraft,
    evidence_by_id: dict[object, BriefingEvidence],
) -> bool:
    if not item.evidence_ids or any(reference not in evidence_by_id for reference in item.evidence_ids):
        return False
    cited = [evidence_by_id[reference] for reference in item.evidence_ids]
    if any(not source.available for source in cited):
        return False
    expected_trust = {
        "observation": "observed",
        "accepted_context": "accepted",
        "pending_review": "pending",
        "external_report": "untrusted",
    }.get(item.category)
    return expected_trust is None or all(source.trust == expected_trust for source in cited)
