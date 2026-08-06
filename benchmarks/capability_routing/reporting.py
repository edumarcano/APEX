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


@dataclass
class RecoveryRouterMetrics:
    name: str
    split: str
    benchmark_kind: str
    benchmark_limitation: str
    report_kind: str
    total_cases: int
    unique_prompt_cases: int
    initial_complete_coverage_rate: float
    final_complete_coverage_rate: float
    recovery_success_rate: float
    recovery_invocation_rate: float
    false_positive_family_rate: float
    avg_schemas_exposed: float
    avg_final_schema_tokens: float
    avg_final_tool_count: float
    avg_search_turns_used: float
    avg_expansion_turns_used: float
    avg_recovered_tool_invocation_turns: float
    no_tool_accuracy: float
    micro_recall_initial: float
    micro_recall_final: float
    unique_initial_complete_coverage_rate: float
    unique_final_complete_coverage_rate: float
    unique_recovery_success_rate: float
    unique_no_tool_accuracy: float
    unique_false_positive_family_rate: float
    by_origin: dict[str, dict[str, float]]
    by_origin_unique: dict[str, dict[str, float]]


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
    """Deprecated: prefer ``classify_case_origin``."""
    return classify_case_origin({"id": case_id})


def classify_case_origin(
    case: dict,
    *,
    seen_prompt_keys: set[tuple[str, tuple[tuple[str, str], ...]]] | None = None,
) -> str:
    """Classify benchmark case provenance without inferring origin from IDs alone."""
    case_id = case.get("id", "")
    difficulty = case.get("difficulty", "")
    history_key = tuple(
        (item.get("role", ""), item.get("content", ""))
        for item in case.get("history", [])
    )
    prompt_key = (case.get("prompt", ""), history_key)

    if seen_prompt_keys is not None:
        if prompt_key in seen_prompt_keys:
            return "exact_duplicate"
        seen_prompt_keys.add(prompt_key)

    if case_id.startswith("pad-"):
        return "synthetic_padding"
    if "-auto-" in case_id:
        return "generated_paraphrase"
    if difficulty == "paraphrased" and case_id.rsplit("-", 1)[-1].isdigit():
        prefix = case_id.rsplit("-", 1)[0]
        if prefix.endswith("-auto") or "-auto-" in prefix:
            return "generated_paraphrase"
    return "handwritten"


def dedupe_cases_by_prompt(cases: list[dict]) -> list[dict]:
    """Keep the first case for each logical prompt/history pair."""
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    unique: list[dict] = []
    for case in cases:
        history_key = tuple(
            (item.get("role", ""), item.get("content", ""))
            for item in case.get("history", [])
        )
        key = (case["prompt"], history_key)
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return unique


def compute_metrics(
    *,
    router_name: str,
    split: str,
    predictions: list[tuple[str, set[str], set[str], int, int]],
    expose_all_tokens: int,
    cases_by_id: dict[str, dict] | None = None,
    ranking_lists: dict[str, list[str]] | None = None,
    runtime: str = "cloud",
) -> RouterMetrics:
    return compute_extended_metrics(
        router_name=router_name,
        split=split,
        predictions=predictions,
        expose_all_tokens=expose_all_tokens,
        cases_by_id=cases_by_id or {},
        ranking_lists=ranking_lists or {},
        runtime=runtime,
    )


