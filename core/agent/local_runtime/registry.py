"""Static process-wide registry of local runtime backends."""

from __future__ import annotations

from core.agent.local_runtime.contract import LocalRuntimeBackend
from core.agent.providers.contract import LocalInferenceProvider


def _ollama_backend() -> LocalRuntimeBackend:
    from core.agent.providers.ollama_lifecycle import get_ollama_runtime_backend

    return get_ollama_runtime_backend()


def get_local_runtime_backend(
    provider: LocalInferenceProvider,
) -> LocalRuntimeBackend:
    """Return the process-wide backend for a local inference provider."""
    if provider == "ollama":
        return _ollama_backend()
    raise KeyError(f"Unsupported local inference provider: {provider!r}")


def iter_local_runtime_backends(
    *,
    enabled_only: bool = False,
) -> tuple[LocalRuntimeBackend, ...]:
    """Return registered local backends, optionally filtering to enabled ones."""
    backends = (get_local_runtime_backend("ollama"),)
    if enabled_only:
        return tuple(backend for backend in backends if backend.enabled)
    return backends


def any_local_runtime_enabled() -> bool:
    """Return whether at least one local runtime backend is enabled."""
    return any(backend.enabled for backend in iter_local_runtime_backends())
