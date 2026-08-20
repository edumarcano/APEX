from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from core.agent.types import CostEstimate, TokenUsage

FELIS_BRIEFING_CONTEXT_WINDOW = 16_384
APODEMUS_BRIEFING_CONTEXT_WINDOW = FELIS_BRIEFING_CONTEXT_WINDOW

SynthesisProvider = Literal[
    "gemini", "ollama", "llama_cpp", "raw", "demo", "openai", "openrouter"
]
SynthesisAgent = Literal["panthera", "felis"]
BriefingMode = Literal["flash", "focused", "structured"]
SynthesisPhase = Literal["idle", "loading", "ready", "generating", "fallback", "complete"]

VALID_BRIEFING_MODES: frozenset[str] = frozenset(
    {"flash", "focused", "structured"}
)
LOCAL_BRIEFING_AGENTS: frozenset[str] = frozenset({"felis"})


def strategy_to_briefing_mode(strategy: str) -> BriefingMode:
    """Validate a canonical briefing mode without accepting legacy aliases."""
    normalized = (strategy or "").strip().lower()
    if normalized in VALID_BRIEFING_MODES:
        return normalized  # type: ignore[return-value]
    return "flash"


class CalendarFact(BaseModel):
    title: str
    start: str
    end: str | None = None
    all_day: bool = False
    location: str | None = None
    time_zone: str | None = None


class F1Fact(BaseModel):
    race_name: str
    start: str
    sprint_scheduled: bool = False


class WeatherDayFact(BaseModel):
    date: str
    condition: str | None = None
    temp_max_f: int | None = None
    temp_min_f: int | None = None
    precip_probability: int | None = None
    wind_speed_mph: int | None = None


class WeatherHourFact(BaseModel):
    time: str
    condition: str | None = None
    temp_f: int | None = None
    precip_probability: int | None = None
    wind_speed_mph: int | None = None


class ReminderFact(BaseModel):
    note: str
    due: str | None = None
    due_time_zone: str | None = None
    importance: str | None = None
    source: str | None = None
    sync_state: str | None = None


class EmailFact(BaseModel):
    sender: str | None = None
    subject: str
    received_at: str | None = None
    snippet: str | None = None


class SportEventFact(BaseModel):
    kind: str
    title: str
    start: str
    detail: str | None = None


class NewsFact(BaseModel):
    topic: str
    headline: str
    source: str | None = None
    published_at: str | None = None
    synopsis: str | None = None


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
    freshness: str = "none"
    observed_at: str | None = None


class BriefingFacts(BaseModel):
    """Normalized, bounded facts collected once and projected per briefing mode."""
    snapshot_id: str | None = None
    snapshot_collected_at: str | None = None
    local_time: str | None = None
    weather_summary: str | None = None
    weather_temp_f: int | None = None
    weather_apparent_temp_f: int | None = None
    weather_temp_max_f: int | None = None
    weather_temp_min_f: int | None = None
    weather_precip_probability: int | None = None
    weather_condition: str | None = None
    weather_daily: list[WeatherDayFact] = Field(default_factory=list)
    weather_hourly: list[WeatherHourFact] = Field(default_factory=list)
    email_unread_count: int = Field(default=0, ge=0)
    email_recent_subjects: list[str] = Field(default_factory=list)
    emails: list[EmailFact] = Field(default_factory=list)
    news_headlines: list[NewsFact] = Field(default_factory=list)
    calendar_event_count: int = Field(default=0, ge=0)
    next_calendar_event: CalendarFact | None = None
    calendar_events: list[CalendarFact] = Field(default_factory=list)
    calendar_truncated: bool = False
    pending_reminder_count: int = Field(default=0, ge=0)
    first_pending_reminder: str | None = None
    reminders: list[ReminderFact] = Field(default_factory=list)
    overdue_reminder_count: int = Field(default=0, ge=0)
    due_today_reminder_count: int = Field(default=0, ge=0)
    reminders_truncated: bool = False
    f1_upcoming: F1Fact | None = None
    football_next_fixture: FootballFact | None = None
    sports_events: list[SportEventFact] = Field(default_factory=list)
    sports_truncated: bool = False
    connector_health: list[ConnectorHealthFact] = Field(default_factory=list)
    failed_connectors: list[str] = Field(default_factory=list)
    generated_at: str
    timezone: str = "America/New_York"

    def flash_view(self) -> "BriefingFacts":
        """Return the deliberately small immediate-orientation projection."""
        now = _parse_fact_time(self.generated_at)
        flash_sports = [
            event for event in self.sports_events
            if (start := _parse_fact_time(event.start)) is not None
            and now <= start <= now + timedelta(hours=72)
        ]
        return self.model_copy(
            update={
                "weather_daily": self.weather_daily[:1],
                "weather_hourly": self.weather_hourly[:24],
                "emails": self.emails[:3],
                "email_recent_subjects": self.email_recent_subjects[:3],
                "news_headlines": self.news_headlines[:1],
                "calendar_events": self.calendar_events[:2],
                "reminders": self.reminders[:3],
                "sports_events": flash_sports[:2],
            }
        )

    def focused_view(self) -> "BriefingFacts":
        """Return the complete bounded planning-horizon projection."""
        now = _parse_fact_time(self.generated_at)
        focused_sports = [
            event for event in self.sports_events
            if (start := _parse_fact_time(event.start)) is not None
            and now <= start < now + timedelta(days=14)
        ]
        return self.model_copy(
            update={
                "weather_daily": self.weather_daily[:10],
                "weather_hourly": self.weather_hourly[:48],
                "emails": self.emails[:8],
                "news_headlines": self.news_headlines[:5],
                "calendar_events": self.calendar_events[:100],
                "reminders": self.reminders[:50],
                "sports_events": focused_sports,
            }
        )

    def structured_view(self) -> "BriefingFacts":
        """Bound deterministic display while retaining totals and truncation facts."""
        calendar_limit = 20
        reminder_limit = 20
        sports_limit = 15
        return self.model_copy(
            update={
                "weather_daily": self.weather_daily[:10],
                "weather_hourly": self.weather_hourly[:48],
                "emails": self.emails[:8],
                "news_headlines": self.news_headlines[:5],
                "calendar_events": self.calendar_events[:calendar_limit],
                "calendar_truncated": self.calendar_truncated or len(self.calendar_events) > calendar_limit,
                "reminders": self.reminders[:reminder_limit],
                "reminders_truncated": self.reminders_truncated or len(self.reminders) > reminder_limit,
                "sports_events": self.sports_events[:sports_limit],
                "sports_truncated": self.sports_truncated or len(self.sports_events) > sports_limit,
            }
        )


# Kept as a source-level alias while callers move to the explicit facts name.
SynthesisInput = BriefingFacts


def _parse_fact_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


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
