"""llama.cpp local-runtime backend: discovery, load, unload, and residency."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, ClassVar

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout as RequestsTimeout,
)

from core.agent.local_runtime.contract import (
    LocalModelProfile,
    LocalModelState,
    LocalRuntimeModel,
    LocalRuntimeSnapshot,
)
from core.config import (
    LLAMA_CPP_IDLE_UNLOAD_MINUTES,
    LLAMA_CPP_MANUAL_UNLOAD_ENABLED,
    LLAMA_CPP_REQUEST_TIMEOUT_SECONDS,
)
from core.agent.providers.llama_cpp_runtime import (
    get_llama_cpp_host,
    get_llama_cpp_runtime_settings,
    is_llama_cpp_enabled,
)

_LOGGER = logging.getLogger(__name__)

_SESSION = requests.Session()
_STATUS_CACHE_TTL_SECONDS = 10.0
_STATUS_PROBE_TIMEOUT_SECONDS = 2.0
_POLL_INTERVAL_SECONDS = 0.35
_KNOWN_STATES: frozenset[str] = frozenset(
    {"unloaded", "loading", "loaded", "sleeping", "failed", "downloading", "unknown"}
)


def get_http_session() -> requests.Session:
    """Return the shared HTTP session for all llama.cpp router traffic."""
    return _SESSION


def get_auth_headers() -> dict[str, str]:
    """Return optional Authorization headers without logging secrets."""
    api_key = os.getenv("LLAMA_CPP_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        return {}
    return {"Authorization": f"Bearer {api_key.strip()}"}


def _auth_headers() -> dict[str, str]:
    return get_auth_headers()


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _normalize_model_state(raw: object) -> LocalModelState:
    if not isinstance(raw, str):
        return "unknown"
    normalized = raw.strip().lower()
    if normalized == "downloading":
        return "loading"
    if normalized in _KNOWN_STATES and normalized != "downloading":
        return normalized  # type: ignore[return-value]
    return "unknown"


def _extract_model_rows(payload: object) -> tuple[bool, list[dict[str, Any]]]:
    """
    Parse a /models payload into (shape_ok, rows).

    Accepted shapes are a top-level list, ``{"data": [...]}``, or
    ``{"models": [...]}``. Any other dictionary fails closed.
    """
    if isinstance(payload, list):
        return True, [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return False, []
    for key in ("data", "models"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return True, [row for row in rows if isinstance(row, dict)]
    return False, []


def _model_id_from_row(row: dict[str, Any]) -> str | None:
    for key in ("id", "model", "name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _context_window_from_args(args: object) -> int | None:
    """Extract context size from router status.args CLI tokens."""
    if not isinstance(args, list):
        return None

    flag_tokens = {"-ctx", "--ctx-size", "--ctx_size", "-c"}
    for index, token in enumerate(args):
        if not isinstance(token, str):
            continue
        stripped = token.strip()
        for prefix in ("--ctx-size=", "--ctx_size=", "-ctx=", "-c="):
            if stripped.startswith(prefix):
                return _coerce_optional_int(stripped[len(prefix) :])
        if stripped in flag_tokens and index + 1 < len(args):
            return _coerce_optional_int(args[index + 1])
    return None


def _parse_row_status(row: dict[str, Any]) -> tuple[LocalModelState, int | None]:
    """
    Normalize router status into a LocalModelState and optional context window.

    Official router builds report ``status`` as an object with ``value``,
    optional ``failed``, and ``args``. Older synthetic fixtures used a flat
    string; both forms are accepted.
    """
    status_raw = row.get("status")
    status_value: object
    failed = False
    args: object = None

    if isinstance(status_raw, dict):
        status_value = status_raw.get("value")
        failed = status_raw.get("failed") is True
        args = status_raw.get("args")
    elif isinstance(status_raw, str):
        status_value = status_raw
    else:
        status_value = row.get("state")

    state: LocalModelState = (
        "failed" if failed else _normalize_model_state(status_value)
    )

    context_window = _coerce_optional_int(
        row.get("n_ctx")
        or row.get("context_window")
        or row.get("ctx_size")
        or row.get("context")
    )
    if context_window is None:
        context_window = _context_window_from_args(args)
    return state, context_window


def _probe_models() -> tuple[bool, list[str], list[LocalRuntimeModel]]:
    """Probe GET /models for reachability, router-reported IDs, and residency."""
    host = get_llama_cpp_host()
    url = f"{host.rstrip('/')}/models"
    try:
        response = _SESSION.get(
            url,
            headers=_auth_headers(),
            timeout=_STATUS_PROBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (RequestsConnectionError, ConnectionError) as exc:
        _LOGGER.warning("llama.cpp router unreachable at %s: %s", url, type(exc).__name__)
        return False, [], []
    except RequestsTimeout as exc:
        _LOGGER.warning("llama.cpp models probe timed out at %s: %s", url, type(exc).__name__)
        return False, [], []
    except RequestException as exc:
        _LOGGER.warning("llama.cpp models request failed at %s: %s", url, type(exc).__name__)
        return False, [], []
    except ValueError as exc:
        _LOGGER.warning(
            "llama.cpp models response was not valid JSON from %s: %s",
            url,
            type(exc).__name__,
        )
        return False, [], []

    shape_ok, rows = _extract_model_rows(payload)
    if not shape_ok:
        _LOGGER.warning(
            "llama.cpp models response missing recognized model array from %s",
            url,
        )
        return False, [], []

    installed: list[str] = []
    loaded_models: list[LocalRuntimeModel] = []
    seen_ids: set[str] = set()

    for row in rows:
        model_id = _model_id_from_row(row)
        if model_id is None:
            continue
        if model_id not in seen_ids:
            installed.append(model_id)
            seen_ids.add(model_id)

        state, context_window = _parse_row_status(row)
        if state in {"loading", "loaded", "sleeping", "failed"}:
            loaded_models.append(
                LocalRuntimeModel(
                    provider="llama_cpp",
                    name=model_id,
                    model=model_id,
                    state=state,
                    size_bytes=_coerce_optional_int(row.get("size") or row.get("size_bytes")),
                    size_vram_bytes=_coerce_optional_int(
                        row.get("size_vram") or row.get("size_vram_bytes")
                    ),
                    processor=_coerce_optional_str(row.get("processor")),
                    context=_coerce_optional_str(context_window),
                    context_window=context_window,
                    expires_at=None,
                )
            )

    return True, installed, loaded_models


def _probe_props(model: str) -> dict[str, Any] | None:
    """Optionally fetch /props without triggering autoload."""
    host = get_llama_cpp_host()
    url = f"{host.rstrip('/')}/props"
    try:
        response = _SESSION.get(
            url,
            params={"model": model, "autoload": "false"},
            headers=_auth_headers(),
            timeout=_STATUS_PROBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (RequestException, ValueError) as exc:
        _LOGGER.info(
            "llama.cpp /props unavailable for %s: %s",
            model,
            type(exc).__name__,
        )
        return None
    if not isinstance(payload, dict):
        return None
    return payload


class LlamaCppRuntimeBackend:
    """llama.cpp-specific discovery, load, unload, and residency operations."""

    provider: ClassVar[str] = "llama_cpp"

    def __init__(self) -> None:
        self._status_lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._status_snapshot: LocalRuntimeSnapshot | None = None
        self._status_epoch = 0

    @property
    def enabled(self) -> bool:
        return is_llama_cpp_enabled()

    @property
    def idle_unload_seconds(self) -> int:
        return int(LLAMA_CPP_IDLE_UNLOAD_MINUTES) * 60

    @property
    def manual_unload_enabled(self) -> bool:
        return bool(LLAMA_CPP_MANUAL_UNLOAD_ENABLED)

    def invalidate_status_snapshot(self) -> None:
        """Discard cached router state after a verified lifecycle transition."""
        with self._status_lock:
            self._status_snapshot = None
            self._status_epoch += 1

    def _cached_snapshot_if_fresh(
        self,
        *,
        force_refresh: bool,
    ) -> LocalRuntimeSnapshot | None:
        snapshot = self._status_snapshot
        if snapshot is None or force_refresh:
            return None
        age = time.monotonic() - snapshot["sampled_at"]
        if age <= _STATUS_CACHE_TTL_SECONDS:
            return snapshot
        return None

    def get_status_snapshot(
        self,
        *,
        force_refresh: bool = False,
    ) -> LocalRuntimeSnapshot:
        """
        Return router reachability, configured aliases, and loaded models.

        Cache reads/publishes use ``_status_lock`` only; network probes run
        outside that lock. An invalidation epoch prevents stale in-flight
        probes from repopulating the cache after load/unload.
        """
        if is_llama_cpp_enabled():
            from core.agent.providers.llama_cpp_supervisor import (
                get_llama_cpp_server_supervisor,
            )

            supervisor = get_llama_cpp_server_supervisor()
            if get_llama_cpp_runtime_settings().managed:
                supervisor.ensure_ready(allow_restart=True)
            supervisor.maybe_stop_after_idle()

        with self._status_lock:
            cached = self._cached_snapshot_if_fresh(force_refresh=force_refresh)
            if cached is not None:
                return cached

        with self._probe_lock:
            while True:
                with self._status_lock:
                    cached = self._cached_snapshot_if_fresh(force_refresh=force_refresh)
                    if cached is not None:
                        return cached
                    epoch = self._status_epoch

                reachable, installed, loaded = _probe_models()
                fresh: LocalRuntimeSnapshot = {
                    "provider": "llama_cpp",
                    "reachable": reachable,
                    "installed_models": installed,
                    "loaded_models": loaded,
                    "sampled_at": time.monotonic(),
                }
                with self._status_lock:
                    if self._status_epoch == epoch:
                        self._status_snapshot = fresh
                        return fresh
                    force_refresh = False

    def is_model_resident(self, model: str) -> bool:
        """Return whether the router currently reports the model as loaded."""
        for loaded_model in self.get_status_snapshot(force_refresh=True)["loaded_models"]:
            if loaded_model["state"] != "loaded":
                continue
            if loaded_model["name"] == model or loaded_model["model"] == model:
                return True
        return False

    def _wait_for_state(
        self,
        model: str,
        *,
        want_resident: bool,
        timeout_seconds: float,
    ) -> bool:
        deadline = time.monotonic() + max(timeout_seconds, 1.0)
        while time.monotonic() < deadline:
            self.invalidate_status_snapshot()
            snapshot = self.get_status_snapshot(force_refresh=True)
            loaded = [
                row
                for row in snapshot["loaded_models"]
                if row["name"] == model or row["model"] == model
            ]
            if want_resident:
                if any(row["state"] == "loaded" for row in loaded):
                    return True
                if any(row["state"] == "failed" for row in loaded):
                    return False
            else:
                if not loaded or all(
                    row["state"] in {"unloaded", "sleeping"} for row in loaded
                ):
                    # Sleeping is not resident for APEX accounting.
                    if not any(row["state"] == "loaded" for row in loaded):
                        return True
            time.sleep(_POLL_INTERVAL_SECONDS)
        return False

    def load_model(self, profile: LocalModelProfile) -> bool:
        """Explicitly load a configured runtime alias and verify residency."""
        from core.agent.providers.llama_cpp_supervisor import (
            get_llama_cpp_server_supervisor,
        )

        if get_llama_cpp_runtime_settings().managed:
            get_llama_cpp_server_supervisor().ensure_ready(allow_restart=True)
        target = profile.runtime_model_id
        if self.is_model_resident(target):
            _LOGGER.info("Model %s already resident in llama.cpp", target)
            return True

        url = f"{get_llama_cpp_host().rstrip('/')}/models/load"
        try:
            response = _SESSION.post(
                url,
                json={"model": target},
                headers=_auth_headers(),
                timeout=min(float(LLAMA_CPP_REQUEST_TIMEOUT_SECONDS), 30.0),
            )
            response.raise_for_status()
        except (RequestsConnectionError, ConnectionError) as exc:
            _LOGGER.warning(
                "llama.cpp unreachable while loading %s: %s",
                target,
                type(exc).__name__,
            )
            return False
        except RequestException as exc:
            _LOGGER.warning(
                "llama.cpp load failed for %s: %s",
                target,
                type(exc).__name__,
            )
            return False

        timeout = float(getattr(profile, "generation_timeout", LLAMA_CPP_REQUEST_TIMEOUT_SECONDS))
        if not self._wait_for_state(target, want_resident=True, timeout_seconds=timeout):
            _LOGGER.warning(
                "llama.cpp did not report %s as loaded after explicit load",
                target,
            )
            self.invalidate_status_snapshot()
            return False

        props = _probe_props(target)
        if props is not None:
            _LOGGER.info(
                "llama.cpp loaded %s; props available keys=%s",
                target,
                sorted(str(key) for key in props.keys())[:12],
            )
        else:
            _LOGGER.info("Loaded model %s into llama.cpp", target)
        self.invalidate_status_snapshot()
        return True

    def unload_model(self, model: str) -> bool:
        """Explicitly unload a runtime alias and verify it is not resident."""
        url = f"{get_llama_cpp_host().rstrip('/')}/models/unload"
        try:
            response = _SESSION.post(
                url,
                json={"model": model},
                headers=_auth_headers(),
                timeout=5.0,
            )
            response.raise_for_status()
        except (RequestsConnectionError, ConnectionError) as exc:
            _LOGGER.warning(
                "llama.cpp unreachable while unloading %s: %s",
                model,
                type(exc).__name__,
            )
            return False
        except RequestException as exc:
            _LOGGER.warning(
                "llama.cpp unload failed for %s: %s",
                model,
                type(exc).__name__,
            )
            return False

        timeout = float(LLAMA_CPP_REQUEST_TIMEOUT_SECONDS)
        if not self._wait_for_state(model, want_resident=False, timeout_seconds=timeout):
            _LOGGER.warning(
                "llama.cpp still reports %s as resident after unload",
                model,
            )
            self.invalidate_status_snapshot()
            return False

        _LOGGER.info("Unloaded model %s from llama.cpp", model)
        self.invalidate_status_snapshot()
        return True


_LLAMA_CPP_BACKEND = LlamaCppRuntimeBackend()


def get_llama_cpp_runtime_backend() -> LlamaCppRuntimeBackend:
    """Return the process-wide llama.cpp local runtime backend."""
    return _LLAMA_CPP_BACKEND
