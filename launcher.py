#!/usr/bin/env python3
"""Master orchestrator for local APEX services and kiosk browser launch."""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from core.config import CUSTOM_BROWSER_PATH
from core.host.processes import python_child_invocation
from core.runtime_logging import configure_logging

ROOT_DIR: Path = Path(__file__).resolve().parent
FRONTEND_URL: str = "http://127.0.0.1:5500"
API_READY_URL: str = "http://127.0.0.1:8000/api/v1/health/ready"
API_RUNTIME_URL: str = "http://127.0.0.1:8000/api/v1/runtime"
FRONTEND_PROBE_URL: str = "http://127.0.0.1:5500/"
STARTUP_ATTEMPTS: int = 30
STARTUP_POLL_SECONDS: float = 0.5
PROBE_TIMEOUT_SECONDS: float = 3.0

_LOGGER = logging.getLogger(__name__)


class _ManagedBackendControl:
    """Own the launcher side of one backend's private control channel."""

    def __init__(self, process: subprocess.Popen[bytes], launch_id: str) -> None:
        from core.host.protocol import ControlEnvelope, decode_frame, encode_envelope

        self.process = process
        self.launch_id = launch_id
        self._encode = encode_envelope
        self._decode = decode_frame
        self._writer_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_sent = False
        self._shutdown_request_id: str | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._failed = threading.Event()
        self._identity: dict[str, object] | None = None
        self._device_preferences_revision = 0
        self._device_state_sequence = 0
        self._error_code: str | None = None
        self._reader = threading.Thread(
            target=self._read_loop, name="apex-launcher-control-reader", daemon=True
        )
        self._reader.start()
        self._send(
            ControlEnvelope(
                version=1,
                type="start",
                request_id=launch_id,
                payload={"launch_id": launch_id},
            )
        )

    @property
    def identity(self) -> dict[str, object] | None:
        return self._identity

    @property
    def error_code(self) -> str | None:
        return self._error_code

    @property
    def failed(self) -> bool:
        return self._failed.is_set()

    def _send(self, envelope: object) -> bool:
        stream = self.process.stdin
        if stream is None:
            self._failed.set()
            return False
        try:
            frame = self._encode(envelope)
            with self._writer_lock:
                view = memoryview(frame)
                while view:
                    written = stream.write(view)
                    if written is None:
                        break
                    if written <= 0:
                        raise BrokenPipeError
                    view = view[written:]
                stream.flush()
            return True
        except (BrokenPipeError, OSError, ValueError, TypeError):
            self._failed.set()
            return False

    def _read_loop(self) -> None:
        from core.host.protocol import MAX_FRAME_BYTES

        stream = self.process.stdout
        if stream is None:
            self._failed.set()
            return
        try:
            while True:
                line = stream.readline(MAX_FRAME_BYTES + 1)
                if not line:
                    break
                envelope = self._decode(line)
                expected: set[str] = set()
                if envelope.type in {"starting", "ready"}:
                    expected = {self.launch_id}
                elif envelope.type in {"stopping", "stopped"}:
                    expected = {
                        self._shutdown_request_id or self.launch_id
                    }
                elif envelope.type == "error":
                    expected = {self.launch_id}
                    if self._shutdown_request_id is not None:
                        expected.add(self._shutdown_request_id)
                elif envelope.type == "completion":
                    expected = {str(envelope.payload.get("run_id", ""))}
                elif envelope.type in {"desktop_preferences", "device_preferences"}:
                    if (
                        self._identity is None
                        or envelope.payload.get("instance_id")
                        != self._identity.get("instance_id")
                    ):
                        raise ValueError("backend preference instance did not match ready identity")
                    if envelope.type == "device_preferences":
                        revision = envelope.payload["revision"]
                        if revision <= self._device_preferences_revision:
                            continue
                        self._device_preferences_revision = revision
                        self._device_state_sequence += 1
                        from core.host.protocol import ControlEnvelope

                        response = ControlEnvelope(
                            version=1,
                            type="device_state",
                            request_id=f"device-state:{self._device_state_sequence}",
                            payload={
                                "instance_id": str(self._identity["instance_id"]),
                                "revision": revision,
                                "permission": "unsupported",
                                "availability": "unsupported",
                            },
                        )
                        if not self._send(response):
                            raise BrokenPipeError
                if not expected or envelope.request_id not in expected:
                    if envelope.type not in {"desktop_preferences", "device_preferences"}:
                        raise ValueError("backend control response correlation mismatch")
                if envelope.type == "ready":
                    self._identity = dict(envelope.payload)
                    self._ready.set()
                elif envelope.type == "error":
                    self._error_code = str(envelope.payload["code"])
                    self._ready.set()
                elif envelope.type == "stopped":
                    self._stopped.set()
        except Exception:
            self._error_code = "protocol_error"
            self._ready.set()
            self._failed.set()
        finally:
            if not self._stopped.is_set():
                self._failed.set()
            self._ready.set()

    def wait_ready(self, timeout: float) -> dict[str, object] | None:
        self._ready.wait(max(0.0, timeout))
        return self._identity

    def request_shutdown(self) -> None:
        from core.host.protocol import ControlEnvelope

        with self._shutdown_lock:
            if self._shutdown_sent or self.process.poll() is not None:
                return
            self._shutdown_sent = True
            self._shutdown_request_id = str(uuid.uuid4())
            self._send(
                ControlEnvelope(
                    version=1,
                    type="shutdown",
                    request_id=self._shutdown_request_id,
                    payload={},
                )
            )


