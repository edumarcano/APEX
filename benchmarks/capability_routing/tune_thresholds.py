"""Threshold tuning helpers for capability routing benchmarks."""

from __future__ import annotations

from dataclasses import replace
from itertools import product

from core.agent.routing.models import RankedCapabilityFamily
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds


def select_families_from_rankings(
    rankings: list[RankedCapabilityFamily],
    thresholds: RoutingThresholds,
    *,
    runtime: str = "cloud",
) -> set[str]:
    from core.agent.routing.service import _family_eligible, _select_families

    selected, _, _, low = _select_families(rankings, thresholds, runtime)
    if low:
        return set()
    return set(selected)


def tune_thresholds(
    cases: list[dict],
    rank_fn,
) -> RoutingThresholds:
    best = DEFAULT_THRESHOLDS
    best_score = -1.0
    for min_top, min_margin in product(
        [0.28, 0.32, 0.36, 0.40, 0.44, 0.48],
        [0.01, 0.03, 0.05, 0.08, 0.10],
    ):
        thresholds = replace(
            DEFAULT_THRESHOLDS,
            minimum_top_score=min_top,
            minimum_none_margin=min_margin,
        )
        tp = fn = 0
        complete = 0
        no_tool_ok = no_tool_total = 0
        for case in cases:
            rankings = rank_fn(case["prompt"], case.get("history", []))
            selected = select_families_from_rankings(rankings, thresholds)
            expected = set(case["expected_families"])
            if "none" in expected:
                expected.discard("none")
            if not expected:
                no_tool_total += 1
                if not selected:
                    no_tool_ok += 1
            tp += len(expected & selected)
            fn += len(expected - selected)
            if expected <= selected:
                complete += 1
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        coverage = complete / len(cases) if cases else 0.0
        no_tool_acc = no_tool_ok / no_tool_total if no_tool_total else 1.0
        score = recall * 0.5 + coverage * 0.35 + no_tool_acc * 0.15
        if score > best_score:
            best_score = score
            best = thresholds
    return best
