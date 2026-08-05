"""LiteRT-specific health and lifecycle backend for the shared local runtime."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import psutil

from core.agent.local_runtime import LOCAL_RUNTIME
from core.agent.providers.litert_models import (
    LiteRTModelProfile,
    artifact_resolution_reason,
)
from core.agent.providers.litert_runtime import LiteRTRuntimeManager, restricted_worker_environment
from core.config import (
    LITERT_BACKEND,
    LITERT_ENABLED,
    LITERT_ENGINE_LOAD_TIMEOUT,
    LITERT_MODEL_DIR,
    LITERT_PACKAGE_VERSION,
    LITERT_PYTHON_EXECUTABLE,
    LOCAL_RUNTIME_IDLE_UNLOAD_MINUTES,
)


_LOGGER = logging.getLogger(__name__)
_PROVIDER = "litert"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

LITERT_DISABLED_REASON = "LiteRT local inference is disabled. Set LITERT_ENABLED=true to enable it."
LITERT_INTERPRETER_REASON = "Configure a compatible Python 3.11 LiteRT worker interpreter."
LITERT_DEPENDENCY_REASON = "Install litert-lm-api==0.15.0 in the configured LiteRT worker environment."
LITERT_BUSY_REASON = "Another local inference provider is using the shared local runtime."
_DEPENDENCY_CACHE_TTL_SECONDS = 30.0
_dependency_cache_lock = threading.Lock()
_dependency_cache_key: tuple[str, str] | None = None
_dependency_cache_checked_at = 0.0
_dependency_cache_result: tuple[bool, str | None] | None = None


def _dependency_available() -> tuple[bool, str | None]:
    """Probe package metadata without starting the native worker or engine."""
    global _dependency_cache_key, _dependency_cache_checked_at, _dependency_cache_result
    interpreter = Path(LITERT_PYTHON_EXECUTABLE)
    cache_key = (str(interpreter), LITERT_PACKAGE_VERSION)
    now = time.monotonic()
    with _dependency_cache_lock:
        if (
            _dependency_cache_key == cache_key
            and _dependency_cache_result is not None
            and now - _dependency_cache_checked_at < _DEPENDENCY_CACHE_TTL_SECONDS
        ):
            return _dependency_cache_result

    def store(result: tuple[bool, str | None]) -> tuple[bool, str | None]:
        global _dependency_cache_key, _dependency_cache_checked_at, _dependency_cache_result
        with _dependency_cache_lock:
            _dependency_cache_key = cache_key
            _dependency_cache_checked_at = now
            _dependency_cache_result = result
        return result

    if not interpreter.is_file():
        return store((False, LITERT_INTERPRETER_REASON))
    script = "import importlib.metadata; print(importlib.metadata.version('litert-lm-api'))"
    try:
        result = subprocess.run(
            [str(interpreter), "-c", script],
            cwd=str(_PROJECT_ROOT),
            env=restricted_worker_environment(),
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return store((False, LITERT_DEPENDENCY_REASON))
    if result.returncode != 0:
        return store((False, LITERT_DEPENDENCY_REASON))
    version = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if version != LITERT_PACKAGE_VERSION:
        return store((False, LITERT_DEPENDENCY_REASON))
    return store((True, None))


def clear_litert_dependency_cache() -> None:
    """Clear the metadata probe cache for tests and explicit diagnostics."""
    global _dependency_cache_key, _dependency_cache_checked_at, _dependency_cache_result
    with _dependency_cache_lock:
        _dependency_cache_key = None
        _dependency_cache_checked_at = 0.0
        _dependency_cache_result = None


def check_litert_resource_gate(profile: LiteRTModelProfile) -> tuple[bool, str | None]:
    """Apply percentage and minimum-free-RAM gates before loading an engine."""
    try:
        memory = psutil.virtual_memory()
        available_mb = memory.available / (1024 * 1024)
        if (
            profile.minimum_free_ram_mb is not None
            and available_mb < profile.minimum_free_ram_mb
        ):
            return False, "insufficient_ram"
        if float(memory.percent) >= profile.ram_limit:
            return False, "insufficient_ram"
        if psutil.cpu_percent(interval=None) >= profile.cpu_limit:
            return False, "cpu_overloaded"
    except Exception:
        # A failed optional measurement must not make the provider appear
        # healthy; the load operation will still report a deterministic error.
        return False, "provider_error"
    return True, None


def resolve_litert_agent_status(
    profile: LiteRTModelProfile,
    *,
    agent_key: str,
) -> tuple[str, str | None, bool, bool, int | None]:
    """Return status, sanitized reason, active/loading flags, and idle countdown."""
    if not LITERT_ENABLED:
        return "disabled", LITERT_DISABLED_REASON, False, False, None
    dependency_ok, dependency_reason = _dependency_available()
    if not dependency_ok:
        return "provider_unreachable", dependency_reason, False, False, None
    artifact_reason = artifact_resolution_reason(agent_key)
    if artifact_reason:
        return "model_not_installed", artifact_reason, False, False, None
    LITERT_LIFECYCLE.reconcile_state()
    active_model = LOCAL_RUNTIME.get_active_model(_PROVIDER)
    loading_model = LOCAL_RUNTIME.get_loading_model(_PROVIDER)
    active = active_model == profile.api_model
    loading = loading_model == profile.api_model
    if active:
        return (
            "available",
            None,
            True,
            False,
            LOCAL_RUNTIME.idle_remaining_seconds(
                _PROVIDER, LOCAL_RUNTIME_IDLE_UNLOAD_MINUTES
            ),
        )
    if loading:
        return "configured", None, False, True, None
    if LOCAL_RUNTIME.is_execution_active() and LOCAL_RUNTIME.execution_provider() != _PROVIDER:
        return "busy", LITERT_BUSY_REASON, False, False, None
    gate_open, gate_reason = check_litert_resource_gate(profile)
    if not gate_open:
        if gate_reason in {"insufficient_ram", "cpu_overloaded"}:
            return gate_reason, "Current local resources are below the LiteRT model threshold.", False, False, None
        return "provider_error", "LiteRT local resource status is unavailable.", False, False, None
    return "available", None, False, False, None


class LiteRTLifecycleBackend:
    provider = _PROVIDER

    def __init__(self) -> None:
        self._loaded_model: str | None = None
        self._loaded_artifact: str | None = None
        self.runtime = LiteRTRuntimeManager(
            interpreter=LITERT_PYTHON_EXECUTABLE,
            project_root=_PROJECT_ROOT,
            load_timeout=LITERT_ENGINE_LOAD_TIMEOUT,
            state_callback=self._runtime_state_changed,
        )

    def _runtime_state_changed(self, _reason: str) -> None:
        """Drop provider and coordinator identities after worker state loss."""
        model = self._loaded_model
        self._loaded_model = None
        self._loaded_artifact = None
        LOCAL_RUNTIME.clear_loading(_PROVIDER)
        LOCAL_RUNTIME.clear_active(_PROVIDER, model)

    def reconcile_state(self) -> None:
        """Require a live worker and matching engine before reporting residency."""
        if (
            self._loaded_model is None
            or not self.runtime.is_running
            or self._loaded_artifact is None
            or self.runtime.engine_model != self._loaded_artifact
        ):
            self._runtime_state_changed("reconcile")

    def reset_state(self) -> None:
        """Fail closed after an aborted provider switch."""
        self._clear_state(shutdown_runtime=True)

    def _clear_state(self, *, shutdown_runtime: bool = False) -> None:
        if shutdown_runtime:
            try:
                self.runtime.shutdown()
            except Exception as exc:
                _LOGGER.warning(
                    "LiteRT runtime shutdown during state clear failed: %s",
                    type(exc).__name__,
                )
        self._runtime_state_changed("clear")

    def get_status_snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        del force_refresh
        self.reconcile_state()
        return {
            "provider": _PROVIDER,
            "enabled": LITERT_ENABLED,
            "running": self.runtime.is_running,
            "loaded_model": self._loaded_model,
            "engine_model": self.runtime.engine_model,
            "state": "ready" if self._loaded_model else ("unavailable" if not LITERT_ENABLED else "idle"),
        }

    def is_model_loaded(self, model_name: str) -> bool:
        self.reconcile_state()
        return (
            self._loaded_model == model_name
            and self.runtime.is_running
            and self._loaded_artifact is not None
            and self.runtime.engine_model == self._loaded_artifact
        )

    def is_model_resident(self, model_name: str) -> bool:
        return self.is_model_loaded(model_name)

    def switch_model(self, profile: object) -> bool:
        if not isinstance(profile, LiteRTModelProfile):
            raise TypeError("LiteRT runtime requires a LiteRTModelProfile.")
        artifact = Path(profile.artifact_path or "")
        if not artifact.is_file():
            self._clear_state(shutdown_runtime=True)
            return False
        if self.is_model_loaded(profile.api_model):
            return True
        LOCAL_RUNTIME.mark_loading(_PROVIDER, profile.api_model)
        try:
            self.runtime.load_engine(artifact, backend=LITERT_BACKEND)
        except Exception as exc:
            LOCAL_RUNTIME.clear_loading(_PROVIDER, profile.api_model)
            self._clear_state(shutdown_runtime=True)
            _LOGGER.warning("LiteRT engine load failed: %s", type(exc).__name__)
            return False
        self._loaded_model = profile.api_model
        self._loaded_artifact = str(artifact)
        LOCAL_RUNTIME.clear_loading(_PROVIDER, profile.api_model)
        LOCAL_RUNTIME.mark_active(_PROVIDER, profile.api_model)
        if not self.is_model_loaded(profile.api_model):
            self._clear_state(shutdown_runtime=True)
            return False
        return True

    def unload_active_model(self) -> bool:
        self.reconcile_state()
        if self._loaded_model is None and self.runtime.engine_model is None:
            self._runtime_state_changed("unload_empty")
            return True
        try:
            self.runtime.unload_engine()
        except Exception as exc:
            self._clear_state()
            _LOGGER.warning("LiteRT engine unload failed: %s", type(exc).__name__)
            return False
        self._clear_state()
        return True

    def unload_model(self, model_name: str) -> bool:
        if self._loaded_model != model_name:
            return True
        return self.unload_active_model()

    def get_idle_unload_remaining_seconds(self) -> int | None:
        return LOCAL_RUNTIME.idle_remaining_seconds(
            _PROVIDER, LOCAL_RUNTIME_IDLE_UNLOAD_MINUTES
        )

    def check_idle(self) -> None:
        with LOCAL_RUNTIME.execution_lease(_PROVIDER) as acquired:
            if not acquired:
                return
            candidate = LOCAL_RUNTIME.idle_candidate(
                _PROVIDER, LOCAL_RUNTIME_IDLE_UNLOAD_MINUTES
            )
            if candidate is None:
                return
            model, activity_snapshot = candidate
            if self.unload_active_model():
                LOCAL_RUNTIME.clear_active_if_unchanged(
                    _PROVIDER, model, activity_snapshot
                )

    def shutdown(self) -> bool:
        """Close worker-owned conversations/engine and terminate the worker."""
        try:
            result = self.runtime.shutdown()
        finally:
            self._clear_state()
        return result


LITERT_LIFECYCLE = LiteRTLifecycleBackend()
LOCAL_RUNTIME.register_backend(LITERT_LIFECYCLE)
