"""Small text sanitizers shared by trusted APEX presentation boundaries."""

from __future__ import annotations

import html
import re
import unicodedata

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKUP_RE = re.compile(r"<[^>]+>|[`*_>#\[\]{}]+")
_SECTION_MARKERS = ("===SPEECH===", "===INSIGHTS===")
_UNTRUSTED_MARKERS = (
    "<untrusted_connector_data>",
    "</untrusted_connector_data>",
    "<untrusted_telemetry_context>",
    "</untrusted_telemetry_context>",
    "<untrusted_retrieved_context>",
    "</untrusted_retrieved_context>",
    "<untrusted_tool_output>",
    "</untrusted_tool_output>",
)


def sanitize_fact(value: object, limit: int = 240) -> str:
    """Normalize untrusted fact text for bounded plain-text context."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    for marker in (*_SECTION_MARKERS, *_UNTRUSTED_MARKERS):
        text = text.replace(marker, " ")
    text = html.unescape(text)
    text = _CONTROL_RE.sub(" ", text)
    text = _MARKUP_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    prefix = text[: limit + 1]
    if " " in prefix:
        shortened = prefix.rsplit(" ", 1)[0].strip()
        if shortened:
            return shortened
    return text[:limit].strip()
