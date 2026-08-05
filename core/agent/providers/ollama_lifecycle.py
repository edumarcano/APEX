"""Ollama local-runtime backend: probes, load, unload, and residency."""

from __future__ import annotations

import logging
import threading
import time
from typing import ClassVar

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout as RequestsTimeout,
)

from core.agent.local_runtime.contract import (
    LocalModelProfile,
    LocalRuntimeModel,
    LocalRuntimeSnapshot,
)
from core.config import (
    OLLAMA_ENABLED,
    OLLAMA_HOST,
    OLLAMA_IDLE_UNLOAD_MINUTES,
    OLLAMA_MANUAL_UNLOAD_ENABLED,
)

_LOGGER = logging.getLogger(__name__)

_SESSION = requests.Session()
_STATUS_CACHE_TTL_SECONDS = 10.0
_STATUS_PROBE_TIMEOUT_SECONDS = 2.0
_STATE_VERIFICATION_ATTEMPTS = 3
_STATE_VERIFICATION_DELAY_SECONDS = 0.2


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


def _probe_ollama_loaded_models() -> list[LocalRuntimeModel]:
    """Issue a single /api/ps probe returning normalized loaded model details."""
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

    loaded_models: list[LocalRuntimeModel] = []
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

        context = _coerce_optional_str(raw_model.get("context"))
        context_window = _coerce_optional_int(raw_model.get("context"))
        loaded_models.append(
            LocalRuntimeModel(
                provider="ollama",
                name=name or model_name,
                model=model_name,
                state="loaded",
                size_bytes=_coerce_optional_int(raw_model.get("size")),
                size_vram_bytes=_coerce_optional_int(raw_model.get("size_vram")),
                processor=_coerce_optional_str(raw_model.get("processor")),
                context=context,
                context_window=context_window,
                expires_at=_coerce_optional_str(raw_model.get("expires_at")),
            )
        )

    return loaded_models


def _loaded_model_matches(loaded_model: LocalRuntimeModel, model_name: str) -> bool:
    """Return whether a loaded Ollama model entry matches a configured tag."""
    return loaded_model["name"] == model_name or loaded_model["model"] == model_name


def _build_warmup_options(profile: LocalModelProfile) -> dict[str, float | int]:
    """Build the runtime options used to warm a local model honestly."""
    num_thread = getattr(profile, "num_thread", None)
    options: dict[str, float | int] = {
        "temperature": float(getattr(profile, "default_temperature", 0.2)),
        "num_ctx": int(profile.context_window),
        "num_predict": 1,
    }
    if isinstance(num_thread, int):
        options["num_thread"] = num_thread
    return options


