"""Typed connector results for briefing trust evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

ConnectorStatus = Literal["healthy", "degraded", "unavailable", "disabled"]
ConnectorFreshness = Literal["live", "fresh_cache", "stale", "none"]

CONNECTOR_NAMES = (
    "weather",
    "news",
    "email",
    "calendar",
    "f1",
    "football",
    "reminders",
)

EXTERNAL_CONNECTOR_NAMES = tuple(
    name for name in CONNECTOR_NAMES if name != "reminders"
)


def utc_now_iso() -> str:
    """Return a timezone-aware UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


class ConnectorResult(BaseModel):
    """Structured outcome from a single briefing connector collection."""

    name: str
    status: ConnectorStatus
    freshness: ConnectorFreshness = "none"
    reason_code: str = "ok"
    observed_at: str = Field(default_factory=utc_now_iso)
    display_text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def score_weight(self) -> float:
        if self.status == "healthy":
            return 1.0
        if self.status == "degraded":
            return 0.5
        # unavailable and disabled contribute nothing; disabled is excluded from scoring.
        return 0.0


class ConnectorHealthEntry(BaseModel):
    """Public per-connector health row for digest payloads."""

    name: str
    status: ConnectorStatus
    freshness: ConnectorFreshness = "none"
    reason_code: str = "ok"
    observed_at: str | None = None


class SyncHealthReport(BaseModel):
    """Aggregate sync health derived from typed connector results."""

    sync_health_score: float
    connector_health: list[ConnectorHealthEntry] = Field(default_factory=list)
    failed_connectors: list[str] = Field(default_factory=list)

    @property
    def confidence_score(self) -> float:
        """Compatibility alias for legacy digest consumers."""
        return self.sync_health_score
