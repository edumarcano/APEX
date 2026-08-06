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

from benchmarks.capability_routing.reporting import compute_metrics, write_json_report
from benchmarks.capability_routing.routers import (
    ExposeAllRouter,
    LexicalBaselineRouter,
    build_candidate_routers,
)
from benchmarks.capability_routing.tune_thresholds import (
    select_families_from_rankings,
    tune_thresholds,
)
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds
from core.agent.types import AgentMessage

BENCH_ROOT = Path(__file__).resolve().parent
CASES_PATH = BENCH_ROOT / "cases.jsonl"
RESULTS_DIR = BENCH_ROOT / "results"


def load_cases(split: str) -> list[dict]:
    cases: list[dict] = []
    with CASES_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            case = json.loads(line)
            if case["split"] == split:
                cases.append(case)
    return cases


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


def run_router(
    router,
    cases: list[dict],
    thresholds: RoutingThresholds,
) -> list[tuple[str, set[str], set[str], int, int]]:
    predictions: list[tuple[str, set[str], set[str], int, int]] = []
    for case in cases:
        history = [
            AgentMessage(role=item["role"], content=item["content"])
            for item in case.get("history", [])
        ]
        rankings = router.rank(case["prompt"], history)
        if router.name == "expose-all":
            selected = {item.key for item in rankings if item.key != "none"}
        else:
            selected = select_families_from_rankings(rankings, thresholds)
        expected = set(case["expected_families"])
        if "none" in expected:
            expected.discard("none")
        predictions.append(
            (
                case["id"],
                expected,
                selected,
                estimate_tools_for_families(selected),
                estimate_schema_tokens_for_families(selected),
            )
        )
    return predictions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--all-candidates", action="store_true")
    parser.add_argument("--locked-parameters", type=Path)
    args = parser.parse_args()
    cases = load_cases(args.split)
    thresholds = DEFAULT_THRESHOLDS
    if args.split == "dev" and args.all_candidates:
        from benchmarks.capability_routing.routers import OnnxBenchmarkRouter

        minilm = OnnxBenchmarkRouter(
            model_key="all-minilm-l6-v2",
            name="minilm-onnx",
        )

        def _rank(prompt: str, history: list[dict]) -> list:
            messages = [
                AgentMessage(role=item["role"], content=item["content"])
                for item in history
            ]
            return minilm.rank(prompt, messages)

        thresholds = tune_thresholds(cases, _rank)
        write_json_report(
            RESULTS_DIR / "selected_parameters.json",
            {
                "minimum_top_score": thresholds.minimum_top_score,
                "minimum_none_margin": thresholds.minimum_none_margin,
                "additional_family_minimum_score": (
                    thresholds.additional_family_minimum_score
                ),
                "additional_family_margin": thresholds.additional_family_margin,
                "max_selected_families": thresholds.max_selected_families,
            },
        )
        print(
            "Tuned thresholds:",
            thresholds.minimum_top_score,
            thresholds.minimum_none_margin,
        )
    elif args.locked_parameters and args.locked_parameters.is_file():
        locked = json.loads(args.locked_parameters.read_text(encoding="utf-8"))
        thresholds = replace(DEFAULT_THRESHOLDS, **locked)

    expose_all = ExposeAllRouter()
    expose_predictions = run_router(expose_all, cases, thresholds)
    expose_tokens = int(
        sum(item[4] for item in expose_predictions) / max(len(expose_predictions), 1)
    )
    routers = [ExposeAllRouter(), LexicalBaselineRouter()]
    if args.all_candidates:
        routers = build_candidate_routers(include_onnx=True)
    report: dict = {"split": args.split, "thresholds": asdict(thresholds), "routers": {}}
    for router in routers:
        predictions = run_router(router, cases, thresholds)
        metrics = compute_metrics(
            router_name=router.name,
            split=args.split,
            predictions=predictions,
            expose_all_tokens=expose_tokens,
        )
        report["routers"][router.name] = metrics.__dict__
        print(
            f"{router.name}: recall={metrics.micro_recall:.3f} "
            f"coverage={metrics.complete_coverage_rate:.3f} "
            f"no_tool={metrics.no_tool_accuracy:.3f}"
        )
    out = RESULTS_DIR / f"quality-{args.split}.json"
    write_json_report(out, report)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