_CONTROL_SESSIONS: dict[int, _ManagedBackendControl] = {}
_CONTROL_SESSIONS_LOCK = threading.Lock()


def _control_for(process: subprocess.Popen[bytes]) -> _ManagedBackendControl | None:
    with _CONTROL_SESSIONS_LOCK:
        return _CONTROL_SESSIONS.get(id(process))


def _get_sanitized_env() -> dict[str, str]:
    """Return a restricted environment for non-backend child processes."""
    allowed_keys = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "PYTHONPATH")
    return {
        key: value
        for key in allowed_keys
        if (value := os.environ.get(key)) is not None
    }


def _resolve_windows_browser_bins() -> list[Path]:
    """Return custom browser (if configured), then likely Chrome and Edge paths."""
    program_files = os.environ.get("PROGRAMFILES", "")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    local_app = os.environ.get("LOCALAPPDATA", "")
    candidates: list[Path] = []
    if CUSTOM_BROWSER_PATH:
        candidates.append(Path(CUSTOM_BROWSER_PATH))
    if program_files:
        base = Path(program_files)
        candidates.extend(
            [
                base / "Google" / "Chrome" / "Application" / "chrome.exe",
                base / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
        )
    if program_files_x86:
        base_x86 = Path(program_files_x86)
        candidates.extend(
            [
                base_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
                base_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
        )
    if local_app:
        candidates.append(
            Path(local_app)
            / "Microsoft"
            / "Edge"
            / "Application"
            / "msedge.exe"
        )
    return candidates


def launch_background_servers() -> tuple[
    subprocess.Popen[bytes], subprocess.Popen[bytes]
]:
    """
    Start FastAPI (uvicorn) and the static frontend server as parallel children.

    Returns:
        Tuple of (uvicorn process, http.server process).
    """
    uvicorn_env = os.environ.copy()
    static_env = _get_sanitized_env()

    # Stable PYTHONPATH from project root for package imports.
    python_path = str(ROOT_DIR)
    uvicorn_existing_pp = uvicorn_env.get("PYTHONPATH", "")
    uvicorn_env["PYTHONPATH"] = (
        python_path
        if not uvicorn_existing_pp
        else f"{python_path}{os.pathsep}{uvicorn_existing_pp}"
    )
    static_existing_pp = static_env.get("PYTHONPATH", "")
    static_env["PYTHONPATH"] = (
        python_path
        if not static_existing_pp
        else f"{python_path}{os.pathsep}{static_existing_pp}"
    )

    launch_id = str(uuid.uuid4())
    uvicorn_cmd, uvicorn_env = python_child_invocation([
        "-m",
        "core.backend_host",
        "serve",
        "--managed",
    ], env=uvicorn_env)
    static_server_cmd, static_env = python_child_invocation([
        "-m",
        "http.server",
        "5500",
        "--bind",
        "127.0.0.1",
        "--directory",
        "dist",
    ], env=static_env)

    uvicorn_proc = subprocess.Popen(
        uvicorn_cmd,
        cwd=ROOT_DIR,
        env=uvicorn_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=None,
        bufsize=0,
    )
    control = _ManagedBackendControl(uvicorn_proc, launch_id)
    with _CONTROL_SESSIONS_LOCK:
        _CONTROL_SESSIONS[id(uvicorn_proc)] = control
    try:
        static_proc = subprocess.Popen(
            static_server_cmd,
            cwd=ROOT_DIR,
            env=static_env,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        _terminate_process(uvicorn_proc)
        with _CONTROL_SESSIONS_LOCK:
            _CONTROL_SESSIONS.pop(id(uvicorn_proc), None)
        raise
    return uvicorn_proc, static_proc


def launch_kiosk_browser(url: str) -> subprocess.Popen[bytes] | None:
    """
    Open the frontend in an application window (no tabs or URL bar) when possible.

    On Windows, tries ``CUSTOM_BROWSER_PATH`` from the environment first (if
    set), then Chrome or Edge with ``--app=``. Falls back to the default handler
    via ``webbrowser`` if no suitable browser binary is found.

    Returns:
        The browser subprocess handle when launched via Popen, else ``None`` when
        the ``webbrowser`` fallback is used.
    """
    app_flag = f"--app={url}"

    if sys.platform == "win32":
        for browser_bin in _resolve_windows_browser_bins():
            if browser_bin.is_file():
                browser_proc = subprocess.Popen(
                    [str(browser_bin), app_flag],
                    cwd=ROOT_DIR,
                    env=_get_sanitized_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return browser_proc

    import webbrowser

    webbrowser.open(url)
    return None


def _terminate_process(proc: subprocess.Popen[bytes]) -> None:
    """Stop a child process if it is still running."""
    if proc.poll() is not None:
        with _CONTROL_SESSIONS_LOCK:
            _CONTROL_SESSIONS.pop(id(proc), None)
        return
    control = _control_for(proc)
    if control is not None:
        control.request_shutdown()
        identity = control.identity
        timeout = identity.get("shutdown_timeout_seconds", 60) if identity else 60
        if isinstance(timeout, int) and not isinstance(timeout, bool):
            try:
                proc.wait(timeout=max(1, timeout))
            except subprocess.TimeoutExpired:
                pass
            else:
                with _CONTROL_SESSIONS_LOCK:
                    _CONTROL_SESSIONS.pop(id(proc), None)
                return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
    if proc.poll() is not None:
        with _CONTROL_SESSIONS_LOCK:
            _CONTROL_SESSIONS.pop(id(proc), None)


def register_shutdown_hooks(
    uvicorn_proc: subprocess.Popen[bytes],
    static_proc: subprocess.Popen[bytes],
) -> None:
    """
    Ensure server children exit when the orchestrator exits or receives signals.

    Note:
        Some Windows console hosts may terminate the interpreter on window close
        without running ``atexit`` handlers; Ctrl+C and orderly interpreter exit
        are handled.
    """

    lock = threading.Lock()
    stopped = False

    def shutdown(signum: int | None = None, _frame: object | None = None) -> None:
        nonlocal stopped
        with lock:
            if stopped:
                if signum is not None:
                    sys.exit(0)
                return
            stopped = True
        _terminate_process(uvicorn_proc)
        _terminate_process(static_proc)
        if signum is not None:
            sys.exit(0)

    atexit.register(lambda: shutdown(None, None))

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)


def _http_ok(url: str) -> bool:
    """Return True when ``url`` responds with HTTP 200."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=PROBE_TIMEOUT_SECONDS) as response:
            return response.getcode() == 200
    except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError):
        return False


def _http_json(url: str) -> dict[str, object] | None:
    """Read one bounded local identity response without consulting proxies."""
    import json

    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=PROBE_TIMEOUT_SECONDS) as response:
            if response.getcode() != 200:
                return None
            payload = response.read(64 * 1024 + 1)
        if len(payload) > 64 * 1024:
            return None
        result = json.loads(payload)
    except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError, ValueError):
        return None
    return result if isinstance(result, dict) else None


def _expected_profile_build(control: _ManagedBackendControl) -> tuple[str, str]:
    from core.host.identity import create_host_identity
    from core.runtime_paths import get_runtime_paths, initialize_environment

    initialize_environment()
    expected = create_host_identity(
        get_runtime_paths(),
        hosting_mode="managed",
        launch_id=control.launch_id,
    )
    return expected.build_id, expected.data_root_fingerprint


def _child_exit_reason(
    name: str,
    proc: subprocess.Popen[bytes],
) -> str | None:
    """Return an actionable message when a child has already exited."""
    if name == "uvicorn":
        control = _control_for(proc)
        if control is not None and control.failed:
            if control.error_code is not None:
                return _backend_error_reason(control.error_code)
            return "The APEX backend control channel closed unexpectedly."
    code = proc.poll()
    if code is None:
        return None
    if code in (1, 48, 98, 100):
        return (
            f"{name} exited early with code {code}. "
            "Likely bind conflict or failed listen on the expected loopback port."
        )
    return f"{name} exited early with code {code}."


def _backend_error_reason(code: str) -> str:
    messages = {
        "port_in_use": "Port 8000 is already in use. Close the existing service before starting APEX.",
        "profile_in_use": "The selected APEX data profile is already in use.",
        "protocol_error": "The APEX backend control channel failed during startup.",
        "startup_failed": "The APEX backend failed during startup.",
        "shutdown_failed": "The APEX backend could not complete safe startup cleanup.",
    }
    return messages.get(code, "The APEX backend reported a startup failure.")


def wait_for_services(
    uvicorn_proc: subprocess.Popen[bytes],
    static_proc: subprocess.Popen[bytes],
) -> str | None:
    """
    Probe backend readiness and frontend HTTP availability.

    Returns:
        ``None`` when both services are ready, otherwise an actionable failure reason.
    """
    control = _control_for(uvicorn_proc)
    if control is None:
        return "Backend control channel was not initialized. Browser launch suppressed."
    try:
        expected_build_id, expected_profile = _expected_profile_build(control)
    except Exception as exc:
        return f"Unable to resolve the selected APEX profile ({type(exc).__name__}). Browser launch suppressed."

    _LOGGER.info("Waiting for owned APEX API readiness and frontend HTTP availability...")
    for _ in range(STARTUP_ATTEMPTS):
        if control.error_code is not None:
            return _backend_error_reason(control.error_code)
        if control.failed:
            return "The APEX backend control channel closed unexpectedly. Browser launch suppressed."
        api_exit = _child_exit_reason("uvicorn", uvicorn_proc)
        if api_exit:
            # The process can exit directly after its last error write. Let the
            # dedicated pipe drainer consume that final safe frame before we
            # fall back to the numeric exit status.
            if uvicorn_proc.poll() is not None:
                control.wait_ready(0.2)
                if control.error_code is not None:
                    return _backend_error_reason(control.error_code)
            return api_exit
        static_exit = _child_exit_reason("http.server", static_proc)
        if static_exit:
            return static_exit

        identity = control.identity
        if identity is not None:
            if (
                identity.get("pid") != uvicorn_proc.pid
                or identity.get("launch_id") != control.launch_id
                or identity.get("hosting_mode") != "managed"
                or identity.get("build_id") != expected_build_id
                or identity.get("data_root_fingerprint") != expected_profile
            ):
                return "The backend identity did not match this APEX launch and profile. Browser launch suppressed."
        runtime_identity = _http_json(API_RUNTIME_URL) if identity is not None else None
        if runtime_identity is not None and runtime_identity != identity:
            return "The API runtime identity did not match its control channel. Browser launch suppressed."
        api_ready = bool(identity is not None and runtime_identity == identity and _http_ok(API_READY_URL))
        frontend_ready = _http_ok(FRONTEND_PROBE_URL)
        if api_ready and frontend_ready:
            _LOGGER.info("Backend and frontend are ready.")
            return None
        time.sleep(STARTUP_POLL_SECONDS)

    identity = control.identity
    api_ready = bool(
        identity is not None
        and _http_json(API_RUNTIME_URL) == identity
        and _http_ok(API_READY_URL)
    )
    frontend_ready = _http_ok(FRONTEND_PROBE_URL)
    missing: list[str] = []
    if not api_ready:
        missing.append("API readiness at /api/v1/health/ready")
    if not frontend_ready:
        missing.append("frontend HTTP at http://127.0.0.1:5500/")
    return (
        "Startup timed out waiting for: "
        + ", ".join(missing)
        + ". Browser launch suppressed."
    )


def fail_startup(
    reason: str,
    uvicorn_proc: subprocess.Popen[bytes],
    static_proc: subprocess.Popen[bytes],
) -> int:
    """Terminate both children and return a nonzero exit code."""
    _LOGGER.error("APEX startup failed: %s", reason)
    _terminate_process(uvicorn_proc)
    _terminate_process(static_proc)
    return 1


def main() -> int:
    """Run the orchestration sequence: servers, warm-up, browser, then wait."""
    configure_logging()
    try:
        uvicorn_proc, static_proc = launch_background_servers()
    except (OSError, subprocess.SubprocessError) as exc:
        _LOGGER.error(
            "Unable to start APEX child processes: error_type=%s",
            type(exc).__name__,
        )
        return 1
    register_shutdown_hooks(uvicorn_proc, static_proc)

    failure = wait_for_services(uvicorn_proc, static_proc)
    if failure is not None:
        return fail_startup(failure, uvicorn_proc, static_proc)

    browser_proc: subprocess.Popen[bytes] | None = None
    exit_code = 0
    try:
        browser_proc = launch_kiosk_browser(FRONTEND_URL)
        if browser_proc is not None:
            while True:
                if browser_proc.poll() is not None:
                    _LOGGER.info(
                        "Browser window closed. Spinning down background services..."
                    )
                    break
                api_exit = _child_exit_reason("uvicorn", uvicorn_proc)
                if api_exit:
                    _LOGGER.error("%s", api_exit)
                    exit_code = 1
                    break
                static_exit = _child_exit_reason("http.server", static_proc)
                if static_exit:
                    _LOGGER.error("%s", static_exit)
                    exit_code = 1
                    break
                time.sleep(1)
            _LOGGER.info("APEX shutdown complete.")
        else:
            _LOGGER.info(
                "APEX local services are running. Press Ctrl+C to stop uvicorn and "
                "http.server."
            )
            while True:
                api_exit = _child_exit_reason("uvicorn", uvicorn_proc)
                if api_exit:
                    _LOGGER.error("%s", api_exit)
                    exit_code = 1
                    break
                static_exit = _child_exit_reason("http.server", static_proc)
                if static_exit:
                    _LOGGER.error("%s", static_exit)
                    exit_code = 1
                    break
                time.sleep(1)
    except OSError as exc:
        _LOGGER.error(
            "Unable to launch the APEX browser: error_type=%s",
            type(exc).__name__,
        )
        exit_code = 1
    except KeyboardInterrupt:
        pass
    finally:
        if browser_proc is not None:
            _terminate_process(browser_proc)
        _terminate_process(uvicorn_proc)
        _terminate_process(static_proc)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
