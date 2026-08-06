"""Benchmark reporting helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.agent.types import AgentMessage

BENCH_ROOT = Path(__file__).resolve().parent
CASES_PATH = BENCH_ROOT / "cases.jsonl"


@dataclass
class RouterMetrics:
    name: str
    split: str
    micro_precision: float
    micro_recall: float
    micro_f1: float
    macro_family_recall: float
    exact_set_accuracy: float
    complete_coverage_rate: float
    no_tool_accuracy: float
    top1_family_recall: float
    top2_family_recall: float
    top3_family_recall: float
    avg_selected_families: float
    avg_selected_tools: float
    avg_selected_schema_tokens: float
    schema_token_reduction: float
    by_family: dict[str, dict[str, float]]
    by_origin: dict[str, dict[str, float]]
    by_difficulty: dict[str, dict[str, float]]
    false_negative_ids: list[str]
    false_positive_ids: list[str]


def load_cases(split: str) -> list[dict]:
    cases: list[dict] = []
    with CASES_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            case = json.loads(line)
            if case["split"] == split:
                cases.append(case)
    return cases


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _case_origin(case_id: str) -> str:
    if case_id.startswith("pad-") or "-auto-" in case_id:
        return "synthetic"
    if case_id.rsplit("-", 1)[-1].isdigit() and not case_id.startswith(
        ("sched-", "wx-", "f1-", "mail-", "search-", "market-", "brief-", "todo-", "multi-", "ambig-")
    ):
        return "synthetic"
    return "handwritten"


def compute_metrics(
    *,
    router_name: str,
    split: str,
    predictions: list[tuple[str, set[str], set[str], int, int]],
    expose_all_tokens: int,
    cases_by_id: dict[str, dict] | None = None,
    ranking_lists: dict[str, list[str]] | None = None,
) -> RouterMetrics:
    return compute_extended_metrics(
        router_name=router_name,
        split=split,
        predictions=predictions,
        expose_all_tokens=expose_all_tokens,
        cases_by_id=cases_by_id or {},
        ranking_lists=ranking_lists or {},
    )


def compute_extended_metrics(
    *,
    router_name: str,
    split: str,
    predictions: list[tuple[str, set[str], set[str], int, int]],
    expose_all_tokens: int,
    cases_by_id: dict[str, dict],
    ranking_lists: dict[str, list[str]],
) -> RouterMetrics:
    tp = fp = fn = 0
    exact = complete = 0
    no_tool_total = no_tool_correct = 0
    family_tp: dict[str, int] = defaultdict(int)
    family_fp: dict[str, int] = defaultdict(int)
    family_fn: dict[str, int] = defaultdict(int)
    origin_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0, "exact": 0, "total": 0}
    )
    difficulty_tp: dict[str, int] = defaultdict(int)
    difficulty_total: dict[str, int] = defaultdict(int)
    false_negative_ids: list[str] = []
    false_positive_ids: list[str] = []
    total = len(predictions)
    family_sets: dict[str, list[bool]] = defaultdict(list)
    token_sum = family_count_sum = tool_count_sum = 0
    top1_hits = top2_hits = top3_hits = expected_family_total = 0

    for case_id, expected, selected, tool_count, schema_tokens in predictions:
        case = cases_by_id.get(case_id, {})
        origin = _case_origin(case_id)
        origin_stats[origin]["total"] += 1
        difficulty = case.get("difficulty", "unknown")
        difficulty_total[difficulty] += 1

        if expected == {"none"}:
            expected = set()
        if selected == {"none"}:
            selected = set()
        if not expected:
            no_tool_total += 1
            if not selected:
                no_tool_correct += 1
        tp += len(expected & selected)
        fp += len(selected - expected)
        fn += len(expected - selected)
        origin_stats[origin]["tp"] += len(expected & selected)
        origin_stats[origin]["fp"] += len(selected - expected)
        origin_stats[origin]["fn"] += len(expected - selected)
        if expected == selected:
            exact += 1
            origin_stats[origin]["exact"] += 1
        if expected <= selected:
            complete += 1
        if fn > 0 or (expected and not selected):
            false_negative_ids.append(case_id)
        if fp > 0:
            false_positive_ids.append(case_id)
        for family in expected:
            family_sets[family].append(family in selected)
            if family in selected:
                family_tp[family] += 1
                difficulty_tp[difficulty] += 1
            else:
                family_fn[family] += 1
        for family in selected - expected:
            family_fp[family] += 1
        ranked = ranking_lists.get(case_id, [])
        for family in expected:
            expected_family_total += 1
            if family in ranked[:1]:
                top1_hits += 1
            if family in ranked[:2]:
                top2_hits += 1
            if family in ranked[:3]:
                top3_hits += 1
        token_sum += schema_tokens
        family_count_sum += len(selected)
        tool_count_sum += tool_count

    macro_recalls = [
        _safe_div(sum(values), len(values))
        for values in family_sets.values()
        if values
    ]
    by_family: dict[str, dict[str, float]] = {}
    for family in sorted(set(family_tp) | set(family_fp) | set(family_fn)):
        precision = _safe_div(family_tp[family], family_tp[family] + family_fp[family])
        recall = _safe_div(family_tp[family], family_tp[family] + family_fn[family])
        by_family[family] = {
            "precision": precision,
            "recall": recall,
            "support": family_tp[family] + family_fn[family],
        }
    by_origin: dict[str, dict[str, float]] = {}
    for origin, stats in origin_stats.items():
        by_origin[origin] = {
            "micro_precision": _safe_div(stats["tp"], stats["tp"] + stats["fp"]),
            "micro_recall": _safe_div(stats["tp"], stats["tp"] + stats["fn"]),
            "exact_set_accuracy": _safe_div(stats["exact"], stats["total"]),
            "case_count": stats["total"],
        }
    by_difficulty: dict[str, dict[str, float]] = {}
    for difficulty, count in difficulty_total.items():
        by_difficulty[difficulty] = {
            "recall": _safe_div(difficulty_tp[difficulty], count),
            "case_count": count,
        }
    return RouterMetrics(
        name=router_name,
        split=split,
        micro_precision=_safe_div(tp, tp + fp),
        micro_recall=_safe_div(tp, tp + fn),
        micro_f1=_safe_div(2 * tp, 2 * tp + fp + fn),
        macro_family_recall=_safe_div(sum(macro_recalls), len(macro_recalls)),
        exact_set_accuracy=_safe_div(exact, total),
        complete_coverage_rate=_safe_div(complete, total),
        no_tool_accuracy=_safe_div(no_tool_correct, no_tool_total),
        top1_family_recall=_safe_div(top1_hits, expected_family_total),
        top2_family_recall=_safe_div(top2_hits, expected_family_total),
        top3_family_recall=_safe_div(top3_hits, expected_family_total),
        avg_selected_families=_safe_div(family_count_sum, total),
        avg_selected_tools=_safe_div(tool_count_sum, total),
        avg_selected_schema_tokens=_safe_div(token_sum, total),
        schema_token_reduction=_safe_div(
            expose_all_tokens - _safe_div(token_sum, total),
            expose_all_tokens,
        ),
        by_family=by_family,
        by_origin=by_origin,
        by_difficulty=by_difficulty,
        false_negative_ids=false_negative_ids,
        false_positive_ids=false_positive_ids,
    )


def run_router_predictions(
    router,
    cases: list[dict],
    thresholds,
    *,
    select_fn,
) -> tuple[list[tuple[str, set[str], set[str], int, int]], dict[str, list[str]]]:
    from benchmarks.capability_routing.benchmark_quality import (
        estimate_schema_tokens_for_families,
        estimate_tools_for_families,
    )

    predictions: list[tuple[str, set[str], set[str], int, int]] = []
    ranking_lists: dict[str, list[str]] = {}
    for case in cases:
        history = [
            AgentMessage(role=item["role"], content=item["content"])
            for item in case.get("history", [])
        ]
        rankings = router.rank(case["prompt"], history)
        ranking_lists[case["id"]] = [item.key for item in rankings if item.key != "none"]
        if router.name == "expose-all":
            selected = {item.key for item in rankings if item.key != "none"}
        else:
            selected = select_fn(
                rankings,
                thresholds,
                rule_matches=getattr(router, "last_rule_matches", None),
            )
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
    return predictions, ranking_lists


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
