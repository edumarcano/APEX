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

_model_lock = threading.Lock()
_active_loaded_model: str | None = None
_last_activity_time: float = time.time()
_IDLE_CHECK_INTERVAL_SECONDS = 30

ResourceGateReason = str  # "insufficient_ram" | "cpu_overloaded"


class SystemVitals(TypedDict):
    cpu: float
    ram: float


def get_system_vitals() -> SystemVitals:
    """
    Sample current CPU and RAM utilization with a single non-blocking read.

    Each psutil query is isolated; failures fall back to 0.0 and emit a
    diagnostic warning.
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
    ram_limit: float, cpu_limit: float
) -> tuple[bool, ResourceGateReason | None]:
    """
    Evaluate whether current host utilization is below profile gate thresholds.

    Returns:
        (True, None) when both RAM and CPU are below their limits.
        (False, "insufficient_ram") when RAM utilization meets or exceeds ram_limit.
        (False, "cpu_overloaded") when CPU utilization meets or exceeds cpu_limit.
    """
    vitals = get_system_vitals()

    if vitals["ram"] >= ram_limit:
        return False, "insufficient_ram"

    if vitals["cpu"] >= cpu_limit:
        return False, "cpu_overloaded"

    return True, None


def is_ollama_reachable() -> bool:
    """Return whether the local Ollama daemon responds to a tags probe."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/tags"

    try:
        response = requests.get(url, timeout=2.0)
        response.raise_for_status()
        return True
    except RequestException:
        return False


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
        elapsed = time.time() - _last_activity_time
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


def get_installed_ollama_tags() -> list[str]:
    """
    Query the local Ollama daemon for installed model tags.

    Returns an empty list when the daemon is unreachable or the response is
    malformed.
    """
    url = f"{OLLAMA_HOST.rstrip('/')}/api/tags"

    try:
        response = requests.get(url, timeout=2.0)
        response.raise_for_status()
        payload = response.json()
    except (RequestsConnectionError, ConnectionError) as exc:
        _LOGGER.warning("Ollama daemon unreachable at %s: %s", url, exc)
        return []
    except RequestException as exc:
        _LOGGER.warning("Ollama tags request failed at %s: %s", url, exc)
        return []
    except ValueError as exc:
        _LOGGER.warning("Ollama tags response was not valid JSON from %s: %s", url, exc)
        return []

    models = payload.get("models")
    if not isinstance(models, list):
        _LOGGER.warning(
            'Ollama tags response missing "models" array from %s', url
        )
        return []

    tags: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if isinstance(name, str) and name:
            tags.append(name)

    return tags


def _post_unload_request(model_name: str) -> bool:
    """Send keep_alive=0 to Ollama without mutating local tracker state."""
    url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    payload = {"model": model_name, "keep_alive": 0, "stream": False}

    try:
        response = requests.post(url, json=payload, timeout=5.0)
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

    Updates the last-activity timestamp on every call. Sets
    ``_active_loaded_model`` only when no model is currently tracked.
    """
    global _active_loaded_model, _last_activity_time

    with _model_lock:
        _last_activity_time = time.time()
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

    Uses a snapshot-and-reverify pattern so concurrent activity or model
    switches are not clobbered by a stale idle decision.
    """
    global _active_loaded_model

    with _model_lock:
        if _active_loaded_model is None:
            return

        idle_seconds = time.time() - _last_activity_time
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
                time.time() - activity_snapshot,
            )


async def check_idle_models_loop() -> None:
    """
    Background worker that periodically unloads idle local models.

    Polls every 30 seconds and compares absolute elapsed time against
    ``OLLAMA_IDLE_UNLOAD_MINUTES``. Safe across system sleep because it
    uses monotonic wall-clock deltas rather than tick counts.
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

    Thread-safe via _model_lock. If multiple threads call this concurrently,
    the last one to acquire the lock will perform its switch operation.

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
            _last_activity_time = time.time()
            return True

        if _active_loaded_model is not None:
            previous_model = _active_loaded_model
            _LOGGER.info(
                "Unloading %s before switching to %s",
                previous_model,
                target_model_name,
            )
            if not _post_unload_request(previous_model):
                _LOGGER.error("Failed to unload %s; aborting switch", previous_model)
                return False
            _active_loaded_model = None

        url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
        payload = {
            "model": target_model_name,
            "prompt": "",
            "keep_alive": "5m",
            "stream": False,
        }

        try:
            response = requests.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            _LOGGER.info("Loaded model %s into Ollama", target_model_name)
        except RequestsTimeout:
            _LOGGER.error("Timeout loading model %s after 60s", target_model_name)
            _active_loaded_model = None
            return False
        except (RequestsConnectionError, ConnectionError) as exc:
            _LOGGER.error("Ollama unreachable while loading %s: %s", target_model_name, exc)
            _active_loaded_model = None
            return False
        except RequestException as exc:
            _LOGGER.error("Failed to load model %s: %s", target_model_name, exc)
            _active_loaded_model = None
            return False

        _active_loaded_model = target_model_name
        _last_activity_time = time.time()
        return True
