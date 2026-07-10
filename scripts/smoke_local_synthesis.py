"""Live Ollama briefing-synthesis smoke matrix for Lynx, Acinonyx, and Neofelis."""

from __future__ import annotations

import time
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.providers.ollama_lifecycle import (
    end_local_execution,
    get_status_snapshot,
    switch_local_model,
    try_begin_local_execution,
)
from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES
from core.synthesis import CalendarFact, F1Fact, SynthesisInput, SynthesisRouter


def main() -> int:
    snapshot = get_status_snapshot(force_refresh=True)
    if not snapshot["reachable"]:
        print("[SMOKE][SKIP] Ollama is unreachable.")
        return 2

    source = SynthesisInput(
        weather_summary="Current temperature is 72 degrees with clear skies.",
        calendar_event_count=1,
        next_calendar_event=CalendarFact(title="Operations review", start="Friday at 2 PM"),
        pending_reminder_count=1,
        first_pending_reminder="Charge the backup laptop",
        f1_this_week=F1Fact(race_name="British Grand Prix", start="Sunday at 10 AM"),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    installed = set(snapshot["installed_tags"])
    failures = 0
    for key, profile in OLLAMA_MODEL_PROFILES.items():
        if profile.api_model not in installed:
            print(f"[SMOKE][SKIP] {key}: {profile.api_model} is not installed.")
            continue
        if not try_begin_local_execution():
            print(f"[SMOKE][FAIL] {key}: local execution slot is busy.")
            failures += 1
            continue
        started = time.monotonic()
        try:
            loaded = switch_local_model(profile)
        finally:
            end_local_execution()
        if not loaded:
            print(f"[SMOKE][FAIL] {key}: model warmup failed.")
            failures += 1
            continue
        warmup_ms = int((time.monotonic() - started) * 1000)
        try:
            result = SynthesisRouter()._ollama(source, key, warmup_ms)
            print(
                f"[SMOKE][PASS] {key}: warmup={warmup_ms}ms "
                f"generation={result.generation_ms}ms briefing={result.briefing!r}"
            )
        except Exception as exc:
            print(f"[SMOKE][FAIL] {key}: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
