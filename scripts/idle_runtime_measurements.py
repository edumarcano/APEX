"""Measure resource use for an explicitly owned desktop process tree."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Iterable

import psutil


@dataclass(frozen=True)
class ProcessRoot:
    """A process whose identity was verified by the caller before sampling."""

    label: str
    pid: int
    create_time: float


@dataclass
class _Reading:
    create_time: float | None
    cpu_seconds: float | None
    working_set_bytes: int | None
    private_bytes: int | None


def _reading(process: psutil.Process) -> _Reading:
    try:
        created: float | None = float(process.create_time())
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        created = None
    try:
        cpu = process.cpu_times()
        cpu_seconds: float | None = float(cpu.user + cpu.system)
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        cpu_seconds = None
    try:
        working_set: int | None = int(process.memory_info().rss)
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        working_set = None
    try:
        memory = process.memory_full_info()
        private = getattr(memory, "private", getattr(memory, "uss", None))
        private_bytes: int | None = int(private) if private is not None else None
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        private_bytes = None
    return _Reading(created, cpu_seconds, working_set, private_bytes)


class OwnedProcessSampler:
    """Sample roots and descendants by verified PID ancestry, never by name."""

    def __init__(
        self,
        roots: Iterable[ProcessRoot],
        *,
        process_iter: Callable[..., Iterable[psutil.Process]] = psutil.process_iter,
    ) -> None:
        self.roots = tuple(roots)
        if not self.roots:
            raise ValueError("at least one verified process root is required")
        if len({root.label for root in self.roots}) != len(self.roots):
            raise ValueError("process root labels must be unique")
        self._process_iter = process_iter
        self._root_times = {root.pid: root.create_time for root in self.roots}
        self._sample_number = 0

    def sample(self) -> dict[str, object]:
        self._sample_number += 1
        processes: dict[int, psutil.Process] = {}
        parents: dict[int, int] = {}
        for process in self._process_iter(attrs=["pid", "ppid", "create_time"]):
            try:
                pid = int(process.info["pid"])
                ppid = int(process.info["ppid"])
            except (psutil.Error, OSError, KeyError, TypeError, ValueError):
                continue
            processes[pid] = process
            parents[pid] = ppid

        owners = {root.pid: root.label for root in self.roots}
        root_status: dict[str, str] = {}
        for root in self.roots:
            process = processes.get(root.pid)
            if process is None:
                root_status[root.label] = "exited_or_unavailable"
                owners.pop(root.pid, None)
                continue
            try:
                info_created = process.info.get("create_time")
                actual = float(info_created if info_created is not None else process.create_time())
            except (psutil.Error, OSError, TypeError, ValueError):
                root_status[root.label] = "identity_unavailable"
                owners.pop(root.pid, None)
            else:
                if not math.isclose(actual, self._root_times[root.pid], rel_tol=0.0, abs_tol=0.01):
                    root_status[root.label] = "pid_reused"
                    owners.pop(root.pid, None)
                else:
                    root_status[root.label] = "verified"

        # Resolve each process upward to the nearest verified root. Repeated
        # parent IDs are guarded so malformed process snapshots cannot loop.
        descendants: dict[int, str] = {}
        for pid in processes:
            current = pid
            seen: set[int] = set()
            while current not in seen:
                seen.add(current)
                if current in owners:
                    descendants[pid] = owners[current]
                    break
                parent = parents.get(current)
                if parent is None or parent == current:
                    break
                current = parent

        readings: dict[int, _Reading] = {}
        for pid in descendants:
            process = processes.get(pid)
            if process is not None:
                readings[pid] = _reading(process)
        metrics = {
            "cpu_time_seconds": [item.cpu_seconds for item in readings.values()],
            "working_set_bytes": [item.working_set_bytes for item in readings.values()],
            "private_bytes": [item.private_bytes for item in readings.values()],
        }
        totals: dict[str, int | float | None] = {}
        for name, values in metrics.items():
            available = [value for value in values if value is not None]
            totals[name] = sum(available) if available else None
        process_records: dict[str, dict[str, object]] = {}
        for pid in sorted(readings):
            reading = readings[pid]
            identity = f"{pid}:{reading.create_time:.6f}" if reading.create_time is not None else f"{pid}:unknown:{self._sample_number}"
            process_records[identity] = {
                "owner": descendants[pid],
                "cpu_time_seconds": reading.cpu_seconds,
                "working_set_bytes": reading.working_set_bytes,
                "private_bytes": reading.private_bytes,
            }
        return {
            "process_count": len(descendants),
            "root_status": root_status,
            "totals": totals,
            "complete_metrics": {
                name: len(values) == len(descendants) and len(descendants) > 0 and all(value is not None for value in values)
                for name, values in metrics.items()
            },
            "processes": process_records,
        }

    def measure(
        self,
        phase: str,
        duration_seconds: float,
        *,
        interval_seconds: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, object]:
        if not phase.strip():
            raise ValueError("phase name must not be empty")
        if duration_seconds <= 0 or interval_seconds <= 0:
            raise ValueError("measurement duration and interval must be positive")
        started = monotonic()
        deadline = started + duration_seconds
        samples: list[dict[str, object]] = []
        previous: dict[str, object] | None = None
        identity_labels: dict[str, str] = {}
        unverified_intervals = 0
        while True:
            current = self.sample()
            totals = current["totals"]
            assert isinstance(totals, dict)
            delta_cpu: float | None = None
            delta_complete = False
            if previous is not None:
                prior_processes = previous["processes"]
                current_processes = current["processes"]
                assert isinstance(prior_processes, dict) and isinstance(current_processes, dict)
                shared = set(prior_processes) & set(current_processes)
                identities_match = set(prior_processes) == set(current_processes)
                cpu_deltas: list[float] = []
                process_deltas: list[dict[str, object]] = []
                for identity in sorted(shared):
                    before = prior_processes[identity].get("cpu_time_seconds")
                    now = current_processes[identity].get("cpu_time_seconds")
                    if isinstance(before, (int, float)) and isinstance(now, (int, float)):
                        amount = max(0.0, float(now) - float(before))
                        cpu_deltas.append(amount)
                        label = identity_labels.setdefault(identity, f"process_{len(identity_labels) + 1}")
                        process_deltas.append({"process": label, "cpu_delta_seconds": round(amount, 4)})
                delta_cpu = sum(cpu_deltas) if cpu_deltas and identities_match else None
                delta_complete = identities_match and len(cpu_deltas) == len(shared) and bool(shared)
                if not delta_complete:
                    unverified_intervals += 1
            else:
                process_deltas = []
            labeled_processes = {
                identity_labels.setdefault(identity, f"process_{len(identity_labels) + 1}"): {
                    "owner": value.get("owner"),
                    "cpu_time_seconds": value.get("cpu_time_seconds"),
                    "working_set_bytes": value.get("working_set_bytes"),
                    "private_bytes": value.get("private_bytes"),
                }
                for identity, value in current["processes"].items()
            }
            samples.append({
                **current,
                "elapsed_seconds": round(max(0.0, monotonic() - started), 3),
                "processes": labeled_processes,
                "process_cpu_deltas": process_deltas,
                "aggregate_cpu_delta_seconds": delta_cpu,
                "cpu_delta_complete": delta_complete,
            })
            previous = current
            remaining = duration_seconds - float(samples[-1]["elapsed_seconds"])
            if remaining <= 0:
                break
            sleep(min(interval_seconds, remaining))

        metric_names = ("working_set_bytes", "private_bytes")
        peaks: dict[str, int | None] = {}
        means: dict[str, int | None] = {}
        for metric in metric_names:
            values = [
                int(sample["totals"][metric])
                for sample in samples
                if isinstance(sample["totals"].get(metric), int)
            ]
            peaks[metric] = max(values) if values else None
            means[metric] = round(sum(values) / len(values)) if values else None
        process_counts = [int(sample["process_count"]) for sample in samples]
        aggregate_cpu = [
            float(sample["aggregate_cpu_delta_seconds"])
            for sample in samples
            if isinstance(sample.get("aggregate_cpu_delta_seconds"), (int, float))
        ]
        unavailable = sorted({
            metric
            for metric in ("cpu_time_seconds", *metric_names)
            if any(not sample["complete_metrics"].get(metric, False) for sample in samples)
        })
        roots_verified = all(
            all(status == "verified" for status in sample["root_status"].values())
            for sample in samples
        )
        intervals_complete = unverified_intervals == 0
        status = "measured" if len(samples) >= 2 and not unavailable and roots_verified and intervals_complete else "unverified"
        return {
            "name": phase,
            "status": status,
            "requested_duration_seconds": duration_seconds,
            "actual_duration_seconds": round(max(0.0, monotonic() - started), 3),
            "sample_interval_seconds": interval_seconds,
            "sample_count": len(samples),
            "aggregate_cpu_delta_seconds": round(sum(aggregate_cpu), 4) if aggregate_cpu else None,
            "process_count_min": min(process_counts) if process_counts else None,
            "process_count_max": max(process_counts) if process_counts else None,
            "working_set_peak_bytes": peaks["working_set_bytes"],
            "working_set_mean_bytes": means["working_set_bytes"],
            "private_peak_bytes": peaks["private_bytes"],
            "private_mean_bytes": means["private_bytes"],
            "unavailable_metrics": unavailable,
            "unverified_cpu_intervals": unverified_intervals,
            "samples": samples,
        }
