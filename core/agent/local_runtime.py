"""Provider-neutral coordination for APEX local inference runtimes.

This module owns only the state that must be shared by local providers: the
single admission slot, active/loading provider identity, activity timestamps,
and registered provider lifecycle backends.  A backend keeps ownership of its
provider-specific probes, residency checks, load/unload implementation, and
status payloads.

The coordinator deliberately does not own conversations, prompts, tool
execution, or model-provider protocol state.  Those concerns remain scoped to
the request and provider adapter that use the local runtime.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Protocol


_LOGGER = logging.getLogger(__name__)
_IDLE_CHECK_INTERVAL_SECONDS = 30


@dataclass(frozen=True, slots=True)
class LocalRuntimeIdentity:
    """Provider/model identity for the one shared local residency slot."""

    provider: str
    model: str


class LocalRuntimeBackend(Protocol):
    """Provider-specific lifecycle hook owned by a local backend."""

    provider: str

    def get_status_snapshot(self, *, force_refresh: bool = False) -> Any:
        """Return the backend's provider-specific status snapshot."""

    def is_model_loaded(self, model_name: str) -> bool:
        """Return whether APEX tracks or observes a model as loaded."""

    def is_model_resident(self, model_name: str) -> bool:
        """Return whether the provider reports a model resident."""

    def switch_model(self, profile: object) -> bool:
        """Load or switch to one provider-specific model profile."""

    def unload_active_model(self) -> bool:
        """Unload the provider's active model."""

    def unload_model(self, model_name: str) -> bool:
        """Unload one provider-specific model."""

    def get_idle_unload_remaining_seconds(self) -> int | None:
        """Return the provider's configured idle-unload countdown."""

    def check_idle(self) -> None:
        """Perform one bounded idle-unload check for the provider."""

    def shutdown(self) -> bool:
        """Release provider-owned runtime resources during application shutdown."""

    def reconcile_state(self) -> None:
        """Reconcile provider state after a failed lifecycle operation."""

    def reset_state(self) -> None:
        """Clear provider state after an aborted model switch."""


