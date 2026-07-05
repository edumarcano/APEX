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

from core.agent.providers.ollama_models import OLLAMA_MODEL_PROFILES, OllamaModelProfile
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


class LoadedOllamaModel(TypedDict):
    name: str
    model: str
    size_bytes: int | None
    size_vram_bytes: int | None
    processor: str | None
    context: str | None
    expires_at: str | None


class OllamaStatusSnapshot(TypedDict):
    reachable: bool
    installed_tags: list[str]
    loaded_models: list[LoadedOllamaModel]
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


def _coerce_optional_int(value: object) -> int | None:
    """Return an integer when Ollama reports a numeric runtime field."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _coerce_optional_str(value: object) -> str | None:
    """Return a non-empty string for optional Ollama runtime fields."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _probe_ollama_loaded_models() -> list[LoadedOllamaModel]:
    """Issue a single /api/ps probe returning loaded model runtime details."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/ps"

    try:
        response = _SESSION.get(url, timeout=_STATUS_PROBE_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except (RequestsConnectionError, ConnectionError) as exc:
        _LOGGER.warning("Ollama daemon unreachable during ps probe at %s: %s", url, exc)
        return []
    except RequestException as exc:
        _LOGGER.warning("Ollama ps request failed at %s: %s", url, exc)
        return []
    except ValueError as exc:
        _LOGGER.warning("Ollama ps response was not valid JSON from %s: %s", url, exc)
        return []

    models = payload.get("models")
    if not isinstance(models, list):
        _LOGGER.warning('Ollama ps response missing "models" array from %s', url)
        return []

    loaded_models: list[LoadedOllamaModel] = []
    for raw_model in models:
        if not isinstance(raw_model, dict):
            continue

        raw_name = raw_model.get("name")
        raw_model_name = raw_model.get("model")
        name = raw_name if isinstance(raw_name, str) and raw_name else None
        model_name = (
            raw_model_name
            if isinstance(raw_model_name, str) and raw_model_name
            else name
        )
        if model_name is None:
            continue

        loaded_models.append(
            LoadedOllamaModel(
                name=name or model_name,
                model=model_name,
                size_bytes=_coerce_optional_int(raw_model.get("size")),
                size_vram_bytes=_coerce_optional_int(raw_model.get("size_vram")),
                processor=_coerce_optional_str(raw_model.get("processor")),
                context=_coerce_optional_str(raw_model.get("context")),
                expires_at=_coerce_optional_str(raw_model.get("expires_at")),
            )
        )

    return loaded_models


def _loaded_model_matches(loaded_model: LoadedOllamaModel, model_name: str) -> bool:
    """Return whether a loaded Ollama model entry matches a configured tag."""
    return loaded_model["name"] == model_name or loaded_model["model"] == model_name


def is_local_model_loaded(model_name: str) -> bool:
    """
    Return whether a specific local model is already resident in Ollama.

    Checks the fast in-process tracker first, then falls back to /api/ps so the
    API can recognize models that survived an APEX server restart.
    """
    with _model_lock:
        if _active_loaded_model == model_name:
            return True

    return any(
        _loaded_model_matches(loaded_model, model_name)
        for loaded_model in _probe_ollama_loaded_models()
    )


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
        loaded_models = _probe_ollama_loaded_models() if reachable else []
        fresh: OllamaStatusSnapshot = {
            "reachable": reachable,
            "installed_tags": tags,
            "loaded_models": loaded_models,
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
    Unload the active APEX local model from Ollama memory.

    Prefers the in-process tracker, then falls back to /api/ps so manual unload
    still works after an API restart. Returns True when no APEX local model is
    active or every unload request succeeds.
    """
    with _model_lock:
        model_name = _active_loaded_model

    if model_name is None:
        profile_model_names = {
            profile.api_model for profile in OLLAMA_MODEL_PROFILES.values()
        }
        loaded_profile_names: list[str] = []
        for loaded_model in _probe_ollama_loaded_models():
            for loaded_name in (loaded_model["model"], loaded_model["name"]):
                if (
                    loaded_name in profile_model_names
                    and loaded_name not in loaded_profile_names
                ):
                    loaded_profile_names.append(loaded_name)

        if not loaded_profile_names:
            return True

        unloaded_all = True
        for loaded_name in loaded_profile_names:
            unloaded_all = unload_local_model(loaded_name) and unloaded_all
        return unloaded_all

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


def _build_warmup_options(profile: OllamaModelProfile) -> dict[str, float | int]:
    """Build the runtime options used to warm a local model honestly."""
    return {
        "temperature": profile.default_temperature,
        "num_ctx": profile.context_window,
        "num_thread": profile.num_thread,
        "num_predict": 1,
    }


def switch_local_model(profile: OllamaModelProfile) -> bool:
    """
    Switch the active loaded model, unloading the current one first if needed.

    This is the primary entry point for coordinated model switches. It ensures
    only one local model remains in Ollama memory at any time. The warmup
    request mirrors the profile's real runtime options so the first assistant
    turn does not pay a second setup cost for context/thread/think settings.

    Callers must hold the execution slot (``try_begin_local_execution``) so
    concurrent switches cannot occur. ``_model_lock`` guards only state reads
    and writes and is never held across HTTP I/O, so status readers stay
    responsive during long warmups.

    Args:
        profile: Local model profile to switch to.

    Returns:
        True if the switch succeeded or was already satisfied.
        False if the warmup/load failed or an unrecoverable error occurred.
    """
    global _active_loaded_model, _last_activity_time

    target_model_name = profile.api_model

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

    if is_local_model_loaded(target_model_name):
        with _model_lock:
            _active_loaded_model = target_model_name
            _last_activity_time = time.monotonic()
        _LOGGER.info("Model %s already resident in Ollama", target_model_name)
        return True

    url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
    payload = {
        "model": target_model_name,
        "messages": [],
        "stream": False,
        "options": _build_warmup_options(profile),
        "think": profile.think,
        "keep_alive": get_keep_alive_duration(),
    }

    try:
        response = _SESSION.post(url, json=payload, timeout=profile.generation_timeout)
        response.raise_for_status()
        _LOGGER.info("Loaded model %s into Ollama", target_model_name)
    except RequestsTimeout:
        _LOGGER.error(
            "Timeout loading model %s after %ss",
            target_model_name,
            profile.generation_timeout,
        )
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
