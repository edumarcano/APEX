"""Run a small, local-only APEX model comparison.

This is intentionally a developer utility rather than a persistent benchmark
service.  It uses the normal local runtime coordinator and Agent loop, but
keeps benchmark cases, synthetic tool fixtures, and result rendering local to
this command.
"""

from __future__ import annotations

import argparse
import ctypes
import copy
import json
import logging
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from jsonschema import Draft202012Validator

from core.agent.capabilities import (
    CapabilityDescriptor,
    CapabilityError,
    CapabilityErrorCategory,
    get_capability_descriptor,
)
from core.agent.catalog import (
    AGENT_SPECS,
    build_concrete_agent,
    compose_agent_system_instruction,
    known_local_model_refs,
    local_agent_keys,
    local_reasoning_modes_for_agent,
    resolve_selected_model_profile,
)
from core.agent.model_catalog import DEFAULT_LYNX_MODEL, get_model_profile
from core.agent.local_runtime.contract import (
    LocalModelRef,
    LocalModelProfile,
    LocalRuntimeSnapshot,
)
from core.agent.local_runtime.coordinator import (
    check_resource_gate,
    end_local_execution,
    get_active_local_model,
    get_provider_snapshot,
    switch_local_model,
    try_begin_local_execution,
    unload_active_local_model,
)
from core.agent.local_runtime.registry import (
    get_local_runtime_backend,
    iter_local_runtime_backends,
)
from core.agent.loop import run_agent_loop
from core.agent.prompting import build_tool_access_instruction
from core.agent.providers.llama_cpp import LlamaCppProvider
from core.agent.providers.llama_cpp_models import (
    LLAMA_CPP_RUNTIME_CONFIGS,
    build_llama_cpp_profile,
)
from core.agent.providers.ollama import OllamaProvider
from core.agent.providers.ollama_models import OLLAMA_RUNTIME_CONFIGS
from core.agent.tool_schemas import (
    descriptor_to_openai_schema,
    estimate_json_tokens,
    project_descriptor_for_agent,
)
from core.agent.types import (
    AgentQueryRequest,
    AgentQueryResponse,
    ToolSelectionDiagnostics,
)
from core.config import LOCAL_AGENT_SYSTEM_PROMPT


_LOGGER = logging.getLogger(__name__)
_CASES_PATH = ROOT / "benchmarks" / "cases.json"
_DEFAULT_REPETITIONS = 3
_COOLDOWN_SECONDS = 1.0
_RESOURCE_RECOVERY_TIMEOUT_SECONDS = 30.0
_RESOURCE_RECOVERY_POLL_SECONDS = 0.5
_RESOURCE_RECOVERY_STABLE_SAMPLES = 2
_RESOURCE_SAMPLE_INTERVAL_SECONDS = 0.1
_RESIDENT_STATES = frozenset({"loading", "loaded"})
_APEX_LIVE_URL = "http://127.0.0.1:8000/api/v1/health/live"
_BENCHMARK_LOCK_PATH = ROOT / "benchmarks" / ".benchmark.lock"


class BenchmarkFailure(RuntimeError):
    """A configuration failed without making the runtime unsafe to continue."""


class ResourceBlocked(BenchmarkFailure):
    """A configuration was not run because host resources did not recover."""


