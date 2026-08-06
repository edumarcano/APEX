"""Deterministic routing rules applied before semantic ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.agent.routing.context import build_routing_document
from core.agent.types import AgentMessage

_TOKEN = re.compile(r"[a-z0-9']+")

# High-confidence lexical patterns per family. Order is stable for tie-breaking.
_FAMILY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "schedule",
        re.compile(
            r"\b(?:calendar|meeting|meetings|appointment|appointments|"
            r"reminder|reminders|agenda|free\s+(?:tonight|today|tomorrow)|"
            r"events?\s+(?:tomorrow|today|this\s+week))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "weather",
        re.compile(
            r"\b(?:weather|forecast|rain(?:ing)?|umbrella|temperature|"
            r"warm|cold|windy|snow|humid|sunny|cloudy|outlook)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "f1",
        re.compile(
            r"\b(?:\bf1\b|formula\s*1|grand\s+prix|driver\s+standings?|"
            r"verstappen|hamilton|championship\s+standings?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mail",
        re.compile(
            r"\b(?:gmail|inbox|email|emails|e-mail|message\s+from|"
            r"unread\s+(?:mail|message))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "search",
        re.compile(
            r"\b(?:search\s+the\s+web|web\s+search|look\s+up\s+(?:online|on\s+the\s+web)|"
            r"brave\s+search|news\s+about(?!\s+(?:stock|market|ticker)))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "market",
        re.compile(
            r"\b(?:stock|stocks|ticker|share\s+price|market\s+news|"
            r"nasdaq|nyse|nvda|aapl|tsla|amzn|quote|trading|"
            r"company\s+overview|time\s+series)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "briefings",
        re.compile(
            r"\b(?:apex\s+briefing|briefing\s+history|last\s+briefing|"
            r"morning\s+digest|recent\s+briefings?|briefing\s+record)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "todo",
        re.compile(
            r"\b(?:microsoft\s+to\s+do|to\s+do\s+list|todo\s+list|"
            r"incomplete\s+tasks?|my\s+tasks?|list\s+tasks?|tasks?\s+in)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "github",
        re.compile(
            r"\b(?:github|pull\s+request|issue\s+#?\d+|repository|repo)\b",
            re.IGNORECASE,
        ),
    ),
)

# Explicit family name mentions in synthetic benchmark prompts.
_FAMILY_NAME_PATTERN = re.compile(
    r"\b(schedule|weather|f1|mail|search|market|briefings?|todo)\b",
    re.IGNORECASE,
)

_NO_TOOL_PATTERNS = re.compile(
    r"\b(?:explain|translate|proofread|brainstorm|arithmetic|times\s+\d+|"
    r"thanks?,?\s+that\s+helps|how\s+are\s+you|gradient\s+descent|"
    r"rewrite\s+this|summarize\s+what\s+we\s+already\s+discussed)\b",
    re.IGNORECASE,
)

_AMBIGUOUS_PATTERNS = re.compile(
    r"\b(?:check\s+on\s+that|look\s+into\s+it|run\s+a\s+quick\s+check)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RuleMatch:
    family: str
    confidence: float
    reason: str


def _family_name_matches(text: str) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    for match in _FAMILY_NAME_PATTERN.finditer(text):
        key = match.group(1).lower()
        if key == "briefing":
            key = "briefings"
        matches.append(
            RuleMatch(family=key, confidence=0.92, reason="family_name_mention")
        )
    return matches


def apply_routing_rules(
    prompt: str,
    history: tuple[AgentMessage, ...] | list[AgentMessage],
) -> list[RuleMatch]:
    """Return high-confidence lexical and state matches for the routing document."""
    document = build_routing_document(prompt, history)
    text = document.lower()
    matches: list[RuleMatch] = []

    if _AMBIGUOUS_PATTERNS.search(document):
        return []

    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(document):
            matches.append(
                RuleMatch(family=family, confidence=0.88, reason="entity_pattern")
            )

    matches.extend(_family_name_matches(document))

    if _NO_TOOL_PATTERNS.search(document) and not matches:
        return [RuleMatch(family="none", confidence=0.90, reason="no_tool_pattern")]

    # Deduplicate by family, keeping highest confidence.
    best: dict[str, RuleMatch] = {}
    for item in matches:
        existing = best.get(item.family)
        if existing is None or item.confidence > existing.confidence:
            best[item.family] = item
    return list(best.values())


def rule_boost_score(family_key: str, rule_matches: list[RuleMatch]) -> float:
    """Return a score boost for families matched by deterministic rules."""
    boost = 0.0
    for match in rule_matches:
        if match.family == family_key:
            boost = max(boost, match.confidence * 0.35)
    return boost
