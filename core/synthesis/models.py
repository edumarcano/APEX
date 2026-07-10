from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SynthesisProvider = Literal["gemini", "ollama", "raw", "demo"]
SynthesisProfile = Literal["comet", "lynx", "acinonyx", "neofelis"]
SynthesisPhase = Literal["idle", "loading", "ready", "generating", "fallback", "complete"]


class CalendarFact(BaseModel):
    title: str
    start: str
    all_day: bool = False


class F1Fact(BaseModel):
    race_name: str
    start: str
    sprint_scheduled: bool = False


class SynthesisInput(BaseModel):
    weather_summary: str | None = None
    calendar_event_count: int = Field(default=0, ge=0)
    next_calendar_event: CalendarFact | None = None
    pending_reminder_count: int = Field(default=0, ge=0)
    first_pending_reminder: str | None = None
    f1_this_week: F1Fact | None = None
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
