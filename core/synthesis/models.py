from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.agent.types import CostEstimate, TokenUsage

LYNX_BRIEFING_CONTEXT_WINDOW = 16_384
APODEMUS_BRIEFING_CONTEXT_WINDOW = LYNX_BRIEFING_CONTEXT_WINDOW

SynthesisProvider = Literal["gemini", "ollama", "llama_cpp", "raw", "demo", "openai"]
SynthesisAgent = Literal["panthera", "lynx"]
BriefingMode = Literal["panthera", "lynx", "structured_digest"]
SynthesisPhase = Literal["idle", "loading", "ready", "generating", "fallback", "complete"]

VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"panthera", "lynx", "structured_digest"}
)
LOCAL_BRIEFING_AGENTS: frozenset[str] = frozenset({"lynx"})


def strategy_to_briefing_mode(strategy: str) -> BriefingMode:
    """Map legacy synthesis strategies onto explicit briefing modes."""
    normalized = (strategy or "").strip().lower()
    if normalized == "raw":
        return "structured_digest"
    if normalized == "local":
        return "lynx"
    if normalized == "cloud":
        return "panthera"
    if normalized == "comet":
        return "panthera"
    if normalized in {"lynx", "acinonyx", "neofelis", "apodemus"}:
        return "lynx"
    if normalized in VALID_BRIEFING_MODES:
        return normalized  # type: ignore[return-value]
    return "panthera"


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
    team: str
    opponent: str
    home_or_away: Literal["home", "away"]
    competition: str
    kickoff: str


class ConnectorHealthFact(BaseModel):
    name: str
    status: str
    reason_code: str = "ok"


class SynthesisInput(BaseModel):
    weather_summary: str | None = None
    weather_temp_f: int | None = None
    weather_apparent_temp_f: int | None = None
    weather_temp_max_f: int | None = None
    weather_temp_min_f: int | None = None
    weather_precip_probability: int | None = None
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
    agent: SynthesisAgent | None = None
    fallback_reason: str | None = None
    fallback_steps: list[str] = Field(default_factory=list)
    warmup_ms: int | None = None
    generation_ms: int | None = None
    provider_ms: float | None = None
    resolved_model: str | None = None
    usage: TokenUsage | None = None
    cost_estimate: CostEstimate | None = None
