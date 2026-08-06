"""Deterministic routing-context document construction."""

from __future__ import annotations

from core.agent.types import AgentMessage

_HISTORY_MESSAGE_LIMIT = 6
_HISTORY_ITEM_CHAR_LIMIT = 600
_DOCUMENT_CHAR_LIMIT = 2400


def build_routing_document(
    prompt: str,
    history: tuple[AgentMessage, ...] | list[AgentMessage],
) -> str:
    """Build a bounded routing document from prompt and recent textual history."""
    bounded_prompt = prompt[:_DOCUMENT_CHAR_LIMIT]
    lines = [f"CURRENT REQUEST:\n{bounded_prompt}"]

    recent: list[str] = []
    for message in list(history)[-_HISTORY_MESSAGE_LIMIT:]:
        content = (message.content or "").strip()
        if not content:
            continue
        role = "USER" if message.role == "user" else "APEX"
        clipped = content[:_HISTORY_ITEM_CHAR_LIMIT]
        recent.append(f"{role}: {clipped}")

    if recent:
        lines.append("RECENT CONVERSATION:\n" + "\n".join(recent))

    document = "\n\n".join(lines)
    return document[:_DOCUMENT_CHAR_LIMIT]
