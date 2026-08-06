#!/usr/bin/env python3
"""Quality benchmark for capability routing candidates."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.capability_routing.reporting import (
    CASES_PATH,
    compute_extended_metrics,
    load_cases,
    run_router_predictions,
    write_json_report,
)
from benchmarks.capability_routing.routers import (
    ExposeAllRouter,
    HybridOnnxRouter,
    LexicalBaselineRouter,
    OnnxBenchmarkRouter,
    build_candidate_routers,
)
from benchmarks.capability_routing.tune_thresholds import (
    calibration_payload,
    fit_calibrator_from_cases,
    select_families_from_rankings,
    tune_thresholds,
)
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds

BENCH_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_ROOT / "results"

ACCEPTANCE_GATES = {
    "micro_recall": 0.97,
    "complete_coverage_rate": 0.95,
    "no_tool_accuracy": 0.93,
}


def estimate_tools_for_families(families: set[str]) -> int:
    from core.agent.capabilities import list_agent_capabilities

    if not families:
        return 0
    return sum(
        1
        for descriptor in list_agent_capabilities()
        if descriptor.routing_family in families
    )


def estimate_schema_tokens_for_families(families: set[str]) -> int:
    from core.agent.capabilities import list_agent_capabilities
    from core.agent.local_commands import estimate_schema_tokens

    descriptors = [
        descriptor
        for descriptor in list_agent_capabilities()
        if descriptor.routing_family in families
    ]
    return estimate_schema_tokens(descriptors)


def _cases_by_id(cases: list[dict]) -> dict[str, dict]:
    return {case["id"]: case for case in cases}


def _evaluate_router(
    router,
    cases: list[dict],
    thresholds: RoutingThresholds,
    expose_tokens: int,
) -> dict:
    predictions, ranking_lists = run_router_predictions(
        router,
        cases,
        thresholds,
        select_fn=select_families_from_rankings,
    )
    metrics = compute_extended_metrics(
        router_name=router.name,
        split=cases[0]["split"] if cases else "dev",
        predictions=predictions,
        expose_all_tokens=expose_tokens,
        cases_by_id=_cases_by_id(cases),
        ranking_lists=ranking_lists,
    )
    return asdict(metrics)


def _passes_gates(metrics: dict) -> bool:
    return all(metrics[key] >= required for key, required in ACCEPTANCE_GATES.items())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--all-candidates", action="store_true")
    parser.add_argument("--compare-prototypes", action="store_true")
    parser.add_argument("--compare-max-families", action="store_true")
    parser.add_argument("--router", default=None)
    args = parser.parse_args()
    cases = load_cases(args.split)
    dev_cases = load_cases("dev")
    thresholds = DEFAULT_THRESHOLDS

    routers = [ExposeAllRouter(), LexicalBaselineRouter()]
    if args.all_candidates:
        routers = build_candidate_routers(include_onnx=True)
    if args.router:
        if args.router == "hybrid-minilm-onnx":
            routers = [HybridOnnxRouter(model_key="all-minilm-l6-v2", name="hybrid-minilm-onnx")]
        elif args.router == "minilm-onnx":
            routers = [OnnxBenchmarkRouter(model_key="all-minilm-l6-v2", name="minilm-onnx")]
        else:
            routers = [item for item in build_candidate_routers(include_onnx=True) if item.name == args.router]

    tuning_router = routers[2] if len(routers) > 2 else routers[0]
    if hasattr(tuning_router, "rank"):
        thresholds = tune_thresholds(dev_cases, tuning_router.rank)
        calibrator = fit_calibrator_from_cases(dev_cases, tuning_router.rank, thresholds)
        from core.agent.routing import calibration as calibration_module

        calibration_module.DEFAULT_CALIBRATOR = calibrator
        write_json_report(
            RESULTS_DIR / "selected_parameters.json",
            {
                **{k: getattr(thresholds, k) for k in asdict(DEFAULT_THRESHOLDS)},
                "calibration": calibration_payload(calibrator),
            },
        )

    expose_predictions, _ = run_router_predictions(
        ExposeAllRouter(),
        cases,
        thresholds,
        select_fn=select_families_from_rankings,
    )
    expose_tokens = int(
        sum(item[4] for item in expose_predictions) / max(len(expose_predictions), 1)
    )

    report: dict = {
        "split": args.split,
        "thresholds": asdict(thresholds),
        "acceptance_gates": ACCEPTANCE_GATES,
        "routers": {},
        "configurations": {},
    }

    for router in routers:
        metrics = _evaluate_router(router, cases, thresholds, expose_tokens)
        report["routers"][router.name] = metrics
        report["configurations"][router.name] = {
            "passes_gates": _passes_gates(metrics),
            "max_selected_families": thresholds.max_selected_families,
        }
        print(
            f"{router.name}: recall={metrics['micro_recall']:.3f} "
            f"coverage={metrics['complete_coverage_rate']:.3f} "
            f"no_tool={metrics['no_tool_accuracy']:.3f} "
            f"top1={metrics['top1_family_recall']:.3f}"
        )

    if args.compare_prototypes and args.split == "dev":
        prototype_report = {}
        for mode, label in (
            ("description", "minilm-description-onnx"),
            ("exemplars", "minilm-exemplars-onnx"),
            ("combined", "minilm-onnx"),
        ):
            router = OnnxBenchmarkRouter(
                model_key="all-minilm-l6-v2",
                name=label,
                prototype_mode=mode,
            )
            prototype_report[label] = _evaluate_router(router, cases, thresholds, expose_tokens)
        report["prototype_comparison"] = prototype_report

    if args.compare_max_families:
        cap_report = {}
        for cap in (2, 3):
            capped = replace(thresholds, max_selected_families=cap)
            router = HybridOnnxRouter(model_key="all-minilm-l6-v2", name="hybrid-minilm-onnx")
            cap_report[f"max_selected_families={cap}"] = _evaluate_router(
                router,
                cases,
                capped,
                expose_tokens,
            )
        report["max_family_cap_comparison"] = cap_report

    out = RESULTS_DIR / f"quality-{args.split}.json"
    write_json_report(out, report)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