class LocalRuntimeCoordinator:
    """Coordinate admission and residency state across local providers.

    Provider backends remain responsible for all external runtime operations.
    This class only serializes local work and records the provider-neutral
    identity needed for cross-provider exclusion and HUD lifecycle reporting.
    """

    def __init__(self) -> None:
        self._execution_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._execution_provider: str | None = None
        self._active: LocalRuntimeIdentity | None = None
        self._loading: LocalRuntimeIdentity | None = None
        self._last_activity_time = time.monotonic()
        self._backends: dict[str, LocalRuntimeBackend] = {}

    def register_backend(self, backend: LocalRuntimeBackend) -> None:
        """Register or replace one provider-specific lifecycle backend."""
        provider = str(backend.provider).strip()
        if not provider:
            raise ValueError("Local runtime backends require a provider name.")
        with self._state_lock:
            self._backends[provider] = backend

    def get_backend(self, provider: str) -> LocalRuntimeBackend | None:
        """Return a registered backend without importing provider modules."""
        with self._state_lock:
            return self._backends.get(provider)

    def _require_backend(self, provider: str) -> LocalRuntimeBackend:
        backend = self.get_backend(provider)
        if backend is None:
            raise RuntimeError(f"Local runtime provider is not registered: {provider}")
        return backend

    def get_status_snapshot(self, provider: str, *, force_refresh: bool = False) -> Any:
        """Delegate status reads to a registered provider backend."""
        return self._require_backend(provider).get_status_snapshot(
            force_refresh=force_refresh
        )

    def is_model_loaded(self, provider: str, model_name: str) -> bool:
        """Delegate loaded-model checks to a registered provider backend."""
        return self._require_backend(provider).is_model_loaded(model_name)

    def is_model_resident(self, provider: str, model_name: str) -> bool:
        """Delegate residency checks to a registered provider backend."""
        return self._require_backend(provider).is_model_resident(model_name)

    def switch_model(self, provider: str, profile: object) -> bool:
        """Switch providers under the shared lease and enforce exclusion.

        Every non-target backend is asked to unload, even when the coordinator
        has no tracked active identity.  This allows a provider to detect
        residency that predates the current process or was observed externally.
        """
        target = self._require_backend(provider)
        owner = self.execution_provider()
        acquired = False
        if owner is None:
            if not self.try_begin_execution(provider):
                return False
            acquired = True
        elif owner != provider:
            _LOGGER.warning(
                "Refusing %s model switch while %s owns the local execution lease.",
                provider,
                owner,
            )
            return False

        try:
            for backend in self.backend_snapshot():
                if backend.provider == provider:
                    continue
                try:
                    if not backend.unload_active_model():
                        try:
                            target.reset_state()
                        except Exception:
                            pass
                        _LOGGER.warning(
                            "Refusing %s model switch because %s could not unload.",
                            provider,
                            backend.provider,
                        )
                        return False
                except Exception as exc:
                    try:
                        target.reset_state()
                    except Exception:
                        pass
                    _LOGGER.warning(
                        "Refusing %s model switch after %s unload error: %s",
                        provider,
                        backend.provider,
                        type(exc).__name__,
                    )
                    return False

            try:
                switched = bool(target.switch_model(profile))
            except Exception as exc:
                _LOGGER.warning(
                    "Local provider %s model switch failed: %s",
                    provider,
                    type(exc).__name__,
                )
                switched = False
            if not switched:
                try:
                    target.reset_state()
                except Exception as exc:
                    _LOGGER.warning(
                        "Local provider %s state reconciliation failed: %s",
                        provider,
                        type(exc).__name__,
                    )
            return switched
        finally:
            if acquired:
                self.end_execution(provider)

    def unload_active_model(self, provider: str) -> bool:
        """Delegate active-model unload to a registered provider backend."""
        return self._require_backend(provider).unload_active_model()

    def unload_model(self, provider: str, model_name: str) -> bool:
        """Delegate one provider-specific model unload."""
        return self._require_backend(provider).unload_model(model_name)

    def get_idle_unload_remaining_seconds(self, provider: str) -> int | None:
        """Delegate the provider-specific idle-unload countdown."""
        return self._require_backend(provider).get_idle_unload_remaining_seconds()

    def try_begin_execution(self, provider: str = "local") -> bool:
        """Claim the single local execution slot without blocking."""
        if not self._execution_lock.acquire(blocking=False):
            return False
        with self._state_lock:
            self._execution_provider = provider
        return True

    def end_execution(self, provider: str | None = None) -> None:
        """Release the lease, rejecting releases by the wrong provider."""
        with self._state_lock:
            owner = self._execution_provider
            if owner is None:
                raise RuntimeError("Local execution lease is not held.")
            if provider is not None and owner != provider:
                raise RuntimeError(
                    f"Local execution lease belongs to {owner}, not {provider}."
                )
            self._execution_provider = None
        self._execution_lock.release()

    @contextmanager
    def execution_lease(self, provider: str) -> Iterator[bool]:
        """Attempt a provider-validated non-blocking execution lease."""
        acquired = self.try_begin_execution(provider)
        try:
            yield acquired
        finally:
            if acquired:
                self.end_execution(provider)

    def is_execution_active(self) -> bool:
        """Return whether any local provider currently owns the slot."""
        return self._execution_lock.locked()

    def execution_provider(self) -> str | None:
        """Return the provider currently holding the execution slot."""
        with self._state_lock:
            return self._execution_provider

    def mark_loading(self, provider: str, model: str | None) -> None:
        """Record a provider/model while its backend is loading."""
        identity = (
            LocalRuntimeIdentity(provider=provider, model=model)
            if model is not None
            else None
        )
        with self._state_lock:
            self._loading = identity

    def clear_loading(self, provider: str, model: str | None = None) -> None:
        """Clear loading state when it still belongs to the supplied target."""
        with self._state_lock:
            if self._loading is None or self._loading.provider != provider:
                return
            if model is not None and self._loading.model != model:
                return
            self._loading = None

    def get_loading_identity(self, provider: str | None = None) -> LocalRuntimeIdentity | None:
        """Return the loading identity, optionally filtered by provider."""
        with self._state_lock:
            if provider is not None and (
                self._loading is None or self._loading.provider != provider
            ):
                return None
            return self._loading

    def get_loading_model(self, provider: str | None = None) -> str | None:
        """Return the loading model name, optionally filtered by provider."""
        identity = self.get_loading_identity(provider)
        return identity.model if identity is not None else None

    def mark_active(self, provider: str, model: str) -> None:
        """Record a verified resident provider/model and refresh activity."""
        with self._state_lock:
            self._active = LocalRuntimeIdentity(provider=provider, model=model)
            self._last_activity_time = time.monotonic()

    def clear_active(self, provider: str, model: str | None = None) -> bool:
        """Clear active state when it still belongs to the supplied provider."""
        with self._state_lock:
            if self._active is None or self._active.provider != provider:
                return False
            if model is not None and self._active.model != model:
                return False
            self._active = None
            return True

    def get_active_identity(self, provider: str | None = None) -> LocalRuntimeIdentity | None:
        """Return the active identity, optionally filtered by provider."""
        with self._state_lock:
            if provider is not None and (
                self._active is None or self._active.provider != provider
            ):
                return None
            return self._active

    def get_active_model(self, provider: str | None = None) -> str | None:
        """Return the active model name, optionally filtered by provider."""
        identity = self.get_active_identity(provider)
        return identity.model if identity is not None else None

    def register_activity(self, provider: str, model: str) -> None:
        """Refresh activity for a completed generation.

        The legacy Ollama lifecycle initialized active state lazily from the
        first completed provider turn.  Preserve that behavior while keeping
        an explicit provider identity in the coordinator.
        """
        with self._state_lock:
            self._last_activity_time = time.monotonic()
            if self._active is None:
                self._active = LocalRuntimeIdentity(provider=provider, model=model)

    def idle_remaining_seconds(self, provider: str, idle_minutes: int) -> int | None:
        """Return seconds remaining before the provider's idle threshold."""
        with self._state_lock:
            if self._active is None or self._active.provider != provider:
                return None
            elapsed = time.monotonic() - self._last_activity_time
            remaining = (idle_minutes * 60) - elapsed
            return max(0, int(remaining))

    def idle_candidate(
        self, provider: str, idle_minutes: int
    ) -> tuple[str, float] | None:
        """Snapshot an idle model for a backend's bounded unload attempt."""
        with self._state_lock:
            if self._active is None or self._active.provider != provider:
                return None
            activity_snapshot = self._last_activity_time
            idle_seconds = time.monotonic() - activity_snapshot
            if idle_seconds < idle_minutes * 60:
                return None
            return self._active.model, activity_snapshot

    def clear_active_if_unchanged(
        self, provider: str, model: str, activity_snapshot: float
    ) -> bool:
        """Clear a stale idle candidate only when no new activity intervened."""
        with self._state_lock:
            if (
                self._active is None
                or self._active.provider != provider
                or self._active.model != model
                or self._last_activity_time != activity_snapshot
            ):
                return False
            self._active = None
            return True

    def backend_snapshot(self) -> tuple[LocalRuntimeBackend, ...]:
        """Return a stable backend list for the idle monitor."""
        with self._state_lock:
            return tuple(self._backends.values())

    def shutdown(self) -> bool:
        """Shut down every registered backend and clear shared identities."""
        success = True
        for backend in self.backend_snapshot():
            try:
                if not backend.shutdown():
                    success = False
            except Exception as exc:
                success = False
                _LOGGER.warning(
                    "Local provider %s shutdown failed: %s",
                    backend.provider,
                    type(exc).__name__,
                )
        with self._state_lock:
            self._active = None
            self._loading = None
            self._execution_provider = None
        if self._execution_lock.locked():
            try:
                self._execution_lock.release()
            except RuntimeError:
                pass
        return success


