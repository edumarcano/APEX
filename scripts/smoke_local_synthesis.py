"""Live briefing-synthesis smoke matrix for configured local models."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.local_runtime.coordinator import (
    end_local_execution,
    get_provider_snapshot,
    switch_local_model,
    try_begin_local_execution,
)
from core.agent.catalog import build_concrete_agent
from core.agent.model_catalog import visible_local_models
from core.config import is_dev_mode
from core.synthesis import CalendarFact, F1Fact, BriefingFacts, SynthesisRouter


def main() -> int:
    source = BriefingFacts(
        weather_summary="Current temperature is 72 degrees with clear skies.",
        calendar_event_count=1,
        next_calendar_event=CalendarFact(title="Operations review", start="Friday at 2 PM"),
        pending_reminder_count=1,
        first_pending_reminder="Charge the backup laptop",
        f1_upcoming=F1Fact(race_name="British Grand Prix", start="Sunday at 10 AM"),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    failures = 0
    skipped = 0
    for model in visible_local_models(dev_mode=is_dev_mode()):
        profile = build_concrete_agent(
            "apex", native_effort=None, model_id=model.model_id
        )
        snapshot = get_provider_snapshot(profile.provider, force_refresh=True)
        if not snapshot["reachable"]:
            print(f"[SMOKE][SKIP] {model.model_id}: {profile.provider} is unreachable.")
            skipped += 1
            continue
        installed = set(snapshot["installed_models"])
        if profile.runtime_model_id not in installed:
            print(f"[SMOKE][SKIP] {model.model_id}: {profile.runtime_model_id} is not installed.")
            skipped += 1
            continue
        if not try_begin_local_execution():
            print(f"[SMOKE][FAIL] {model.model_id}: local execution slot is busy.")
            failures += 1
            continue
        started = time.monotonic()
        try:
            loaded = switch_local_model(profile)
        finally:
            end_local_execution()
        if not loaded:
            print(f"[SMOKE][FAIL] {model.model_id}: model warmup failed.")
            failures += 1
            continue
        warmup_ms = int((time.monotonic() - started) * 1000)
        try:
            result = SynthesisRouter()._local(source, model.model_id, warmup_ms)
            print(
                f"[SMOKE][PASS] {model.model_id}: warmup={warmup_ms}ms "
                f"generation={result.generation_ms}ms briefing={result.briefing!r}"
            )
        except Exception as exc:
            print(f"[SMOKE][FAIL] {model.model_id}: {exc}")
            failures += 1
    return 1 if failures else (2 if skipped else 0)


if __name__ == "__main__":
    raise SystemExit(main())
