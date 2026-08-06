"""Regression coverage for recovery benchmark reporting."""

from __future__ import annotations

import unittest

from benchmarks.capability_routing.reporting import (
    classify_case_origin,
    compute_recovery_metrics,
    dedupe_cases_by_prompt,
)


class RecoveryReportingTests(unittest.TestCase):
    def test_origin_counts_each_case_once(self) -> None:
        cases = [
            {
                "id": "sched-direct-1",
                "prompt": "Calendar",
                "history": [],
                "expected_families": ["schedule"],
            },
            {
                "id": "multi-todo-sched-1-240",
                "prompt": "List my todos and tomorrow's meetings.",
                "history": [],
                "expected_families": ["todo", "schedule"],
            },
            {
                "id": "multi-todo-sched-1-245",
                "prompt": "List my todos and tomorrow's meetings.",
                "history": [],
                "expected_families": ["todo", "schedule"],
            },
        ]
        initial = [
            ("sched-direct-1", {"schedule"}, {"schedule"}, 1, 100),
            ("multi-todo-sched-1-240", {"todo", "schedule"}, {"schedule"}, 1, 100),
            ("multi-todo-sched-1-245", {"todo", "schedule"}, {"schedule"}, 1, 100),
        ]
        final = [
            ("sched-direct-1", {"schedule"}, {"schedule"}, 1, 100),
            ("multi-todo-sched-1-240", {"todo", "schedule"}, {"todo", "schedule"}, 2, 150),
            ("multi-todo-sched-1-245", {"todo", "schedule"}, {"todo", "schedule"}, 2, 150),
        ]
        metrics = compute_recovery_metrics(
            config_name="test",
            split="test",
            cases=cases,
            initial_predictions=initial,
            final_predictions=final,
            search_invoked={
                "sched-direct-1": False,
                "multi-todo-sched-1-240": True,
                "multi-todo-sched-1-245": True,
            },
            search_turns={
                "sched-direct-1": 0,
                "multi-todo-sched-1-240": 1,
                "multi-todo-sched-1-245": 1,
            },
            expansion_turns={
                "sched-direct-1": 0,
                "multi-todo-sched-1-240": 1,
                "multi-todo-sched-1-245": 1,
            },
            recovered_tool_turns={
                "sched-direct-1": 0,
                "multi-todo-sched-1-240": 0,
                "multi-todo-sched-1-245": 0,
            },
        )
        self.assertEqual(metrics.total_cases, 3)
        self.assertEqual(metrics.unique_prompt_cases, 2)
        self.assertAlmostEqual(metrics.initial_complete_coverage_rate, 1 / 3)
        self.assertAlmostEqual(metrics.unique_initial_complete_coverage_rate, 0.5)
        self.assertAlmostEqual(metrics.final_complete_coverage_rate, 1.0)
        self.assertEqual(
            metrics.by_origin["handwritten"]["case_count"],
            2,
        )
        self.assertEqual(
            metrics.by_origin_unique["handwritten"]["case_count"],
            2,
        )

    def test_classify_case_origin_distinguishes_duplicate_and_generated(self) -> None:
        base = {
            "prompt": "List my todos and tomorrow's meetings.",
            "history": [],
        }
        seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        first = classify_case_origin(
            {"id": "multi-todo-sched-1-240", **base},
            seen_prompt_keys=seen,
        )
        duplicate = classify_case_origin(
            {"id": "multi-todo-sched-1-245", **base},
            seen_prompt_keys=seen,
        )
        generated = classify_case_origin(
            {
                "id": "schedule-auto-1",
                "prompt": "Please help with schedule information request 1.",
                "history": [],
                "difficulty": "paraphrased",
            }
        )
        self.assertEqual(first, "handwritten")
        self.assertEqual(duplicate, "exact_duplicate")
        self.assertEqual(generated, "generated_paraphrase")
        self.assertEqual(len(dedupe_cases_by_prompt([base | {"id": "a"}, base | {"id": "b"}])), 1)


if __name__ == "__main__":
    unittest.main()
