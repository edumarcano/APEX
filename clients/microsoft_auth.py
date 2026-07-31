"""Delegated Microsoft authentication for the optional To Do integration."""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import msal
from msal_extensions import PersistedTokenCache, build_encrypted_persistence

MICROSOFT_TODO_SCOPES = ("Tasks.Read",)
_DEFAULT_TENANT = "common"

MicrosoftAuthState = Literal[
    "not-configured",
    "disconnected",
    "authorizing",
    "connected",
    "authentication-required",
    "degraded",
]


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
    ) -> None:
        self.client_id = (client_id if client_id is not None else os.getenv(
            "MICROSOFT_TODO_CLIENT_ID", ""
        )).strip()
        self.tenant_id = (tenant_id if tenant_id is not None else os.getenv(
            "MICROSOFT_TODO_TENANT_ID", _DEFAULT_TENANT
        )).strip() or _DEFAULT_TENANT
        self.cache_path = Path(cache_path) if cache_path else self._default_cache_path()
        self._lock = threading.RLock()
        self._authorization_lock = asyncio.Lock()
        self._flow: dict[str, Any] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._state: MicrosoftAuthState = (
            "disconnected" if self.client_id else "not-configured"
        )
        self._application: msal.PublicClientApplication | None = None
        self._cache: PersistedTokenCache | None = None
        if self.client_id:
            try:
                self._build_application()
                if self._application and self._application.get_accounts():
                    self._state = "connected"
            except Exception:
                self._state = "degraded"

    @staticmethod
    def _default_cache_path() -> Path:
        configured = os.getenv("MICROSOFT_TODO_TOKEN_CACHE_PATH", "").strip()
        if configured:
            return Path(configured)
        base = os.getenv("LOCALAPPDATA") or os.getenv("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
        return root / "APEX" / "auth" / "microsoft_todo_token_cache.bin"

    def _build_application(self) -> None:
        if not self.cache_path.is_absolute():
            raise ValueError("Microsoft token cache path must be absolute.")
        resolved_cache = self.cache_path.resolve()
        project_root = Path(__file__).resolve().parent.parent
        if resolved_cache == project_root or project_root in resolved_cache.parents:
            raise ValueError(
                "Microsoft token cache path must be outside the repository."
            )
        self.cache_path = resolved_cache
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        persistence = build_encrypted_persistence(str(self.cache_path))
        self._cache = PersistedTokenCache(persistence)
        self._application = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=self._cache,
        )

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "configured": bool(self.client_id),
                "state": self._state,
                "permission": "Tasks.Read",
            }

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
                raise MicrosoftTodoAuthenticationRequiredError(
                    "Connect Microsoft To Do in Settings."
                )
            result = self._application.acquire_token_silent(
                list(MICROSOFT_TODO_SCOPES), account=accounts[0]
            )
            token = result.get("access_token") if isinstance(result, dict) else None
            if not isinstance(token, str) or not token:
                self._state = "authentication-required"
                raise MicrosoftTodoAuthenticationRequiredError(
                    "Reconnect Microsoft To Do in Settings."
                )
            self._state = "connected"
            return token

    async def begin_device_authorization(self) -> dict[str, Any]:
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
                raise RuntimeError("Microsoft authorization could not be started.")
            with self._lock:
                self._flow = flow
                self._state = "authorizing"
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
                self._state = (
                    "connected"
                    if isinstance(result, dict) and result.get("access_token")
                    else "authentication-required"
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            with self._lock:
                if self._flow is flow:
                    self._state = "degraded"
        finally:
            with self._lock:
                if self._flow is flow:
                    self._flow = None
                    self._poll_task = None

    @staticmethod
    def _public_flow(flow: dict[str, Any]) -> dict[str, Any]:
        expires_at = flow.get("expires_at")
        if not isinstance(expires_at, (int, float)):
            expires_in = int(flow.get("expires_in") or 0)
            expires_at = datetime.now(timezone.utc).timestamp() + expires_in
        return {
            "state": "authorizing",
            "verification_uri": str(flow.get("verification_uri") or ""),
            "user_code": str(flow.get("user_code") or ""),
            "expires_at": datetime.fromtimestamp(
                float(expires_at), tz=timezone.utc
            ).isoformat(),
        }

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
                self._build_application()
                self._state = "disconnected"
            except Exception:
                self._state = "degraded"
                raise RuntimeError("Microsoft authentication could not be reset.")

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
