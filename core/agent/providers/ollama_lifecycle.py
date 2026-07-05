import asyncio
import logging
import threading
import time
from typing import TypedDict

import psutil
import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout as RequestsTimeout,
)

from core.config import OLLAMA_HOST, OLLAMA_IDLE_UNLOAD_MINUTES

_LOGGER = logging.getLogger(__name__)

# Shared HTTP session so lifecycle probes and provider calls reuse pooled TCP
# connections instead of opening a new socket per request.
_SESSION = requests.Session()

_model_lock = threading.Lock()
_active_loaded_model: str | None = None
_last_activity_time: float = time.monotonic()
_IDLE_CHECK_INTERVAL_SECONDS = 30

# Serializes local generations end-to-end. Held for the full duration of a
# query so the idle unloader and manual unload can detect in-flight work and
# stand down instead of evicting a model mid-inference.
_execution_lock = threading.Lock()

_STATUS_CACHE_TTL_SECONDS = 10.0
_STATUS_PROBE_TIMEOUT_SECONDS = 2.0
_status_lock = threading.Lock()

ResourceGateReason = str  # "insufficient_ram" | "cpu_overloaded"


class SystemVitals(TypedDict):
    cpu: float
    ram: float


class OllamaStatusSnapshot(TypedDict):
    reachable: bool
    installed_tags: list[str]
    vitals: SystemVitals
    sampled_at: float


_status_snapshot: OllamaStatusSnapshot | None = None

# Prime the process-wide CPU counter; without this the first
# cpu_percent(interval=None) read always returns 0.0.
try:
    psutil.cpu_percent(interval=None)
except Exception:
    pass


def get_http_session() -> requests.Session:
    """Return the shared HTTP session for all Ollama daemon traffic."""
    return _SESSION


def get_keep_alive_duration() -> str:
    """
    Return the daemon-side keep_alive window derived from the idle config.

    One minute is added on top of ``OLLAMA_IDLE_UNLOAD_MINUTES`` so the
    Python-side idle unloader is always the deciding authority; Ollama's own
    eviction acts only as a fail-safe backstop.
    """
    return f"{OLLAMA_IDLE_UNLOAD_MINUTES + 1}m"


def try_begin_local_execution() -> bool:
    """
    Attempt to claim the single local execution slot without blocking.

    Returns False when another local generation is already running, allowing
    the caller to reject the request instead of parking a worker thread.
    """
    return _execution_lock.acquire(blocking=False)


def end_local_execution() -> None:
    """Release the local execution slot claimed by try_begin_local_execution."""
    _execution_lock.release()


def is_local_execution_active() -> bool:
    """Return whether a local generation currently holds the execution slot."""
    return _execution_lock.locked()


