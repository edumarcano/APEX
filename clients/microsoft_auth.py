"""Delegated Microsoft authentication for the optional To Do integration."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import msal
from msal_extensions import PersistedTokenCache, build_encrypted_persistence

from clients.microsoft_todo_models import (
    MicrosoftAuthState,
    MicrosoftTodoAuthErrorCode,
    MicrosoftTodoAuthConfig,
    MicrosoftTodoAuthStatus,
    MicrosoftTodoDeviceAuthorization,
)

MICROSOFT_TODO_SCOPES = ("Tasks.ReadWrite",)
_DEFAULT_TENANT = "common"
_LOGGER = logging.getLogger(__name__)

_AUTH_FAILURES: dict[str, tuple[MicrosoftTodoAuthErrorCode, str]] = {
    "access_denied": ("cancelled", "Microsoft sign-in was cancelled or permission was declined."),
    "authorization_declined": ("cancelled", "Microsoft sign-in was cancelled or permission was declined."),
    "bad_verification_code": ("expired", "The Microsoft sign-in code is invalid or has expired. Start a new connection."),
    "expired_token": ("expired", "The Microsoft sign-in code has expired. Start a new connection."),
    "invalid_client": ("app-configuration", "Microsoft rejected this app registration. Check its client ID and public-client settings."),
    "unauthorized_client": ("app-configuration", "Microsoft rejected this app registration. Check supported accounts and public-client settings."),
    "invalid_scope": ("permission", "Microsoft rejected the requested To Do permission. Confirm delegated Tasks.ReadWrite is configured."),
    "invalid_request": ("request", "Microsoft rejected the sign-in request. Check the app registration settings."),
}
_DEFAULT_AUTH_FAILURE: tuple[MicrosoftTodoAuthErrorCode, str] = (
    "sign-in-failed",
    "Microsoft did not complete sign-in. Start a new connection and try again.",
)
_RECONNECT_FOR_WRITE_PERMISSION = (
    "Reconnect Microsoft To Do to grant Tasks.ReadWrite."
)

MicrosoftTodoApplicationFactory = Callable[[MicrosoftTodoAuthConfig], tuple[Any, Any]]


def _create_msal_application(
    config: MicrosoftTodoAuthConfig,
) -> tuple[msal.PublicClientApplication, PersistedTokenCache]:
    """Build encrypted persistence and an MSAL application for one configuration."""
    if not config.cache_path.is_absolute():
        raise ValueError("Microsoft token cache path must be absolute.")
    resolved_cache = config.cache_path.resolve()
    project_root = Path(__file__).resolve().parent.parent
    if resolved_cache == project_root or project_root in resolved_cache.parents:
        raise ValueError("Microsoft token cache path must be outside the repository.")
    resolved_cache.parent.mkdir(parents=True, exist_ok=True)
    persistence = build_encrypted_persistence(str(resolved_cache))
    cache = PersistedTokenCache(persistence)
    application = msal.PublicClientApplication(
        config.client_id,
        authority=f"https://login.microsoftonline.com/{config.tenant_id}",
        token_cache=cache,
    )
    return application, cache


class MicrosoftTodoNotConfiguredError(RuntimeError):
    """Raised when the Microsoft application identifier is absent."""


class MicrosoftTodoAuthenticationRequiredError(RuntimeError):
    """Raised when no usable delegated token is available."""


class MicrosoftTodoAuthenticationService:
    """Own MSAL state, encrypted persistence, and one device-code flow."""

    def __init__(
        self,
        *,
        client_id: str | None = None,
        tenant_id: str | None = None,
        cache_path: str | Path | None = None,
        config: MicrosoftTodoAuthConfig | None = None,
        application_factory: MicrosoftTodoApplicationFactory | None = None,
    ) -> None:
        if config is not None and any(value is not None for value in (client_id, tenant_id, cache_path)):
            raise ValueError("Use either config or individual Microsoft authentication settings.")
        self.config = config or MicrosoftTodoAuthConfig(
            client_id=(client_id if client_id is not None else os.getenv(
                "MICROSOFT_TODO_CLIENT_ID", ""
            )).strip(),
            tenant_id=(tenant_id if tenant_id is not None else os.getenv(
                "MICROSOFT_TODO_TENANT_ID", _DEFAULT_TENANT
            )).strip() or _DEFAULT_TENANT,
            cache_path=Path(cache_path) if cache_path else self._default_cache_path(),
        )
        self.client_id = self.config.client_id
        self.tenant_id = self.config.tenant_id
        self.cache_path = self.config.cache_path
        self._application_factory = application_factory or _create_msal_application
        self._lock = threading.RLock()
        self._authorization_lock = asyncio.Lock()
        self._flow: dict[str, Any] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._state: MicrosoftAuthState = (
            "disconnected" if self.config.client_id else "not-configured"
        )
        self._application: Any | None = None
        self._cache: Any | None = None
        self._auth_error: tuple[MicrosoftTodoAuthErrorCode, str] | None = None
        if self.config.client_id:
            try:
                self._initialize_application()
                self._refresh_cached_authorization()
            except Exception:
                self._state = "degraded"
                self._auth_error = (
                    "initialization-failed",
                    "Microsoft authentication could not be initialized on this device.",
                )

    @staticmethod
    def _default_cache_path() -> Path:
        configured = os.getenv("MICROSOFT_TODO_TOKEN_CACHE_PATH", "").strip()
        if configured:
            return Path(configured)
        base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
        return root / "APEX" / "auth" / "microsoft_todo_token_cache.bin"

    def _initialize_application(self) -> None:
        self._application, self._cache = self._application_factory(self.config)

    def status_snapshot(self) -> MicrosoftTodoAuthStatus:
        with self._lock:
            return MicrosoftTodoAuthStatus(
                configured=bool(self.config.client_id),
                state=self._state,
                auth_error_code=self._auth_error[0] if self._auth_error else None,
                auth_error_message=self._auth_error[1] if self._auth_error else None,
            )

    def _refresh_cached_authorization(self) -> None:
        """Classify the persisted grant once without making status polling interactive."""
        if self._application is None:
            self._state = "degraded"
            return
        accounts = self._application.get_accounts()
        if not accounts:
            self._state = "disconnected"
            self._auth_error = None
            return
        result = self._application.acquire_token_silent(
            list(MICROSOFT_TODO_SCOPES), account=accounts[0]
        )
        token = result.get("access_token") if isinstance(result, dict) else None
        if isinstance(token, str) and token:
            self._state = "connected"
            self._auth_error = None
            return
        self._state = "authentication-required"
        self._auth_error = ("permission", _RECONNECT_FOR_WRITE_PERMISSION)

    def acquire_access_token(self) -> str:
        """Return a cached/refreshable token without starting interactive auth."""
        with self._lock:
            if not self.client_id:
                raise MicrosoftTodoNotConfiguredError(
                    "Microsoft To Do is not configured."
                )
            if self._application is None:
                raise MicrosoftTodoAuthenticationRequiredError(
                    "Microsoft To Do authentication is unavailable."
                )
            accounts = self._application.get_accounts()
            if not accounts:
                self._state = "authentication-required"
                self._auth_error = ("permission", _RECONNECT_FOR_WRITE_PERMISSION)
                raise MicrosoftTodoAuthenticationRequiredError(
                    _RECONNECT_FOR_WRITE_PERMISSION
                )
            result = self._application.acquire_token_silent(
                list(MICROSOFT_TODO_SCOPES), account=accounts[0]
            )
            token = result.get("access_token") if isinstance(result, dict) else None
            if not isinstance(token, str) or not token:
                self._state = "authentication-required"
                self._auth_error = ("permission", _RECONNECT_FOR_WRITE_PERMISSION)
                raise MicrosoftTodoAuthenticationRequiredError(
                    _RECONNECT_FOR_WRITE_PERMISSION
                )
            self._state = "connected"
            self._auth_error = None
            return token

    def mark_authentication_required(self) -> None:
        """Reflect a rejected Graph token in the visible connection state."""
        with self._lock:
            self._state = "authentication-required"
            self._auth_error = ("permission", _RECONNECT_FOR_WRITE_PERMISSION)

    async def begin_device_authorization(self) -> MicrosoftTodoDeviceAuthorization:
        if not self.client_id:
            raise MicrosoftTodoNotConfiguredError("Microsoft To Do is not configured.")
        async with self._authorization_lock:
            with self._lock:
                if self._application is None:
                    raise RuntimeError("Microsoft To Do authentication is unavailable.")
                if self._poll_task is not None and not self._poll_task.done() and self._flow:
                    return self._public_flow(self._flow)
                application = self._application
            flow = await asyncio.to_thread(
                application.initiate_device_flow,
                scopes=list(MICROSOFT_TODO_SCOPES),
            )
            if not isinstance(flow, dict) or not flow.get("user_code"):
                with self._lock:
                    self._state = "degraded"
                    self._record_auth_failure(flow if isinstance(flow, dict) else None)
                raise RuntimeError("Microsoft authorization could not be started.")
            with self._lock:
                self._flow = flow
                self._state = "authorizing"
                self._auth_error = None
                self._poll_task = asyncio.create_task(self._complete_device_flow(flow))
            return self._public_flow(flow)

    async def _complete_device_flow(self, flow: dict[str, Any]) -> None:
        try:
            if self._application is None:
                return
            result = await asyncio.to_thread(
                self._application.acquire_token_by_device_flow, flow
            )
            with self._lock:
                if self._flow is not flow:
                    return
                if isinstance(result, dict) and result.get("access_token"):
                    # The just-completed device flow requested exactly
                    # MICROSOFT_TODO_SCOPES, so its token is authoritative.
                    self._state = "connected"
                    self._auth_error = None
                else:
                    self._state = "authentication-required"
                    self._record_auth_failure(result if isinstance(result, dict) else None)
        except asyncio.CancelledError:
            raise
        except Exception:
            with self._lock:
                if self._flow is flow:
                    self._state = "degraded"
                    self._record_auth_failure(None)
        finally:
            with self._lock:
                if self._flow is flow:
                    self._flow = None
                    self._poll_task = None

    @staticmethod
    def _public_flow(flow: dict[str, Any]) -> MicrosoftTodoDeviceAuthorization:
        expires_at = flow.get("expires_at")
        if not isinstance(expires_at, (int, float)):
            expires_in = int(flow.get("expires_in") or 0)
            expires_at = datetime.now(timezone.utc).timestamp() + expires_in
        return MicrosoftTodoDeviceAuthorization(
            verification_uri=str(flow.get("verification_uri") or ""),
            user_code=str(flow.get("user_code") or ""),
            expires_at=datetime.fromtimestamp(
                float(expires_at), tz=timezone.utc
            ).isoformat(),
        )

    async def disconnect(self) -> None:
        await self._cancel_polling()
        with self._lock:
            self._application = None
            self._cache = None
            try:
                self.cache_path.unlink(missing_ok=True)
            except OSError:
                self._state = "degraded"
                raise RuntimeError("Microsoft authorization could not be removed.")
            try:
                self._initialize_application()
                self._state = "disconnected"
                self._auth_error = None
            except Exception:
                self._state = "degraded"
                raise RuntimeError("Microsoft authentication could not be reset.")

    def _record_auth_failure(self, result: dict[str, Any] | None) -> None:
        """Keep only a locally classified error; never retain upstream details."""
        upstream_code = result.get("error") if result else None
        failure = _AUTH_FAILURES.get(upstream_code, _DEFAULT_AUTH_FAILURE)
        self._auth_error = failure
        _LOGGER.warning("Microsoft To Do authentication failed: category=%s", failure[0])

    async def _cancel_polling(self) -> None:
        with self._lock:
            flow = self._flow
            task = self._poll_task
            self._flow = None
            self._poll_task = None
            if flow is not None:
                flow["expires_at"] = 0
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        await self._cancel_polling()


_SERVICE: MicrosoftTodoAuthenticationService | None = None


def set_microsoft_auth_service(
    service: MicrosoftTodoAuthenticationService | None,
) -> None:
    global _SERVICE
    _SERVICE = service


def get_microsoft_auth_service() -> MicrosoftTodoAuthenticationService | None:
    return _SERVICE
