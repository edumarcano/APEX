"""Threshold tuning helpers for capability routing benchmarks."""

from __future__ import annotations

from dataclasses import asdict, replace
from itertools import product

from core.agent.routing.calibration import ScoreCalibrator, fit_calibrator
from core.agent.routing.models import RankedCapabilityFamily
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS, RoutingThresholds
from core.agent.types import AgentMessage


def _history_messages(history: list) -> list[AgentMessage]:
    messages: list[AgentMessage] = []
    for item in history:
        if isinstance(item, AgentMessage):
            messages.append(item)
        else:
            messages.append(AgentMessage(role=item["role"], content=item["content"]))
    return messages


def select_families_from_rankings(
    rankings: list[RankedCapabilityFamily],
    thresholds: RoutingThresholds,
    *,
    runtime: str = "cloud",
    rule_matches=None,
    calibrator: ScoreCalibrator | None = None,
) -> set[str]:
    from core.agent.routing.calibration import DISABLED_CALIBRATOR
    from core.agent.routing.service import _select_families

    selected, _, _, low = _select_families(
        rankings,
        thresholds,
        runtime,
        rule_matches=rule_matches,
        calibrator=calibrator or DISABLED_CALIBRATOR,
    )
    if low:
        return set()
    return set(selected)


def _case_expected(case: dict) -> set[str]:
    expected = set(case["expected_families"])
    if "none" in expected:
        expected.discard("none")
    return expected


def _evaluate_thresholds(
    cases: list[dict],
    rank_fn,
    thresholds: RoutingThresholds,
) -> tuple[float, float, float]:
    tp = fn = 0
    complete = 0
    no_tool_ok = no_tool_total = 0
    for case in cases:
        rankings = rank_fn(case["prompt"], _history_messages(case.get("history", [])))
        selected = select_families_from_rankings(rankings, thresholds)
        expected = _case_expected(case)
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
    return recall, coverage, no_tool_acc


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
        recall, coverage, no_tool_acc = _evaluate_thresholds(cases, rank_fn, thresholds)
        score = recall * 0.5 + coverage * 0.35 + no_tool_acc * 0.15
        if score > best_score:
            best_score = score
            best = thresholds
    return best


def fit_calibrator_from_cases(
    cases: list[dict],
    rank_fn,
    thresholds: RoutingThresholds,
) -> ScoreCalibrator:
    samples: list[tuple[float, bool]] = []
    for case in cases:
        history = _history_messages(case.get("history", []))
        rankings = rank_fn(case["prompt"], history)
        expected = _case_expected(case)
        selected = select_families_from_rankings(rankings, thresholds)
        top_score = next((item.score for item in rankings if item.key != "none"), None)
        if top_score is None:
            continue
        is_correct = expected == selected
        samples.append((top_score, is_correct))
    return fit_calibrator(samples)


def calibration_payload(calibrator: ScoreCalibrator) -> dict:
    return {
        "default_error_rate": calibrator.default_error_rate,
        "bins": [asdict(item) for item in calibrator.bins],
    }
