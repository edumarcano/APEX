#!/usr/bin/env python3
"""Compare routing-only, relaxed second-family, and tool-search recovery."""

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
from core.agent.capabilities import list_agent_capabilities
from core.agent.routing import calibration as calibration_module
from core.agent.routing.families import CAPABILITY_FAMILIES
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds
from core.agent.routing.tool_search import (
    build_searchable_catalog,
    simulate_tool_search_recovery,
)

BENCH_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_ROOT / "results"

RELAXED_SECOND_FAMILY_THRESHOLDS = replace(
    DEFAULT_THRESHOLDS,
    max_selected_families=3,
    additional_family_minimum_score=0.32,
    additional_family_margin=0.08,
)


def _searchable_families_for_runtime(runtime: str) -> set[str]:
    if runtime == "local":
        return {
            family.key
            for family in CAPABILITY_FAMILIES
            if family.local_auto_enabled and family.key != "none"
        }
    return {
        family.key
        for family in CAPABILITY_FAMILIES
        if family.cloud_auto_enabled and family.key != "none"
    }


def _apply_recovery(
    cases: list[dict],
    initial_predictions: list[tuple[str, set[str], set[str], int, int]],
    *,
    runtime: str,
    max_result_families: int,
) -> tuple[
    list[tuple[str, set[str], set[str], int, int]],
    dict[str, bool],
    dict[str, int],
]:
    searchable = build_searchable_catalog(
        list_agent_capabilities(),
        runtime=runtime,
        agent_key="neofelis",
    )
    searchable_families = {
        descriptor.routing_family
        for descriptor in searchable
        if descriptor.routing_family is not None
    }
    cases_by_id = {case["id"]: case for case in cases}
    final_predictions: list[tuple[str, set[str], set[str], int, int]] = []
    search_invoked: dict[str, bool] = {}
    extra_turns: dict[str, int] = {}

    for case_id, expected_set, initial_selected, _tools, _tokens in initial_predictions:
        case = cases_by_id[case_id]
        expected = set(expected_set)
        final_selected, invoked, turns, _false_positive = simulate_tool_search_recovery(
            prompt=case["prompt"],
            initial_selected=initial_selected,
            expected=expected,
            searchable_families=searchable_families,
            max_result_families=max_result_families,
            history=case.get("history", []),
        )
        search_invoked[case_id] = invoked
        extra_turns[case_id] = turns
        final_predictions.append(
            (
                case_id,
                expected,
                final_selected,
                estimate_tools_for_families(final_selected),
                estimate_schema_tokens_for_families(final_selected),
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
            max_result_families=thresholds.tool_search_max_result_families,
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
    )
    return asdict(metrics)


def main() -> int:
    parser = argparse.ArgumentParser()
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
        "searchable_families": sorted(_searchable_families_for_runtime(args.runtime)),
        "configurations": {},
    }

    configs = [
        ("hybrid-router", thresholds, False),
        ("relaxed-second-family", RELAXED_SECOND_FAMILY_THRESHOLDS, False),
        (
            "hybrid-router-plus-tool-search",
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
            f"{name}: initial_coverage={metrics['initial_complete_coverage_rate']:.3f} "
            f"final_coverage={metrics['final_complete_coverage_rate']:.3f} "
            f"recovery_success={metrics['recovery_success_rate']:.3f} "
            f"extra_turns={metrics['avg_extra_turns']:.3f}"
        )

    out = RESULTS_DIR / f"recovery-{args.runtime}-{args.split}.json"
    write_json_report(out, report)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
