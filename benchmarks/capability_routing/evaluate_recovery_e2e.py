#!/usr/bin/env python3
"""Optional real-provider recovery evaluation harness.

Not run in CI. Invoke explicitly when credentials and a safe prompt set are available.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENCH_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_ROOT / "results"
PROMPTS_PATH = BENCH_ROOT / "recovery_eval_prompts.json"


@dataclass
class RecoveryEvalSummary:
    cases: int
    search_invocation_rate: float
    useful_query_rate: float
    final_capability_availability_rate: float
    recovered_tool_invocation_rate: float
    end_to_end_completion_rate: float
    no_tool_over_search_rate: float
    avg_added_provider_turns: float
    avg_input_tokens: float
    avg_output_tokens: float
    avg_latency_ms: float


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Optional real-provider recovery evaluation harness (not for CI)."
    )
    parser.add_argument("--agent", default="neofelis")
    parser.add_argument("--enable-recovery", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not args.enable_recovery:
        print(
            "Recovery evaluation requires --enable-recovery and configured credentials."
        )
        return 2

    if not PROMPTS_PATH.exists():
        print(f"Missing prompt set: {PROMPTS_PATH}")
        return 2

    prompts = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    print(
        "Real-provider recovery evaluation is intentionally manual. "
        f"Loaded {len(prompts)} safe prompts from {PROMPTS_PATH.name}."
    )
    print(
        "Wire this harness to query_agent() in a credentialed environment and "
        "report search-invocation, useful-query, recovered-tool, token, and "
        "latency metrics separately from oracle catalog-recovery coverage."
    )

    summary = RecoveryEvalSummary(
        cases=len(prompts),
        search_invocation_rate=0.0,
        useful_query_rate=0.0,
        final_capability_availability_rate=0.0,
        recovered_tool_invocation_rate=0.0,
        end_to_end_completion_rate=0.0,
        no_tool_over_search_rate=0.0,
        avg_added_provider_turns=0.0,
        avg_input_tokens=0.0,
        avg_output_tokens=0.0,
        avg_latency_ms=0.0,
    )
    out = args.output or RESULTS_DIR / f"recovery-e2e-{args.agent}-{int(time.time())}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")
    print(f"Wrote placeholder summary to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
