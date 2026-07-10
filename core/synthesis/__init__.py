"""Provider-neutral briefing synthesis."""

from core.synthesis.models import (
    CalendarFact,
    F1Fact,
    SynthesisInput,
    SynthesisResult,
)
from core.synthesis.router import SynthesisRouter, WarmupHandle

__all__ = [
    "CalendarFact",
    "F1Fact",
    "SynthesisInput",
    "SynthesisResult",
    "SynthesisRouter",
    "WarmupHandle",
]
