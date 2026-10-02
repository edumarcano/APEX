"""Ownership-aware cleanup for child processes started by the APEX host."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import BinaryIO

_LOGGER = logging.getLogger(__name__)


def python_child_invocation(
    arguments: list[str], *, env: dict[str, str] | None = None
) -> tuple[list[str], dict[str, str]]:
    """Build a Python child invocation whose process handle owns the interpreter.

    Windows venv launchers redirect to a second base-interpreter process. Use
    that interpreter directly with CPython's launcher hint so Popen.pid remains
    the actual Python process while venv prefix and packages stay active.
    """
    child_env = dict(os.environ if env is None else env)
    executable = sys.executable
    if os.name == "nt" and not getattr(sys, "frozen", False):
        base_executable = getattr(sys, "_base_executable", None)
        if isinstance(base_executable, str) and base_executable:
            executable = base_executable
            if os.path.normcase(executable) != os.path.normcase(sys.executable):
                child_env["__PYVENV_LAUNCHER__"] = sys.executable
    return [executable, *arguments], child_env


def redirect_stdout_to_stderr() -> BinaryIO:
    """Preserve the original stdout pipe and redirect app output to stderr.

    Call this before importing application or pygame modules in a managed
    worker. The returned non-inheritable binary stream is reserved for control
    protocol output and must be closed by its owner.
    """
    private_fd = os.dup(1)
    try:
        os.set_inheritable(private_fd, False)
        os.dup2(2, 1, inheritable=False)
        import sys

        sys.stdout = sys.stderr
        return os.fdopen(private_fd, "wb", buffering=0)
    except BaseException:
        os.close(private_fd)
        raise


@dataclass(frozen=True, slots=True)
class OwnedProcessRegistration:
    process: subprocess.Popen[bytes]
    kind: str


class OwnedProcessRegistry:
    """Track exact ``Popen`` handles created by this host process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: dict[int, OwnedProcessRegistration] = {}

    def register_owned_process(
        self, process: subprocess.Popen[bytes], *, kind: str
    ) -> OwnedProcessRegistration:
        if not isinstance(kind, str) or not kind.strip() or len(kind) > 64:
            raise ValueError("kind must be a short, non-empty label.")
        registration = OwnedProcessRegistration(process=process, kind=kind.strip())
        with self._lock:
            self._processes[id(process)] = registration
        return registration

    def unregister_owned_process(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            registration = self._processes.get(id(process))
            if registration is not None and registration.process is process:
                del self._processes[id(process)]

    def registrations(self) -> tuple[OwnedProcessRegistration, ...]:
        with self._lock:
            return tuple(self._processes.values())

    def terminate_owned_processes(self, timeout_seconds: float) -> None:
        """Terminate, kill if needed, and reap only registered children."""
        timeout = max(0.0, float(timeout_seconds))
        deadline = time.monotonic() + timeout
        graceful_deadline = time.monotonic() + timeout * 0.75
        registrations = self.registrations()
        active: list[OwnedProcessRegistration] = []
        for registration in registrations:
            process = registration.process
            if process.poll() is not None:
                self.unregister_owned_process(process)
                continue
            active.append(registration)
            try:
                process.terminate()
            except (OSError, ProcessLookupError):
                pass

        remaining: list[OwnedProcessRegistration] = []
        for registration in active:
            process = registration.process
            wait_for = max(0.0, min(graceful_deadline, deadline) - time.monotonic())
            try:
                process.wait(timeout=wait_for)
                self.unregister_owned_process(process)
            except subprocess.TimeoutExpired:
                remaining.append(registration)
            except (OSError, ChildProcessError):
                remaining.append(registration)

        for registration in remaining:
            try:
                registration.process.kill()
            except (OSError, ProcessLookupError):
                pass

        for registration in remaining:
            process = registration.process
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except (subprocess.TimeoutExpired, OSError, ChildProcessError):
                _LOGGER.warning("Could not reap registered %s child before shutdown deadline", registration.kind)
            else:
                self.unregister_owned_process(process)


_OWNED_PROCESSES = OwnedProcessRegistry()


def register_owned_process(
    process: subprocess.Popen[bytes], *, kind: str
) -> OwnedProcessRegistration:
    """Register an exact child process handle for host-owned cleanup."""
    return _OWNED_PROCESSES.register_owned_process(process, kind=kind)


def unregister_owned_process(process: subprocess.Popen[bytes]) -> None:
    """Remove an exact child process handle from host cleanup ownership."""
    _OWNED_PROCESSES.unregister_owned_process(process)


def terminate_owned_processes(timeout_seconds: float) -> None:
    """Stop and reap registered child handles; never discover by name or port."""
    _OWNED_PROCESSES.terminate_owned_processes(timeout_seconds)


__all__ = [
    "OwnedProcessRegistration",
    "OwnedProcessRegistry",
    "python_child_invocation",
    "redirect_stdout_to_stderr",
    "register_owned_process",
    "terminate_owned_processes",
    "unregister_owned_process",
]
