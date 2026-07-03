import logging
import threading
from typing import TypedDict

import psutil
import requests
from requests.exceptions import RequestException

from core.config import OLLAMA_HOST

_LOGGER = logging.getLogger(__name__)

_model_lock = threading.Lock()
_active_loaded_model: str | None = None

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
    except ConnectionError as exc:
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

    url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    payload = {"model": model_name, "keep_alive": 0}

    try:
        response = requests.post(url, json=payload, timeout=5.0)
        response.raise_for_status()
        _LOGGER.info("Unloaded model %s from Ollama", model_name)
    except ConnectionError as exc:
        _LOGGER.warning(
            "Ollama unreachable while unloading %s; clearing tracker anyway: %s",
            model_name,
            exc,
        )
    except RequestException as exc:
        _LOGGER.warning("Failed to unload model %s: %s", model_name, exc)
        return False

    with _model_lock:
        _active_loaded_model = None

    return True


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
    global _active_loaded_model

    with _model_lock:
        if _active_loaded_model == target_model_name:
            _LOGGER.debug("Model %s already loaded; skipping switch", target_model_name)
            return True

        if _active_loaded_model is not None:
            _LOGGER.info(
                "Unloading %s before switching to %s",
                _active_loaded_model,
                target_model_name,
            )
            if not unload_local_model(_active_loaded_model):
                _LOGGER.error("Failed to unload %s; aborting switch", _active_loaded_model)
                return False

        url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
        payload = {"model": target_model_name, "prompt": "", "keep_alive": "5m"}

        try:
            response = requests.post(url, json=payload, timeout=10.0)
            response.raise_for_status()
            _LOGGER.info("Loaded model %s into Ollama", target_model_name)
        except requests.Timeout:
            _LOGGER.error("Timeout loading model %s after 10s", target_model_name)
            _active_loaded_model = None
            return False
        except ConnectionError as exc:
            _LOGGER.error("Ollama unreachable while loading %s: %s", target_model_name, exc)
            _active_loaded_model = None
            return False
        except RequestException as exc:
            _LOGGER.error("Failed to load model %s: %s", target_model_name, exc)
            _active_loaded_model = None
            return False

        _active_loaded_model = target_model_name
        return True
