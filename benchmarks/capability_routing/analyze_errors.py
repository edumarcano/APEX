"""Held-out failure analysis for capability routing benchmarks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.capability_routing.reporting import (
    compute_extended_metrics,
    load_cases,
    run_router_predictions,
)
from benchmarks.capability_routing.routers import (
    HybridOnnxRouter,
    OnnxBenchmarkRouter,
    build_candidate_routers,
)
from benchmarks.capability_routing.tune_thresholds import (
    fit_calibrator_from_cases,
    select_families_from_rankings,
    tune_thresholds,
)
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS
from core.agent.types import AgentMessage

BENCH_ROOT = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_ROOT / "results"

_HANDWRITTEN_PREFIXES = (
    "sched-",
    "wx-",
    "f1-",
    "mail-",
    "search-",
    "market-",
    "brief-",
    "todo-",
    "multi-",
    "ambig-",
    "explain-",
    "rewrite-",
    "arithmetic-",
    "thanks",
    "brainstorm-",
    "translate-",
    "summarize-",
    "casual-",
    "define-",
    "proofread-",
)


def case_origin(case: dict) -> str:
    case_id = case["id"]
    if case_id.startswith("pad-"):
        return "synthetic"
    if re.search(r"-auto-\d+$", case_id):
        return "synthetic"
    if re.search(r"-\d+$", case_id) and not case_id.startswith(tuple(_HANDWRITTEN_PREFIXES)):
        return "synthetic"
    return "handwritten"


def prompt_category(case: dict) -> str:
    difficulty = case.get("difficulty", "unknown")
    expected = case.get("expected_families", [])
    if expected == ["none"] or not expected:
        return "no_tool"
    if len(expected) > 1:
        return "multi_family"
    if difficulty in {"ambiguous", "false_friend"}:
        return difficulty
    return str(expected[0])


@dataclass
class FailureRecord:
    case_id: str
    split: str
    origin: str
    prompt_category: str
    difficulty: str
    prompt: str
    expected_family_count: int
    expected_families: list[str]
    selected_families: list[str]
    missing_families: list[str]
    irrelevant_selected_families: list[str]
    top_score: float | None
    score_margin: float | None
    none_score: float | None
    fallback_outcome: str
    max_selected_families: int
    cap_caused_miss: bool
    ranking_top3: list[dict[str, float]]


def _fallback_outcome(selected: set[str], expected: set[str], low_confidence: bool) -> str:
    if low_confidence and not selected:
        return "low_confidence_fallback"
    if not expected and not selected:
        return "correct_none"
    if not expected and selected:
        return "false_positive_tools"
    if expected and not selected:
        return "false_negative_empty"
    if expected - selected:
        return "partial_coverage"
    if selected - expected:
        return "false_positive_extra"
    return "exact_match"


def _analyze_router_failures(
    router,
    cases: list[dict],
    thresholds,
    *,
    calibrator=None,
) -> list[FailureRecord]:
    failures: list[FailureRecord] = []
    for case in cases:
        history = [
            AgentMessage(role=item["role"], content=item["content"])
            for item in case.get("history", [])
        ]
        rankings = router.rank(case["prompt"], history)
        selected = select_families_from_rankings(
            rankings,
            thresholds,
            runtime="cloud",
            rule_matches=getattr(router, "last_rule_matches", None),
            calibrator=calibrator,
        )
        expected = set(case["expected_families"])
        if "none" in expected:
            expected.discard("none")

        if expected == selected:
            continue

        none_score = next((item.score for item in rankings if item.key == "none"), None)
        real = [item for item in rankings if item.key != "none"]
        top_score = real[0].score if real else None
        margin = (top_score - none_score) if top_score is not None and none_score is not None else None

        missing = sorted(expected - selected)
        cap_caused = False
        if len(expected) > thresholds.max_selected_families and missing:
            cap_caused = True
        elif len(expected) > 1 and missing:
            ranked_expected = [item.key for item in rankings if item.key in expected]
            if ranked_expected:
                within_cap = set(ranked_expected[: thresholds.max_selected_families])
                cap_caused = bool(expected - within_cap - selected or (expected - within_cap and not (expected & selected)))

        low_confidence = not selected and bool(expected)
        failures.append(
            FailureRecord(
                case_id=case["id"],
                split=case["split"],
                origin=case_origin(case),
                prompt_category=prompt_category(case),
                difficulty=case.get("difficulty", ""),
                prompt=case["prompt"],
                expected_family_count=len(expected),
                expected_families=sorted(expected),
                selected_families=sorted(selected),
                missing_families=missing,
                irrelevant_selected_families=sorted(selected - expected),
                top_score=top_score,
                score_margin=margin,
                none_score=none_score,
                fallback_outcome=_fallback_outcome(selected, expected, low_confidence),
                max_selected_families=thresholds.max_selected_families,
                cap_caused_miss=cap_caused,
                ranking_top3=[
                    {"family": item.key, "score": round(item.score, 4)}
                    for item in rankings[:3]
                ],
            )
        )
    return failures


def _group_failures(failures: list[FailureRecord]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in failures:
        key = (
            f"{item.prompt_category}|expected={item.expected_family_count}|"
            f"fallback={item.fallback_outcome}|cap={item.cap_caused_miss}|origin={item.origin}"
        )
        grouped[key].append(asdict(item))
    return dict(grouped)


def _failure_patterns(failures: list[FailureRecord], limit: int = 10) -> list[dict]:
    patterns: Counter[str] = Counter()
    for item in failures:
        pattern = (
            f"{item.prompt_category}; missing={','.join(item.missing_families) or '-'}; "
            f"irrelevant={','.join(item.irrelevant_selected_families) or '-'}; "
            f"fallback={item.fallback_outcome}; cap={item.cap_caused_miss}; "
            f"origin={item.origin}"
        )
        patterns[pattern] += 1
    return [
        {"pattern": pattern, "count": count}
        for pattern, count in patterns.most_common(limit)
    ]


def _render_markdown(report: dict) -> str:
    lines = [
        "# Capability routing held-out failure analysis",
        "",
        f"- Router: `{report['router']}`",
        f"- Split: `{report['split']}`",
        f"- Total failures: {report['failure_count']}",
        f"- Label corrections applied: {report['label_corrections']}",
        "",
        "## Failure patterns (top 10)",
        "",
    ]
    for item in report["top_failure_patterns"]:
        lines.append(f"- ({item['count']}x) {item['pattern']}")
    lines.extend(["", "## Grouped failures", ""])
    for group_key, items in sorted(report["grouped_failures"].items()):
        lines.append(f"### {group_key} ({len(items)} cases)")
        for record in items[:5]:
            lines.append(
                f"- `{record['case_id']}` ({record['origin']}): "
                f"expected={record['expected_families']} selected={record['selected_families']} "
                f"top={record['top_score']} margin={record['score_margin']}"
            )
        if len(items) > 5:
            lines.append(f"- ... and {len(items) - 5} more")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--router", default="hybrid-minilm-onnx")
    parser.add_argument("--max-selected-families", type=int, default=2)
    args = parser.parse_args()

    cases = load_cases(args.split)
    dev_cases = load_cases("dev")
    thresholds = replace(
        DEFAULT_THRESHOLDS,
        max_selected_families=args.max_selected_families,
    )
    calibrator = None

    if args.router == "hybrid-minilm-onnx":
        router = HybridOnnxRouter(model_key="all-minilm-l6-v2", name="hybrid-minilm-onnx")
        tuned = tune_thresholds(dev_cases, router.rank)
        thresholds = replace(thresholds, **{k: v for k, v in asdict(tuned).items() if k in asdict(DEFAULT_THRESHOLDS)})
        calibrator = fit_calibrator_from_cases(dev_cases, router.rank, thresholds)
    elif args.router == "minilm-onnx":
        router = OnnxBenchmarkRouter(model_key="all-minilm-l6-v2", name="minilm-onnx")
        tuned = tune_thresholds(dev_cases, router.rank)
        thresholds = replace(thresholds, **{k: v for k, v in asdict(tuned).items() if k in asdict(DEFAULT_THRESHOLDS)})
    else:
        routers = {item.name: item for item in build_candidate_routers(include_onnx=True)}
        router = routers[args.router]

    failures = _analyze_router_failures(
        router,
        cases,
        thresholds,
        calibrator=calibrator,
    )
    report = {
        "router": args.router,
        "split": args.split,
        "thresholds": asdict(thresholds),
        "failure_count": len(failures),
        "label_corrections": [
            {
                "case_id": "market-false-friend-1",
                "original": ["weather"],
                "corrected": ["none"],
                "justification": (
                    "false_friend difficulty; prompt uses weather wording without "
                    "forecast intent and matches other false_friend none labels."
                ),
            }
        ],
        "failures": [asdict(item) for item in failures],
        "grouped_failures": _group_failures(failures),
        "top_failure_patterns": _failure_patterns(failures),
        "by_origin": {
            origin: sum(1 for item in failures if item.origin == origin)
            for origin in ("handwritten", "synthetic")
        },
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"error-analysis-{args.split}.json"
    md_path = RESULTS_DIR / f"error-analysis-{args.split}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Failures: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
