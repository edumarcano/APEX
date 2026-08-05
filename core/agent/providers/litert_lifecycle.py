"""LiteRT-specific health and lifecycle backend for the shared local runtime."""

from __future__ import annotations

import logging
import subprocess
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


def _dependency_available() -> tuple[bool, str | None]:
    """Probe package metadata without starting the native worker or engine."""
    interpreter = Path(LITERT_PYTHON_EXECUTABLE)
    if not interpreter.is_file():
        return False, LITERT_INTERPRETER_REASON
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
        return False, LITERT_DEPENDENCY_REASON
    if result.returncode != 0:
        return False, LITERT_DEPENDENCY_REASON
    version = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if version != LITERT_PACKAGE_VERSION:
        return False, LITERT_DEPENDENCY_REASON
    return True, None


def check_litert_resource_gate(profile: LiteRTModelProfile) -> tuple[bool, str | None]:
    """Apply a conservative free-RAM gate before loading a native engine."""
    try:
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
        if (
            profile.minimum_free_ram_mb is not None
            and available_mb < profile.minimum_free_ram_mb
        ):
            return False, "insufficient_ram"
        if psutil.cpu_percent(interval=None) >= 95.0:
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
        self.runtime = LiteRTRuntimeManager(
            interpreter=LITERT_PYTHON_EXECUTABLE,
            project_root=_PROJECT_ROOT,
            load_timeout=LITERT_ENGINE_LOAD_TIMEOUT,
        )
        self._loaded_model: str | None = None

    def get_status_snapshot(self, *, force_refresh: bool = False) -> dict[str, Any]:
        del force_refresh
        return {
            "provider": _PROVIDER,
            "enabled": LITERT_ENABLED,
            "running": self.runtime.is_running,
            "loaded_model": self._loaded_model,
            "engine_model": self.runtime.engine_model,
            "state": "ready" if self._loaded_model else ("unavailable" if not LITERT_ENABLED else "idle"),
        }

    def is_model_loaded(self, model_name: str) -> bool:
        return self._loaded_model == model_name and self.runtime.engine_model is not None

    def is_model_resident(self, model_name: str) -> bool:
        return self.is_model_loaded(model_name)

    def switch_model(self, profile: object) -> bool:
        if not isinstance(profile, LiteRTModelProfile):
            raise TypeError("LiteRT runtime requires a LiteRTModelProfile.")
        artifact = Path(profile.artifact_path or "")
        if not artifact.is_file():
            return False
        if self.is_model_loaded(profile.api_model):
            return True
        # Cross-provider exclusion is explicit: unload a resident Ollama
        # backend before creating the LiteRT engine.
        for backend in LOCAL_RUNTIME.backend_snapshot():
            if backend.provider != _PROVIDER:
                if LOCAL_RUNTIME.get_active_model(backend.provider) is None:
                    continue
                try:
                    backend.unload_active_model()
                except Exception as exc:
                    _LOGGER.warning("Failed to release local provider %s: %s", backend.provider, type(exc).__name__)
        LOCAL_RUNTIME.mark_loading(_PROVIDER, profile.api_model)
        try:
            self.runtime.load_engine(artifact, backend=LITERT_BACKEND)
        except Exception as exc:
            LOCAL_RUNTIME.clear_loading(_PROVIDER, profile.api_model)
            self.runtime.shutdown()
            _LOGGER.warning("LiteRT engine load failed: %s", type(exc).__name__)
            return False
        self._loaded_model = profile.api_model
        LOCAL_RUNTIME.clear_loading(_PROVIDER, profile.api_model)
        LOCAL_RUNTIME.mark_active(_PROVIDER, profile.api_model)
        return True

    def unload_active_model(self) -> bool:
        if self._loaded_model is None:
            return True
        try:
            self.runtime.unload_engine()
        except Exception as exc:
            _LOGGER.warning("LiteRT engine unload failed: %s", type(exc).__name__)
            return False
        model = self._loaded_model
        self._loaded_model = None
        LOCAL_RUNTIME.clear_active(_PROVIDER, model)
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


LITERT_LIFECYCLE = LiteRTLifecycleBackend()
LOCAL_RUNTIME.register_backend(LITERT_LIFECYCLE)
