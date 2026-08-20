"""Provider-neutral briefing synthesis."""

from core.synthesis.models import (
    CalendarFact,
    ConnectorHealthFact,
    F1Fact,
    FootballFact,
    BriefingFacts,
    EmailFact,
    NewsFact,
    ReminderFact,
    SportEventFact,
    WeatherDayFact,
    WeatherHourFact,
    BriefingMode,
    SynthesisAgent,
    SynthesisResult,
    strategy_to_briefing_mode,
)
from core.synthesis.router import SynthesisRouter, WarmupHandle

__all__ = [
    "BriefingMode",
    "BriefingFacts",
    "SynthesisAgent",
    "CalendarFact",
    "ConnectorHealthFact",
    "F1Fact",
    "FootballFact",
    "EmailFact",
    "NewsFact",
    "ReminderFact",
    "SportEventFact",
    "WeatherDayFact",
    "WeatherHourFact",
    "SynthesisResult",
    "SynthesisRouter",
    "WarmupHandle",
    "strategy_to_briefing_mode",
]
