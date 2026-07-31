"""API route package exports."""

from __future__ import annotations

from core.api.routers import assistant, briefings, market, mcp, microsoft_todo, reminders, system, telemetry, voice

__all__ = [
    "assistant",
    "briefings",
    "market",
    "mcp",
    "reminders",
    "microsoft_todo",
    "system",
    "telemetry",
    "voice",
]
