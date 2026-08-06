"""Benchmark reporting helpers."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    avg_selected_families: float
    avg_selected_tools: float
    avg_selected_schema_tokens: float
    schema_token_reduction: float
    by_family: dict[str, dict[str, float]]
    by_difficulty: dict[str, dict[str, float]]
    false_negative_ids: list[str]
    false_positive_ids: list[str]


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def compute_metrics(
    *,
    router_name: str,
    split: str,
    predictions: list[tuple[str, set[str], set[str], int, int]],
    expose_all_tokens: int,
) -> RouterMetrics:
    tp = fp = fn = 0
    exact = complete = 0
    no_tool_total = no_tool_correct = 0
    family_tp: dict[str, int] = defaultdict(int)
    family_fn: dict[str, int] = defaultdict(int)
    difficulty_tp: dict[str, int] = defaultdict(int)
    difficulty_total: dict[str, int] = defaultdict(int)
    false_negative_ids: list[str] = []
    false_positive_ids: list[str] = []
    total = len(predictions)
    family_sets: dict[str, list[bool]] = defaultdict(list)
    token_sum = family_count_sum = tool_count_sum = 0

    for case_id, expected, selected, tool_count, schema_tokens in predictions:
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
        if expected == selected:
            exact += 1
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
            else:
                family_fn[family] += 1
        token_sum += schema_tokens
        family_count_sum += len(selected)
        tool_count_sum += tool_count

    macro_recalls = [
        _safe_div(sum(values), len(values))
        for values in family_sets.values()
        if values
    ]
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
        avg_selected_families=_safe_div(family_count_sum, total),
        avg_selected_tools=_safe_div(tool_count_sum, total),
        avg_selected_schema_tokens=_safe_div(token_sum, total),
        schema_token_reduction=_safe_div(
            expose_all_tokens - _safe_div(token_sum, total),
            expose_all_tokens,
        ),
        by_family={},
        by_difficulty={},
        false_negative_ids=false_negative_ids,
        false_positive_ids=false_positive_ids,
    )


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
