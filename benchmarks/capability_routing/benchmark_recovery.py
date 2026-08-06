#!/usr/bin/env python3
"""Oracle upper-bound catalog-recovery benchmark for capability routing."""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.capability_routing.recovery_simulation import (
    simulate_runtime_catalog_recovery,
)
from benchmarks.capability_routing.reporting import (
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
from core.agent.routing.ranker import RankerResult
from core.agent.routing.service import resolve_capabilities
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds
from core.agent.routing.models import CapabilityRoutingRequest
from core.agent.capabilities import list_agent_capabilities
from core.agent.types import AgentMessage

BENCH_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_ROOT / "results"

ORACLE_BENCHMARK_KIND = "oracle_catalog_recovery"
ORACLE_BENCHMARK_LIMITATION = (
    "Uses expected labels and the original prompt as the search query. "
    "This is an oracle upper bound on catalog recovery, not agent-initiated recovery."
)
CLASSIFIER_REPORT_KIND = "classifier_family_oracle"
ENABLED_RUNTIME_REPORT_KIND = "enabled_runtime_simulation"

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
    dict[str, int],
    dict[str, int],
]:
    agent_key = _RUNTIME_AGENT[runtime]
    max_tool_turns = AGENT_SPECS[agent_key].max_tool_turns
    cases_by_id = {case["id"]: case for case in cases}
    final_predictions: list[tuple[str, set[str], set[str], int, int]] = []
    search_invoked: dict[str, bool] = {}
    search_turns: dict[str, int] = {}
    expansion_turns: dict[str, int] = {}
    recovered_tool_turns: dict[str, int] = {}

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
        final_families = result.final_selected
        search_invoked[case_id] = result.search_attempted
        search_turns[case_id] = result.search_turns_used
        expansion_turns[case_id] = result.expansion_turns_used
        recovered_tool_turns[case_id] = result.recovered_tool_invocation_turns
        final_predictions.append(
            (
                case_id,
                expected,
                final_families,
                result.final_tool_count,
                result.final_schema_tokens,
            )
        )
    return (
        final_predictions,
        search_invoked,
        search_turns,
        expansion_turns,
        recovered_tool_turns,
    )


def _enabled_runtime_predictions(
    router: HybridOnnxRouter,
    cases: list[dict],
    *,
    runtime: str,
    agent_key: str,
    thresholds: RoutingThresholds,
    calibrator,
) -> list[tuple[str, set[str], set[str], int, int]]:
    predictions: list[tuple[str, set[str], set[str], int, int]] = []
    for case in cases:
        history = [
            AgentMessage(role=item["role"], content=item["content"])
            for item in case.get("history", [])
        ]
        rankings = router.rank(case["prompt"], history)
        rank_outcome = RankerResult(
            rankings=rankings,
            model_key=router.model_key,
            latency_ms=0.0,
            rule_matches=getattr(router, "last_rule_matches", ()),
        )
        request = CapabilityRoutingRequest(
            prompt=case["prompt"],
            history=tuple(history),
            capabilities=tuple(list_agent_capabilities()),
            agent_key=agent_key,
            runtime=runtime,  # type: ignore[arg-type]
            mode="enabled",
            explicit_scope=None,
        )
        with patch(
            "core.agent.routing.service.rank_capability_families",
            return_value=rank_outcome,
        ):
            decision = resolve_capabilities(
                request,
                thresholds=thresholds,
                calibrator=calibrator,
            )
        offered_families = {
            descriptor.routing_family
            for descriptor in decision.offered_capabilities
            if descriptor.routing_family is not None
        }
        expected = set(case["expected_families"])
        if "none" in expected:
            expected.discard("none")
        predictions.append(
            (
                case["id"],
                expected,
                offered_families,
                decision.offered_tool_count,
                decision.offered_schema_tokens,
            )
        )
    return predictions