def get_system_vitals() -> SystemVitals:
    """
    Sample current CPU and RAM utilization with a single non-blocking read.

    The CPU reading reflects utilization since the previous call from this
    process; callers are rate-limited (snapshot refresh and query admission)
    so the sampling window stays meaningful. Failures fall back to 0.0.
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

    Args:
        ram_limit: Maximum RAM utilization percentage allowed.
        cpu_limit: Maximum CPU utilization percentage allowed.
        vitals: Pre-sampled vitals (e.g. from the status snapshot). When
            omitted, a fresh sample is taken.

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


def _probe_ollama_tags() -> tuple[bool, list[str]]:
    """Issue a single /api/tags probe returning (reachable, installed tags)."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/tags"

    try:
        response = _SESSION.get(url, timeout=_STATUS_PROBE_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except (RequestsConnectionError, ConnectionError) as exc:
        _LOGGER.warning("Ollama daemon unreachable at %s: %s", url, exc)
        return False, []
    except RequestException as exc:
        _LOGGER.warning("Ollama tags request failed at %s: %s", url, exc)
        return False, []
    except ValueError as exc:
        _LOGGER.warning("Ollama tags response was not valid JSON from %s: %s", url, exc)
        return False, []

    models = payload.get("models")
    if not isinstance(models, list):
        _LOGGER.warning('Ollama tags response missing "models" array from %s', url)
        return True, []

    tags: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if isinstance(name, str) and name:
            tags.append(name)

    return True, tags


def get_status_snapshot(force_refresh: bool = False) -> OllamaStatusSnapshot:
    """
    Return daemon reachability, installed tags, and host vitals from a TTL cache.

    A single /api/tags probe feeds both the reachability flag and the tag
    list, refreshed at most once per ``_STATUS_CACHE_TTL_SECONDS``. While a
    local generation holds the execution slot the last snapshot is returned
    without probing, so a saturated daemon is never queried mid-inference.
    Concurrent callers collapse onto one probe via ``_status_lock``.

    The returned mapping must be treated as read-only.
    """
    global _status_snapshot

    with _status_lock:
        snapshot = _status_snapshot
        if snapshot is not None:
            if is_local_execution_active():
                return snapshot
            age = time.monotonic() - snapshot["sampled_at"]
            if age < _STATUS_CACHE_TTL_SECONDS and not force_refresh:
                return snapshot

        reachable, tags = _probe_ollama_tags()
        fresh: OllamaStatusSnapshot = {
            "reachable": reachable,
            "installed_tags": tags,
            "vitals": get_system_vitals(),
            "sampled_at": time.monotonic(),
        }
        _status_snapshot = fresh
        return fresh


def get_active_loaded_model() -> str | None:
    """Return the Ollama model tag currently tracked as loaded in memory."""
    with _model_lock:
        return _active_loaded_model


def get_idle_unload_remaining_seconds() -> int | None:
    """
    Return seconds until the active model is auto-unloaded due to inactivity.

    Returns None when no model is currently tracked as loaded.
    """
    with _model_lock:
        if _active_loaded_model is None:
            return None
        elapsed = time.monotonic() - _last_activity_time
        remaining = (OLLAMA_IDLE_UNLOAD_MINUTES * 60) - elapsed
        return max(0, int(remaining))


def unload_active_local_model() -> bool:
    """
    Unload the currently tracked active model from Ollama memory.

    Returns True when no model is active or the unload request succeeds.
    """
    with _model_lock:
        model_name = _active_loaded_model

    if model_name is None:
        return True

    return unload_local_model(model_name)


def _post_unload_request(model_name: str) -> bool:
    """Send keep_alive=0 to Ollama without mutating local tracker state."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload = {"model": model_name, "messages": [], "keep_alive": 0}

    try:
        response = _SESSION.post(url, json=payload, timeout=5.0)
        response.raise_for_status()
        _LOGGER.info("Unloaded model %s from Ollama", model_name)
        return True
    except (RequestsConnectionError, ConnectionError) as exc:
        _LOGGER.warning(
            "Ollama unreachable while unloading %s; clearing tracker anyway: %s",
            model_name,
            exc,
        )
        return True
    except RequestException as exc:
        _LOGGER.warning("Failed to unload model %s: %s", model_name, exc)
        return False


def register_activity(model_name: str) -> None:
    """
    Record model usage so the idle auto-unload timer resets.

    Called once per completed generation turn so long tool-calling sessions
    keep refreshing the idle clock. Sets ``_active_loaded_model`` only when
    no model is currently tracked.
    """
    global _active_loaded_model, _last_activity_time

    with _model_lock:
        _last_activity_time = time.monotonic()
        if _active_loaded_model is None:
            _active_loaded_model = model_name


def unload_local_model(model_name: str) -> bool:
    """
    Unload a model from Ollama by sending a keep_alive=0 signal.

    This forces Ollama to immediately release the model from memory.
    Clears the _active_loaded_model tracker on success, even if Ollama
    is unreachable (fail-safe for consistency).

    Args:
        model_name: Name of the model to unload.

    Returns:
        True if the unload request succeeded or was safely cleared.
        False if an unexpected error occurred.
    """
    global _active_loaded_model

    if not _post_unload_request(model_name):
        return False

    with _model_lock:
        if _active_loaded_model == model_name:
            _active_loaded_model = None

    return True


def _maybe_unload_idle_model() -> None:
    """
    Unload the active model when idle duration exceeds the configured threshold.

    Skips the cycle entirely while a generation holds the execution slot so a
    model is never evicted mid-inference. Uses a snapshot-and-reverify pattern
    so concurrent activity or model switches are not clobbered by a stale
    idle decision.
    """
    global _active_loaded_model

    if is_local_execution_active():
        return

    with _model_lock:
        if _active_loaded_model is None:
            return

        idle_seconds = time.monotonic() - _last_activity_time
        idle_threshold_seconds = OLLAMA_IDLE_UNLOAD_MINUTES * 60
        if idle_seconds < idle_threshold_seconds:
            return

        model_to_unload = _active_loaded_model
        activity_snapshot = _last_activity_time

    if not _post_unload_request(model_to_unload):
        return

    with _model_lock:
        if (
            _active_loaded_model == model_to_unload
            and _last_activity_time == activity_snapshot
        ):
            _active_loaded_model = None
            _LOGGER.info(
                "Idle unload triggered for %s after %.0fs of inactivity",
                model_to_unload,
                time.monotonic() - activity_snapshot,
            )


async def check_idle_models_loop() -> None:
    """
    Background worker that periodically unloads idle local models.

    Polls every 30 seconds and compares monotonic elapsed time against
    ``OLLAMA_IDLE_UNLOAD_MINUTES``, so wall-clock jumps (NTP corrections,
    manual clock changes) cannot trigger premature unloads.
    """
    while True:
        try:
            await asyncio.sleep(_IDLE_CHECK_INTERVAL_SECONDS)
            await asyncio.to_thread(_maybe_unload_idle_model)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.warning("Idle model check failed: %s", exc)


def switch_local_model(target_model_name: str) -> bool:
    """
    Switch the active loaded model, unloading the current one first if needed.

    This is the primary entry point for coordinated model switches. It ensures
    only one local model remains in Ollama memory at any time.

    Callers must hold the execution slot (``try_begin_local_execution``) so
    concurrent switches cannot occur. ``_model_lock`` guards only state reads
    and writes and is never held across HTTP I/O, so status readers stay
    responsive during long warmups.

    Args:
        target_model_name: Name of the model to switch to.

    Returns:
        True if the switch succeeded or was already satisfied.
        False if the warmup/load failed or an unrecoverable error occurred.
    """
    global _active_loaded_model, _last_activity_time

    with _model_lock:
        if _active_loaded_model == target_model_name:
            _LOGGER.debug("Model %s already loaded; skipping switch", target_model_name)
            _last_activity_time = time.monotonic()
            return True
        previous_model = _active_loaded_model
        _active_loaded_model = None

    if previous_model is not None:
        _LOGGER.info(
            "Unloading %s before switching to %s",
            previous_model,
            target_model_name,
        )
        if not _post_unload_request(previous_model):
            _LOGGER.error("Failed to unload %s; aborting switch", previous_model)
            with _model_lock:
                _active_loaded_model = previous_model
            return False

    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload = {
        "model": target_model_name,
        "messages": [],
        "keep_alive": get_keep_alive_duration(),
    }

    try:
        response = _SESSION.post(url, json=payload, timeout=60.0)
        response.raise_for_status()
        _LOGGER.info("Loaded model %s into Ollama", target_model_name)
    except RequestsTimeout:
        _LOGGER.error("Timeout loading model %s after 60s", target_model_name)
        return False
    except (RequestsConnectionError, ConnectionError) as exc:
        _LOGGER.error("Ollama unreachable while loading %s: %s", target_model_name, exc)
        return False
    except RequestException as exc:
        _LOGGER.error("Failed to load model %s: %s", target_model_name, exc)
        return False

    with _model_lock:
        _active_loaded_model = target_model_name
        _last_activity_time = time.monotonic()

    return True
