"""Compatibility façade for provider-neutral briefing synthesis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.config import DEV_AI_SYNTHESIS, is_dev_mode
from core.synthesis import (
    BriefingMode,
    SynthesisInput,
    SynthesisRouter,
    WarmupHandle,
    strategy_to_briefing_mode,
)


def process_telemetry(
    raw_data: str = "",
    *,
    synthesis_input: SynthesisInput | None = None,
    strategy: str | None = None,
    mode: BriefingMode | None = None,
    warmup: WarmupHandle | None = None,
    router: SynthesisRouter | None = None,
) -> dict[str, Any]:
    """Synthesize telemetry while preserving the historical dictionary return shape.

    ``raw_data`` remains accepted for compatibility but is never forwarded to a
    model. Callers should supply a typed ``SynthesisInput``. Prefer ``mode``;
    ``strategy`` remains for legacy callers and DEV_MODE mapping.
    """
    source = synthesis_input or SynthesisInput(
        weather_summary=raw_data or None,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    resolved_mode = mode or strategy_to_briefing_mode(
        strategy or (DEV_AI_SYNTHESIS if is_dev_mode() else "cloud")
    )
    active_router = router or SynthesisRouter()
    result = active_router.synthesize_mode(source, resolved_mode, warmup)
    return result.model_dump()


if __name__ == "__main__":
    print(process_telemetry("Current temperature is 82 degrees with scattered clouds."))