def compute_extended_metrics(
    *,
    router_name: str,
    split: str,
    predictions: list[tuple[str, set[str], set[str], int, int]],
    expose_all_tokens: int,
    cases_by_id: dict[str, dict],
    ranking_lists: dict[str, list[str]],
    runtime: str = "cloud",
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
    seen_prompt_keys: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    for case_id, expected, selected, tool_count, schema_tokens in predictions:
        case = cases_by_id.get(case_id, {})
        origin = classify_case_origin(case, seen_prompt_keys=seen_prompt_keys)
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
        case_false_negatives = expected - selected
        case_false_positives = selected - expected
        if case_false_negatives:
            false_negative_ids.append(case_id)
        if case_false_positives:
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
    runtime: str = "cloud",
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
                runtime=runtime,
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


def compute_recovery_metrics(
    *,
    config_name: str,
    split: str,
    cases: list[dict],
    initial_predictions: list[tuple[str, set[str], set[str], int, int]],
    final_predictions: list[tuple[str, set[str], set[str], int, int]],
    search_invoked: dict[str, bool],
    search_turns: dict[str, int],
    expansion_turns: dict[str, int],
    recovered_tool_turns: dict[str, int],
    benchmark_kind: str = "oracle_catalog_recovery",
    benchmark_limitation: str = (
        "Uses expected labels and the original prompt as the search query. "
        "This is an oracle upper bound, not agent-initiated recovery."
    ),
    report_kind: str = "classifier_family_oracle",
) -> RecoveryRouterMetrics:
    total = len(cases)
    unique_cases = dedupe_cases_by_prompt(cases)
    unique_case_ids = {case["id"] for case in unique_cases}
    initial_complete = final_complete = recovery_successes = invocations = 0
    false_positive_cases = 0
    no_tool_total = no_tool_correct = 0
    schema_sum = schema_token_sum = tool_count_sum = 0
    search_turn_sum = expansion_turn_sum = recovered_tool_turn_sum = 0
    tp_initial = fn_initial = tp_final = fn_final = 0
    unique_initial_complete = unique_final_complete = unique_recovery_successes = 0
    unique_false_positive_cases = 0
    unique_no_tool_total = unique_no_tool_correct = 0
    origin_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "initial_complete": 0,
            "final_complete": 0,
            "recovery_success": 0,
            "total": 0,
        }
    )
    unique_origin_stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "initial_complete": 0,
            "final_complete": 0,
            "recovery_success": 0,
            "total": 0,
        }
    )
    seen_prompt_keys: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    for case in cases:
        case_id = case["id"]
        expected = set(case["expected_families"])
        if "none" in expected:
            expected.discard("none")
        origin = classify_case_origin(case, seen_prompt_keys=seen_prompt_keys)
        origin_stats[origin]["total"] += 1
        is_unique = case_id in unique_case_ids

        initial = next(item for item in initial_predictions if item[0] == case_id)
        final = next(item for item in final_predictions if item[0] == case_id)
        initial_selected = initial[2]
        final_selected = final[2]

        if not expected:
            no_tool_total += 1
            if not final_selected:
                no_tool_correct += 1
            if is_unique:
                unique_no_tool_total += 1
                if not final_selected:
                    unique_no_tool_correct += 1

        if expected <= initial_selected:
            initial_complete += 1
            origin_stats[origin]["initial_complete"] += 1
            if is_unique:
                unique_initial_complete += 1
                unique_origin_stats[origin]["initial_complete"] += 1
        if expected <= final_selected:
            final_complete += 1
            origin_stats[origin]["final_complete"] += 1
            if is_unique:
                unique_final_complete += 1
                unique_origin_stats[origin]["final_complete"] += 1
        if expected > initial_selected and expected <= final_selected:
            recovery_successes += 1
            origin_stats[origin]["recovery_success"] += 1
            if is_unique:
                unique_recovery_successes += 1
                unique_origin_stats[origin]["recovery_success"] += 1
        if search_invoked.get(case_id, False):
            invocations += 1
        if final_selected - expected:
            false_positive_cases += 1
            if is_unique:
                unique_false_positive_cases += 1

        if is_unique:
            unique_origin_stats[origin]["total"] += 1

        tp_initial += len(expected & initial_selected)
        fn_initial += len(expected - initial_selected)
        tp_final += len(expected & final_selected)
        fn_final += len(expected - final_selected)
        schema_sum += final[4]
        schema_token_sum += final[4]
        tool_count_sum += final[3]
        search_turn_sum += search_turns.get(case_id, 0)
        expansion_turn_sum += expansion_turns.get(case_id, 0)
        recovered_tool_turn_sum += recovered_tool_turns.get(case_id, 0)

    by_origin: dict[str, dict[str, float]] = {}
    for origin, stats in origin_stats.items():
        by_origin[origin] = {
            "initial_complete_coverage_rate": _safe_div(
                stats["initial_complete"], stats["total"]
            ),
            "final_complete_coverage_rate": _safe_div(
                stats["final_complete"], stats["total"]
            ),
            "recovery_success_rate": _safe_div(
                stats["recovery_success"],
                max(stats["total"] - stats["initial_complete"], 0),
            ),
            "case_count": stats["total"],
        }
    by_origin_unique: dict[str, dict[str, float]] = {}
    for origin, stats in unique_origin_stats.items():
        by_origin_unique[origin] = {
            "initial_complete_coverage_rate": _safe_div(
                stats["initial_complete"], stats["total"]
            ),
            "final_complete_coverage_rate": _safe_div(
                stats["final_complete"], stats["total"]
            ),
            "recovery_success_rate": _safe_div(
                stats["recovery_success"],
                max(stats["total"] - stats["initial_complete"], 0),
            ),
            "case_count": stats["total"],
        }

    incomplete = total - initial_complete
    unique_incomplete = len(unique_cases) - unique_initial_complete
    unique_no_tool_denom = unique_no_tool_total
    return RecoveryRouterMetrics(
        name=config_name,
        split=split,
        benchmark_kind=benchmark_kind,
        benchmark_limitation=benchmark_limitation,
        report_kind=report_kind,
        total_cases=total,
        unique_prompt_cases=len(unique_cases),
        initial_complete_coverage_rate=_safe_div(initial_complete, total),
        final_complete_coverage_rate=_safe_div(final_complete, total),
        recovery_success_rate=_safe_div(recovery_successes, incomplete),
        recovery_invocation_rate=_safe_div(invocations, total),
        false_positive_family_rate=_safe_div(false_positive_cases, total),
        avg_schemas_exposed=_safe_div(schema_sum, total),
        avg_final_schema_tokens=_safe_div(schema_token_sum, total),
        avg_final_tool_count=_safe_div(tool_count_sum, total),
        avg_search_turns_used=_safe_div(search_turn_sum, total),
        avg_expansion_turns_used=_safe_div(expansion_turn_sum, total),
        avg_recovered_tool_invocation_turns=_safe_div(recovered_tool_turn_sum, total),
        no_tool_accuracy=_safe_div(no_tool_correct, no_tool_total),
        micro_recall_initial=_safe_div(tp_initial, tp_initial + fn_initial),
        micro_recall_final=_safe_div(tp_final, tp_final + fn_final),
        unique_initial_complete_coverage_rate=_safe_div(
            unique_initial_complete, len(unique_cases)
        ),
        unique_final_complete_coverage_rate=_safe_div(
            unique_final_complete, len(unique_cases)
        ),
        unique_recovery_success_rate=_safe_div(
            unique_recovery_successes, unique_incomplete
        ),
        unique_no_tool_accuracy=_safe_div(
            unique_no_tool_correct, unique_no_tool_denom
        ),
        unique_false_positive_family_rate=_safe_div(
            unique_false_positive_cases, len(unique_cases)
        ),
        by_origin=by_origin,
        by_origin_unique=by_origin_unique,
    )


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
