#!/usr/bin/env python3
"""Master orchestrator for local APEX services and kiosk browser launch."""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from core.config import CUSTOM_BROWSER_PATH
from core.runtime_logging import configure_logging

ROOT_DIR: Path = Path(__file__).resolve().parent
FRONTEND_URL: str = "http://127.0.0.1:5500"
API_READY_URL: str = "http://127.0.0.1:8000/api/v1/health/ready"
FRONTEND_PROBE_URL: str = "http://127.0.0.1:5500/"
STARTUP_ATTEMPTS: int = 30
STARTUP_POLL_SECONDS: float = 0.5
PROBE_TIMEOUT_SECONDS: float = 3.0

_LOGGER = logging.getLogger(__name__)


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

    uvicorn_cmd: list[str] = [
        sys.executable,
        "-m",
        "uvicorn",
        "core.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    static_server_cmd: list[str] = [
        sys.executable,
        "-m",
        "http.server",
        "5500",
        "--bind",
        "127.0.0.1",
        "--directory",
        "dist",
    ]

    uvicorn_proc = subprocess.Popen(
        uvicorn_cmd,
        cwd=ROOT_DIR,
        env=uvicorn_env,
        stdin=subprocess.DEVNULL,
    )
    static_proc = subprocess.Popen(
        static_server_cmd,
        cwd=ROOT_DIR,
        env=static_env,
        stdin=subprocess.DEVNULL,
    )
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
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


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

    def shutdown(signum: int | None = None, _frame: object | None = None) -> None:
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
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as response:
            return response.getcode() == 200
    except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError):
        return False


def _child_exit_reason(
    name: str,
    proc: subprocess.Popen[bytes],
) -> str | None:
    """Return an actionable message when a child has already exited."""
    code = proc.poll()
    if code is None:
        return None
    if code in (1, 48, 98, 100):
        return (
            f"{name} exited early with code {code}. "
            "Likely bind conflict or failed listen on the expected loopback port."
        )
    return f"{name} exited early with code {code}."


def wait_for_services(
    uvicorn_proc: subprocess.Popen[bytes],
    static_proc: subprocess.Popen[bytes],
) -> str | None:
    """
    Probe backend readiness and frontend HTTP availability.

    Returns:
        ``None`` when both services are ready, otherwise an actionable failure reason.
    """
    _LOGGER.info("Waiting for APEX API readiness and frontend HTTP availability...")
    for _ in range(STARTUP_ATTEMPTS):
        api_exit = _child_exit_reason("uvicorn", uvicorn_proc)
        if api_exit:
            return api_exit
        static_exit = _child_exit_reason("http.server", static_proc)
        if static_exit:
            return static_exit

        api_ready = _http_ok(API_READY_URL)
        frontend_ready = _http_ok(FRONTEND_PROBE_URL)
        if api_ready and frontend_ready:
            _LOGGER.info("Backend and frontend are ready.")
            return None
        time.sleep(STARTUP_POLL_SECONDS)

    api_ready = _http_ok(API_READY_URL)
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
    uvicorn_proc, static_proc = launch_background_servers()
    register_shutdown_hooks(uvicorn_proc, static_proc)

    failure = wait_for_services(uvicorn_proc, static_proc)
    if failure is not None:
        return fail_startup(failure, uvicorn_proc, static_proc)

    browser_proc = launch_kiosk_browser(FRONTEND_URL)

    try:
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
                    break
                static_exit = _child_exit_reason("http.server", static_proc)
                if static_exit:
                    _LOGGER.error("%s", static_exit)
                    break
                time.sleep(1)
            _LOGGER.info("APEX shutdown complete.")
        else:
            _LOGGER.info(
                "APEX local services are running. Press Ctrl+C to stop uvicorn and "
                "http.server."
            )
            while True:
                if uvicorn_proc.poll() is not None:
                    _LOGGER.error("uvicorn exited unexpectedly.")
                    break
                if static_proc.poll() is not None:
                    _LOGGER.error("Static http.server exited unexpectedly.")
                    break
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _terminate_process(uvicorn_proc)
        _terminate_process(static_proc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
