from __future__ import annotations

from collections import deque
from types import SimpleNamespace
import unittest

from scripts.idle_runtime_measurements import OwnedProcessSampler, ProcessRoot
from scripts.smoke_desktop_shell import _trace_summary


class _FakeProcess:
    def __init__(
        self,
        pid: int,
        ppid: int,
        created: float,
        cpu: float,
        rss: int | None = 1000,
        private: int | None = 500,
    ) -> None:
        self.info = {"pid": pid, "ppid": ppid, "create_time": created}
        self._created = created
        self._cpu = cpu
        self._rss = rss
        self._private = private

    def create_time(self) -> float:
        return self._created

    def cpu_times(self) -> SimpleNamespace:
        return SimpleNamespace(user=self._cpu, system=0.0)

    def memory_info(self) -> SimpleNamespace:
        if self._rss is None:
            raise PermissionError("working set unavailable")
        return SimpleNamespace(rss=self._rss)

    def memory_full_info(self) -> SimpleNamespace:
        if self._private is None:
            raise PermissionError("private bytes unavailable")
        return SimpleNamespace(private=self._private)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, value: float) -> None:
        self.value += value


def _snapshot_provider(snapshots: list[list[_FakeProcess]]):
    remaining = deque(snapshots)

    def iterate(*, attrs: list[str]) -> list[_FakeProcess]:
        if not remaining:
            raise AssertionError("sampler requested more snapshots than the deterministic fixture supplied")
        return remaining.popleft()

    return iterate


class OwnedProcessSamplerTests(unittest.TestCase):
    def test_sample_includes_only_verified_roots_and_descendants(self) -> None:
        sampler = OwnedProcessSampler(
            [ProcessRoot("shell", 10, 1.0)],
            process_iter=_snapshot_provider([[
                _FakeProcess(10, 1, 1.0, 2.0),
                _FakeProcess(11, 10, 2.0, 3.0),
                _FakeProcess(12, 99, 3.0, 50.0),
            ]]),
        )

        sample = sampler.sample()

        self.assertEqual(sample["root_status"], {"shell": "verified"})
        self.assertEqual(sample["process_count"], 2)
        self.assertEqual(sample["totals"]["cpu_time_seconds"], 5.0)
        self.assertTrue(sample["complete_metrics"]["private_bytes"])
        self.assertNotIn("12", " ".join(sample["processes"]))
        self.assertNotIn("pid", next(iter(sample["processes"].values())))

    def test_root_pid_reuse_is_reported_and_not_sampled(self) -> None:
        sampler = OwnedProcessSampler(
            [ProcessRoot("backend", 21, 1.0)],
            process_iter=_snapshot_provider([[_FakeProcess(21, 4, 3.0, 10.0)]]),
        )

        sample = sampler.sample()

        self.assertEqual(sample["root_status"], {"backend": "pid_reused"})
        self.assertEqual(sample["process_count"], 0)
        self.assertIsNone(sample["totals"]["cpu_time_seconds"])

    def test_partial_metric_access_is_explicit_and_never_reported_as_measured(self) -> None:
        snapshots = [[
            _FakeProcess(30, 1, 1.0, 1.0, private=None),
        ] for _ in range(2)]
        sampler = OwnedProcessSampler(
            [ProcessRoot("backend", 30, 1.0)],
            process_iter=_snapshot_provider(snapshots),
        )
        clock = _Clock()

        measurement = sampler.measure("private-unavailable", 1.0, monotonic=clock.monotonic, sleep=clock.sleep)

        self.assertEqual(measurement["status"], "unverified")
        self.assertIn("private_bytes", measurement["unavailable_metrics"])
        self.assertEqual(measurement["private_peak_bytes"], None)

    def test_process_churn_makes_cpu_interval_unverified(self) -> None:
        snapshots = [
            [_FakeProcess(40, 1, 1.0, 1.0), _FakeProcess(41, 40, 2.0, 2.0)],
            [_FakeProcess(40, 1, 1.0, 2.0)],
        ]
        sampler = OwnedProcessSampler(
            [ProcessRoot("shell", 40, 1.0)],
            process_iter=_snapshot_provider(snapshots),
        )
        clock = _Clock()

        measurement = sampler.measure("process-churn", 1.0, monotonic=clock.monotonic, sleep=clock.sleep)

        self.assertEqual(measurement["status"], "unverified")
        self.assertGreater(measurement["unverified_cpu_intervals"], 0)
        interval = measurement["samples"][1]
        self.assertIsNone(interval["aggregate_cpu_delta_seconds"])

    def test_stable_processes_report_per_process_and_aggregate_cpu_deltas(self) -> None:
        snapshots = [
            [_FakeProcess(50, 1, 1.0, 1.0), _FakeProcess(51, 50, 2.0, 2.0)],
            [_FakeProcess(50, 1, 1.0, 2.0), _FakeProcess(51, 50, 2.0, 4.0)],
            [_FakeProcess(50, 1, 1.0, 3.0), _FakeProcess(51, 50, 2.0, 6.0)],
        ]
        sampler = OwnedProcessSampler(
            [ProcessRoot("shell", 50, 1.0)],
            process_iter=_snapshot_provider(snapshots),
        )
        clock = _Clock()

        measurement = sampler.measure("stable", 2.0, monotonic=clock.monotonic, sleep=clock.sleep)

        self.assertEqual(measurement["status"], "measured")
        self.assertEqual(measurement["aggregate_cpu_delta_seconds"], 6.0)
        self.assertEqual(measurement["sample_count"], 3)
        self.assertEqual([sample["elapsed_seconds"] for sample in measurement["samples"]], [0.0, 1.0, 2.0])
        self.assertEqual(len(measurement["samples"][1]["process_cpu_deltas"]), 2)


class IdleSmokeDiagnosticTests(unittest.TestCase):
    def test_tool_failure_reports_only_safe_error_category(self) -> None:
        message = {
            "response_metadata": {
                "tool_trace": [{"name": "search_apex_docs", "status": "error"}],
                "tool_outputs": [{
                    "name": "search_apex_docs",
                    "status": "error",
                    "output": {
                        "error": "private diagnostic detail",
                        "error_category": "invalid-input",
                    },
                }],
            },
        }

        summary = _trace_summary(message)

        self.assertEqual(summary, [{
            "name": "search_apex_docs",
            "status": "error",
            "error_category": "invalid-input",
        }])
        self.assertNotIn("private diagnostic detail", str(summary))


if __name__ == "__main__":
    unittest.main()
