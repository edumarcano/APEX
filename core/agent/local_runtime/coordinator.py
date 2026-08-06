"""APEX-global local runtime policy: lock, gating, switching, and idle unload."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import psutil

from core.agent.local_runtime.contract import (
    LocalModelProfile,
    LocalModelRef,
    LocalRuntimeSnapshot,
    ResourceGateReason,
    SystemVitals,
)
from core.agent.local_runtime.registry import (
    get_local_runtime_backend,
    iter_local_runtime_backends,
)
from core.agent.providers.contract import LocalInferenceProvider

_LOGGER = logging.getLogger(__name__)

_IDLE_CHECK_INTERVAL_SECONDS = 30

_execution_lock = threading.Lock()
_runtime_transition_lock = threading.Lock()
_state_lock = threading.Lock()
_active_local_model: LocalModelRef | None = None
_loading_local_model: LocalModelRef | None = None
_last_activity_time: float = time.monotonic()
_monotonic = time.monotonic

# Prime the process-wide CPU counter; without this the first
# cpu_percent(interval=None) read always returns 0.0.
try:
    psutil.cpu_percent(interval=None)
except Exception:
    pass


def _profile_ref(profile: LocalModelProfile) -> LocalModelRef:
    return LocalModelRef(provider=profile.provider, model=profile.runtime_model_id)


def _known_local_model_refs() -> frozenset[LocalModelRef]:
    """Resolve known APEX local models without importing catalog at module load."""
    from core.agent.catalog import known_local_model_refs

    return known_local_model_refs()


def _discover_known_residents() -> list[LocalModelRef]:
    """Probe enabled backends for resident known APEX models (I/O, no locks)."""
    known = _known_local_model_refs()
    found: list[LocalModelRef] = []
    seen: set[LocalModelRef] = set()
    for backend in iter_local_runtime_backends(enabled_only=True):
        snapshot = backend.get_status_snapshot()
        if not snapshot["reachable"]:
            continue
        for loaded in snapshot["loaded_models"]:
            if loaded["state"] != "loaded":
                continue
            for candidate_model in (loaded["model"], loaded["name"]):
                ref = LocalModelRef(provider=backend.provider, model=candidate_model)
                if ref in known and ref not in seen:
                    seen.add(ref)
                    found.append(ref)
                    break
    return found


def _adopt_single_resident(found: list[LocalModelRef]) -> LocalModelRef | None:
    """Adopt exactly one discovered resident under the state lock."""
    global _active_local_model, _last_activity_time

    # Never reconcile during a coordinated switch or while any local lifecycle
    # holder owns the execution slot; a status poll must not re-adopt the old
    # resident after the tracker was intentionally cleared.
    if is_local_execution_active():
        return None

    with _state_lock:
        if _active_local_model is not None:
            return _active_local_model
        if _loading_local_model is not None:
            return None
        if len(found) == 1:
            _active_local_model = found[0]
            _last_activity_time = _monotonic()
            return _active_local_model
        return None


def try_begin_local_runtime_transition() -> bool:
    """
    Attempt to claim the local-runtime settings transition gate without blocking.

    Returns False when another transition is in progress or Apodemus is active
    or loading, allowing callers to reject conflicting settings changes.
    """
    if not _runtime_transition_lock.acquire(blocking=False):
        return False
    if is_local_execution_active() or get_loading_local_model() is not None:
        _runtime_transition_lock.release()
        return False
    return True


def end_local_runtime_transition() -> None:
    """Release the local-runtime settings transition gate."""
    _runtime_transition_lock.release()


def is_local_runtime_transition_active() -> bool:
    """Return whether a local-runtime settings transition is in progress."""
    return _runtime_transition_lock.locked()


def try_begin_local_execution() -> bool:
    """
    Attempt to claim the single local execution slot without blocking.

    Returns False when another local generation is already running, allowing
    the caller to reject the request instead of parking a worker thread.
    """
    if _runtime_transition_lock.locked():
        return False
    return _execution_lock.acquire(blocking=False)


def end_local_execution() -> None:
    """Release the local execution slot claimed by try_begin_local_execution."""
    _execution_lock.release()
    try:
        from core.agent.providers.llama_cpp_supervisor import (
            get_llama_cpp_server_supervisor,
        )

        get_llama_cpp_server_supervisor().maybe_stop_after_idle()
    except Exception:
        _LOGGER.debug(
            "Deferred llama.cpp shutdown check failed after local execution",
            exc_info=True,
        )


def is_local_execution_active() -> bool:
    """Return whether a local generation currently holds the execution slot."""
    return _execution_lock.locked()


def get_system_vitals() -> SystemVitals:
    """
    Sample current CPU and RAM utilization with a single non-blocking read.

    Failures fall back to 0.0.
    """
    cpu = 0.0
    ram = 0.0

    try:
        cpu = float(psutil.cpu_percent(interval=None))
    except Exception as exc:
        _LOGGER.warning("CPU vitals query failed: %s", exc)

    try:
        ram = float(psutil.virtual_memory().percent)
    except Exception as exc:
        _LOGGER.warning("RAM vitals query failed: %s", exc)

    return {"cpu": cpu, "ram": ram}


def check_resource_gate(
    ram_limit: float,
    cpu_limit: float,
    vitals: SystemVitals | None = None,
) -> tuple[bool, ResourceGateReason | None]:
    """
    Evaluate whether host utilization is below profile gate thresholds.

    Returns:
        (True, None) when both RAM and CPU are below their limits.
        (False, "insufficient_ram") when RAM meets or exceeds ram_limit.
        (False, "cpu_overloaded") when CPU meets or exceeds cpu_limit.
    """
    resolved = vitals if vitals is not None else get_system_vitals()

    if resolved["ram"] >= ram_limit:
        return False, "insufficient_ram"

    if resolved["cpu"] >= cpu_limit:
        return False, "cpu_overloaded"

    return True, None


def get_provider_snapshot(
    provider: LocalInferenceProvider,
    *,
    force_refresh: bool = False,
) -> LocalRuntimeSnapshot:
    """Return a normalized provider snapshot through the registered backend."""
    return get_local_runtime_backend(provider).get_status_snapshot(
        force_refresh=force_refresh
    )


def get_active_local_model() -> LocalModelRef | None:
    """Return the provider-qualified active local model, reconciling after restart."""
    with _state_lock:
        if _active_local_model is not None:
            return _active_local_model
        if _loading_local_model is not None:
            return None
    if is_local_execution_active():
        return None
    return _adopt_single_resident(_discover_known_residents())


def get_loading_local_model() -> LocalModelRef | None:
    """Return the provider-qualified model currently being warmed up, or None."""
    with _state_lock:
        return _loading_local_model


def get_idle_unload_remaining_seconds() -> int | None:
    """
    Return seconds until the active model is auto-unloaded due to inactivity.

    Returns None when no model is currently tracked as loaded.
    """
    active = get_active_local_model()
    if active is None:
        return None
    backend = get_local_runtime_backend(active.provider)
    with _state_lock:
        if _active_local_model != active:
            return None
        elapsed = _monotonic() - _last_activity_time
        remaining = backend.idle_unload_seconds - elapsed
        return max(0, int(remaining))


def register_local_activity(model: LocalModelRef) -> None:
    """
    Record model usage so the idle auto-unload timer resets.

    Called once per completed generation turn so long tool-calling sessions
    keep refreshing the idle clock. Sets the active model only when none is
    currently tracked.
    """
    global _active_local_model, _last_activity_time

    with _state_lock:
        _last_activity_time = _monotonic()
        if _active_local_model is None:
            _active_local_model = model


def is_local_model_ready(ref: LocalModelRef) -> bool:
    """
    Return whether a model is already available without a cold load.

    The in-memory tracker is never trusted alone: residency is always verified
    with the provider backend. Stale tracker entries (provider restart, external
    unload) are cleared so callers fall through the cold-load admission path.
    """
    global _active_local_model

    with _state_lock:
        tracked = _active_local_model == ref

    backend = get_local_runtime_backend(ref.provider)
    if backend.is_model_resident(ref.model):
        return True

    if tracked:
        with _state_lock:
            if _active_local_model == ref:
                _active_local_model = None
                _LOGGER.info(
                    "Cleared stale active tracker for %s/%s after residency miss",
                    ref.provider,
                    ref.model,
                )
    return False


def switch_local_model(profile: LocalModelProfile) -> bool:
    """
    Switch the active loaded model, unloading competing known APEX models first.

    Callers must hold the execution slot (``try_begin_local_execution``) so
    concurrent switches cannot occur. ``_state_lock`` guards only state reads
    and writes and is never held across HTTP I/O.
    """
    global _active_local_model, _loading_local_model, _last_activity_time

    target = _profile_ref(profile)
    backend = get_local_runtime_backend(target.provider)
    previous: LocalModelRef | None

    with _state_lock:
        tracked_match = _active_local_model == target
        if not tracked_match:
            previous = _active_local_model
            _active_local_model = None
            _loading_local_model = target

    if tracked_match:
        if backend.is_model_resident(target.model):
            _LOGGER.debug(
                "Model %s/%s already loaded; skipping switch",
                target.provider,
                target.model,
            )
            with _state_lock:
                if _active_local_model == target:
                    _last_activity_time = _monotonic()
            return True
        _LOGGER.info(
            "Tracked model %s/%s is absent at the provider; reloading",
            target.provider,
            target.model,
        )
        with _state_lock:
            if _active_local_model == target:
                _active_local_model = None
            previous = None
            _loading_local_model = target

    try:
        known = _known_local_model_refs()
        competitors: list[LocalModelRef] = []
        seen: set[LocalModelRef] = set()

        if previous is not None and previous != target:
            competitors.append(previous)
            seen.add(previous)

        for candidate_backend in iter_local_runtime_backends(enabled_only=True):
            for loaded in candidate_backend.get_status_snapshot()["loaded_models"]:
                if loaded["state"] != "loaded":
                    continue
                for candidate_model in (loaded["model"], loaded["name"]):
                    ref = LocalModelRef(
                        provider=candidate_backend.provider,
                        model=candidate_model,
                    )
                    if ref == target or ref not in known or ref in seen:
                        continue
                    seen.add(ref)
                    competitors.append(ref)
                    break

        for competitor in competitors:
            _LOGGER.info(
                "Unloading %s/%s before switching to %s/%s",
                competitor.provider,
                competitor.model,
                target.provider,
                target.model,
            )
            competitor_backend = get_local_runtime_backend(competitor.provider)
            if not competitor_backend.unload_model(competitor.model):
                _LOGGER.error(
                    "Failed to unload %s/%s; aborting switch",
                    competitor.provider,
                    competitor.model,
                )
                with _state_lock:
                    _active_local_model = competitor
                return False

        if not backend.load_model(profile):
            return False

        with _state_lock:
            _active_local_model = target
            _last_activity_time = _monotonic()
        return True
    finally:
        with _state_lock:
            if _loading_local_model == target:
                _loading_local_model = None


def unload_active_local_model() -> bool:
    """
    Unload the coordinator-tracked active APEX local model.

    Returns True when no known APEX model is active or the unload succeeds.
    """
    global _active_local_model

    active = get_active_local_model()
    if active is None:
        return True

    backend = get_local_runtime_backend(active.provider)
    if not backend.unload_model(active.model):
        return False

    with _state_lock:
        if _active_local_model == active:
            _active_local_model = None
    return True


def _maybe_unload_idle_model() -> None:
    """
    Unload the active model when idle duration exceeds the configured threshold.

    Claims the global execution slot for the full evaluate/unload/cleanup window
    so a newly started generation cannot race between the idle check and the
    unload request. Uses a snapshot-and-reverify pattern so concurrent activity
    or model switches are not clobbered by a stale idle decision.
    """
    global _active_local_model

    if not try_begin_local_execution():
        return

    try:
        active = get_active_local_model()
        if active is None:
            return

        backend = get_local_runtime_backend(active.provider)
        with _state_lock:
            if _active_local_model != active:
                return
            idle_seconds = _monotonic() - _last_activity_time
            if idle_seconds < backend.idle_unload_seconds:
                return
            model_to_unload = active
            activity_snapshot = _last_activity_time

        if not get_local_runtime_backend(model_to_unload.provider).unload_model(
            model_to_unload.model
        ):
            return

        with _state_lock:
            if (
                _active_local_model == model_to_unload
                and _last_activity_time == activity_snapshot
            ):
                _active_local_model = None
                _LOGGER.info(
                    "Idle unload triggered for %s/%s after %.0fs of inactivity",
                    model_to_unload.provider,
                    model_to_unload.model,
                    _monotonic() - activity_snapshot,
                )
    finally:
        end_local_execution()


async def check_idle_local_models_loop() -> None:
    """
    Background worker that periodically unloads idle local models.

    Polls every 30 seconds and compares monotonic elapsed time against each
    backend's idle threshold, so wall-clock jumps cannot trigger premature
    unloads.
    """
    while True:
        try:
            await asyncio.sleep(_IDLE_CHECK_INTERVAL_SECONDS)
            await asyncio.to_thread(_maybe_unload_idle_model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.warning("Idle model check failed: %s", exc)
