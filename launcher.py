#!/usr/bin/env python3
"""Master orchestrator for local APEX services and kiosk browser launch."""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from core.config import CUSTOM_BROWSER_PATH


ROOT_DIR: Path = Path(__file__).resolve().parent
FRONTEND_URL: str = "http://127.0.0.1:5500"


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
    ]
    static_server_cmd: list[str] = [
        sys.executable,
        "-m",
        "http.server",
        "5500",
        "--directory",
        "frontend",
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


def launch_kiosk_browser(url: str) -> None:
    """
    Open the frontend in an application window (no tabs or URL bar) when possible.

    On Windows, tries ``CUSTOM_BROWSER_PATH`` from the environment first (if
    set), then Chrome or Edge with ``--app=``. Falls back to the default handler
    via ``webbrowser`` if no suitable browser binary is found.
    """
    app_flag = f"--app={url}"

    if sys.platform == "win32":
        for browser_bin in _resolve_windows_browser_bins():
            if browser_bin.is_file():
                subprocess.Popen(
                    [str(browser_bin), app_flag],
                    cwd=ROOT_DIR,
                    env=_get_sanitized_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return

    import webbrowser

    webbrowser.open(url)


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


def main() -> None:
    """Run the orchestration sequence: servers, warm-up, browser, then wait."""
    uvicorn_proc, static_proc = launch_background_servers()
    register_shutdown_hooks(uvicorn_proc, static_proc)

    # Allow uvicorn and the static server time to bind ports before opening UI.
    time.sleep(3)

    launch_kiosk_browser(FRONTEND_URL)

    print(
        "APEX local services are running. Press Ctrl+C to stop uvicorn and "
        "http.server.",
        flush=True,
    )
    try:
        while True:
            if uvicorn_proc.poll() is not None:
                print("uvicorn exited unexpectedly.", file=sys.stderr, flush=True)
                break
            if static_proc.poll() is not None:
                print(
                    "Static http.server exited unexpectedly.",
                    file=sys.stderr,
                    flush=True,
                )
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _terminate_process(uvicorn_proc)
        _terminate_process(static_proc)


if __name__ == "__main__":
    main()
