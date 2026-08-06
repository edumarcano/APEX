#!/usr/bin/env python3
"""Oracle upper-bound catalog-recovery benchmark for capability routing."""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.capability_routing.benchmark_quality import (
    estimate_schema_tokens_for_families,
    estimate_tools_for_families,
)
from benchmarks.capability_routing.recovery_simulation import (
    estimate_final_schema_tokens,
    simulate_runtime_catalog_recovery,
)
from benchmarks.capability_routing.reporting import (
    CASES_PATH,
    compute_recovery_metrics,
    load_cases,
    run_router_predictions,
    write_json_report,
)
from benchmarks.capability_routing.routers import HybridOnnxRouter
from benchmarks.capability_routing.tune_thresholds import (
    fit_calibrator_from_cases,
    select_families_from_rankings,
    tune_thresholds,
)
from core.agent.catalog import AGENT_SPECS
from core.agent.routing import calibration as calibration_module
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds

BENCH_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_ROOT / "results"

ORACLE_BENCHMARK_KIND = "oracle_catalog_recovery"
ORACLE_BENCHMARK_LIMITATION = (
    "Uses expected labels and the original prompt as the search query. "
    "This is an oracle upper bound on catalog recovery, not agent-initiated recovery."
)

RELAXED_SECOND_FAMILY_THRESHOLDS = replace(
    DEFAULT_THRESHOLDS,
    max_selected_families=3,
    additional_family_minimum_score=0.32,
    additional_family_margin=0.08,
)

_RUNTIME_AGENT = {
    "cloud": "neofelis",
    "local": "mus",
}


def _apply_recovery(
    cases: list[dict],
    initial_predictions: list[tuple[str, set[str], set[str], int, int]],
    *,
    runtime: str,
    thresholds: RoutingThresholds,
) -> tuple[
    list[tuple[str, set[str], set[str], int, int]],
    dict[str, bool],
    dict[str, int],
]:
    agent_key = _RUNTIME_AGENT[runtime]
    max_tool_turns = AGENT_SPECS[agent_key].max_tool_turns
    cases_by_id = {case["id"]: case for case in cases}
    final_predictions: list[tuple[str, set[str], set[str], int, int]] = []
    search_invoked: dict[str, bool] = {}
    extra_turns: dict[str, int] = {}

    for case_id, expected_set, initial_selected, _tools, _tokens in initial_predictions:
        case = cases_by_id[case_id]
        expected = set(expected_set)
        result = simulate_runtime_catalog_recovery(
            prompt=case["prompt"],
            initial_selected=initial_selected,
            expected=expected,
            runtime=runtime,
            agent_key=agent_key,
            thresholds=thresholds,
            max_tool_turns=max_tool_turns,
            history=case.get("history", []),
        )
        final_selected = result.final_selected
        search_invoked[case_id] = result.search_attempted
        extra_turns[case_id] = result.extra_turns
        final_predictions.append(
            (
                case_id,
                expected,
                final_selected,
                estimate_tools_for_families(final_selected),
                estimate_final_schema_tokens(
                    final_selected,
                    runtime=runtime,
                    agent_key=agent_key,
                    thresholds=thresholds,
                ),
            )
        )
    return final_predictions, search_invoked, extra_turns


def _evaluate_configuration(
    *,
    name: str,
    cases: list[dict],
    thresholds: RoutingThresholds,
    router: HybridOnnxRouter,
    runtime: str,
    with_recovery: bool,
) -> dict:
    initial_predictions, _ = run_router_predictions(
        router,
        cases,
        thresholds,
        select_fn=select_families_from_rankings,
    )
    if with_recovery:
        final_predictions, search_invoked, extra_turns = _apply_recovery(
            cases,
            initial_predictions,
            runtime=runtime,
            thresholds=thresholds,
        )
    else:
        final_predictions = initial_predictions
        search_invoked = {case_id: False for case_id, *_ in initial_predictions}
        extra_turns = {case_id: 0 for case_id, *_ in initial_predictions}

    metrics = compute_recovery_metrics(
        config_name=name,
        split=cases[0]["split"] if cases else "dev",
        cases=cases,
        initial_predictions=initial_predictions,
        final_predictions=final_predictions,
        search_invoked=search_invoked,
        extra_turns=extra_turns,
        benchmark_kind=ORACLE_BENCHMARK_KIND,
        benchmark_limitation=ORACLE_BENCHMARK_LIMITATION,
    )
    return asdict(metrics)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Oracle upper-bound catalog-recovery benchmark. "
            "Recovery uses the original prompt and expected labels; "
            "it does not model agent-initiated search."
        )
    )
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--runtime", choices=["cloud", "local"], default="cloud")
    args = parser.parse_args()

    cases = load_cases(args.split)
    dev_cases = load_cases("dev")
    router = HybridOnnxRouter(model_key="all-minilm-l6-v2", name="hybrid-minilm-onnx")
    thresholds = tune_thresholds(dev_cases, router.rank)
    calibration_module.DEFAULT_CALIBRATOR = fit_calibrator_from_cases(
        dev_cases,
        router.rank,
        thresholds,
    )

    report = {
        "split": args.split,
        "runtime": args.runtime,
        "benchmark_kind": ORACLE_BENCHMARK_KIND,
        "benchmark_limitation": ORACLE_BENCHMARK_LIMITATION,
        "runtime_agent": _RUNTIME_AGENT[args.runtime],
        "configurations": {},
    }

    configs = [
        ("hybrid-router", thresholds, False),
        ("relaxed-second-family", RELAXED_SECOND_FAMILY_THRESHOLDS, False),
        (
            "hybrid-router-plus-oracle-catalog-recovery",
            thresholds,
            True,
        ),
    ]
    for name, config_thresholds, with_recovery in configs:
        metrics = _evaluate_configuration(
            name=name,
            cases=cases,
            thresholds=config_thresholds,
            router=router,
            runtime=args.runtime,
            with_recovery=with_recovery,
        )
        report["configurations"][name] = metrics
        print(
            f"{name}: cases={metrics['total_cases']} "
            f"unique_prompts={metrics['unique_prompt_cases']} "
            f"initial_coverage={metrics['initial_complete_coverage_rate']:.3f} "
            f"final_coverage={metrics['final_complete_coverage_rate']:.3f} "
            f"recovery_success={metrics['recovery_success_rate']:.3f} "
            f"extra_turns={metrics['avg_extra_turns']:.3f}"
        )

    out = RESULTS_DIR / f"oracle-catalog-recovery-{args.runtime}-{args.split}.json"
    write_json_report(out, report)
    print(f"Wrote {out}")
    print(f"NOTE: {ORACLE_BENCHMARK_LIMITATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
