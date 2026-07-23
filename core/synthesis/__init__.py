"""Provider-neutral briefing synthesis."""

from core.synthesis.models import (
    CalendarFact,
    ConnectorHealthFact,
    F1Fact,
    FootballFact,
    NewsFact,
    BriefingMode,
    SynthesisInput,
    SynthesisResult,
    strategy_to_briefing_mode,
)
from core.synthesis.router import SynthesisRouter, WarmupHandle

__all__ = [
    "BriefingMode",
    "CalendarFact",
    "ConnectorHealthFact",
    "F1Fact",
    "FootballFact",
    "NewsFact",
    "SynthesisInput",
    "SynthesisResult",
    "SynthesisRouter",
    "WarmupHandle",
    "strategy_to_briefing_mode",
]
