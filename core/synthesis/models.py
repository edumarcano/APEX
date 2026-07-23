from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SynthesisProvider = Literal["gemini", "ollama", "raw", "demo"]
SynthesisProfile = Literal["comet", "lynx", "acinonyx", "neofelis"]
BriefingMode = Literal[
    "comet", "lynx", "acinonyx", "neofelis", "structured_digest"
]
SynthesisPhase = Literal["idle", "loading", "ready", "generating", "fallback", "complete"]

VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"comet", "lynx", "acinonyx", "neofelis", "structured_digest"}
)
LOCAL_BRIEFING_PROFILES: frozenset[str] = frozenset({"lynx", "acinonyx", "neofelis"})


def strategy_to_briefing_mode(strategy: str) -> BriefingMode:
    """Map legacy synthesis strategies onto explicit briefing modes."""
    normalized = (strategy or "").strip().lower()
    if normalized == "raw":
        return "structured_digest"
    if normalized == "local":
        return "acinonyx"
    if normalized == "cloud":
        return "comet"
    if normalized in VALID_BRIEFING_MODES:
        return normalized  # type: ignore[return-value]
    return "comet"


class CalendarFact(BaseModel):
    title: str
    start: str
    all_day: bool = False


class F1Fact(BaseModel):
    race_name: str
    start: str
    sprint_scheduled: bool = False


class NewsFact(BaseModel):
    topic: str
    headline: str


class FootballFact(BaseModel):
    opponent: str
    fixture_date: str
    summary: str | None = None


class ConnectorHealthFact(BaseModel):
    name: str
    status: str
    reason_code: str = "ok"


class SynthesisInput(BaseModel):
    weather_summary: str | None = None
    weather_temp_f: int | None = None
    weather_condition: str | None = None
    email_unread_count: int = Field(default=0, ge=0)
    email_recent_subjects: list[str] = Field(default_factory=list)
    news_headlines: list[NewsFact] = Field(default_factory=list)
    calendar_event_count: int = Field(default=0, ge=0)
    next_calendar_event: CalendarFact | None = None
    pending_reminder_count: int = Field(default=0, ge=0)
    first_pending_reminder: str | None = None
    f1_this_week: F1Fact | None = None
    football_next_fixture: FootballFact | None = None
    connector_health: list[ConnectorHealthFact] = Field(default_factory=list)
    failed_connectors: list[str] = Field(default_factory=list)
    generated_at: str
    timezone: str = "America/New_York"


class SynthesisResult(BaseModel):
    briefing: str
    insights: list[str] = Field(default_factory=list)
    provider: SynthesisProvider
    profile: SynthesisProfile | None = None
    fallback_reason: str | None = None
    warmup_ms: int | None = None
    generation_ms: int | None = None
