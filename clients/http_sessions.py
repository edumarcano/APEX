"""Lifespan-owned synchronous HTTP sessions for HUD data connectors."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Literal, Protocol

import requests

ConnectorName = Literal["market", "weather", "news", "sports"]


class SessionLike(Protocol):
    """Minimal session contract used by connector clients and tests."""

    def get(self, url: str, **kwargs: Any) -> Any:
        ...

    def close(self) -> None:
        ...


class ManagedSession:
    """Serialize access to one reusable Requests session and close it safely."""

    def __init__(self, session: SessionLike) -> None:
        self._session = session
        self._lock = threading.Lock()
        self._closed = False

    def get(self, url: str, **kwargs: Any) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError("HTTP connector session is closed.")
            self._clear_cookies()
            try:
                return self._session.get(url, **kwargs)
            finally:
                self._clear_cookies()

    def _clear_cookies(self) -> None:
        cookies = getattr(self._session, "cookies", None)
        clear = getattr(cookies, "clear", None)
        if callable(clear):
            clear()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._session.close()


class ConnectorHttpSessions:
    """Own one isolated, reusable session for each HUD data provider."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], SessionLike] = requests.Session,
    ) -> None:
        self._sessions: dict[ConnectorName, ManagedSession] = {
            name: ManagedSession(session_factory())
            for name in ("market", "weather", "news", "sports")
        }
        self._closed = False

    def for_connector(self, name: ConnectorName) -> ManagedSession:
        return self._sessions[name]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        for session in self._sessions.values():
            try:
                session.close()
            except Exception as exc:  # pragma: no cover - defensive cleanup
                first_error = first_error or exc
        if first_error is not None:
            raise first_error


_ACTIVE_SESSIONS: ConnectorHttpSessions | None = None


def set_connector_http_sessions(
    sessions: ConnectorHttpSessions | None,
) -> None:
    """Install the lifespan-owned connector sessions for application calls."""
    global _ACTIVE_SESSIONS
    _ACTIVE_SESSIONS = sessions


def get_connector_http_session(name: ConnectorName) -> ManagedSession | None:
    """Return an installed provider session, or ``None`` outside app lifespan."""
    if _ACTIVE_SESSIONS is None:
        return None
    return _ACTIVE_SESSIONS.for_connector(name)


def reset_connector_http_sessions_for_tests() -> None:
    """Clear the installed registry without closing externally-owned sessions."""
    global _ACTIVE_SESSIONS
    _ACTIVE_SESSIONS = None
