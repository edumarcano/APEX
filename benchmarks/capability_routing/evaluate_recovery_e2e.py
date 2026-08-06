#!/usr/bin/env python3
"""Optional real-provider recovery evaluation harness.

Not run in CI. Invoke explicitly when credentials and a safe prompt set are available.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BENCH_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_ROOT / "results"
PROMPTS_PATH = BENCH_ROOT / "recovery_eval_prompts.json"


@dataclass
class RecoveryEvalCaseResult:
    case_id: str
    search_attempted: bool
    search_succeeded: bool
    schemas_expanded: bool
    recovered_tool_invoked: bool
    completed: bool
    over_searched: bool
    provider_turns: int
    input_tokens: int
    output_tokens: int
    latency_ms: float


@dataclass
class RecoveryEvalSummary:
    agent: str
    recovery_enabled: bool
    compared_control: bool
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
    case_results: list[dict]


def _load_prompts() -> list[dict]:
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


def _validate_agent(agent_key: str) -> None:
    from core.agent.catalog import AGENT_SPECS
    from core.api.cortex import agent_has_credentials

    if agent_key not in AGENT_SPECS:
        raise SystemExit(f"Unknown agent: {agent_key}")
    spec = AGENT_SPECS[agent_key]
    if spec.runtime != "cloud":
        raise SystemExit(
            f"Recovery evaluation currently supports cloud agents only, not {agent_key!r}."
        )
    if spec.credential_env and not agent_has_credentials(agent_key):
        raise SystemExit(
            f"Missing credentials for {agent_key}. "
            f"Set {spec.credential_env} before running recovery evaluation."
        )


def _run_case(
    *,
    agent_key: str,
    prompt: dict,
    recovery_enabled: bool,
) -> RecoveryEvalCaseResult:
    from unittest import mock

    from core.agent.types import AgentQueryRequest
    from core.api.cortex import query_agent
    from core.agent.routing.thresholds import DEFAULT_THRESHOLDS

    started = time.perf_counter()
    thresholds = replace(
        DEFAULT_THRESHOLDS,
        tool_search_recovery_enabled=recovery_enabled,
    )
    store = mock.Mock()
    snapshot = store.get_snapshot.return_value
    snapshot.ask_apex.enabled = True
    snapshot.ask_apex.tool_routing_mode = "enabled"
    snapshot.ask_apex.neofelis_google_search_enabled = False
    snapshot.ask_apex.neofelis_google_maps_enabled = False
    snapshot.ask_apex.delphinus_x_search_enabled = False
    snapshot.ask_apex.orcinus_x_search_enabled = False

    with (
        mock.patch("core.api.cortex.DEFAULT_THRESHOLDS", thresholds),
        mock.patch("core.api.cortex.get_settings_store", return_value=store),
        mock.patch("core.api.cortex.DEMO_MODE", False),
    ):
        response = query_agent(
            AgentQueryRequest(prompt=prompt["prompt"], agent=agent_key),
        )

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    routing = response.routing
    tool_trace = response.tool_trace or []
    search_attempted = bool(routing and routing.tool_search_attempted)
    search_succeeded = bool(routing and routing.tool_search_succeeded)
    schemas_expanded = bool(routing and routing.recovery_expanded_tool_count > 0)
    recovered_tool_invoked = bool(
        routing and routing.recovery_recovered_tool_invocation_turns > 0
    )
    completed = bool(response.answer and not response.error)
    expect_search = bool(prompt.get("expect_search", False))
    over_searched = search_attempted and not expect_search and not prompt.get(
        "expected_families"
    )
    usage = response.metadata.usage if response.metadata and response.metadata.usage else None
    input_tokens = usage.input_tokens if usage and usage.input_tokens is not None else 0
    output_tokens = usage.output_tokens if usage and usage.output_tokens is not None else 0
    provider_turns = sum(1 for item in tool_trace if item.get("name"))

    return RecoveryEvalCaseResult(
        case_id=prompt["id"],
        search_attempted=search_attempted,
        search_succeeded=search_succeeded,
        schemas_expanded=schemas_expanded,
        recovered_tool_invoked=recovered_tool_invoked,
        completed=completed,
        over_searched=over_searched,
        provider_turns=provider_turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )


def _summarize(
    *,
    agent: str,
    recovery_enabled: bool,
    compared_control: bool,
    results: list[RecoveryEvalCaseResult],
) -> RecoveryEvalSummary:
    total = len(results)
    return RecoveryEvalSummary(
        agent=agent,
        recovery_enabled=recovery_enabled,
        compared_control=compared_control,
        cases=total,
        search_invocation_rate=_rate(results, lambda item: item.search_attempted),
        useful_query_rate=_rate(results, lambda item: item.search_succeeded),
        final_capability_availability_rate=_rate(
            results, lambda item: item.schemas_expanded or item.completed
        ),
        recovered_tool_invocation_rate=_rate(
            results, lambda item: item.recovered_tool_invoked
        ),
        end_to_end_completion_rate=_rate(results, lambda item: item.completed),
        no_tool_over_search_rate=_rate(results, lambda item: item.over_searched),
        avg_added_provider_turns=_avg(results, lambda item: item.provider_turns),
        avg_input_tokens=_avg(results, lambda item: item.input_tokens),
        avg_output_tokens=_avg(results, lambda item: item.output_tokens),
        avg_latency_ms=_avg(results, lambda item: item.latency_ms),
        case_results=[asdict(item) for item in results],
    )


def _rate(results: list[RecoveryEvalCaseResult], predicate) -> float:
    if not results:
        return 0.0
    return sum(1 for item in results if predicate(item)) / len(results)


def _avg(results: list[RecoveryEvalCaseResult], accessor) -> float:
    if not results:
        return 0.0
    return sum(accessor(item) for item in results) / len(results)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Optional real-provider recovery evaluation harness (not for CI)."
    )
    parser.add_argument("--agent", default="neofelis")
    parser.add_argument("--enable-recovery", action="store_true")
    parser.add_argument("--compare-control", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if not args.enable_recovery:
        print(
            "Recovery evaluation requires --enable-recovery and configured credentials.",
            file=sys.stderr,
        )
        return 2

    if not PROMPTS_PATH.exists():
        print(f"Missing prompt set: {PROMPTS_PATH}", file=sys.stderr)
        return 2

    _validate_agent(args.agent)
    prompts = _load_prompts()
    recovery_results = [
        _run_case(agent_key=args.agent, prompt=prompt, recovery_enabled=True)
        for prompt in prompts
    ]
    report: dict = {
        "recovery_enabled": _summarize(
            agent=args.agent,
            recovery_enabled=True,
            compared_control=args.compare_control,
            results=recovery_results,
        ),
    }
    if args.compare_control:
        control_results = [
            _run_case(agent_key=args.agent, prompt=prompt, recovery_enabled=False)
            for prompt in prompts
        ]
        report["recovery_disabled_control"] = _summarize(
            agent=args.agent,
            recovery_enabled=False,
            compared_control=True,
            results=control_results,
        )

    out = args.output or RESULTS_DIR / f"recovery-e2e-{args.agent}-{int(time.time())}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "recovery_enabled": asdict(report["recovery_enabled"]),
                **(
                    {"recovery_disabled_control": asdict(report["recovery_disabled_control"])}
                    if "recovery_disabled_control" in report
                    else {}
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    summary = report["recovery_enabled"]
    print(
        f"Wrote recovery evaluation for {summary.cases} prompts to {out}. "
        f"search_rate={summary.search_invocation_rate:.3f} "
        f"completion={summary.end_to_end_completion_rate:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
