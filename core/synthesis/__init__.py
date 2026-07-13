"""Provider-neutral briefing synthesis."""

from core.synthesis.models import (
    CalendarFact,
    ConnectorHealthFact,
    F1Fact,
    FootballFact,
    NewsFact,
    SynthesisInput,
    SynthesisResult,
)
from core.synthesis.router import SynthesisRouter, WarmupHandle

__all__ = [
    "CalendarFact",
    "ConnectorHealthFact",
    "F1Fact",
    "FootballFact",
    "NewsFact",
    "SynthesisInput",
    "SynthesisResult",
    "SynthesisRouter",
    "WarmupHandle",
]