class OllamaRuntimeBackend:
    """Ollama-specific discovery, load, unload, and residency operations."""

    provider: ClassVar[str] = "ollama"

    def __init__(self) -> None:
        self._status_lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._status_snapshot: LocalRuntimeSnapshot | None = None

    @property
    def enabled(self) -> bool:
        return bool(OLLAMA_ENABLED)

    @property
    def idle_unload_seconds(self) -> int:
        return int(OLLAMA_IDLE_UNLOAD_MINUTES) * 60

    @property
    def manual_unload_enabled(self) -> bool:
        return bool(OLLAMA_MANUAL_UNLOAD_ENABLED)

    def invalidate_status_snapshot(self) -> None:
        """Discard cached daemon state after a verified lifecycle transition."""
        with self._status_lock:
            self._status_snapshot = None

    def _cached_snapshot_if_fresh(
        self,
        *,
        force_refresh: bool,
    ) -> LocalRuntimeSnapshot | None:
        """Return a usable cached snapshot, or None when a probe is required."""
        snapshot = self._status_snapshot
        if snapshot is None or force_refresh:
            return None

        from core.agent.local_runtime.coordinator import is_local_execution_active

        if is_local_execution_active():
            return snapshot
        age = time.monotonic() - snapshot["sampled_at"]
        if age < _STATUS_CACHE_TTL_SECONDS:
            return snapshot
        return None

    def get_status_snapshot(
        self,
        *,
        force_refresh: bool = False,
    ) -> LocalRuntimeSnapshot:
        """
        Return daemon reachability, installed models, and loaded models.

        Host vitals are owned by the global coordinator. Cache reads and
        publishes use ``_status_lock`` only; network probes run outside that
        lock so invalidation and competing readers are not blocked by timeouts.
        ``_probe_lock`` collapses concurrent probes.
        """
        with self._status_lock:
            cached = self._cached_snapshot_if_fresh(force_refresh=force_refresh)
            if cached is not None:
                return cached

        with self._probe_lock:
            with self._status_lock:
                cached = self._cached_snapshot_if_fresh(force_refresh=force_refresh)
                if cached is not None:
                    return cached

            reachable, tags = _probe_ollama_tags()
            loaded_models = _probe_ollama_loaded_models() if reachable else []
            fresh: LocalRuntimeSnapshot = {
                "provider": "ollama",
                "reachable": reachable,
                "installed_models": tags,
                "loaded_models": loaded_models,
                "sampled_at": time.monotonic(),
            }
            with self._status_lock:
                self._status_snapshot = fresh
                return fresh

    def is_model_resident(self, model: str) -> bool:
        """Return whether Ollama currently reports a model resident in memory."""
        return any(
            _loaded_model_matches(loaded_model, model)
            for loaded_model in _probe_ollama_loaded_models()
        )

    def _verify_residency(self, model_name: str, *, expected: bool) -> bool:
        """Confirm a lifecycle action against Ollama with bounded rechecks."""
        for attempt in range(_STATE_VERIFICATION_ATTEMPTS):
            resident = self.is_model_resident(model_name)
            if resident is expected:
                return True
            if attempt < _STATE_VERIFICATION_ATTEMPTS - 1:
                time.sleep(_STATE_VERIFICATION_DELAY_SECONDS)
        return False

    def load_model(self, profile: LocalModelProfile) -> bool:
        """Warm the target model into Ollama memory and verify residency."""
        target_model_name = profile.runtime_model_id
        if self.is_model_resident(target_model_name):
            self.invalidate_status_snapshot()
            _LOGGER.info("Model %s already resident in Ollama", target_model_name)
            return True

        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = {
            "model": target_model_name,
            "messages": [],
            "stream": False,
            "options": _build_warmup_options(profile),
            "think": bool(getattr(profile, "think", False)),
            "keep_alive": get_keep_alive_duration(),
        }

        try:
            response = _SESSION.post(
                url, json=payload, timeout=profile.generation_timeout
            )
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
            _LOGGER.error(
                "Ollama unreachable while loading %s: %s", target_model_name, exc
            )
            return False
        except RequestException as exc:
            _LOGGER.error("Failed to load model %s: %s", target_model_name, exc)
            return False

        if not self._verify_residency(target_model_name, expected=True):
            _LOGGER.error(
                "Ollama did not report %s as resident after warmup", target_model_name
            )
            return False

        self.invalidate_status_snapshot()
        return True

    def unload_model(self, model: str) -> bool:
        """Unload a model from Ollama by sending a keep_alive=0 signal."""
        url = f"{OLLAMA_HOST.rstrip('/')}/api/chat"
        payload = {"model": model, "messages": [], "keep_alive": 0}

        try:
            response = _SESSION.post(url, json=payload, timeout=5.0)
            response.raise_for_status()
            _LOGGER.info("Requested unload for model %s from Ollama", model)
        except (RequestsConnectionError, ConnectionError) as exc:
            _LOGGER.warning(
                "Ollama unreachable while unloading %s: %s",
                model,
                exc,
            )
            return False
        except RequestException as exc:
            _LOGGER.warning("Failed to unload model %s: %s", model, exc)
            return False

        if not self._verify_residency(model, expected=False):
            _LOGGER.warning("Ollama still reports %s as resident after unload", model)
            return False

        self.invalidate_status_snapshot()
        return True


_OLLAMA_BACKEND = OllamaRuntimeBackend()


def get_ollama_runtime_backend() -> OllamaRuntimeBackend:
    """Return the process-wide Ollama local runtime backend."""
    return _OLLAMA_BACKEND