LOCAL_RUNTIME = LocalRuntimeCoordinator()


def try_begin_local_execution(provider: str = "local") -> bool:
    """Compatibility facade for callers migrating to the coordinator."""
    return LOCAL_RUNTIME.try_begin_execution(provider)


def end_local_execution(provider: str | None = None) -> None:
    """Compatibility facade for releasing the shared local slot."""
    LOCAL_RUNTIME.end_execution(provider)


def is_local_execution_active() -> bool:
    """Compatibility facade for checking shared local admission state."""
    return LOCAL_RUNTIME.is_execution_active()


def get_active_loaded_model(provider: str = "ollama") -> str | None:
    """Compatibility facade for provider-neutral active-model identity."""
    return LOCAL_RUNTIME.get_active_model(provider)


def get_loading_model(provider: str = "ollama") -> str | None:
    """Compatibility facade for provider-neutral loading identity."""
    return LOCAL_RUNTIME.get_loading_model(provider)


def get_idle_unload_remaining_seconds(provider: str = "ollama") -> int | None:
    """Compatibility facade for provider-neutral idle-unload countdowns."""
    return LOCAL_RUNTIME.get_idle_unload_remaining_seconds(provider)


def get_status_snapshot(provider: str = "ollama", *, force_refresh: bool = False) -> Any:
    """Compatibility facade for provider-neutral status access."""
    return LOCAL_RUNTIME.get_status_snapshot(provider, force_refresh=force_refresh)


def is_local_model_loaded(model_name: str, provider: str = "ollama") -> bool:
    """Compatibility facade for provider-neutral loaded-model checks."""
    return LOCAL_RUNTIME.is_model_loaded(provider, model_name)


def is_local_model_resident(model_name: str, provider: str = "ollama") -> bool:
    """Compatibility facade for provider-neutral residency checks."""
    return LOCAL_RUNTIME.is_model_resident(provider, model_name)


def switch_local_model(profile: object, provider: str = "ollama") -> bool:
    """Compatibility facade for provider-neutral model switching."""
    return LOCAL_RUNTIME.switch_model(provider, profile)


def unload_active_local_model(provider: str = "ollama") -> bool:
    """Compatibility facade for provider-neutral active-model unload."""
    return LOCAL_RUNTIME.unload_active_model(provider)


def unload_local_model(model_name: str, provider: str = "ollama") -> bool:
    """Compatibility facade for provider-neutral single-model unload."""
    return LOCAL_RUNTIME.unload_model(provider, model_name)


async def check_idle_models_loop() -> None:
    """Run the registered provider idle checks until application shutdown."""
    while True:
        try:
            await asyncio.sleep(_IDLE_CHECK_INTERVAL_SECONDS)
            for backend in LOCAL_RUNTIME.backend_snapshot():
                try:
                    await asyncio.to_thread(backend.check_idle)
                except Exception as exc:
                    _LOGGER.warning(
                        "Idle model check failed for provider %s: %s",
                        backend.provider,
                        exc,
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.warning("Local idle model check failed: %s", exc)
