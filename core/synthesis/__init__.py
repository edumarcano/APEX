"""Provider-neutral briefing synthesis."""

from core.synthesis.models import (
    APODEMUS_BRIEFING_CONTEXT_WINDOW,
    CalendarFact,
    ConnectorHealthFact,
    F1Fact,
    FootballFact,
    NewsFact,
    BriefingMode,
    SynthesisAgent,
    SynthesisInput,
    SynthesisResult,
    strategy_to_briefing_mode,
)
from core.synthesis.router import SynthesisRouter, WarmupHandle

__all__ = [
    "APODEMUS_BRIEFING_CONTEXT_WINDOW",
    "BriefingMode",
    "SynthesisAgent",
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
