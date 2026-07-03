import logging
from typing import TypedDict

import psutil
import requests
from requests.exceptions import RequestException

from core.config import OLLAMA_HOST

_LOGGER = logging.getLogger(__name__)

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