class BenchmarkAbort(RuntimeError):
    """A strict lifecycle invariant failed and the benchmark must stop."""

    def __init__(
        self,
        message: str,
        *,
        partial_run: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.partial_run = partial_run


@dataclass(frozen=True, slots=True)
class BenchmarkConfiguration:
    """One model/context/reasoning configuration to compare."""

    agent: str
    provider: str
    model: str
    runtime_alias: str
    context: int
    reasoning: str
    profile: LocalModelProfile
    agent_key: str | None
    tool_projection_agent: str

    @property
    def runtime_ref(self) -> LocalModelRef:
        return LocalModelRef(
            provider=self.provider,  # type: ignore[arg-type]
            model=self.runtime_alias,
        )


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """Best-effort host and provider-process memory observation."""

    total_ram_bytes: int | None = None
    available_ram_bytes: int | None = None
    committed_bytes: int | None = None
    commit_limit_bytes: int | None = None
    commit_percentage: float | None = None
    process_working_set_bytes: int | None = None
    process_private_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class FixtureInvocation:
    """One synthetic dispatcher call and its schema-validation outcome."""

    name: str
    arguments: dict[str, Any]
    schema_valid: bool
    expected_error: bool = False


def _windows_commit_snapshot() -> tuple[int | None, int | None, float | None]:
    """Return Windows commit charge, limit, and percentage when available."""
    if os.name != "nt":
        return None, None, None

    class _PerformanceInformation(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("CommitTotal", ctypes.c_size_t),
            ("CommitLimit", ctypes.c_size_t),
            ("CommitPeak", ctypes.c_size_t),
            ("PhysicalTotal", ctypes.c_size_t),
            ("PhysicalAvailable", ctypes.c_size_t),
            ("SystemCache", ctypes.c_size_t),
            ("KernelTotal", ctypes.c_size_t),
            ("KernelPaged", ctypes.c_size_t),
            ("KernelNonpaged", ctypes.c_size_t),
            ("PageSize", ctypes.c_size_t),
            ("HandleCount", ctypes.c_ulong),
            ("ProcessCount", ctypes.c_ulong),
            ("ThreadCount", ctypes.c_ulong),
        ]

    try:
        psapi = ctypes.WinDLL("psapi")
        info = _PerformanceInformation()
        info.cb = ctypes.sizeof(info)
        get_performance_info = psapi.GetPerformanceInfo
        get_performance_info.argtypes = [
            ctypes.POINTER(_PerformanceInformation),
            ctypes.c_ulong,
        ]
        get_performance_info.restype = ctypes.c_bool
        if not get_performance_info(ctypes.byref(info), ctypes.sizeof(info)):
            return None, None, None
        page_size = int(info.PageSize)
        committed = int(info.CommitTotal) * page_size
        limit = int(info.CommitLimit) * page_size
        percentage = (committed / limit * 100.0) if limit else None
        return committed, limit, percentage
    except (AttributeError, OSError, TypeError, ValueError):
        return None, None, None


def _provider_process_memory(
    provider: str | None,
) -> tuple[int | None, int | None]:
    """Sum working-set and private memory for the selected provider process."""
    if provider is None:
        return None, None
    fragments = {
        "ollama": ("ollama",),
        "llama_cpp": ("llama",),
    }.get(provider)
    if fragments is None:
        return None, None

    working_set = 0
    private_bytes = 0
    working_set_found = False
    private_found = False
    try:
        processes: Iterable[psutil.Process] = psutil.process_iter(["name", "exe"])
        for process in processes:
            try:
                info = process.info
                process_name = str(info.get("name") or "").lower()
                executable = Path(str(info.get("exe") or "")).name.lower()
                if not any(
                    fragment in process_name or fragment in executable
                    for fragment in fragments
                ):
                    continue

                memory = process.memory_info()
                rss = getattr(memory, "rss", None)
                if isinstance(rss, int) and rss >= 0:
                    working_set += rss
                    working_set_found = True

                private = getattr(memory, "private", None)
                if not isinstance(private, int):
                    try:
                        full_memory = process.memory_full_info()
                        private = getattr(full_memory, "uss", None)
                    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                        private = None
                if isinstance(private, int) and private >= 0:
                    private_bytes += private
                    private_found = True
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
    except (psutil.Error, OSError):
        return None, None

    return (
        working_set if working_set_found else None,
        private_bytes if private_found else None,
    )


def capture_memory(provider: str | None) -> MemorySnapshot:
    """Capture memory values without making missing platform data fatal."""
    try:
        virtual = psutil.virtual_memory()
        total_ram = int(virtual.total)
        available_ram = int(virtual.available)
    except (AttributeError, OSError, psutil.Error, TypeError, ValueError):
        total_ram = None
        available_ram = None

    committed, commit_limit, commit_percentage = _windows_commit_snapshot()
    process_working_set, process_private = _provider_process_memory(provider)
    return MemorySnapshot(
        total_ram_bytes=total_ram,
        available_ram_bytes=available_ram,
        committed_bytes=committed,
        commit_limit_bytes=commit_limit,
        commit_percentage=commit_percentage,
        process_working_set_bytes=process_working_set,
        process_private_bytes=process_private,
    )


class ResourceSampler:
    """Sample host memory during one load-and-query configuration."""

    def __init__(
        self,
        provider: str,
        *,
        interval_seconds: float = _RESOURCE_SAMPLE_INTERVAL_SECONDS,
        capture: Callable[[str | None], MemorySnapshot] = capture_memory,
    ) -> None:
        self._provider = provider
        self._interval_seconds = interval_seconds
        self._capture = capture
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[MemorySnapshot] = []
        self._lock = threading.Lock()

    def _record(self, snapshot: MemorySnapshot) -> None:
        with self._lock:
            self._samples.append(snapshot)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            self._record(self._capture(self._provider))

    def start(self) -> None:
        """Capture immediately and then begin periodic sampling."""
        self._record(self._capture(self._provider))
        self._thread = threading.Thread(
            target=self._run,
            name="apex-benchmark-memory",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> MemorySnapshot:
        """Stop sampling and include one final observation."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds * 5))
        final = self._capture(self._provider)
        self._record(final)
        return final

    @property
    def samples(self) -> tuple[MemorySnapshot, ...]:
        with self._lock:
            return tuple(self._samples)


def _minimum(values: Iterable[int | None]) -> int | None:
    resolved = [value for value in values if isinstance(value, int)]
    return min(resolved) if resolved else None


def _maximum(values: Iterable[int | None]) -> int | None:
    resolved = [value for value in values if isinstance(value, int)]
    return max(resolved) if resolved else None


def _maximum_float(values: Iterable[float | None]) -> float | None:
    resolved = [value for value in values if isinstance(value, (int, float))]
    return max(resolved) if resolved else None


def build_resource_record(
    baseline: MemorySnapshot,
    final: MemorySnapshot,
    samples: Sequence[MemorySnapshot],
) -> dict[str, Any]:
    """Serialize resource observations, retaining nulls for unavailable data."""
    observations = (baseline, *samples, final)
    minimum_available = _minimum(
        snapshot.available_ram_bytes for snapshot in observations
    )
    peak_committed = _maximum(snapshot.committed_bytes for snapshot in observations)
    peak_commit_percentage = _maximum_float(
        snapshot.commit_percentage for snapshot in observations
    )
    peak_working_set = _maximum(
        snapshot.process_working_set_bytes for snapshot in observations
    )
    peak_private = _maximum(
        snapshot.process_private_bytes for snapshot in observations
    )

    committed_delta = None
    if peak_committed is not None and baseline.committed_bytes is not None:
        committed_delta = peak_committed - baseline.committed_bytes

    return {
        "total_ram_bytes": baseline.total_ram_bytes or final.total_ram_bytes,
        "available_ram_before_bytes": baseline.available_ram_bytes,
        "minimum_available_ram_bytes": minimum_available,
        "available_ram_final_bytes": final.available_ram_bytes,
        "committed_memory_before_bytes": baseline.committed_bytes,
        "peak_committed_memory_bytes": peak_committed,
        "peak_committed_delta_bytes": committed_delta,
        "commit_limit_bytes": baseline.commit_limit_bytes or final.commit_limit_bytes,
        "commit_percentage_before": baseline.commit_percentage,
        "peak_commit_percentage": peak_commit_percentage,
        "provider_process_working_set_before_bytes": (
            baseline.process_working_set_bytes
        ),
        "provider_process_working_set_peak_bytes": peak_working_set,
        "provider_process_private_before_bytes": baseline.process_private_bytes,
        "provider_process_private_peak_bytes": peak_private,
        "sample_count": len(observations),
    }


def load_benchmark_cases(path: Path = _CASES_PATH) -> dict[str, list[dict[str, Any]]]:
    """Load and minimally validate the versioned local case file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load benchmark cases from {path.name}.") from exc

    if not isinstance(payload, dict):
        raise ValueError("Benchmark cases must be a JSON object.")
    performance = payload.get("performance")
    tool_cases = payload.get("tool_cases")
    if not isinstance(performance, list) or not isinstance(tool_cases, list):
        raise ValueError("Benchmark cases must contain performance and tool_cases lists.")

    for case in performance:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("Each performance case needs a string id.")
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            raise ValueError(f"Performance case {case.get('id')!r} has no prompt.")

    for case in tool_cases:
        if not isinstance(case, dict):
            raise ValueError("Each tool case must be a JSON object.")
        for key in ("id", "category", "prompt", "tools", "expected_tools"):
            if key not in case:
                raise ValueError(f"Tool case is missing {key!r}.")
        if not all(isinstance(value, str) for value in (case["id"], case["category"])):
            raise ValueError("Tool case ids and categories must be strings.")
        if not isinstance(case["prompt"], str) or not case["prompt"].strip():
            raise ValueError(f"Tool case {case['id']!r} has no prompt.")
        if not isinstance(case["tools"], list) or not all(
            isinstance(name, str) for name in case["tools"]
        ):
            raise ValueError(f"Tool case {case['id']!r} has invalid tools.")
        if not isinstance(case["expected_tools"], list) or not all(
            isinstance(name, str) for name in case["expected_tools"]
        ):
            raise ValueError(f"Tool case {case['id']!r} has invalid expected_tools.")
        if not set(case["expected_tools"]).issubset(set(case["tools"])):
            raise ValueError(
                f"Tool case {case['id']!r} expects a tool that it does not attach."
            )
        for key in ("required_answer_facts", "fixture_errors"):
            if key in case and key == "required_answer_facts":
                if not isinstance(case[key], list) or not all(
                    isinstance(fact, str) for fact in case[key]
                ):
                    raise ValueError(
                        f"Tool case {case['id']!r} has invalid required_answer_facts."
                    )
            elif key in case and key == "fixture_errors":
                if not isinstance(case[key], dict) or not all(
                    isinstance(name, str) and isinstance(message, str)
                    for name, message in case[key].items()
                ):
                    raise ValueError(
                        f"Tool case {case['id']!r} has invalid fixture_errors."
                    )

    return {"performance": performance, "tool_cases": tool_cases}


def _context_values(
    agent_key: str,
    *,
    context: int | None,
    all_contexts: bool,
) -> tuple[int, ...]:
    model_profile = resolve_selected_model_profile(agent_key)
    model_id = model_profile.model_id
    if model_profile.provider == "llama_cpp":
        runtime = LLAMA_CPP_RUNTIME_CONFIGS[model_id]
        if all_contexts:
            return runtime.allowed_context_windows
        if context is not None:
            if context not in runtime.allowed_context_windows:
                raise ValueError(
                    f"Unsupported context {context} for model {model_id!r}; "
                    f"choose from {runtime.allowed_context_windows}."
                )
            return (context,)
        return (runtime.default_context_window,)

    runtime = OLLAMA_RUNTIME_CONFIGS[model_id]
    if all_contexts:
        return (runtime.context_window,)
    if context is not None and context != runtime.context_window:
        raise ValueError(
            f"Ollama model {model_id!r} only supports context "
            f"{runtime.context_window}."
        )
    return (runtime.context_window,)


def _normalize_reasoning_modes(reasoning_modes: Sequence[str] | None) -> tuple[str, ...]:
    modes = tuple(reasoning_modes or ("none",))
    normalized: list[str] = []
    for mode in modes:
        candidate = mode.strip().lower()
        if candidate not in {"none", "focused"}:
            raise ValueError("Reasoning must be one of: none, focused.")
        if candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


def _build_registered_configuration(
    agent_key: str,
    *,
    context: int,
    reasoning: str,
) -> BenchmarkConfiguration:
    supported = local_reasoning_modes_for_agent(agent_key)
    if reasoning not in supported:
        raise ValueError(
            f"Agent {agent_key!r} does not support reasoning mode {reasoning!r}."
        )
    profile = build_concrete_agent(
        agent_key,
        native_effort=None,
        local_context_window=context,
        local_reasoning_mode=reasoning,  # type: ignore[arg-type]
    )
    return BenchmarkConfiguration(
        agent=agent_key,
        provider=profile.provider,
        model=profile.api_model,
        runtime_alias=profile.runtime_model_id,
        context=profile.context_window,
        reasoning=profile.reasoning_mode,
        profile=profile,
        agent_key=agent_key,
        tool_projection_agent=agent_key,
    )


def _build_candidate_configuration(
    model: str,
    runtime_alias: str,
    *,
    context: int | None,
    reasoning: str,
) -> BenchmarkConfiguration:
    """Build an in-memory llama.cpp profile without changing the Agent catalog."""
    resolved_context = context or LLAMA_CPP_RUNTIME_CONFIGS[
        DEFAULT_LYNX_MODEL
    ].default_context_window
    supported = local_reasoning_modes_for_agent("lynx")
    if reasoning not in supported:
        raise ValueError(
            f"llama.cpp candidate does not support reasoning mode {reasoning!r}."
        )
    model_name = Path(model.strip()).name
    if not model_name:
        raise ValueError("The llama.cpp candidate model must not be empty.")
    alias = runtime_alias.strip()
    if not alias:
        raise ValueError("The llama.cpp candidate requires a runtime alias.")

    lynx_profile = get_model_profile(DEFAULT_LYNX_MODEL)
    assert lynx_profile is not None
    profile = build_llama_cpp_profile(
        DEFAULT_LYNX_MODEL,
        display_name="Benchmark candidate",
        agent_version="benchmark-v0",
        api_model=model_name,
        tier=lynx_profile.tier,  # type: ignore[arg-type]
        stability=lynx_profile.stability,
        max_tool_turns=lynx_profile.max_tool_turns,
        max_tool_calls=lynx_profile.max_tool_calls,
        system_instruction=LOCAL_AGENT_SYSTEM_PROMPT,
        context_window=resolved_context,
        reasoning_mode=reasoning,  # type: ignore[arg-type]
    ).model_copy(update={"runtime_model_id": alias})
    return BenchmarkConfiguration(
        agent="candidate",
        provider="llama_cpp",
        model=model_name,
        runtime_alias=alias,
        context=profile.context_window,
        reasoning=profile.reasoning_mode,
        profile=profile,
        agent_key=None,
        tool_projection_agent="lynx",
    )


def build_configurations(
    *,
    agents: Sequence[str] | None,
    context: int | None,
    all_contexts: bool,
    reasoning_modes: Sequence[str] | None,
    candidate_model: str | None = None,
    runtime_alias: str | None = None,
) -> tuple[BenchmarkConfiguration, ...]:
    """Resolve registered Agents and at most one ad-hoc candidate."""
    if candidate_model and all_contexts:
        raise ValueError(
            "--all-contexts cannot be used with a one-off candidate because its "
            "runtime alias represents one context."
        )
    if candidate_model and not runtime_alias:
        raise ValueError("--runtime-alias is required with --llama-candidate.")
    if runtime_alias and not candidate_model:
        raise ValueError("--runtime-alias is only valid with --llama-candidate.")

    modes = _normalize_reasoning_modes(reasoning_modes)
    selected_agents: list[str]
    if agents is None:
        if candidate_model:
            selected_agents = []
        else:
            lynx_profile = resolve_selected_model_profile("lynx")
            if get_local_runtime_backend(lynx_profile.provider).enabled:
                selected_agents = ["lynx"]
            else:
                selected_agents = []
    else:
        selected_agents = []
        for raw_key in agents:
            key = raw_key.strip().lower()
            if key not in selected_agents:
                selected_agents.append(key)

    configurations: list[BenchmarkConfiguration] = []
    for agent_key in selected_agents:
        spec = AGENT_SPECS.get(agent_key)
        if spec is None or spec.runtime != "local":
            raise ValueError(
                f"{agent_key!r} is not a registered local Agent. "
                "Use a local Ollama or llama.cpp Agent."
            )
        for context_value in _context_values(
            agent_key,
            context=context,
            all_contexts=all_contexts,
        ):
            for reasoning in modes:
                configurations.append(
                    _build_registered_configuration(
                        agent_key,
                        context=context_value,
                        reasoning=reasoning,
                    )
                )

    if candidate_model:
        for reasoning in modes:
            configurations.append(
                _build_candidate_configuration(
                    candidate_model,
                    runtime_alias or "",
                    context=context,
                    reasoning=reasoning,
                )
            )

    if not configurations:
        raise ValueError(
            "Select at least one local Agent with --agents or provide "
            "--llama-candidate."
        )
    return tuple(configurations)


def requires_model_reload(
    previous_ref: LocalModelRef | None,
    current_ref: LocalModelRef,
) -> bool:
    """Return whether a provider load is needed for the runtime alias change."""
    return previous_ref != current_ref


def _resident_refs(
    snapshots: Mapping[str, LocalRuntimeSnapshot],
    *,
    allowed_refs: Iterable[LocalModelRef] | None = None,
) -> frozenset[LocalModelRef]:
    allowed = frozenset(allowed_refs or ())
    refs: set[LocalModelRef] = set()
    for provider, snapshot in snapshots.items():
        for loaded in snapshot.get("loaded_models", []):
            if loaded.get("state") not in _RESIDENT_STATES:
                continue
            row_refs: set[LocalModelRef] = set()
            for model_value in (loaded.get("model"), loaded.get("name")):
                if isinstance(model_value, str) and model_value.strip():
                    row_refs.add(
                        LocalModelRef(
                            provider=provider,  # type: ignore[arg-type]
                            model=model_value.strip(),
                        )
                    )
            matched = row_refs & allowed
            refs.update(matched or row_refs)
    return frozenset(refs)


def inspect_runtime_residents(
    allowed_refs: Iterable[LocalModelRef],
    *,
    required_provider: str | None = None,
) -> tuple[dict[str, LocalRuntimeSnapshot], frozenset[LocalModelRef]]:
    """Probe local backends and reject unrecognized resident models."""
    allowed = frozenset(allowed_refs)
    snapshots: dict[str, LocalRuntimeSnapshot] = {}
    for backend in iter_local_runtime_backends(enabled_only=False):
        enabled = bool(backend.enabled)
        snapshot = get_provider_snapshot(backend.provider, force_refresh=True)
        if not snapshot["reachable"]:
            if enabled or backend.provider == required_provider:
                raise BenchmarkAbort(
                    f"Cannot verify {backend.provider} runtime state before "
                    "continuing the benchmark."
                )
            continue
        snapshots[backend.provider] = snapshot

    residents = _resident_refs(snapshots, allowed_refs=allowed)
    unknown = residents - allowed
    if unknown:
        formatted = ", ".join(
            f"{ref.provider}/{ref.model}"
            for ref in sorted(unknown, key=lambda item: (item.provider, item.model))
        )
        raise BenchmarkAbort(
            "Unknown externally loaded local model detected; refusing to "
            f"unload it or continue: {formatted}."
        )
    return snapshots, residents


def _selection_diagnostics(
    descriptors: Sequence[CapabilityDescriptor],
) -> ToolSelectionDiagnostics:
    names = [descriptor.name for descriptor in descriptors]
    return ToolSelectionDiagnostics(
        requested_tool_names=names,
        offered_tool_names=names,
        selected_schema_tokens=(
            estimate_json_tokens(
                [descriptor_to_openai_schema(descriptor) for descriptor in descriptors]
            )
            if descriptors
            else 0
        ),
    )


class FixtureDispatcher:
    """Dispatch benchmark calls to fixed JSON fixtures, never live connectors."""

    def __init__(
        self,
        case: Mapping[str, Any],
        descriptors: Sequence[CapabilityDescriptor],
    ) -> None:
        self.case = case
        self.descriptors = {descriptor.name: descriptor for descriptor in descriptors}
        self._validators = {
            name: Draft202012Validator(descriptor.input_schema)
            for name, descriptor in self.descriptors.items()
        }
        self.invocations: list[FixtureInvocation] = []

    def __call__(self, name: str, arguments: dict[str, Any]) -> Any:
        descriptor = self.descriptors.get(name)
        if descriptor is None:
            raise CapabilityError(
                CapabilityErrorCategory.UNAVAILABLE,
                "The benchmark fixture does not expose this capability.",
            )

        schema_valid = not any(
            self._validators[name].iter_errors(arguments)
        )
        self.invocations.append(
            FixtureInvocation(
                name=name,
                arguments=copy.deepcopy(arguments),
                schema_valid=schema_valid,
            )
        )
        if not schema_valid:
            raise CapabilityError(
                CapabilityErrorCategory.INVALID_INPUT,
                "The benchmark fixture rejected invalid tool arguments.",
            )

        fixture_errors = self.case.get("fixture_errors", {})
        if isinstance(fixture_errors, dict) and name in fixture_errors:
            self.invocations[-1] = FixtureInvocation(
                name=name,
                arguments=copy.deepcopy(arguments),
                schema_valid=True,
                expected_error=True,
            )
            raise CapabilityError(
                CapabilityErrorCategory.UPSTREAM_FAILURE,
                "Synthetic benchmark fixture failure.",
            )

        fixtures = self.case.get("fixtures", {})
        if not isinstance(fixtures, dict) or name not in fixtures:
            raise CapabilityError(
                CapabilityErrorCategory.UNAVAILABLE,
                "Synthetic benchmark fixture is missing.",
            )
        return copy.deepcopy(fixtures[name])


def _provider_for_profile(profile: LocalModelProfile) -> Any:
    if profile.provider == "ollama":
        return OllamaProvider()
    if profile.provider == "llama_cpp":
        return LlamaCppProvider()
    raise ValueError(f"Unsupported local benchmark provider: {profile.provider!r}")


def _response_metrics(
    response: AgentQueryResponse,
    elapsed_seconds: float,
) -> dict[str, Any]:
    timing = response.timing
    total_seconds = (
        timing.total_ms / 1000.0
        if timing is not None and timing.total_ms is not None
        else elapsed_seconds
    )
    provider_seconds = (
        timing.provider_ms / 1000.0
        if timing is not None and timing.provider_ms is not None
        else None
    )
    usage = response.usage
    prompt_tokens = usage.input_tokens if usage is not None else None
    completion_tokens = usage.output_tokens if usage is not None else None
    throughput_seconds = provider_seconds or total_seconds
    prompt_tps = (
        prompt_tokens / throughput_seconds
        if prompt_tokens is not None and throughput_seconds > 0
        else None
    )
    generation_tps = (
        completion_tokens / throughput_seconds
        if completion_tokens is not None and throughput_seconds > 0
        else None
    )
    return {
        "latency_seconds": round(max(0.0, total_seconds), 4),
        "provider_seconds": (
            round(max(0.0, provider_seconds), 4)
            if provider_seconds is not None
            else None
        ),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": usage.total_tokens if usage is not None else None,
        "effective_input_tokens_per_second": (
            round(prompt_tps, 3) if prompt_tps is not None else None
        ),
        "effective_output_tokens_per_second": (
            round(generation_tps, 3) if generation_tps is not None else None
        ),
        "success": response.error is None and bool(response.answer.strip()),
        "error": response.error,
    }


def _median_metric(
    records: Sequence[Mapping[str, Any]],
    key: str,
) -> float | None:
    values = [
        float(record[key])
        for record in records
        if isinstance(record.get(key), (int, float))
    ]
    return round(statistics.median(values), 4) if values else None


def _average_metric(
    records: Sequence[Mapping[str, Any]],
    key: str,
) -> float | None:
    values = [
        float(record[key])
        for record in records
        if isinstance(record.get(key), (int, float))
    ]
    return round(statistics.mean(values), 4) if values else None


def _rate(numerator: int, denominator: int, *, empty: float = 0.0) -> float:
    if denominator <= 0:
        return empty
    return round(numerator / denominator, 4)


def _safe_tool_trace(response: AgentQueryResponse) -> list[dict[str, Any]]:
    return [
        {
            "name": entry.get("name"),
            "status": entry.get("status"),
            "origin": entry.get("origin", "apex"),
            "duration_ms": entry.get("duration_ms"),
        }
        for entry in response.tool_trace
        if isinstance(entry, dict)
    ]


def score_tool_case(
    case: Mapping[str, Any],
    response: AgentQueryResponse,
    dispatcher: FixtureDispatcher,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Score one deterministic case without an LLM judge."""
    trace = _safe_tool_trace(response)
    expected_tools = {
        value for value in case.get("expected_tools", []) if isinstance(value, str)
    }
    attempted_tools = {
        value for value in (entry.get("name") for entry in trace)
        if isinstance(value, str)
    }
    successful_tools = {
        entry["name"]
        for entry in trace
        if entry.get("status") == "ok" and isinstance(entry.get("name"), str)
    }
    unexpected_tools = [
        entry["name"]
        for entry in trace
        if isinstance(entry.get("name"), str)
        and entry["name"] not in expected_tools
    ]

    invocation_index = 0
    valid_call_count = 0
    total_call_count = len(trace)
    for entry in trace:
        name = entry.get("name")
        if name in dispatcher.descriptors:
            if invocation_index < len(dispatcher.invocations):
                invocation = dispatcher.invocations[invocation_index]
                invocation_index += 1
                if invocation.name == name and invocation.schema_valid:
                    valid_call_count += 1
                continue
        # A tool outside the attached schemas cannot be schema-valid here.
        invocation_index += 0

    schema_validity = valid_call_count == total_call_count
    required_selection_correct = expected_tools.issubset(attempted_tools)
    expected_error_tools = {
        invocation.name
        for invocation in dispatcher.invocations
        if invocation.expected_error
    }
    completed_required_tools = expected_tools.issubset(
        successful_tools | (expected_error_tools & set(case.get("fixture_errors", {})))
    )
    answer = response.answer.strip().lower()
    final_answer_produced = response.error is None and bool(answer)
    facts = [
        fact.strip().lower()
        for fact in case.get("required_answer_facts", [])
        if isinstance(fact, str) and fact.strip()
    ]
    answer_facts_present = all(fact in answer for fact in facts)
    task_success = (
        required_selection_correct
        and not unexpected_tools
        and schema_validity
        and completed_required_tools
        and final_answer_produced
        and answer_facts_present
    )

    result = {
        "case_id": case.get("id"),
        "category": case.get("category"),
        **_response_metrics(response, elapsed_seconds),
        "required_tools": sorted(expected_tools),
        "attempted_tools": sorted(attempted_tools),
        "unexpected_tools": unexpected_tools,
        "required_tools_selected": required_selection_correct,
        "schema_valid": schema_validity,
        "completed_required_tools": completed_required_tools,
        "final_answer_produced": final_answer_produced,
        "required_answer_facts_present": answer_facts_present,
        "task_success": task_success,
        "tool_call_count": total_call_count,
        "schema_valid_call_count": valid_call_count,
        "tool_trace": trace,
    }
    if case.get("fixture_errors"):
        result["expected_fixture_error"] = True
    return result


def aggregate_tool_results(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calculate transparent rates from individual case records."""
    total = len(records)
    multi_tool = [record for record in records if record.get("category") == "multi_tool"]
    task_successes = sum(bool(record.get("task_success")) for record in records)
    selection_successes = sum(
        bool(record.get("required_tools_selected")) for record in records
    )
    schema_successes = sum(bool(record.get("schema_valid")) for record in records)
    completed = sum(bool(record.get("completed_required_tools")) for record in records)
    multi_completed = sum(
        bool(record.get("completed_required_tools")) for record in multi_tool
    )
    unexpected_calls = sum(
        len(record.get("unexpected_tools", []))
        for record in records
        if isinstance(record.get("unexpected_tools"), list)
    )
    total_calls = sum(
        int(record.get("tool_call_count", 0))
        for record in records
        if isinstance(record.get("tool_call_count"), int)
    )
    return {
        "cases": total,
        "task_success_rate": _rate(task_successes, total),
        "tool_selection_rate": _rate(selection_successes, total),
        "schema_validity_rate": _rate(schema_successes, total, empty=1.0),
        "multi_tool_completion_rate": _rate(
            multi_completed,
            len(multi_tool),
            empty=1.0,
        ),
        "unnecessary_tool_rate": _rate(
            unexpected_calls,
            total_calls,
            empty=0.0,
        ),
        "failure_rate": _rate(total - task_successes, total),
        "completed_required_tool_cases": completed,
        "unexpected_tool_calls": unexpected_calls,
        "total_tool_calls": total_calls,
    }


class BenchmarkRunner:
    """Own the local lifecycle for one sequential benchmark command."""

    def __init__(
        self,
        configurations: Sequence[BenchmarkConfiguration],
        cases: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        repetitions: int = _DEFAULT_REPETITIONS,
        cooldown_seconds: float = _COOLDOWN_SECONDS,
        resource_recovery_timeout_seconds: float = _RESOURCE_RECOVERY_TIMEOUT_SECONDS,
        resource_recovery_poll_seconds: float = _RESOURCE_RECOVERY_POLL_SECONDS,
        resource_recovery_stable_samples: int = _RESOURCE_RECOVERY_STABLE_SAMPLES,
        sleep: Callable[[float], None] = time.sleep,
        capture: Callable[[str | None], MemorySnapshot] = capture_memory,
        resource_sampler_factory: Callable[..., ResourceSampler] = ResourceSampler,
    ) -> None:
        if repetitions < 1:
            raise ValueError("Repetitions must be at least 1.")
        if resource_recovery_timeout_seconds < 0:
            raise ValueError("Resource recovery timeout must not be negative.")
        if resource_recovery_poll_seconds <= 0:
            raise ValueError("Resource recovery poll interval must be positive.")
        if resource_recovery_stable_samples < 1:
            raise ValueError("Resource recovery stable samples must be at least 1.")
        self.configurations = tuple(configurations)
        self.cases = {
            "performance": [dict(case) for case in cases.get("performance", ())],
            "tool_cases": [dict(case) for case in cases.get("tool_cases", ())],
        }
        self.repetitions = repetitions
        self.cooldown_seconds = max(0.0, cooldown_seconds)
        self.resource_recovery_timeout_seconds = resource_recovery_timeout_seconds
        self.resource_recovery_poll_seconds = resource_recovery_poll_seconds
        self.resource_recovery_stable_samples = resource_recovery_stable_samples
        self._sleep = sleep
        self._capture = capture
        self._resource_sampler_factory = resource_sampler_factory
        self._owned_model = False
        self._owned_ref: LocalModelRef | None = None
        self._allowed_refs = frozenset(known_local_model_refs()).union(
            configuration.runtime_ref for configuration in self.configurations
        )
        self._validate_case_tools()

    def _validate_case_tools(self) -> None:
        for case in self.cases["tool_cases"]:
            for name in case.get("tools", []):
                descriptor = get_capability_descriptor(name)
                if descriptor is None:
                    raise ValueError(
                        f"Benchmark case {case.get('id')!r} references unknown "
                        f"capability {name!r}."
                    )

    def _descriptors_for_case(
        self,
        case: Mapping[str, Any],
        *,
        agent_key: str,
    ) -> list[CapabilityDescriptor]:
        descriptors: list[CapabilityDescriptor] = []
        for name in case.get("tools", []):
            descriptor = get_capability_descriptor(name)
            if descriptor is None:
                raise ValueError(f"Capability {name!r} is not registered.")
            descriptors.append(project_descriptor_for_agent(agent_key, descriptor))
        return descriptors

    def _system_instruction(
        self,
        configuration: BenchmarkConfiguration,
        descriptors: Sequence[CapabilityDescriptor],
    ) -> str:
        if configuration.agent_key is None:
            base = LOCAL_AGENT_SYSTEM_PROMPT
        else:
            base = compose_agent_system_instruction(
                configuration.agent_key,
                LOCAL_AGENT_SYSTEM_PROMPT,
            )
        return base + build_tool_access_instruction(
            [descriptor.name for descriptor in descriptors],
            hosted_tool_names=(),
        )

    def _execute_query(
        self,
        configuration: BenchmarkConfiguration,
        provider: Any,
        prompt: str,
        descriptors: Sequence[CapabilityDescriptor],
        *,
        dispatcher: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> tuple[AgentQueryResponse, float]:
        request = AgentQueryRequest(
            prompt=prompt,
            # AgentQueryRequest intentionally accepts only product Agent keys.
            # Candidates use the local system prompt and omit agent_key below;
            # this value is never used to resolve a candidate profile.
            agent="lynx",
            selected_tool_names=[descriptor.name for descriptor in descriptors],
        )
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "selected_tools": list(descriptors),
            "tool_selection": _selection_diagnostics(descriptors),
            "system_instruction_override": self._system_instruction(
                configuration,
                descriptors,
            ),
            "agent_key": configuration.agent_key,
        }
        if dispatcher is not None:
            kwargs["tools_dispatcher"] = dispatcher
        response = run_agent_loop(
            request,
            provider,
            configuration.profile,
            **kwargs,
        )
        return response, time.perf_counter() - started

    def _wait_for_resource_recovery(
        self,
        configuration: BenchmarkConfiguration,
    ) -> tuple[bool, str | None]:
        """Wait for the next model's resource gate to be stably open."""
        poll_seconds = self.resource_recovery_poll_seconds
        max_checks = max(
            self.resource_recovery_stable_samples,
            int(self.resource_recovery_timeout_seconds / poll_seconds) + 1,
        )
        consecutive_open = 0
        last_reason: str | None = None
        for index in range(max_checks):
            gate_open, gate_reason = check_resource_gate(
                configuration.profile.ram_limit,
                configuration.profile.cpu_limit,
            )
            if gate_open:
                consecutive_open += 1
                last_reason = None
                if consecutive_open >= self.resource_recovery_stable_samples:
                    return True, None
            else:
                consecutive_open = 0
                last_reason = gate_reason
            if index + 1 < max_checks:
                self._sleep(poll_seconds)
        return False, last_reason or "resource gate did not remain stable after unload"

    def _unload_known_residents(self) -> None:
        """Unload only recognized models, then verify an empty runtime."""
        _, residents = inspect_runtime_residents(self._allowed_refs)
        active = get_active_local_model()
        if active is not None:
            if active not in self._allowed_refs:
                raise BenchmarkAbort(
                    f"Coordinator reported an unknown active local model "
                    f"{active.provider}/{active.model}."
                )
            if not unload_active_local_model():
                raise BenchmarkAbort(
                    f"Could not verify unload of {active.provider}/{active.model}; "
                    "aborting before the next configuration."
                )
            self._owned_model = False
            self._owned_ref = None

        _, residents = inspect_runtime_residents(self._allowed_refs)
        for reference in sorted(
            residents,
            key=lambda item: (item.provider, item.model),
        ):
            backend = get_local_runtime_backend(reference.provider)
            if not backend.unload_model(reference.model):
                raise BenchmarkAbort(
                    f"Could not verify unload of {reference.provider}/{reference.model}; "
                    "aborting before the next configuration."
                )

        _, remaining = inspect_runtime_residents(self._allowed_refs)
        if remaining:
            formatted = ", ".join(
                f"{ref.provider}/{ref.model}"
                for ref in sorted(
                    remaining,
                    key=lambda item: (item.provider, item.model),
                )
            )
            raise BenchmarkAbort(
                "Local runtime remained resident after unload verification: "
                f"{formatted}."
            )
        self._sleep(self.cooldown_seconds)

    def _prepare_configuration(
        self,
        configuration: BenchmarkConfiguration,
    ) -> tuple[bool, MemorySnapshot]:
        backend = get_local_runtime_backend(configuration.provider)
        snapshots, residents = inspect_runtime_residents(
            self._allowed_refs,
            required_provider=(
                configuration.provider if backend.enabled else None
            ),
        )
        if not backend.enabled:
            raise BenchmarkFailure(
                f"{configuration.provider} local inference is disabled."
            )
        target = configuration.runtime_ref
        reused = (
            self._owned_model
            and self._owned_ref == target
            and residents == frozenset({target})
        )
        transitioned = False
        if residents and not reused:
            self._unload_known_residents()
            transitioned = True
            snapshots, residents = inspect_runtime_residents(
                self._allowed_refs,
                required_provider=configuration.provider,
            )
            if residents:
                raise BenchmarkAbort(
                    "A known local model remained resident after the transition; "
                    "aborting before loading another configuration."
                )

        target_snapshot = snapshots.get(configuration.provider)
        if target_snapshot is None:
            raise BenchmarkAbort(
                f"Could not verify {configuration.provider} before loading "
                f"{configuration.runtime_alias}."
            )
        if configuration.runtime_alias not in target_snapshot["installed_models"]:
            raise BenchmarkFailure(
                f"Runtime alias {configuration.runtime_alias!r} is not configured "
                f"in {configuration.provider}."
            )

        if not reused:
            if transitioned:
                gate_open, gate_reason = self._wait_for_resource_recovery(configuration)
            else:
                gate_open, gate_reason = check_resource_gate(
                    configuration.profile.ram_limit,
                    configuration.profile.cpu_limit,
                )
            if not gate_open:
                raise ResourceBlocked(
                    f"Host resources did not recover enough for "
                    f"{configuration.runtime_alias!r}"
                    f" ({gate_reason or 'resource pressure'})."
                )
        baseline = self._capture(configuration.provider)
        return reused, baseline

    def _verify_target_resident(
        self,
        configuration: BenchmarkConfiguration,
    ) -> None:
        snapshots, residents = inspect_runtime_residents(
            self._allowed_refs,
            required_provider=configuration.provider,
        )
        target = configuration.runtime_ref
        if residents != frozenset({target}):
            if residents:
                formatted = ", ".join(
                    f"{ref.provider}/{ref.model}"
                    for ref in sorted(
                        residents,
                        key=lambda item: (item.provider, item.model),
                    )
                )
                raise BenchmarkAbort(
                    "More than the selected local model is resident after load: "
                    f"{formatted}."
                )
            raise BenchmarkFailure(
                f"Could not verify residency of {configuration.runtime_alias!r}."
            )
        target_rows = [
            row
            for row in snapshots[configuration.provider]["loaded_models"]
            if row.get("model") == configuration.runtime_alias
            or row.get("name") == configuration.runtime_alias
        ]
        if not any(row.get("state") == "loaded" for row in target_rows):
            raise BenchmarkFailure(
                f"Runtime did not report {configuration.runtime_alias!r} as loaded."
            )
        reported_contexts = {
            row.get("context_window")
            for row in target_rows
            if isinstance(row.get("context_window"), int)
        }
        if reported_contexts and configuration.context not in reported_contexts:
            raise BenchmarkFailure(
                f"Runtime reported context {sorted(reported_contexts)} for "
                f"{configuration.runtime_alias!r}, requested {configuration.context}."
            )
        if not reported_contexts:
            _LOGGER.warning(
                "Runtime did not expose context_window for %s; context was not verified.",
                configuration.runtime_alias,
            )

    def _run_performance(
        self,
        configuration: BenchmarkConfiguration,
        provider: Any,
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        for repetition in range(1, self.repetitions + 1):
            for case in self.cases["performance"]:
                response, elapsed = self._execute_query(
                    configuration,
                    provider,
                    str(case["prompt"]),
                    [],
                )
                records.append(
                    {
                        "case_id": case["id"],
                        "repetition": repetition,
                        **_response_metrics(response, elapsed),
                    }
                )
        successes = sum(bool(record["success"]) for record in records)
        return {
            "prompt_cases": len(self.cases["performance"]),
            "repetitions": self.repetitions,
            "measured_requests": len(records),
            "successful_requests": successes,
            "failures": len(records) - successes,
            "median_latency_seconds": _median_metric(records, "latency_seconds"),
            "median_prompt_tokens": _median_metric(records, "prompt_tokens"),
            "median_completion_tokens": _median_metric(
                records,
                "completion_tokens",
            ),
            "median_effective_input_tokens_per_second": _median_metric(
                records,
                "effective_input_tokens_per_second",
            ),
            "median_effective_output_tokens_per_second": _median_metric(
                records,
                "effective_output_tokens_per_second",
            ),
            "requests": records,
        }

    def _run_tool_suite(
        self,
        configuration: BenchmarkConfiguration,
        provider: Any,
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        for repetition in range(1, self.repetitions + 1):
            for case in self.cases["tool_cases"]:
                descriptors = self._descriptors_for_case(
                    case,
                    agent_key=configuration.tool_projection_agent,
                )
                dispatcher = FixtureDispatcher(case, descriptors)
                response, elapsed = self._execute_query(
                    configuration,
                    provider,
                    str(case["prompt"]),
                    descriptors,
                    dispatcher=dispatcher,
                )
                record = score_tool_case(case, response, dispatcher, elapsed)
                record["repetition"] = repetition
                records.append(record)
        return {
            "case_definitions": len(self.cases["tool_cases"]),
            "repetitions": self.repetitions,
            "measured_tasks": len(records),
            "metrics": aggregate_tool_results(records),
            "cases": records,
        }

    def _run_configuration(
        self,
        configuration: BenchmarkConfiguration,
    ) -> dict[str, Any]:
        run: dict[str, Any] = {
            "agent": configuration.agent,
            "provider": configuration.provider,
            "model": configuration.model,
            "runtime_alias": configuration.runtime_alias,
            "context": configuration.context,
            "reasoning": configuration.reasoning,
            "status": "running",
            "reused_runtime": False,
            "load_seconds": None,
            "warmup": None,
            "resources": None,
            "performance": None,
            "tool_suite": None,
            "error": None,
        }
        sampler: ResourceSampler | None = None
        try:
            reused, baseline = self._prepare_configuration(configuration)
            run["reused_runtime"] = reused
            sampler = self._resource_sampler_factory(
                configuration.provider,
                capture=self._capture,
            )
            sampler.start()

            load_started = time.perf_counter()
            if not switch_local_model(configuration.profile):
                try:
                    _, residents = inspect_runtime_residents(
                        self._allowed_refs,
                        required_provider=configuration.provider,
                    )
                except BenchmarkAbort:
                    raise
                if residents:
                    raise BenchmarkAbort(
                        "Model transition failed to unload a resident model; "
                        "aborting before the next configuration."
                    )
                raise BenchmarkFailure(
                    f"Runtime failed to load {configuration.runtime_alias!r}."
                )
            run["load_seconds"] = (
                0.0 if reused else round(time.perf_counter() - load_started, 4)
            )
            # switch_local_model succeeded, so the benchmark owns the target
            # even if post-load verification rejects its reported state.
            self._owned_model = True
            self._owned_ref = configuration.runtime_ref
            self._verify_target_resident(configuration)

            provider = _provider_for_profile(configuration.profile)
            warmup_started = time.perf_counter()
            warmup_response, _ = self._execute_query(
                configuration,
                provider,
                "Reply with the single word READY.",
                [],
            )
            run["warmup"] = {
                "seconds": round(time.perf_counter() - warmup_started, 4),
                "success": warmup_response.error is None,
                "error": warmup_response.error,
            }
            if warmup_response.error is not None:
                raise BenchmarkFailure("Warmup request failed.")

            run["performance"] = self._run_performance(configuration, provider)
            run["tool_suite"] = self._run_tool_suite(configuration, provider)
            run["status"] = "ok"
            run["error"] = None
        except BenchmarkAbort as exc:
            run["status"] = "aborted"
            run["error"] = str(exc)
            if exc.partial_run is None:
                exc.partial_run = run
            raise
        except ResourceBlocked as exc:
            run["status"] = "resource_blocked"
            run["error"] = str(exc)
        except BenchmarkFailure as exc:
            run["status"] = "failed"
            run["error"] = str(exc)
        except Exception as exc:
            _LOGGER.warning(
                "Benchmark configuration failed: provider=%s alias=%s error_type=%s",
                configuration.provider,
                configuration.runtime_alias,
                type(exc).__name__,
            )
            run["status"] = "failed"
            run["error"] = f"Benchmark operation failed ({type(exc).__name__})."
        finally:
            if sampler is not None:
                final = sampler.stop()
                run["resources"] = build_resource_record(
                    baseline if "baseline" in locals() else MemorySnapshot(),
                    final,
                    sampler.samples,
                )
        return run

    def _cleanup_owned_model(self) -> None:
        """Unload the benchmark-owned model and verify no model remains."""
        owned_ref = self._owned_ref
        if not self._owned_model or owned_ref is None:
            return

        active = get_active_local_model()
        if active is not None:
            if active not in self._allowed_refs:
                raise BenchmarkAbort(
                    f"Coordinator reported an unknown active local model "
                    f"{active.provider}/{active.model} during cleanup."
                )
            if not unload_active_local_model():
                raise BenchmarkAbort(
                    f"Could not verify unload of {active.provider}/{active.model}; "
                    "aborting."
                )
        else:
            backend = get_local_runtime_backend(owned_ref.provider)
            if backend.is_model_resident(owned_ref.model) and not backend.unload_model(
                owned_ref.model
            ):
                raise BenchmarkAbort(
                    f"Could not verify unload of {owned_ref.provider}/{owned_ref.model}; "
                    "aborting."
                )

        self._owned_model = False
        self._owned_ref = None
        _, residents = inspect_runtime_residents(self._allowed_refs)
        if residents:
            for reference in sorted(
                residents,
                key=lambda item: (item.provider, item.model),
            ):
                backend = get_local_runtime_backend(reference.provider)
                if not backend.unload_model(reference.model):
                    raise BenchmarkAbort(
                        f"Could not verify unload of {reference.provider}/"
                        f"{reference.model}; aborting."
                    )
            _, residents = inspect_runtime_residents(self._allowed_refs)
        if residents:
            formatted = ", ".join(
                f"{ref.provider}/{ref.model}"
                for ref in sorted(
                    residents,
                    key=lambda item: (item.provider, item.model),
                )
            )
            raise BenchmarkAbort(
                f"Local runtime remained resident after final unload: {formatted}."
            )

    def run(self) -> dict[str, Any]:
        """Run all configurations under one process-wide local execution slot."""
        result: dict[str, Any] = {
            "benchmark_version": 0,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "apex_commit": _git_commit(),
            "system": _system_metadata(),
            "repetitions": self.repetitions,
            "runs": [],
            "aborted": False,
            "abort_reason": None,
        }

        claimed = False
        try:
            if not try_begin_local_execution():
                result["aborted"] = True
                result["abort_reason"] = (
                    "A local model generation or lifecycle action is already in progress."
                )
                return result
            claimed = True
            for configuration in self.configurations:
                try:
                    result["runs"].append(self._run_configuration(configuration))
                except BenchmarkAbort as exc:
                    if exc.partial_run is not None:
                        result["runs"].append(exc.partial_run)
                    result["aborted"] = True
                    result["abort_reason"] = str(exc)
                    break
        finally:
            if claimed:
                try:
                    self._cleanup_owned_model()
                except BenchmarkAbort as exc:
                    result["aborted"] = True
                    result["abort_reason"] = str(exc)
                finally:
                    end_local_execution()

        result["completed_runs"] = sum(
            run.get("status") == "ok" for run in result["runs"]
        )
        result["failed_runs"] = sum(
            run.get("status") == "failed" for run in result["runs"]
        )
        result["resource_blocked_runs"] = sum(
            run.get("status") == "resource_blocked" for run in result["runs"]
        )
        return result


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = completed.stdout.strip()
    return commit or None


def _system_metadata() -> dict[str, Any]:
    snapshot = capture_memory(None)
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "ram_gb": (
            round(snapshot.total_ram_bytes / (1024**3), 2)
            if snapshot.total_ram_bytes is not None
            else None
        ),
        "cpu_count": psutil.cpu_count(logical=True),
        "python": platform.python_version(),
    }


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return ROOT / "benchmarks" / "results" / f"{stamp}.json"


def _apex_is_running() -> bool:
    try:
        with urllib.request.urlopen(_APEX_LIVE_URL, timeout=0.5) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


class _BenchmarkLock:
    def __enter__(self) -> "_BenchmarkLock":
        try:
            self._fd = os.open(
                _BENCHMARK_LOCK_PATH,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise BenchmarkAbort(
                f"Another benchmark command is already running ({_BENCHMARK_LOCK_PATH})."
            ) from exc
        os.write(self._fd, str(os.getpid()).encode("ascii"))
        return self

    def __exit__(self, *_args: Any) -> None:
        os.close(self._fd)
        _BENCHMARK_LOCK_PATH.unlink(missing_ok=True)


def render_markdown(result: Mapping[str, Any]) -> str:
    """Render a compact human-readable companion report."""
    system = result.get("system", {})
    lines = [
        "# APEX Local Model Benchmark v0",
        "",
        f"- Timestamp: `{result.get('timestamp', '')}`",
        f"- APEX commit: `{result.get('apex_commit') or 'unknown'}`",
        f"- System: `{system.get('os', 'unknown')}` / "
        f"`{system.get('ram_gb') or '?'} GB RAM`",
        f"- Repetitions: `{result.get('repetitions', '?')}`",
        "",
    ]
    if result.get("aborted"):
        lines.extend(
            [
                "## Aborted",
                "",
                str(result.get("abort_reason") or "The benchmark was aborted."),
                "",
            ]
        )

    runs = [run for run in result.get("runs", []) if isinstance(run, dict)]
    lines.extend(
        [
            "## Performance",
            "",
            "| Agent | Status | Provider | Context | Reasoning | Load | Median latency | Effective output | Peak private memory | Commit delta | Failures |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for run in runs:
        performance = run.get("performance") or {}
        resources = run.get("resources") or {}
        lines.append(
            "| {agent} | {status} | {provider} | {context} | {reasoning} | {load} | {latency} | "
            "{generation} | {private} | {commit} | {failures} |".format(
                agent=run.get("agent", "?"),
                status=run.get("status", "?"),
                provider=run.get("provider", "?"),
                context=run.get("context", "?"),
                reasoning=run.get("reasoning", "?"),
                load=_display_seconds(run.get("load_seconds")),
                latency=_display_seconds(
                    performance.get("median_latency_seconds")
                ),
                generation=_display_throughput(
                    performance.get("median_effective_output_tokens_per_second")
                ),
                private=_display_bytes(
                    resources.get("provider_process_private_peak_bytes")
                ),
                commit=_display_bytes(resources.get("peak_committed_delta_bytes")),
                failures=performance.get("failures", "—"),
            )
        )

    lines.extend(
        [
            "",
            "## APEX tasks",
            "",
            "| Agent | Task success | Tool selection | Schema validity | Multi-tool completion | Unnecessary tools | Failure rate |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for run in runs:
        metrics = (run.get("tool_suite") or {}).get("metrics") or {}
        if not metrics:
            continue
        lines.append(
            "| {agent} | {task} | {selection} | {schema} | {multi} | {unnecessary} | {failure} |".format(
                agent=run.get("agent", "?"),
                task=_display_rate(metrics.get("task_success_rate")),
                selection=_display_rate(metrics.get("tool_selection_rate")),
                schema=_display_rate(metrics.get("schema_validity_rate")),
                multi=_display_rate(metrics.get("multi_tool_completion_rate")),
                unnecessary=_display_rate(metrics.get("unnecessary_tool_rate")),
                failure=_display_rate(metrics.get("failure_rate")),
            )
        )
    lines.extend(
        [
            "",
            "Raw task records and machine-specific resource observations are in the "
            "JSON result beside this report.",
            "",
        ]
    )
    return "\n".join(lines)


def _display_seconds(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:.2f} s"


def _display_rate(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value * 100:.1f}%"


def _display_throughput(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:.1f} t/s"


def _display_bytes(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value / (1024**3):.2f} GB"


def write_results(result: Mapping[str, Any], output_path: Path) -> tuple[Path, Path]:
    """Write JSON and the adjacent Markdown summary."""
    json_path = output_path
    if json_path.suffix.lower() != ".json":
        json_path = json_path.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path = json_path.with_suffix(".md")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, markdown_path


def render_terminal_summary(result: Mapping[str, Any]) -> str:
    """Return the concise terminal summary shown after a run."""
    lines = [
        "APEX LOCAL MODEL BENCHMARK v0",
        "",
        f"System: {result.get('system', {}).get('os', 'unknown')} / "
        f"{result.get('system', {}).get('ram_gb') or '?'} GB RAM",
        f"Repetitions: {result.get('repetitions', '?')}",
        "",
        "PERFORMANCE",
        "Agent / context              Status             Load       Median latency   Effective output   Failures",
    ]
    for run in result.get("runs", []):
        performance = run.get("performance") or {}
        lines.append(
            f"{str(run.get('agent', '?')) + ' ' + str(run.get('context', '?')):28}"
            f"{str(run.get('status', '?')):19}"
            f"{_display_seconds(run.get('load_seconds')):11}"
            f"{_display_seconds(performance.get('median_latency_seconds')):18}"
            f"{_display_throughput(performance.get('median_effective_output_tokens_per_second')):19}"
            f"{performance.get('failures', '—')}"
        )

    lines.extend(["", "APEX TASKS", "Agent / context              Task success   Multi-tool   Failures"])
    for run in result.get("runs", []):
        metrics = (run.get("tool_suite") or {}).get("metrics") or {}
        if not metrics:
            continue
        lines.append(
            f"{str(run.get('agent', '?')) + ' ' + str(run.get('context', '?')):28}"
            f"{_display_rate(metrics.get('task_success_rate')):16}"
            f"{_display_rate(metrics.get('multi_tool_completion_rate')):13}"
            f"{_display_rate(metrics.get('failure_rate'))}"
        )
    if result.get("aborted"):
        lines.extend(["", f"ABORTED: {result.get('abort_reason')}"])
    if result.get("resource_blocked_runs", 0):
        lines.extend(
            [
                "",
                f"RESOURCE BLOCKED: {result.get('resource_blocked_runs')} configuration(s) "
                "were not benchmarked because host resources did not recover in time.",
            ]
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare configured local APEX Agents one model at a time."
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        help="Registered local Agent keys, such as lynx.",
    )
    context_group = parser.add_mutually_exclusive_group()
    context_group.add_argument(
        "--context",
        type=int,
        help="One context window to use for each compatible local Agent.",
    )
    context_group.add_argument(
        "--all-contexts",
        action="store_true",
        help="Benchmark every registered llama.cpp context preset.",
    )
    parser.add_argument(
        "--reasoning",
        action="append",
        choices=("none", "focused"),
        help=(
            "Reasoning mode; repeat the option to compare modes without reloading "
            "the same runtime alias. Defaults to none."
        ),
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=_DEFAULT_REPETITIONS,
        help=f"Measured repetitions per prompt/case (default: {_DEFAULT_REPETITIONS}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="JSON output path; Markdown is written beside it.",
    )
    parser.add_argument(
        "--llama-candidate",
        help="One-off llama.cpp model filename or path, without an Agent identity.",
    )
    parser.add_argument(
        "--runtime-alias",
        help="Existing machine-local llama.cpp preset alias for the candidate.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.repetitions < 1:
        parser.error("--repetitions must be at least 1.")
    if _apex_is_running():
        parser.error(
            "APEX is running at /api/v1/health/live; stop the normal APEX process "
            "before benchmarking local models."
        )

    try:
        configurations = build_configurations(
            agents=args.agents,
            context=args.context,
            all_contexts=args.all_contexts,
            reasoning_modes=args.reasoning,
            candidate_model=args.llama_candidate,
            runtime_alias=args.runtime_alias,
        )
        cases = load_benchmark_cases()
        with _BenchmarkLock():
            if _apex_is_running():
                raise BenchmarkAbort(
                    "APEX started while preparing the benchmark; refusing to run."
                )
            result = BenchmarkRunner(
                configurations,
                cases,
                repetitions=args.repetitions,
            ).run()
        json_path, markdown_path = write_results(
            result,
            args.output or _default_output_path(),
        )
    except (ValueError, BenchmarkAbort) as exc:
        parser.error(str(exc))

    print(render_terminal_summary(result))
    print(f"\nJSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 1 if (
        result.get("aborted")
        or result.get("failed_runs", 0)
        or result.get("resource_blocked_runs", 0)
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
