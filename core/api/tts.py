"""TTS engine resolution and markdown sanitization for spoken output."""

from __future__ import annotations

import re

from core import scanner


def resolve_tts_diagnostics(
    *,
    dev_mode: bool,
    configured_tts: str,
) -> tuple[str, bool]:
    """
    Resolve the active TTS engine and throttle flag for runtime diagnostics.

    When hardware throttle thresholds are met, Kokoro ONNX downgrades to pyttsx3.
    Google Cloud TTS bypasses throttling because cloud synthesis has negligible
    local CPU/RAM overhead.
    """
    system_load_throttled = scanner.is_system_throttled()
    normalized = configured_tts.strip().lower()

    if system_load_throttled and normalized == "kokoro":
        return "pyttsx3", True

    if dev_mode:
        return normalized if normalized in {"google", "kokoro", "pyttsx3"} else "pyttsx3", system_load_throttled

    if normalized in {"google", "kokoro", "pyttsx3"}:
        return normalized, system_load_throttled

    return "google", system_load_throttled


_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MARKDOWN_HEADER_PATTERN = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MARKDOWN_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MARKDOWN_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_MARKDOWN_STRIKE_PATTERN = re.compile(r"~~(.+?)~~")
_MARKDOWN_CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
_MARKDOWN_INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
_MARKDOWN_BLOCKQUOTE_PATTERN = re.compile(r"^>\s?", re.MULTILINE)
_MARKDOWN_HRULE_PATTERN = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_MARKDOWN_LIST_MARKER_PATTERN = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_MARKDOWN_ORDERED_LIST_PATTERN = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_NON_ASCII_PATTERN = re.compile(r"[^\x00-\x7F]+")


def clean_for_tts(text: str) -> str:
    """
    Strip markdown constructs and non-ASCII characters for TTS-safe output.

    Args:
        text: Source string that may contain markdown or emoji.

    Returns:
        ASCII-only plain text with collapsed whitespace.
    """
    cleaned = text
    replacements = (
        (_MARKDOWN_CODE_BLOCK_PATTERN, " "),
        (_MARKDOWN_IMAGE_PATTERN, r"\1"),
        (_MARKDOWN_LINK_PATTERN, r"\1"),
        (_MARKDOWN_INLINE_CODE_PATTERN, r"\1"),
        (_MARKDOWN_HEADER_PATTERN, ""),
        (_MARKDOWN_BLOCKQUOTE_PATTERN, ""),
        (_MARKDOWN_HRULE_PATTERN, " "),
        (_MARKDOWN_LIST_MARKER_PATTERN, ""),
        (_MARKDOWN_ORDERED_LIST_PATTERN, ""),
        (_MARKDOWN_BOLD_PATTERN, lambda match: match.group(1) or match.group(2) or ""),
        (_MARKDOWN_ITALIC_PATTERN, lambda match: match.group(1) or match.group(2) or ""),
        (_MARKDOWN_STRIKE_PATTERN, r"\1"),
    )
    for pattern, replacement in replacements:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = _NON_ASCII_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


# Compatibility aliases for callers and tests that used private names.
_resolve_tts_diagnostics = resolve_tts_diagnostics
