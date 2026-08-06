"""APEX-owned llama.cpp router process supervision.

Owns optional start/stop of a user-installed ``llama-server`` process. Model
load and unload remain in ``llama_cpp_lifecycle``. Never terminates a server
that APEX did not launch.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from requests.exceptions import RequestException

from core.agent.local_runtime.coordinator import (
    get_loading_local_model,
    is_local_execution_active,
)
from core.agent.providers.llama_cpp_runtime import get_llama_cpp_runtime_settings
from core.settings.models import (
    LlamaCppServerOwnership,
    LlamaCppServerState,
    LlamaCppServerStatusResponse,
    LlamaCppSettings,
)
from core.settings.store import get_settings_store

_LOGGER = logging.getLogger(__name__)

_STARTUP_TIMEOUT_SECONDS = 45.0
_STARTUP_POLL_SECONDS = 0.5
_SHUTDOWN_GRACE_SECONDS = 8.0
_PROBE_TIMEOUT_SECONDS = 2.0
_LOG_TAIL_LINES = 40
_LOG_LINE_MAX = 400
_ERROR_MAX = 280

_WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s\"']+")
_UNIX_PATH_RE = re.compile(r"(?<![\w-])(/[^\s\"']+)")
_USER_HOME_RE = re.compile(r"(?i)\bUsers[/\\][^/\\\s\"']+")


@dataclass(frozen=True)
class _BindAddress:
    host: str
    port: int


class LlamaCppManagedServerError(RuntimeError):
    """Raised when managed llama.cpp configuration or launch fails."""


def parse_loopback_bind(host_url: str) -> _BindAddress:
    """Derive ``--host`` / ``--port`` bind values from a validated loopback URL."""
    parsed = urlparse(host_url.strip().rstrip("/"))
    hostname = (parsed.hostname or "").lower()
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise LlamaCppManagedServerError(
            "Managed llama.cpp host must target a loopback address."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise LlamaCppManagedServerError(
            "Managed llama.cpp host must include a valid port."
        ) from exc
    if port is None or port < 1 or port > 65535:
        raise LlamaCppManagedServerError(
            "Managed llama.cpp host must include a valid port."
        )
    if hostname == "::1":
        return _BindAddress(host="::1", port=port)
    if hostname == "localhost":
        return _BindAddress(host="127.0.0.1", port=port)
    return _BindAddress(host=hostname, port=port)


def build_llama_server_args(
    *,
    executable_path: str,
    preset_path: str,
    bind: _BindAddress,
) -> list[str]:
    """Return the argv sequence for a managed llama-server launch."""
    return [
        executable_path,
        "--host",
        bind.host,
        "--port",
        str(bind.port),
        "--models-preset",
        preset_path,
        "--models-max",
        "1",
        "--no-models-autoload",
    ]


def windows_creationflags() -> int:
    """Return subprocess creation flags that avoid a second console window."""
    if sys.platform != "win32":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))


def sanitize_process_text(text: str, *, max_length: int = _ERROR_MAX) -> str:
    """Strip filesystem paths and truncate text before exposing it."""
    cleaned = text.replace("\r", "\n")
    cleaned = _WINDOWS_PATH_RE.sub("<path>", cleaned)
    cleaned = _UNIX_PATH_RE.sub("<path>", cleaned)
    cleaned = _USER_HOME_RE.sub("Users/<redacted>", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_length:
        return cleaned[: max_length - 3] + "..."
    return cleaned


def validate_managed_paths(settings: LlamaCppSettings) -> None:
    """Require existing executable and preset files when managed mode is on."""
    executable = Path(settings.executable_path)
    preset = Path(settings.preset_path)
    if not settings.executable_path or not executable.is_file():
        raise LlamaCppManagedServerError(
            "Managed llama.cpp executable_path must point to an existing file."
        )
    if not settings.preset_path or not preset.is_file():
        raise LlamaCppManagedServerError(
            "Managed llama.cpp preset_path must point to an existing file."
        )


def probe_router_reachable(host: str, *, timeout: float = _PROBE_TIMEOUT_SECONDS) -> bool:
    """Return True when ``GET {host}/models`` succeeds."""
    from core.agent.providers.llama_cpp_lifecycle import get_auth_headers, get_http_session

    url = f"{host.rstrip('/')}/models"
    try:
        response = get_http_session().get(
            url,
            headers=get_auth_headers(),
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except (RequestException, ValueError, OSError):
        return False


class LlamaCppServerSupervisor:
    """Supervise an optional APEX-owned llama-server child process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._owned = False
        self._state: LlamaCppServerState = "disabled"
        self._last_error: str | None = None
        self._log_tail: deque[str] = deque(maxlen=_LOG_TAIL_LINES)
        # After an unexpected exit, one restart may be consumed by ensure_ready.
        self._restart_allowed = False
        self._stop_after_idle = False
        self._launch_identity: tuple[str, str, str, bool] | None = None
        self._reader_threads: list[threading.Thread] = []

    def status_snapshot(self) -> LlamaCppServerStatusResponse:
        """Return sanitized ownership state without filesystem paths."""
        with self._lock:
            settings = get_llama_cpp_runtime_settings()
            self._reconcile_process_locked()
            if self._stop_after_idle and not is_local_execution_active():
                self._stop_after_idle = False
                if self._owned and self._process_alive_locked():
                    self._stop_owned_process_locked(force=False)
            return self._snapshot_locked(settings)

    def ensure_ready(self, *, allow_restart: bool = False) -> LlamaCppServerStatusResponse:
        """
        Probe the configured router and start a managed child when needed.

        Startup polling is bounded so APEX boot is never blocked indefinitely.
        When ``allow_restart`` is True after an unexpected owned-process exit,
        at most one restart is attempted until the next successful run or
        settings change.
        """
        with self._lock:
            settings = get_llama_cpp_runtime_settings()
            if not settings.enabled:
                self._state = "disabled"
                self._last_error = None
                return self._snapshot_locked(settings)

            if probe_router_reachable(settings.host):
                if self._owned and self._process_alive_locked():
                    self._state = "managed_running"
                else:
                    if self._owned and not self._process_alive_locked():
                        self._clear_owned_process_locked()
                    self._state = "external_connected"
                    self._last_error = None
                self._restart_allowed = False
                return self._snapshot_locked(settings)

            if not settings.managed:
                self._state = "managed_stopped"
                return self._snapshot_locked(settings)

            self._reconcile_process_locked()
            if self._owned and self._process_alive_locked():
                if self._wait_until_healthy_locked(
                    settings.host, timeout=_STARTUP_TIMEOUT_SECONDS
                ):
                    self._mark_running_locked()
                else:
                    self._record_startup_failure_locked(
                        "Managed llama.cpp server did not become ready before timeout."
                    )
                return self._snapshot_locked(settings)

            if self._state == "startup_failed":
                if not (allow_restart and self._restart_allowed):
                    return self._snapshot_locked(settings)
                self._restart_allowed = False
            elif self._state == "managed_stopped" and self._last_error is not None:
                # Unexpected exit path: require allow_restart + budget.
                if not (allow_restart and self._restart_allowed):
                    return self._snapshot_locked(settings)
                self._restart_allowed = False

            try:
                self._start_owned_process_locked(settings)
            except LlamaCppManagedServerError as exc:
                self._record_startup_failure_locked(str(exc))
                return self._snapshot_locked(settings)

            if self._wait_until_healthy_locked(
                settings.host, timeout=_STARTUP_TIMEOUT_SECONDS
            ):
                self._mark_running_locked()
            else:
                self._record_startup_failure_locked(
                    "Managed llama.cpp server did not become ready before timeout."
                )
                self._stop_owned_process_locked(force=True)
            return self._snapshot_locked(settings)

    def validate_settings_transition(
        self,
        previous: LlamaCppSettings,
        current: LlamaCppSettings,
    ) -> None:
        """Reject unsafe llama.cpp settings changes before persistence."""
        with self._lock:
            if self._state == "starting":
                raise LlamaCppManagedServerError(
                    "Cannot change llama.cpp settings while the managed server is starting."
                )

            identity_changed = self._identity_tuple(current) != self._identity_tuple(
                previous
            )
            if not identity_changed:
                return

            if is_local_execution_active() or get_loading_local_model() is not None:
                raise LlamaCppManagedServerError(
                    "Cannot change llama.cpp server settings while Apodemus is active "
                    "or loading."
                )

    def on_settings_changed(
        self,
        previous: LlamaCppSettings,
        current: LlamaCppSettings,
    ) -> None:
        """Apply managed-server transitions after a successful settings write."""
        with self._lock:
            self._reconcile_process_locked()
            identity_changed = self._identity_tuple(current) != self._identity_tuple(
                previous
            )
            owns_running = self._owned and self._process_alive_locked()

            if owns_running and identity_changed:
                self._stop_owned_process_locked(force=False)

            if not current.enabled:
                if self._owned and self._process_alive_locked():
                    if is_local_execution_active():
                        self._stop_after_idle = True
                        _LOGGER.info(
                            "Deferring managed llama.cpp shutdown until local execution ends."
                        )
                    else:
                        self._stop_owned_process_locked(force=False)
                self._state = "disabled"
                self._restart_allowed = False
                return

            self._stop_after_idle = False
            if not current.managed:
                if self._owned and self._process_alive_locked():
                    if is_local_execution_active():
                        self._stop_after_idle = True
                    else:
                        self._stop_owned_process_locked(force=False)
                self._state = (
                    "external_connected"
                    if probe_router_reachable(current.host)
                    else "managed_stopped"
                )
                self._restart_allowed = False
                return

            # Managed enabled: never restart an external server.
            if probe_router_reachable(current.host) and not (
                self._owned and self._process_alive_locked()
            ):
                self._state = "external_connected"
                self._last_error = None
                self._restart_allowed = False
                return

            self._restart_allowed = True
            self._last_error = None
            self._state = "managed_stopped"

        if current.enabled and current.managed:
            self.ensure_ready(allow_restart=True)

    def maybe_stop_after_idle(self) -> None:
        """Stop a deferred owned process once local execution is idle."""
        with self._lock:
            if not self._stop_after_idle:
                return
            if is_local_execution_active():
                return
            self._stop_after_idle = False
            if self._owned and self._process_alive_locked():
                self._stop_owned_process_locked(force=False)
            settings = get_llama_cpp_runtime_settings()
            self._state = "disabled" if not settings.enabled else "managed_stopped"

    def shutdown_owned(self) -> None:
        """Terminate only an APEX-owned child during application shutdown."""
        with self._lock:
            self._stop_after_idle = False
            self._stop_owned_process_locked(force=False)
            settings = get_llama_cpp_runtime_settings()
            if not settings.enabled:
                self._state = "disabled"
            elif self._state not in {"startup_failed", "external_connected"}:
                self._state = "managed_stopped"

    def _snapshot_locked(self, settings: LlamaCppSettings) -> LlamaCppServerStatusResponse:
        ownership = self._ownership_locked(settings)
        state = self._public_state_locked(settings, ownership)
        return LlamaCppServerStatusResponse(
            enabled=settings.enabled,
            managed=settings.managed,
            ownership=ownership,
            state=state,
            last_error=self._last_error if state == "startup_failed" else None,
        )

    def _mark_running_locked(self) -> None:
        self._state = "managed_running"
        self._last_error = None
        self._restart_allowed = False

    def _identity_tuple(self, settings: LlamaCppSettings) -> tuple[str, str, str, bool]:
        return (
            settings.host,
            settings.executable_path,
            settings.preset_path,
            settings.managed,
        )

    def _ownership_locked(self, settings: LlamaCppSettings) -> LlamaCppServerOwnership:
        if self._owned and self._process_alive_locked():
            return "apex"
        if settings.enabled and probe_router_reachable(settings.host):
            return "external"
        return "none"

    def _public_state_locked(
        self,
        settings: LlamaCppSettings,
        ownership: LlamaCppServerOwnership,
    ) -> LlamaCppServerState:
        if not settings.enabled:
            return "disabled"
        if self._state == "starting":
            return "starting"
        if self._state == "startup_failed":
            return "startup_failed"
        if ownership == "apex":
            return "managed_running"
        if ownership == "external":
            return "external_connected"
        return "managed_stopped"

    def _process_alive_locked(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _reconcile_process_locked(self) -> None:
        if not self._owned or self._process is None:
            return
        code = self._process.poll()
        if code is None:
            return
        _LOGGER.warning(
            "Managed llama.cpp process exited unexpectedly with code %s",
            code,
        )
        self._clear_owned_process_locked()
        if self._state != "startup_failed":
            self._state = "managed_stopped"
            self._last_error = sanitize_process_text(
                f"Managed llama.cpp process exited unexpectedly (code {code})."
            )
            self._restart_allowed = True

    def _clear_owned_process_locked(self) -> None:
        self._process = None
        self._owned = False
        self._launch_identity = None
        self._reader_threads = []

    def _record_startup_failure_locked(self, message: str) -> None:
        self._state = "startup_failed"
        self._last_error = sanitize_process_text(message)
        _LOGGER.warning("Managed llama.cpp startup failed")

    def _start_owned_process_locked(self, settings: LlamaCppSettings) -> None:
        if self._owned and self._process_alive_locked():
            return
        validate_managed_paths(settings)
        bind = parse_loopback_bind(settings.host)
        args = build_llama_server_args(
            executable_path=settings.executable_path,
            preset_path=settings.preset_path,
            bind=bind,
        )
        self._state = "starting"
        self._last_error = None
        self._log_tail.clear()
        _LOGGER.info(
            "Starting managed llama.cpp server on %s:%s",
            bind.host,
            bind.port,
        )
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=windows_creationflags(),
            )
        except OSError as exc:
            raise LlamaCppManagedServerError(
                f"Failed to launch managed llama.cpp executable ({type(exc).__name__})."
            ) from exc

        self._process = process
        self._owned = True
        self._launch_identity = self._identity_tuple(settings)
        self._start_log_readers_locked(process)

    def _start_log_readers_locked(self, process: subprocess.Popen[str]) -> None:
        def _drain(stream: Any, label: str) -> None:
            if stream is None:
                return
            try:
                for line in stream:
                    text = line.rstrip("\n")
                    if not text:
                        continue
                    clipped = text[:_LOG_LINE_MAX]
                    with self._lock:
                        self._log_tail.append(f"{label}: {clipped}")
            except Exception:
                return

        threads = [
            threading.Thread(
                target=_drain,
                args=(process.stdout, "stdout"),
                name="llama-cpp-stdout",
                daemon=True,
            ),
            threading.Thread(
                target=_drain,
                args=(process.stderr, "stderr"),
                name="llama-cpp-stderr",
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        self._reader_threads = threads

    def _wait_until_healthy_locked(self, host: str, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._owned and self._process is not None and self._process.poll() is not None:
                code = self._process.poll()
                tail = sanitize_process_text(
                    " | ".join(list(self._log_tail)[-5:]),
                    max_length=_ERROR_MAX,
                )
                detail = f"Managed llama.cpp process exited during startup (code {code})."
                if tail:
                    detail = f"{detail} {tail}"
                self._record_startup_failure_locked(detail)
                self._clear_owned_process_locked()
                return False
            if probe_router_reachable(host):
                return True
            self._lock.release()
            try:
                time.sleep(_STARTUP_POLL_SECONDS)
            finally:
                self._lock.acquire()
        return False

    def _stop_owned_process_locked(self, *, force: bool) -> None:
        del force  # Graceful terminate always escalates after timeout.
        process = self._process
        if not self._owned or process is None:
            self._clear_owned_process_locked()
            return
        if process.poll() is not None:
            self._clear_owned_process_locked()
            return
        _LOGGER.info("Stopping APEX-owned llama.cpp process pid=%s", process.pid)
        try:
            process.terminate()
            try:
                process.wait(timeout=_SHUTDOWN_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    _LOGGER.warning("Owned llama.cpp process did not exit after kill.")
        except OSError as exc:
            _LOGGER.warning(
                "Error stopping owned llama.cpp process: %s",
                type(exc).__name__,
            )
        self._clear_owned_process_locked()


_SUPERVISOR: LlamaCppServerSupervisor | None = None
_SUPERVISOR_LOCK = threading.Lock()


def get_llama_cpp_server_supervisor() -> LlamaCppServerSupervisor:
    """Return the process-wide llama.cpp server supervisor singleton."""
    global _SUPERVISOR
    with _SUPERVISOR_LOCK:
        if _SUPERVISOR is None:
            _SUPERVISOR = LlamaCppServerSupervisor()
        return _SUPERVISOR


def reset_llama_cpp_server_supervisor_for_tests() -> None:
    """Reset the supervisor singleton between tests."""
    global _SUPERVISOR
    with _SUPERVISOR_LOCK:
        if _SUPERVISOR is not None:
            try:
                _SUPERVISOR.shutdown_owned()
            except Exception:
                pass
        _SUPERVISOR = None


def empty_llama_cpp_server_status() -> LlamaCppServerStatusResponse:
    """Return a disabled status payload when the supervisor is unavailable."""
    settings = get_settings_store().get_snapshot().llama_cpp
    return LlamaCppServerStatusResponse(
        enabled=settings.enabled,
        managed=settings.managed,
        ownership="none",
        state="disabled" if not settings.enabled else "managed_stopped",
        last_error=None,
    )