def _evaluate_configuration(
    *,
    name: str,
    cases: list[dict],
    thresholds: RoutingThresholds,
    router: HybridOnnxRouter,
    runtime: str,
    with_recovery: bool,
    calibrator,
    report_kind: str,
    select_fn,
    initial_predictions: list[tuple[str, set[str], set[str], int, int]] | None = None,
) -> dict:
    if initial_predictions is None:
        initial_predictions, _ = run_router_predictions(
            router,
            cases,
            thresholds,
            select_fn=select_fn,
            runtime=runtime,
        )
    if with_recovery:
        (
            final_predictions,
            search_invoked,
            search_turns,
            expansion_turns,
            recovered_tool_turns,
        ) = _apply_recovery(
            cases,
            initial_predictions,
            runtime=runtime,
            thresholds=thresholds,
        )
    else:
        final_predictions = initial_predictions
        search_invoked = {case_id: False for case_id, *_ in initial_predictions}
        search_turns = {case_id: 0 for case_id, *_ in initial_predictions}
        expansion_turns = {case_id: 0 for case_id, *_ in initial_predictions}
        recovered_tool_turns = {case_id: 0 for case_id, *_ in initial_predictions}

    metrics = compute_recovery_metrics(
        config_name=name,
        split=cases[0]["split"] if cases else "dev",
        cases=cases,
        initial_predictions=initial_predictions,
        final_predictions=final_predictions,
        search_invoked=search_invoked,
        search_turns=search_turns,
        expansion_turns=expansion_turns,
        recovered_tool_turns=recovered_tool_turns,
        benchmark_kind=ORACLE_BENCHMARK_KIND,
        benchmark_limitation=ORACLE_BENCHMARK_LIMITATION,
        report_kind=report_kind,
    )
    return asdict(metrics)


def _print_metrics(metrics: dict) -> None:
    print(
        f"{metrics['name']} [{metrics['report_kind']}]: "
        f"cases={metrics['total_cases']} "
        f"unique_prompts={metrics['unique_prompt_cases']} "
        f"raw_initial={metrics['initial_complete_coverage_rate']:.3f} "
        f"raw_final={metrics['final_complete_coverage_rate']:.3f} "
        f"unique_initial={metrics['unique_initial_complete_coverage_rate']:.3f} "
        f"unique_final={metrics['unique_final_complete_coverage_rate']:.3f} "
        f"recovery_success={metrics['recovery_success_rate']:.3f} "
        f"search_turns={metrics['avg_search_turns_used']:.3f}"
    )


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
    calibrator = fit_calibrator_from_cases(dev_cases, router.rank, thresholds)
    agent_key = _RUNTIME_AGENT[args.runtime]

    def calibrated_select(rankings, config_thresholds, **kwargs):
        return select_families_from_rankings(
            rankings,
            config_thresholds,
            calibrator=calibrator,
            **kwargs,
        )

    report = {
        "split": args.split,
        "runtime": args.runtime,
        "benchmark_kind": ORACLE_BENCHMARK_KIND,
        "benchmark_limitation": ORACLE_BENCHMARK_LIMITATION,
        "runtime_agent": agent_key,
        "classifier_family_oracle": {},
        "enabled_runtime_simulation": {},
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
        classifier_metrics = _evaluate_configuration(
            name=name,
            cases=cases,
            thresholds=config_thresholds,
            router=router,
            runtime=args.runtime,
            with_recovery=with_recovery,
            calibrator=calibrator,
            report_kind=CLASSIFIER_REPORT_KIND,
            select_fn=calibrated_select,
        )
        report["classifier_family_oracle"][name] = classifier_metrics
        _print_metrics(classifier_metrics)

        enabled_initial = _enabled_runtime_predictions(
            router,
            cases,
            runtime=args.runtime,
            agent_key=agent_key,
            thresholds=config_thresholds,
            calibrator=calibrator,
        )
        enabled_metrics = _evaluate_configuration(
            name=name,
            cases=cases,
            thresholds=config_thresholds,
            router=router,
            runtime=args.runtime,
            with_recovery=with_recovery,
            calibrator=calibrator,
            report_kind=ENABLED_RUNTIME_REPORT_KIND,
            select_fn=calibrated_select,
            initial_predictions=enabled_initial,
        )
        report["enabled_runtime_simulation"][name] = enabled_metrics
        _print_metrics(enabled_metrics)

    out = RESULTS_DIR / f"oracle-catalog-recovery-{args.runtime}-{args.split}.json"
    write_json_report(out, report)
    print(f"Wrote {out}")
    print(f"NOTE: {ORACLE_BENCHMARK_LIMITATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
