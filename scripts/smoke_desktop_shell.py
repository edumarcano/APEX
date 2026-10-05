"""Run a bounded WebDriver smoke against an assembled Windows APEX desktop app."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

API_ORIGIN = "http://127.0.0.1:8000"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
POLL_INTERVAL_SECONDS = 0.2
ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
TH32CS_SNAPPROCESS = 0x00000002
WM_CLOSE = 0x0010
WAIT_OBJECT_0 = 0
ESSENTIAL_CHECKS = {
    "first_run_fresh_start",
    "native_import_picker_cancel",
    "native_import_preview",
    "desktop_import_preservation_after_startup",
    "desktop_import_quit_cleanup",
    "desktop_import_repeat_launch",
    "desktop_import_repeat_cleanup",
    "startup_conflict",
    "startup_retry",
    "managed_backend_identity",
    "workspace_overview",
    "workspace_briefing",
    "workspace_cortex",
    "workspace_reports",
    "demo_briefing",
    "cortex_stream",
    "cortex_cancel",
    "backend_crash_recovery",
    "close_to_tray",
    "single_instance_activation",
    "tray_show",
    "tray_quit",
    "fixture_backend_identity",
    "native_shell_cleanup",
    "owned_backend_cleanup",
}


@dataclass
class Check:
    name: str
    status: str
    detail: str | None = None


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    diagnostics: list[dict[str, str]] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str | None = None) -> None:
        self.checks.append(Check(name, status, detail))

    def add_diagnostic(self, name: str, value: str) -> None:
        self.diagnostics.append({"name": name, "value": value})

    @property
    def result(self) -> str:
        if any(check.status == "failed" for check in self.checks):
            return "failed"
        if any(check.status == "unverified" for check in self.checks):
            return "unverified"
        return "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "result": self.result,
            "checks": [asdict(check) for check in self.checks],
            "diagnostics": self.diagnostics,
        }


class SmokeFailure(RuntimeError):
    pass


class WebDriverCommandError(SmokeFailure):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(f"WebDriver command failed ({error}): {message}")
        self.error = error


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class LlamaCppStreamFixture:
    """Loopback OpenAI-compatible stream used to hold a real run at a boundary."""

    def __init__(self, hold_timeout: float = 90.0) -> None:
        self.first_delta_sent = threading.Event()
        self.release_cancelled_stream = threading.Event()
        self.hold_timeout = hold_timeout
        self.request_count = 0
        self.request_metadata: list[dict[str, object]] = []
        self.response_started_count = 0
        self.first_delta_error: str | None = None
        self._lock = threading.Lock()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _json(self, value: object) -> None:
                body = json.dumps(value).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/models":
                    self._json({"models": [{"name": "gemma-4-e2b-16k", "state": "loaded", "context_window": 16384}]})
                    return
                if self.path == "/props":
                    self._json({"default_generation_settings": {"n_ctx": 16384}})
                    return
                self.send_error(404)

            def _write_chunk(self, payload: bytes) -> None:
                self.wfile.write(f"{len(payload):X}\r\n".encode("ascii"))
                self.wfile.write(payload)
                self.wfile.write(b"\r\n")
                self.wfile.flush()

            def _chunk(self, text: str, *, finish: str | None = None) -> None:
                payload = {
                    "model": "gemma-4-e2b-16k",
                    "choices": [{"delta": {"content": text} if text else {}, "finish_reason": finish}],
                }
                data = ("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode("utf-8")
                self._write_chunk(data)

            def do_POST(self) -> None:
                if self.path.split("?", 1)[0] != "/v1/chat/completions":
                    self.send_error(404)
                    return
                self.close_connection = True
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self.send_error(400)
                    return
                if length <= 0 or length > MAX_RESPONSE_BYTES:
                    self.send_error(413)
                    return
                request_body = self.rfile.read(length)
                try:
                    payload = json.loads(request_body)
                except (UnicodeError, json.JSONDecodeError):
                    payload = None
                messages = payload.get("messages") if isinstance(payload, dict) else None
                roles: dict[str, int] = {}
                if isinstance(messages, list):
                    for message in messages:
                        role = message.get("role") if isinstance(message, dict) else None
                        role = role if isinstance(role, str) and role in {"system", "user", "assistant", "tool"} else "other"
                        roles[role] = roles.get(role, 0) + 1
                with fixture._lock:
                    request_number = fixture.request_count
                    fixture.request_count += 1
                    fixture.request_metadata.append({
                        "stream": payload.get("stream") if isinstance(payload, dict) else None,
                        "message_count": len(messages) if isinstance(messages, list) else None,
                        "message_roles": roles,
                        "body_valid": isinstance(payload, dict),
                    })
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    with fixture._lock:
                        fixture.response_started_count += 1
                    if request_number == 0:
                        self._chunk("The native WebView received the first streamed segment.")
                        # requests.iter_lines buffers 512 bytes by default. Pad
                        # the first transport read so this delta is observable
                        # before the fixture waits for the UI cancellation.
                        self._write_chunk(b":" + b" " * 600 + b"\n\n")
                        fixture.first_delta_sent.set()
                        if not fixture.release_cancelled_stream.wait(timeout=fixture.hold_timeout):
                            self.wfile.write(b"0\r\n\r\n")
                            self.wfile.flush()
                            return
                        self._chunk(" The cancellation boundary was released.", finish="stop")
                        self._write_chunk(b"data: [DONE]\n\n")
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                    else:
                        for text in (
                            "The native WebView received ",
                            "an incremental provider stream ",
                            "through the packaged backend.",
                        ):
                            self._chunk(text)
                        self._chunk("", finish="stop")
                        self._write_chunk(b"data: [DONE]\n\n")
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                    if request_number == 0:
                        with fixture._lock:
                            fixture.first_delta_error = type(exc).__name__
                    return

        class FixtureHTTPServer(ThreadingHTTPServer):
            def handle_error(self, request: object, client_address: object) -> None:
                if isinstance(sys.exc_info()[1], ConnectionResetError):
                    return
                super().handle_error(request, client_address)

        self.server = FixtureHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.release_cancelled_stream.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def diagnostics(self) -> dict[str, object]:
        with self._lock:
            return {
                "request_count": self.request_count,
                "requests": list(self.request_metadata[:10]),
                "response_started_count": self.response_started_count,
                "first_delta_sent": self.first_delta_sent.is_set(),
                "first_delta_error_type": self.first_delta_error,
                "release_sent": self.release_cancelled_stream.is_set(),
            }


class WebDriver:
    """Small W3C WebDriver client for tauri-driver's native WebView session."""

    def __init__(self, port: int, timeout: float) -> None:
        self.base_url = f"http://127.0.0.1:{port}"
        self.timeout = timeout
        self.session_id: str | None = None

    def request(self, method: str, path: str, body: object | None = None) -> object:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=self.timeout) as response:
                result = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            message = exc.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")
            try:
                envelope = json.loads(message)
            except (UnicodeError, json.JSONDecodeError):
                envelope = None
            if isinstance(envelope, dict):
                value = envelope.get("value")
                if isinstance(value, dict) and isinstance(value.get("error"), str):
                    raise WebDriverCommandError(
                        value["error"], str(value.get("message", value["error"]))
                    ) from None
            raise SmokeFailure(f"WebDriver {method} {path} returned HTTP {exc.code}: {message[:500]}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SmokeFailure(f"WebDriver {method} {path} failed: {exc}") from None
        if len(result) > MAX_RESPONSE_BYTES:
            raise SmokeFailure("WebDriver response exceeded the 2 MiB limit")
        if not result:
            return None
        try:
            envelope = json.loads(result)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SmokeFailure(f"WebDriver returned invalid JSON: {exc}") from None
        if isinstance(envelope, dict) and envelope.get("value") is not None:
            value = envelope["value"]
            if isinstance(value, dict) and isinstance(value.get("error"), str):
                raise WebDriverCommandError(
                    value["error"], str(value.get("message", value["error"]))
                )
            return value
        return envelope

    def start(self, application: Path) -> None:
        result = self.request("POST", "/session", {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "wry",
                    "tauri:options": {"application": str(application)},
                },
            },
        })
        if not isinstance(result, dict) or not isinstance(result.get("sessionId"), str):
            raise SmokeFailure("tauri-driver did not return a WebDriver session identity")
        self.session_id = result["sessionId"]

    def close(self) -> None:
        if self.session_id is None:
            return
        session = self.session_id
        self.session_id = None
        try:
            self.request("DELETE", f"/session/{session}")
        except SmokeFailure:
            # The application may have exited during its own close handler.
            pass

    def _command(self, method: str, path: str, body: object | None = None) -> object:
        if self.session_id is None:
            raise SmokeFailure("WebDriver session is not active")
        return self.request(method, f"/session/{self.session_id}{path}", body)

    def find(self, using: str, value: str) -> str | None:
        try:
            result = self._command("POST", "/element", {"using": using, "value": value})
        except WebDriverCommandError as exc:
            if exc.error == "no such element":
                return None
            raise
        if not isinstance(result, dict):
            return None
        element_id = result.get(ELEMENT_KEY)
        return element_id if isinstance(element_id, str) else None

    def find_all(self, using: str, value: str) -> list[str]:
        try:
            result = self._command("POST", "/elements", {"using": using, "value": value})
        except WebDriverCommandError as exc:
            if exc.error == "no such element":
                return []
            raise
        if not isinstance(result, list):
            return []
        return [item[ELEMENT_KEY] for item in result if isinstance(item, dict) and isinstance(item.get(ELEMENT_KEY), str)]

    def is_displayed(self, element_id: str) -> bool:
        result = self._command("GET", f"/element/{element_id}/displayed")
        return result is True

    def is_enabled(self, element_id: str) -> bool:
        result = self._command("GET", f"/element/{element_id}/enabled")
        return result is True

    def element_text(self, element_id: str) -> str:
        result = self._command("GET", f"/element/{element_id}/text")
        return result if isinstance(result, str) else ""

    def click(self, element_id: str) -> None:
        self._command("POST", f"/element/{element_id}/click", {})

    def type_text(self, element_id: str, value: str) -> None:
        self._command("POST", f"/element/{element_id}/value", {"text": value, "value": list(value)})

    def text(self) -> str:
        result = self._command(
            "POST",
            "/execute/sync",
            {"script": "return document.body ? document.body.innerText : '';", "args": []},
        )
        return result if isinstance(result, str) else ""

    def current_url(self) -> str:
        result = self._command("GET", "/url")
        return result if isinstance(result, str) else ""

    def page_source(self) -> str:
        result = self._command("GET", "/source")
        return result if isinstance(result, str) else ""

    def page_context(self) -> dict[str, object]:
        result = self._command("POST", "/execute/sync", {
            "script": (
                "const root = document.getElementById('root');"
                "return {href: location.href, tauriInternals: Boolean(window.__TAURI_INTERNALS__),"
                "bodyText: document.body ? document.body.innerText.slice(0, 12000) : '',"
                "rootHtml: root ? root.innerHTML.slice(0, 12000) : '',"
                "scripts: Array.from(document.scripts).slice(0, 20).map(item => item.src.slice(0, 1000))};"
            ),
            "args": [],
        })
        return result if isinstance(result, dict) else {}

    def selector_state(self, selector: str) -> list[dict[str, object]]:
        result = self._command("POST", "/execute/sync", {
            "script": (
                "return Array.from(document.querySelectorAll(arguments[0])).slice(0, 10).map(element => {"
                "const rect = element.getBoundingClientRect();"
                "const style = getComputedStyle(element);"
                "return {tag: element.tagName, placeholder: element.getAttribute('placeholder'),"
                "disabled: Boolean(element.disabled), readOnly: Boolean(element.readOnly),"
                "display: style.display, visibility: style.visibility, opacity: style.opacity,"
                "rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},"
                "outerHTML: element.outerHTML.slice(0, 1500)};});"
            ),
            "args": [selector],
        })
        return result if isinstance(result, list) else []

    def wait_for(self, description: str, predicate: Callable[[], bool], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if predicate():
                    return True
            except SmokeFailure:
                if self.session_id is None:
                    return False
            time.sleep(POLL_INTERVAL_SECONDS)
        return False


def _capture_failure_diagnostics(
    report: Report,
    *,
    stage: str,
    driver: WebDriver | None,
    log_paths: list[tuple[str, Path]],
) -> dict[str, str]:
    captured: dict[str, str] = {}
    if driver is not None and driver.session_id is not None:
        for key, read in (
            ("url", driver.current_url),
            ("visible_text", driver.text),
            ("page_source", driver.page_source),
        ):
            try:
                value = read()
            except (SmokeFailure, OSError, ValueError) as exc:
                value = f"unavailable: {exc}"
            captured[key] = value[:12_000]
            report.add_diagnostic(f"{stage}_{key}", captured[key])
        try:
            page_context = driver.page_context()
        except (SmokeFailure, OSError, ValueError) as exc:
            report.add_diagnostic(f"{stage}_page_context_error", str(exc)[:2_000])
        else:
            for key, limit in (
                ("href", 2_000),
                ("tauriInternals", 32),
                ("bodyText", 12_000),
                ("rootHtml", 12_000),
                ("scripts", 4_000),
            ):
                value = page_context.get(key)
                if key == "scripts":
                    rendered = json.dumps(value if isinstance(value, list) else [], ensure_ascii=False)
                else:
                    rendered = str(value if value is not None else "")
                captured[key] = rendered[:limit]
                report.add_diagnostic(f"{stage}_{key}", captured[key])
    else:
        captured["visible_text"] = "unavailable: WebDriver session is no longer active"
        report.add_diagnostic(f"{stage}_visible_text", captured["visible_text"])

    for label, path in log_paths:
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 16_384), os.SEEK_SET)
                value = handle.read(16_384).decode("utf-8", "replace")
        except OSError as exc:
            value = f"unavailable: {exc}"
        if value:
            report.add_diagnostic(f"{stage}_{label}_log_tail", value[-12_000:])
            captured[f"{label}_log_tail"] = value[-12_000:]
    return captured


def _http_json(path: str, timeout: float = 2.0) -> object:
    request = urllib.request.Request(
        API_ORIGIN + path,
        headers={"Accept": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise SmokeFailure(f"API response exceeded the size limit: {path}")
    return json.loads(body)


def _http_sse_event_types(run_id: str, timeout: float = 15.0) -> list[str]:
    request = urllib.request.Request(
        f"{API_ORIGIN}/api/v1/cortex/runs/{run_id}/events",
        headers={"Accept": "text/event-stream"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise SmokeFailure("run event replay exceeded the smoke-test size limit")
    return [
        line[6:].strip()
        for line in body.decode("utf-8", "replace").splitlines()
        if line.startswith("event:")
    ]


def _wait_sse_event_type(run_id: str, expected: str, timeout: float) -> bool:
    request = urllib.request.Request(
        f"{API_ORIGIN}/api/v1/cortex/runs/{run_id}/events",
        headers={"Accept": "text/event-stream"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    total_bytes = 0
    try:
        with opener.open(request, timeout=timeout) as response:
            raw_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            if raw_socket is None:
                raise SmokeFailure("could not apply an overall deadline to the run-event connection")
            line = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                raw_socket.settimeout(remaining)
                next_byte = response.read(1)
                if not next_byte:
                    return False
                total_bytes += 1
                if total_bytes > MAX_RESPONSE_BYTES:
                    raise SmokeFailure("run-event wait exceeded the smoke-test byte limit")
                if next_byte == b"\n":
                    if line.startswith(b"event:") and line[6:].decode("utf-8", "replace").strip() == expected:
                        return True
                    line.clear()
                else:
                    line.extend(next_byte)
    except (OSError, TimeoutError, urllib.error.URLError):
        return False
    return False


def _api_port_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            return False
    return True


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _sanitized_environment(root: Path, *, demo: bool = True, local_model_host: str | None = None) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
        if os.environ.get(key)
    }
    system_root = env.get("SYSTEMROOT", r"C:\Windows")
    env["PATH"] = os.pathsep.join((str(Path(system_root) / "System32"), system_root))
    for name in ("temp", "local-app-data", "roaming-app-data", "profile"):
        (root / name).mkdir(parents=True, exist_ok=True)
    env.update({
        "TEMP": str(root / "temp"),
        "TMP": str(root / "temp"),
        "LOCALAPPDATA": str(root / "local-app-data"),
        "APPDATA": str(root / "roaming-app-data"),
        "APEX_DATA_DIR": str((root / "profile").resolve()),
        "PYTHON_DOTENV_DISABLED": "1",
        "DEMO_MODE": "true" if demo else "false",
        "DEV_MODE": "false",
        "PYTHONUTF8": "1",
    })
    if local_model_host is not None:
        local_config = Path(env["APEX_DATA_DIR"]) / "config.local.json"
        local_config.write_text(json.dumps({
            "ask_apex": {
                "enabled": True,
                "selected_model": "gemma-4-E2B-Q4_K_M.gguf",
                "local": {
                    "last_model": "gemma-4-E2B-Q4_K_M.gguf",
                    "context_window": 16384,
                    "reasoning_mode": "none",
                },
            },
            "tts_settings": {"primary_tts": "pyttsx3", "voice_gender": "female"},
            "llama_cpp": {"enabled": True, "managed": False, "host": local_model_host},
            "ollama": {"enabled": False, "host": "http://127.0.0.1:11434"},
        }, indent=2) + "\n", encoding="utf-8")
    return env


def _close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not kernel32.CloseHandle(handle):
        error = ctypes.get_last_error()
        raise SmokeFailure(f"CloseHandle failed (Windows error {error})")


def _process_image_path(pid: int) -> tuple[int, Path]:
    if os.name != "nt":
        raise SmokeFailure("desktop shell smoke is supported on Windows only")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE,
        False,
        pid,
    )
    if not handle:
        raise SmokeFailure(f"could not open verified process {pid}")
    capacity = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(capacity.value)
    if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
        error = ctypes.get_last_error()
        _close_handle(handle)
        raise SmokeFailure(f"could not verify backend child image path (Windows error {error})")
    return handle, Path(buffer.value)


def _expected_backend_image(application: Path) -> Path:
    return (application.parent / "backend-bundle" / "apex-backend.exe").resolve()


def _terminate_verified_backend(pid: int, application: Path, profile: Path, instance_id: object) -> None:
    handle, image = _process_image_path(pid)
    try:
        if image.resolve() != _expected_backend_image(application):
            raise SmokeFailure("runtime identity PID image is not the bundled backend executable")
        current = _runtime_identity(profile, 5.0)
        if current.get("pid") != pid or current.get("instance_id") != instance_id:
            raise SmokeFailure("managed runtime identity changed before termination; refusing to target a reused PID")
        _terminate_process_handle(handle, "backend child")
        if not _wait_process_handle(handle, 10.0):
            raise SmokeFailure("verified backend child did not exit after termination")
    finally:
        _close_handle(handle)


def _descendant_process_ids(root_pid: int) -> set[int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        raise SmokeFailure("could not enumerate processes to find the smoke-owned native shell")
    entries: list[tuple[int, int]] = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            entries.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _close_handle(snapshot)
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in entries:
            if parent in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    descendants.discard(root_pid)
    return descendants


def _native_window(driver_pid: int, application: Path) -> tuple[int, int, int]:
    """Return the exact smoke-owned native process handle, PID, and window handle."""
    if os.name != "nt":
        raise SmokeFailure("native window inspection is supported on Windows only")
    expected_image = application.resolve()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    matches: list[tuple[int, int, int]] = []
    for pid in _descendant_process_ids(driver_pid):
        try:
            handle, image = _process_image_path(pid)
        except SmokeFailure:
            continue
        if image.resolve() != expected_image:
            _close_handle(handle)
            continue
        hwnds: list[int] = []
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @enum_proc
        def collect(hwnd: int, _lparam: int) -> bool:
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid and user32.IsWindow(hwnd):
                title_length = user32.GetWindowTextLengthW(hwnd)
                title = ctypes.create_unicode_buffer(title_length + 1)
                user32.GetWindowTextW(hwnd, title, len(title))
                if title.value == "APEX":
                    hwnds.append(int(hwnd))
            return True

        user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumWindows(collect, 0)
        if len(hwnds) == 1:
            matches.append((handle, pid, hwnds[0]))
        else:
            _close_handle(handle)
    if len(matches) != 1:
        for handle, _pid, _hwnd in matches:
            _close_handle(handle)
        raise SmokeFailure(f"expected one smoke-owned APEX main window, found {len(matches)}")
    return matches[0]


def _window_visible(hwnd: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    return bool(user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd))


def _invoke_tray_menu_item(label: str, timeout: float, *, expected_pid: int) -> None:
    """Click a verified menu item on the exact APEX Windows tray popup."""
    if os.name != "nt":
        raise SmokeFailure("Windows tray interaction is supported on Windows only")
    if label not in {"Show", "Quit"} or expected_pid <= 0:
        raise ValueError("tray interaction requires a supported menu item and exact APEX PID")
    script = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class TrayNative {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
  [StructLayout(LayoutKind.Sequential)] public struct MENUBARINFO {
    public uint cbSize; public RECT rect; public IntPtr hMenu, hwndMenu; public uint flags;
  }
  [StructLayout(LayoutKind.Sequential)] public struct MENUITEMINFO {
    public uint cbSize, fMask, fType, fState, wID;
    public IntPtr hSubMenu, hbmpChecked, hbmpUnchecked, dwItemData, dwTypeData;
    public uint cch; public IntPtr hbmpItem;
  }
  [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
  [DllImport("user32.dll", SetLastError=true)] public static extern bool GetMenuBarInfo(IntPtr hwnd, int objectId, int item, ref MENUBARINFO info);
  [DllImport("user32.dll", SetLastError=true)] public static extern int GetMenuItemCount(IntPtr menu);
  [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool GetMenuItemInfoW(IntPtr menu, uint item, bool byPosition, ref MENUITEMINFO info);
  [DllImport("user32.dll", SetLastError=true)] public static extern bool GetMenuItemRect(IntPtr hwnd, IntPtr menu, uint item, out RECT rect);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT point);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string className, string title);
  [DllImport("user32.dll", SetLastError=true)]
  public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")]
  public static extern void mouse_event(uint flags, uint x, uint y, uint data, UIntPtr extra);
}
'@
$null = [TrayNative]::SetThreadDpiAwarenessContext([IntPtr](-4))
$expectedPid = [int]__EXPECTED_PID__
$null = Get-Process -Id $expectedPid -ErrorAction Stop
$root = [System.Windows.Automation.AutomationElement]::RootElement
$shellCondition = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ClassNameProperty, 'Shell_TrayWnd')
$shellWindows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $shellCondition)
if ($shellWindows.Count -ne 1) { throw "expected one Windows taskbar, found $($shellWindows.Count)" }
$shell = $shellWindows.Item(0)
$explorerPid = [int]$shell.Current.ProcessId
$explorer = Get-Process -Id $explorerPid -ErrorAction Stop
$expectedExplorerPath = [IO.Path]::GetFullPath((Join-Path $env:WINDIR 'explorer.exe'))
if ([IO.Path]::GetFullPath($explorer.Path) -ine $expectedExplorerPath) { throw 'taskbar UIA host was not Windows Explorer' }
$xamlHwnd = [TrayNative]::FindWindowEx(
  [IntPtr]$shell.Current.NativeWindowHandle, [IntPtr]::Zero,
  'Windows.UI.Composition.DesktopWindowContentBridge', 'DesktopWindowXamlSource')
if ($xamlHwnd -eq [IntPtr]::Zero) { throw 'taskbar XAML UIA host was not found' }
$taskbarHost = [System.Windows.Automation.AutomationElement]::FromHandle($xamlHwnd)
$buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::Button)
$icons = [System.Collections.ArrayList]::new()
function Add-APEXTrayIcons($scopeRoot, $destination, $ownerPid) {
  $elements = $scopeRoot.FindAll([System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
  for ($i = 0; $i -lt $elements.Count; $i++) {
    $element = $elements.Item($i)
    $current = $element.Current
    if ($current.Name -ceq 'APEX' -and
        $current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
        $current.ClassName -ceq 'SystemTray.NormalButton' -and
        $current.AutomationId -ceq 'NotifyItemIcon' -and
        $current.ProcessId -eq $ownerPid -and
        -not $current.IsOffscreen) {
      [void]$destination.Add($element)
    }
  }
}
function Get-APEXOverflowHosts($automationRoot, $ownerPid) {
  $condition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ClassNameProperty,
    'TopLevelWindowForOverflowXamlIsland')
  $windows = $automationRoot.FindAll([System.Windows.Automation.TreeScope]::Children, $condition)
  $hosts = [System.Collections.ArrayList]::new()
  for ($i = 0; $i -lt $windows.Count; $i++) {
    $window = $windows.Item($i)
    if ($window.Current.ProcessId -eq $ownerPid -and -not $window.Current.IsOffscreen) {
      [void]$hosts.Add($window)
    }
  }
  return ,$hosts
}
$overflowHosts = Get-APEXOverflowHosts $root $explorerPid
if ($overflowHosts.Count -gt 1) { throw "ambiguous visible notification overflow windows: $($overflowHosts.Count)" }
Add-APEXTrayIcons $taskbarHost $icons $explorerPid
if ($overflowHosts.Count -eq 1) { Add-APEXTrayIcons $overflowHosts[0] $icons $explorerPid }
if ($icons.Count -eq 0) {
  if ($overflowHosts.Count -eq 1) { throw 'visible notification overflow did not contain the APEX tray icon' }
  $buttons = $taskbarHost.FindAll([System.Windows.Automation.TreeScope]::Descendants, $buttonCondition)
  $hiddenButtons = [System.Collections.ArrayList]::new()
  for ($i = 0; $i -lt $buttons.Count; $i++) {
    $button = $buttons.Item($i)
    $current = $button.Current
    if ($current.ClassName -ceq 'SystemTray.NormalButton' -and
        $current.AutomationId -ceq 'SystemTrayIcon' -and
        $current.ProcessId -eq $explorerPid -and
        $current.Name -match '^Show Hidden Icons(?: Hide)?$') {
      [void]$hiddenButtons.Add($button)
    }
  }
  if ($hiddenButtons.Count -ne 1) { throw "expected one real taskbar Show Hidden Icons control, found $($hiddenButtons.Count)" }
  if ($hiddenButtons[0].Current.Name -ceq 'Show Hidden Icons Hide') {
    throw 'notification overflow reports open but its visible UIA host was absent; refusing to toggle it closed'
  }
  $toggle = $hiddenButtons[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $toggle.Invoke()
  $overflowDeadline = [DateTime]::UtcNow.AddSeconds(__OVERFLOW_TIMEOUT__)
  while ([DateTime]::UtcNow -lt $overflowDeadline -and $icons.Count -eq 0) {
    $overflowHosts = Get-APEXOverflowHosts $root $explorerPid
    if ($overflowHosts.Count -gt 1) { throw "ambiguous visible notification overflow windows: $($overflowHosts.Count)" }
    if ($overflowHosts.Count -eq 1) { Add-APEXTrayIcons $overflowHosts[0] $icons $explorerPid }
    if ($icons.Count -eq 0) { Start-Sleep -Milliseconds 100 }
  }
}
if ($icons.Count -ne 1) { throw "expected one actual APEX notification-area icon, found $($icons.Count)" }
# Explorer publishes transient bounds during the overflow animation. Reacquire
# the exact icon until its usable physical bounds have stayed still for 400 ms.
$stableDeadline = [DateTime]::UtcNow.AddSeconds(__OVERFLOW_TIMEOUT__)
$stableSince = [DateTime]::UtcNow
$lastBounds = ''
$rect = $null
while ([DateTime]::UtcNow -lt $stableDeadline) {
  $icons.Clear()
  Add-APEXTrayIcons $taskbarHost $icons $explorerPid
  $overflowHosts = Get-APEXOverflowHosts $root $explorerPid
  if ($overflowHosts.Count -gt 1) { throw 'ambiguous notification overflow windows during animation' }
  if ($overflowHosts.Count -eq 1) { Add-APEXTrayIcons $overflowHosts[0] $icons $explorerPid }
  if ($icons.Count -ne 1) { throw 'the exact APEX tray icon disappeared or became ambiguous' }
  $candidate = $icons[0].Current.BoundingRectangle
  if ($candidate.IsEmpty -or $candidate.Width -le 0 -or $candidate.Height -le 0) {
    $lastBounds = ''; $stableSince = [DateTime]::UtcNow
  } else {
    $bounds = $candidate.ToString()
    if ($bounds -cne $lastBounds) { $lastBounds = $bounds; $stableSince = [DateTime]::UtcNow }
    if (([DateTime]::UtcNow - $stableSince).TotalMilliseconds -ge 400) { $rect = $candidate; break }
  }
  Start-Sleep -Milliseconds 100
}
if ($null -eq $rect) { throw 'APEX tray icon did not settle at usable screen bounds' }
$existingWindows = $root.FindAll([System.Windows.Automation.TreeScope]::Children,
  [System.Windows.Automation.Condition]::TrueCondition)
for ($i = 0; $i -lt $existingWindows.Count; $i++) {
  $current = $existingWindows.Item($i).Current
  if ($current.ProcessId -eq $expectedPid -and $current.ClassName -ceq '#32768') {
    throw 'an APEX popup menu was already open before the tray action'
  }
}
$x = [int](($rect.Left + $rect.Right) / 2); $y = [int](($rect.Top + $rect.Bottom) / 2)
if (-not [TrayNative]::SetCursorPos($x, $y)) { throw 'could not position pointer on the actual APEX tray icon' }
[TrayNative]::mouse_event(0x0008, 0, 0, 0, [UIntPtr]::Zero)
[TrayNative]::mouse_event(0x0010, 0, 0, 0, [UIntPtr]::Zero)
$deadline = [DateTime]::UtcNow.AddSeconds(__TIMEOUT__)
$menuItem = $null
while ([DateTime]::UtcNow -lt $deadline -and $null -eq $menuItem) {
  $topWindows = $root.FindAll([System.Windows.Automation.TreeScope]::Children,
    [System.Windows.Automation.Condition]::TrueCondition)
  $ownedMenus = [System.Collections.ArrayList]::new()
  for ($i = 0; $i -lt $topWindows.Count; $i++) {
    $window = $topWindows.Item($i)
    $current = $window.Current
    if ($current.ProcessId -eq $expectedPid -and $current.ClassName -ceq '#32768') {
      [void]$ownedMenus.Add($window)
    }
  }
  if ($ownedMenus.Count -gt 1) { throw "ambiguous APEX-owned popup menus: $($ownedMenus.Count)" }
  if ($ownedMenus.Count -eq 1) {
    # Standard popup menus can have no UIA descendants on Windows 11. Read
    # their real HMENU labels and bounds, then click the selected enabled item.
    $popupHwnd = [IntPtr]$ownedMenus[0].Current.NativeWindowHandle
    $bar = [TrayNative+MENUBARINFO]::new()
    $bar.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($bar)
    if ([TrayNative]::GetMenuBarInfo($popupHwnd, -4, 0, [ref]$bar) -and
        [TrayNative]::GetMenuItemCount($bar.hMenu) -eq 2) {
      $actions = @{}
      for ($position = 0; $position -lt 2; $position++) {
        $info = [TrayNative+MENUITEMINFO]::new()
        $info.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($info)
        $info.fMask = 0x147 # MIIM_STRING | MIIM_ID | MIIM_STATE | MIIM_SUBMENU | MIIM_FTYPE
        $info.cch = 256
        $info.dwTypeData = [Runtime.InteropServices.Marshal]::AllocHGlobal(514)
        try {
          if (-not [TrayNative]::GetMenuItemInfoW($bar.hMenu, $position, $true, [ref]$info)) { throw 'could not read the real APEX menu item' }
          $name = [Runtime.InteropServices.Marshal]::PtrToStringUni($info.dwTypeData, [int]$info.cch)
          if ($name -cnotin @('Show', 'Quit') -or $actions.ContainsKey($name) -or
              ($info.fState -band 3) -ne 0 -or $info.fType -ne 0 -or $info.hSubMenu -ne [IntPtr]::Zero) {
            throw 'the exact APEX popup did not contain two distinct enabled Show/Quit actions'
          }
          $itemRect = [TrayNative+RECT]::new()
          if (-not [TrayNative]::GetMenuItemRect($popupHwnd, $bar.hMenu, $position, [ref]$itemRect) -or
              $itemRect.Right -le $itemRect.Left -or $itemRect.Bottom -le $itemRect.Top) { throw 'APEX menu item had no usable bounds' }
          $actions[$name] = $itemRect
        } finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($info.dwTypeData) }
      }
      if ($actions.Count -eq 2) { $menuItem = $actions['__LABEL__'] }
    }
  }
  if ($null -eq $menuItem) { Start-Sleep -Milliseconds 100 }
}
if ($null -eq $menuItem) { throw 'the exact APEX process did not expose its verified tray menu' }
$point = [TrayNative+POINT]::new()
$point.X = [int](($menuItem.Left + $menuItem.Right) / 2)
$point.Y = [int](($menuItem.Top + $menuItem.Bottom) / 2)
$hitHwnd = [TrayNative]::WindowFromPoint($point)
$hitPid = [uint32]0
$null = [TrayNative]::GetWindowThreadProcessId($hitHwnd, [ref]$hitPid)
if ($hitHwnd -ne $popupHwnd -or $hitPid -ne $expectedPid) { throw 'verified tray action was obscured by another window' }
if (-not [TrayNative]::SetCursorPos($point.X, $point.Y)) { throw 'could not position pointer on the verified tray action' }
[TrayNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
[TrayNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
'''.replace("__EXPECTED_PID__", str(expected_pid)).replace(
        "__TIMEOUT__", str(max(1, int(timeout)))
    ).replace("__OVERFLOW_TIMEOUT__", str(max(1, int(min(timeout, 3.0))))).replace(
        "__LABEL__", label
    )
    try:
        # Keep the generated script off the Windows command line: encoded UIA
        # scripts can exceed CreateProcess's 32,767-character limit.
        with tempfile.TemporaryDirectory(prefix="apex-tray-smoke-") as temp_root:
            script_path = Path(temp_root) / "tray-action.ps1"
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout + 2 * min(timeout, 3.0) + 5.0,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SmokeFailure(f"Windows tray interaction could not run: {exc}") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-600:].strip()
        raise SmokeFailure(f"could not invoke the actual APEX tray {label} item: {detail or 'PowerShell failed'}")


def _runtime_identity(profile: Path, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = _http_json("/api/v1/runtime")
            if not isinstance(value, dict):
                raise SmokeFailure("runtime endpoint did not return an object")
            expected_fingerprint = hashlib.sha256(
                os.path.normcase(str(profile.resolve())).encode("utf-8")
            ).hexdigest()
            if value.get("app_id") != "apex" or value.get("hosting_mode") != "managed":
                raise SmokeFailure("API identity does not identify the managed APEX backend")
            if value.get("launch_id") is None or value.get("data_root_fingerprint") != expected_fingerprint:
                raise SmokeFailure("API identity does not match the disposable profile and managed launch")
            if not isinstance(value.get("pid"), int) or value["pid"] <= 0:
                raise SmokeFailure("runtime identity did not provide a valid backend PID")
            return value
        except (OSError, ValueError, SmokeFailure) as exc:
            last_error = exc
            time.sleep(POLL_INTERVAL_SECONDS)
    raise SmokeFailure(f"managed backend identity was not ready: {last_error or 'timeout'}")


def _button_xpath(label: str) -> str:
    if "'" in label:
        raise ValueError("button labels must not contain single quotes")
    return f"//button[normalize-space(.)='{label}' or @aria-label='{label}']"


def _wait_for_ready_element(
    driver: WebDriver,
    using: str,
    value: str,
    timeout: float,
    *,
    require_enabled: bool = True,
) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for element_id in driver.find_all(using, value):
            try:
                if driver.is_displayed(element_id) and (
                    not require_enabled or driver.is_enabled(element_id)
                ):
                    return element_id
            except WebDriverCommandError as exc:
                if exc.error not in {"stale element reference", "no such element"}:
                    raise
        time.sleep(POLL_INTERVAL_SECONDS)
    return None


def _create_port_occupant() -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 8000))
        listener.listen(1)
    except BaseException:
        listener.close()
        raise
    return listener


def _wait_port_free(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _api_port_available():
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return _api_port_available()


def _cleanup_temp_root(path: Path, timeout: float = 5.0) -> list[str]:
    """Retry only locked entries beneath this run's disposable temp root."""
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None

    def propagate_cleanup_error(function: Callable[..., Any], entry: str, error: OSError) -> None:
        raise error

    while True:
        try:
            shutil.rmtree(path, onexc=propagate_cleanup_error)
            return []
        except OSError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            return [f"could not remove {path}: {last_error}"]
        time.sleep(min(POLL_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic())))


def _wait_process_handle(handle: int, timeout: float) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == WAIT_OBJECT_0


def _terminate_process_handle(handle: int, label: str) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    if not kernel32.TerminateProcess(handle, 0xD35C):
        error = ctypes.get_last_error()
        raise SmokeFailure(f"could not terminate verified {label} process (Windows error {error})")


def _click_button(driver: WebDriver, label: str, timeout: float) -> bool:
    locator = _button_xpath(label)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        element = _wait_for_ready_element(
            driver, "xpath", locator,
            max(0.0, deadline - time.monotonic()),
        )
        if element is None:
            return False
        try:
            driver.click(element)
            return True
        except WebDriverCommandError as exc:
            if exc.error not in {
                "stale element reference",
                "no such element",
                "element not interactable",
            }:
                raise
            # The app can replace a transition screen between locator lookup
            # and click, or enable it after a state transition. Reacquire it.
            time.sleep(POLL_INTERVAL_SECONDS)
    return False


def _send_dialog_keys(keys: list[tuple[int, int]]) -> None:
    """Send key events to the already-focused native folder picker."""
    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class InputUnion(ctypes.Union):
        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t),
            ]

        _fields_ = [("mi", MouseInput), ("ki", KeyboardInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    if ctypes.sizeof(Input) != expected_size:
        raise SmokeFailure("native keyboard input structure has an unexpected Windows ABI size")
    events = (Input * len(keys))()
    for index, (key, flags) in enumerate(keys):
        events[index].type = 1  # INPUT_KEYBOARD
        if flags & 0x0004:  # KEYEVENTF_UNICODE uses wScan, with wVk set to zero.
            events[index].union.ki = KeyboardInput(0, key, flags, 0, None)
        else:
            events[index].union.ki = KeyboardInput(key, 0, flags, 0, None)
    sent = user32.SendInput(len(events), events, ctypes.sizeof(Input))
    if sent != len(events):
        raise SmokeFailure(f"could not control native folder picker (Windows error {ctypes.get_last_error()})")


def _picker_is_owned_by(shell_pid: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return False
    class_name = ctypes.create_unicode_buffer(256)
    if not user32.GetClassNameW(foreground, class_name, len(class_name)) or class_name.value != "#32770":
        return False
    owner = user32.GetAncestor(foreground, 3) or foreground  # GA_ROOTOWNER
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(owner, ctypes.byref(process_id))
    return process_id.value == shell_pid


def _wait_native_picker(shell_pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _picker_is_owned_by(shell_pid):
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return False


def _type_native_folder_path(path: Path, shell_pid: int, timeout: float) -> None:
    if not _wait_native_picker(shell_pid, timeout):
        raise SmokeFailure("native folder picker did not become the focused shell-owned window")
    # Ctrl+L focuses the common dialog location field. Unicode SendInput keeps
    # paths with spaces and non-ASCII characters intact without clipboard use.
    key_down, key_up, unicode_flag = 0, 0x0002, 0x0004
    sequence = [(0x11, key_down), (0x4C, key_down), (0x4C, key_up), (0x11, key_up)]
    encoded = str(path.resolve()).encode("utf-16-le", errors="strict")
    for offset in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[offset:offset + 2], "little")
        sequence.extend(((code_unit, unicode_flag), (code_unit, unicode_flag | key_up)))
    sequence.extend(((0x0D, key_down), (0x0D, key_up), (0x0D, key_down), (0x0D, key_up)))
    _send_dialog_keys(sequence)


def _continue_once_if_preflight_advisory(
    driver: WebDriver, fixture: LlamaCppStreamFixture, timeout: float
) -> str:
    dialog_locator = "//div[@role='dialog' and @aria-labelledby='preflight-dialog-title']"
    continue_once_locator = (
        "//div[@role='dialog' and @aria-labelledby='preflight-dialog-title']"
        "//button[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz')='continue once']"
    )
    deadline = time.monotonic() + timeout
    advisory_seen = False
    while time.monotonic() < deadline:
        if fixture.first_delta_sent.is_set():
            return "not_present"
        for dialog in driver.find_all("xpath", dialog_locator):
            try:
                if not driver.is_displayed(dialog):
                    continue
                text = driver.element_text(dialog).casefold()
            except WebDriverCommandError as exc:
                if exc.error in {"stale element reference", "no such element"}:
                    continue
                raise
            if "preflight advisory" not in text:
                continue
            advisory_seen = True
            button = _wait_for_ready_element(
                driver,
                "xpath",
                continue_once_locator,
                max(0.0, deadline - time.monotonic()),
            )
            if button is None:
                return "unavailable"
            try:
                driver.click(button)
            except WebDriverCommandError as exc:
                if exc.error not in {
                    "stale element reference",
                    "no such element",
                    "element not interactable",
                }:
                    raise
                continue
            close_deadline = min(deadline, time.monotonic() + 3.0)
            while time.monotonic() < close_deadline:
                visible = False
                for candidate in driver.find_all("xpath", dialog_locator):
                    try:
                        visible = driver.is_displayed(candidate)
                    except WebDriverCommandError as exc:
                        if exc.error not in {"stale element reference", "no such element"}:
                            raise
                    if visible:
                        break
                if not visible:
                    return "continued"
                time.sleep(POLL_INTERVAL_SECONDS)
            return "unavailable"
        time.sleep(POLL_INTERVAL_SECONDS)
    return "unavailable" if advisory_seen else "not_present"


def _retry_backend(driver: WebDriver, timeout: float) -> bool:
    return _click_button(driver, "Retry backend", timeout) and _click_button(driver, "Restart backend", timeout)


def _wait_text(driver: WebDriver, text: str, timeout: float) -> bool:
    return driver.wait_for("visible text", lambda: text in driver.text(), timeout)


def _run_desktop_import_smoke(
    *, application: Path, tauri_driver: Path, native_driver: Path, timeout: float, report: Report,
) -> None:
    """Exercise Import through the native picker and reopen the imported profile."""
    if not _api_port_available():
        report.add("desktop_import_setup", "unverified", "127.0.0.1:8000 was not free after the main shell smoke")
        return
    helper = Path(__file__).resolve().with_name("data_import_rehearsal.py")
    profile_root: Path | None = None
    shell_handle: int | None = None
    backend_handle: int | None = None
    driver_process: subprocess.Popen[bytes] | None = None
    driver: WebDriver | None = None
    environment: dict[str, str] | None = None
    shell_pid: int | None = None
    root: Path | None = None
    logs: list[tuple[str, Path]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="apex-desktop-import-smoke-", delete=False) as temp_name:
            root = Path(temp_name)
        source = root / "source-profile"
        result = subprocess.run(
            [sys.executable, str(helper), "seed", str(source)],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=min(60.0, timeout), check=False,
            env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        )
        if result.returncode != 0:
            raise SmokeFailure("production preservation fixture could not be prepared for desktop Import")
        seed = json.loads(result.stdout.decode("utf-8"))
        if not isinstance(seed, dict) or not isinstance(seed.get("source_fingerprint"), str):
            raise SmokeFailure("production preservation fixture returned malformed seed evidence")
        source_verify = subprocess.run(
            [sys.executable, str(helper), "verify", str(source)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=min(45.0, timeout), check=False,
            env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        )
        if source_verify.returncode != 0:
            raise SmokeFailure("production fixture could not be read before desktop Import")
        baseline = json.loads(source_verify.stdout.decode("utf-8"))

        profile_root = root / "profile"
        environment = _sanitized_environment(root, demo=False)
        control_port, native_port = _available_port(), _available_port()
        while native_port == control_port:
            native_port = _available_port()
        log_path = root / "tauri-driver-import.log"
        logs.append(("import_driver", log_path))
        with log_path.open("wb") as log_file:
            driver_process = subprocess.Popen(
                [str(tauri_driver), "--port", str(control_port), "--native-port", str(native_port), "--native-driver", str(native_driver)],
                stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
                env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        driver = WebDriver(control_port, min(20.0, timeout))
        service_deadline = time.monotonic() + min(30.0, timeout)
        while time.monotonic() < service_deadline:
            if driver_process.poll() is not None:
                raise SmokeFailure("import tauri-driver exited before accepting WebDriver commands")
            try:
                driver.request("GET", "/status")
                break
            except SmokeFailure:
                time.sleep(POLL_INTERVAL_SECONDS)
        else:
            raise SmokeFailure("import tauri-driver did not become ready")
        driver.start(application.resolve())
        if not driver.wait_for("first-run Import choice", lambda: _clickable(driver, "Import from a checkout"), min(45.0, timeout)):
            raise SmokeFailure("blank import profile did not show the native first-run choice")
        shell_handle, shell_pid, _shell_hwnd = _native_window(driver_process.pid, application)

        if not _click_button(driver, "Import from a checkout", min(8.0, timeout)) or not _wait_native_picker(shell_pid, min(15.0, timeout)):
            raise SmokeFailure("Import did not open its native source-folder picker")
        _send_dialog_keys([(0x1B, 0), (0x1B, 0x0002)])
        if not driver.wait_for("canceled picker leaves setup choice", lambda: _clickable(driver, "Fresh Start") and _clickable(driver, "Import from a checkout"), min(10.0, timeout)):
            raise SmokeFailure("canceling the native folder picker did not leave the setup choice available")
        report.add("native_import_picker_cancel", "passed", "canceling the native picker left the blank profile unchanged")

        if not _click_button(driver, "Import from a checkout", min(8.0, timeout)):
            raise SmokeFailure("Import source picker could not be reopened after cancellation")
        _type_native_folder_path(source, shell_pid, min(15.0, timeout))
        progress_seen = driver.wait_for(
            "native import preview progress",
            lambda: any(label in driver.text() for label in (
                "Reviewing managed files", "Preparing database preview",
                "Preparing database preview transfer", "Preparing database preview backup",
                "Validating imported data",
            )),
            min(20.0, timeout),
        )
        if not driver.wait_for("import preview ready", lambda: _clickable(driver, "Import these files") or "Import cannot continue" in driver.text(), min(90.0, timeout)):
            raise SmokeFailure("the native picker source did not produce a visible import preview")
        preview_text = driver.text()
        if str(source.resolve()).casefold() in preview_text.casefold() or "apex_memory.db" not in preview_text or "Review imported data" not in preview_text:
            raise SmokeFailure("WebView preview exposed the source path or omitted the managed database label")
        if not _clickable(driver, "Import these files"):
            raise SmokeFailure("production fixture import preview contained blockers")
        # The product refreshes setup snapshots every 2.5 seconds while waiting
        # for first-run setup. Keep the preview open through one refresh period.
        refresh_period_deadline = time.monotonic() + 2.7
        if not driver.wait_for(
            "preview retained through setup refresh",
            lambda: time.monotonic() >= refresh_period_deadline
            and "apex_memory.db" in driver.text()
            and _clickable(driver, "Import these files"),
            3.5,
        ):
            raise SmokeFailure("import preview was not retained through the setup snapshot refresh period")
        report.add(
            "native_import_progress", "passed" if progress_seen else "unverified",
            "checking-stage progress rendered in WebView" if progress_seen else "preview completed before WebDriver could sample the short-lived checking-stage progress",
        )
        report.add(
            "native_import_preview", "passed",
            "native picker selected the disposable source; managed database preview remained available through setup snapshot refresh",
        )
        if not _click_button(driver, "Import these files", min(8.0, timeout)):
            raise SmokeFailure("WebView Import confirmation was unavailable")
        if not driver.wait_for("import commit progress", lambda: "Importing APEX data" in driver.text() or "Copying files:" in driver.text(), min(20.0, timeout)):
            # Small fixtures can complete before the next WebDriver poll. The
            # subsequent ready identity is still required for a passing import.
            pass
        runtime = _runtime_identity(profile_root, min(180.0, timeout))
        if runtime.get("hosting_mode") != "managed":
            raise SmokeFailure("imported desktop profile did not start a managed backend")
        verify = subprocess.run(
            [sys.executable, str(helper), "verify", str(profile_root)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=min(45.0, timeout), check=False,
            env=environment,
        )
        if verify.returncode != 0:
            raise SmokeFailure("imported-profile production reader verification failed after backend startup")
        verified = json.loads(verify.stdout.decode("utf-8"))
        if verified.get("action_status") != "outcome_unknown" or verified.get("action_effects") != baseline.get("action_effects") or verified.get("action_events") != baseline.get("action_events") or verified.get("action_effects") != 1:
            raise SmokeFailure("normal backend startup changed the uncertain action or replayed its effect")
        cache_path = root / "local-app-data" / "APEX" / "auth" / "microsoft_todo_token_cache.bin"
        if hashlib.sha256(cache_path.read_bytes()).hexdigest() != seed.get("microsoft_cache_sha256"):
            raise SmokeFailure("desktop Import changed the same-user encrypted Microsoft cache bytes")
        source_fingerprint = subprocess.run(
            [sys.executable, str(helper), "fingerprint", str(source)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False, env=environment,
        )
        if source_fingerprint.returncode != 0 or json.loads(source_fingerprint.stdout.decode("utf-8")).get("fingerprint") != seed.get("source_fingerprint"):
            raise SmokeFailure("desktop Import changed source-profile managed bytes")
        report.add("desktop_import_preservation_after_startup", "passed", "production readers, exact action state, encrypted cache bytes, and source fingerprint survived normal backend startup")

        # Prove Quit owns the managed child, then relaunch the imported profile
        # through the desktop app and re-read the uncertain action after startup.
        backend_handle, _image = _process_image_path(int(runtime["pid"]))
        try:
            _invoke_tray_menu_item("Quit", min(10.0, timeout), expected_pid=shell_pid)
        except SmokeFailure as exc:
            raise SmokeFailure(f"actual tray Quit could not be verified for imported helper cleanup: {exc}") from None
        if not _wait_process_handle(backend_handle, min(float(runtime.get("shutdown_timeout_seconds", 60)) + 20.0, timeout + 20.0)) or not _wait_process_handle(shell_handle, min(30.0, timeout)):
            raise SmokeFailure("tray Quit did not stop both the imported backend child and desktop shell")
        _close_handle(backend_handle)
        backend_handle = None
        _close_handle(shell_handle)
        shell_handle = None
        driver.close()
        driver = None
        if driver_process.poll() is None:
            driver_process.terminate()
            driver_process.wait(timeout=5)
        driver_process = None
        if not _wait_port_free(min(30.0, timeout)):
            raise SmokeFailure("tray Quit did not release the imported backend API port")
        report.add("desktop_import_quit_cleanup", "passed", "tray Quit stopped the imported helper and shell and released its API port")

        # Normal second launch verifies existing imported profile admission.
        control_port, native_port = _available_port(), _available_port()
        while native_port == control_port:
            native_port = _available_port()
        restart_log = root / "tauri-driver-import-restart.log"
        logs.append(("import_restart_driver", restart_log))
        with restart_log.open("wb") as log_file:
            driver_process = subprocess.Popen(
                [str(tauri_driver), "--port", str(control_port), "--native-port", str(native_port), "--native-driver", str(native_driver)],
                stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
                env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        driver = WebDriver(control_port, min(20.0, timeout))
        driver.wait_for("restart driver", lambda: _driver_ready(driver, driver_process), min(30.0, timeout))
        driver.start(application.resolve())
        restarted_runtime = _runtime_identity(profile_root, min(90.0, timeout))
        if restarted_runtime.get("hosting_mode") != "managed" or restarted_runtime.get("data_root_fingerprint") != runtime.get("data_root_fingerprint"):
            raise SmokeFailure("repeat desktop launch did not reopen the imported data root")
        verify = subprocess.run(
            [sys.executable, str(helper), "verify", str(profile_root)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=min(45.0, timeout), check=False, env=environment,
        )
        replay = json.loads(verify.stdout.decode("utf-8")) if verify.returncode == 0 else {}
        if replay.get("action_status") != "outcome_unknown" or replay.get("action_events") != baseline.get("action_events") or replay.get("action_effects") != baseline.get("action_effects") or replay.get("action_effects") != 1:
            raise SmokeFailure("backend restart replayed or changed the uncertain action effect")
        report.add("desktop_import_repeat_launch", "passed", "existing imported profile reopened and uncertain action remained unchanged after normal backend startup")
        shell_handle, shell_pid, _ = _native_window(driver_process.pid, application)
        backend_handle, _ = _process_image_path(int(restarted_runtime["pid"]))
        _invoke_tray_menu_item("Quit", min(10.0, timeout), expected_pid=shell_pid)
        if not _wait_process_handle(backend_handle, 90.0) or not _wait_process_handle(shell_handle, 30.0):
            raise SmokeFailure("repeat-launch tray Quit did not stop its managed child")
        report.add("desktop_import_repeat_cleanup", "passed", "repeat-launch helper child exited through tray Quit")
    except (SmokeFailure, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        _capture_failure_diagnostics(report, stage="desktop_import", driver=driver, log_paths=logs)
        report.add("desktop_import_setup", "failed", str(exc))
    finally:
        if shell_handle is not None and not _wait_process_handle(shell_handle, 0):
            try:
                if shell_pid is None:
                    raise SmokeFailure("native shell PID was not captured")
                _invoke_tray_menu_item("Quit", 3.0, expected_pid=shell_pid)
            except SmokeFailure:
                _terminate_process_handle(shell_handle, "exact smoke-owned desktop import shell")
            _wait_process_handle(shell_handle, 5.0)
        if backend_handle is not None and not _wait_process_handle(backend_handle, 0):
            _wait_process_handle(backend_handle, 5.0)
        for handle in (backend_handle, shell_handle):
            if handle is not None:
                _close_handle(handle)
        if driver is not None:
            driver.close()
        if driver_process is not None and driver_process.poll() is None:
            driver_process.terminate()
            try:
                driver_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                driver_process.kill()
                driver_process.wait(timeout=5)
        if profile_root is not None and profile_root.exists():
            try:
                remaining = _runtime_identity(profile_root, 2.0)
            except SmokeFailure:
                pass
            else:
                try:
                    _terminate_verified_backend(int(remaining["pid"]), application, profile_root, remaining["instance_id"])
                except (SmokeFailure, OSError, ValueError):
                    pass
        if root is not None and root.exists():
            cleanup_errors = _cleanup_temp_root(root)
            report.add("desktop_import_profile_cleanup", "passed" if not root.exists() else "unverified", "desktop Import fixture directory was removed" if not root.exists() else "desktop Import fixture directory remained after bounded cleanup")


def _clickable(driver: WebDriver, label: str) -> bool:
    try:
        return driver.find("xpath", _button_xpath(label)) is not None
    except SmokeFailure:
        return False


def _driver_ready(driver: WebDriver, process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        raise SmokeFailure("tauri-driver exited before accepting WebDriver commands")
    try:
        driver.request("GET", "/status")
        return True
    except SmokeFailure:
        return False


def _capture_cortex_stream_failure(
    report: Report,
    *,
    driver: WebDriver,
    fixture: LlamaCppStreamFixture,
    log_paths: list[tuple[str, Path]],
) -> None:
    _capture_failure_diagnostics(
        report,
        stage="cortex_stream_failure",
        driver=driver,
        log_paths=log_paths,
    )
    report.add_diagnostic(
        "cortex_stream_fixture_state",
        json.dumps(fixture.diagnostics(), ensure_ascii=False)[:8_000],
    )
    try:
        raw_runs = _http_json("/api/v1/cortex/runs?limit=10")
    except (SmokeFailure, OSError, ValueError) as exc:
        report.add_diagnostic("cortex_stream_public_runs_error", str(exc)[:2_000])
        return
    safe_runs: list[dict[str, object]] = []
    if isinstance(raw_runs, list):
        for record in raw_runs[:10]:
            if not isinstance(record, dict):
                continue
            safe: dict[str, object] = {
                key: record.get(key)
                for key in (
                    "status",
                    "provider",
                    "runtime",
                    "turns_count",
                    "tool_calls_count",
                    "retries_count",
                )
                if isinstance(record.get(key), (str, int, float, type(None)))
            }
            error = record.get("error")
            if isinstance(error, dict):
                safe["error"] = {
                    "code": error.get("code") if isinstance(error.get("code"), str) else None,
                    "message": error.get("message")[:300] if isinstance(error.get("message"), str) else None,
                }
            safe_runs.append(safe)
    report.add_diagnostic(
        "cortex_stream_public_runs",
        json.dumps(safe_runs, ensure_ascii=False)[:8_000],
    )


def _run_smoke(
    *,
    application: Path,
    tauri_driver: Path,
    native_driver: Path,
    timeout: float,
) -> Report:
    report = Report()
    if os.name != "nt":
        report.add("windows_host", "failed", "the packaged desktop shell smoke requires Windows")
        return report
    for name, path in (("application", application), ("tauri-driver", tauri_driver), ("msedgedriver", native_driver)):
        if not path.is_file():
            report.add(f"{name}_exists", "failed", f"file was not found: {path}")
            return report
    report.add("smoke_inputs", "passed")

    if not _api_port_available():
        report.add("api_port_available", "failed", "127.0.0.1:8000 is occupied; existing listener left untouched")
        return report
    report.add("api_port_available", "passed", "127.0.0.1:8000 was free before application launch")

    profile_root: Path | None = None
    driver_process: subprocess.Popen[bytes] | None = None
    driver: WebDriver | None = None
    fixture: LlamaCppStreamFixture | None = None
    driver_log_paths: list[tuple[str, Path]] = []
    held_api_port: socket.socket | None = None
    root: Path | None = None
    with tempfile.TemporaryDirectory(
        prefix="apex-desktop-smoke-", delete=False
    ) as temp_name:
        root = Path(temp_name)
        profile_root = root / "profile"
        env = _sanitized_environment(root)
        control_port = _available_port()
        native_port = _available_port()
        while native_port == control_port:
            native_port = _available_port()
        log_path = root / "tauri-driver.log"
        driver_log_paths.append(("demo_driver", log_path))
        try:
            with log_path.open("wb") as log_file:
                driver_process = subprocess.Popen(
                    [
                        str(tauri_driver),
                        "--port", str(control_port),
                        "--native-port", str(native_port),
                        "--native-driver", str(native_driver),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            driver = WebDriver(control_port, min(20.0, timeout))
            deadline = time.monotonic() + min(30.0, timeout)
            while time.monotonic() < deadline:
                if driver_process.poll() is not None:
                    raise SmokeFailure("tauri-driver exited before accepting WebDriver commands")
                try:
                    driver.request("GET", "/status")
                    break
                except SmokeFailure:
                    time.sleep(POLL_INTERVAL_SECONDS)
            else:
                raise SmokeFailure("tauri-driver did not become ready on its private control port")
            report.add("webdriver_service", "passed", f"tauri-driver control port {control_port}")

            # Create one short-lived, owned port conflict so the native startup
            # error and Retry path are exercised without touching an existing
            # listener. The earlier preflight guarantees this socket is ours.
            held_api_port = _create_port_occupant()
            driver.start(application.resolve())
            if not driver.wait_for("native shell window", lambda: bool(driver.text()), min(45.0, timeout)):
                held_api_port.close()
                raise SmokeFailure("native WebView did not expose a document")
            report.add("native_webview_started", "passed")

            # A brand-new desktop data root must wait for an explicit choice.
            # Select Fresh Start here so the remainder of this established
            # lifecycle smoke continues to exercise the normal backend path.
            if not driver.wait_for(
                "first-run setup choice",
                lambda: driver.find("xpath", _button_xpath("Fresh Start")) is not None,
                min(20.0, timeout),
            ):
                raise SmokeFailure("blank desktop profile did not show its first-run setup choice")
            if not _click_button(driver, "Fresh Start", min(8.0, timeout)):
                raise SmokeFailure("Fresh Start was unavailable for the blank disposable desktop profile")
            if not driver.wait_for(
                "first-run Fresh Start completion",
                lambda: driver.find("xpath", _button_xpath("Retry backend")) is not None
                or "port" in driver.text().lower(),
                min(20.0, timeout),
            ):
                raise SmokeFailure("explicit Fresh Start did not continue to backend startup")
            report.add("first_run_fresh_start", "passed", "blank profile proceeded only after the user selected Fresh Start")

            conflict_visible = driver.wait_for(
                "port conflict state",
                lambda: (
                    driver.find("xpath", _button_xpath("Retry backend")) is not None
                    and "port" in driver.text().lower()
                    and any(term in driver.text().lower() for term in ("in use", "already", "occupied", "reserve"))
                ),
                min(30.0, timeout),
            )
            held_api_port.close()
            held_api_port = None
            if not conflict_visible:
                diagnostic = _capture_failure_diagnostics(
                    report,
                    stage="startup_conflict",
                    driver=driver,
                    log_paths=driver_log_paths,
                )
                observed = diagnostic.get("visible_text", "")[:3_000]
                report.add(
                    "startup_conflict",
                    "failed",
                    "native shell did not show an actionable 127.0.0.1:8000 conflict with Retry backend; "
                    f"observed WebView text: {observed or '(empty)'}",
                )
                raise SmokeFailure("port conflict recovery state was not displayed")
            report.add("startup_conflict", "passed", "owned temporary listener triggered recoverable native startup error")
            if not _retry_backend(driver, min(8.0, timeout)):
                report.add("startup_retry", "failed", "Retry control was not available after releasing the owned test listener")
                raise SmokeFailure("native shell could not retry after the test released its listener")

            runtime = _runtime_identity(profile_root, timeout)
            report.add("managed_backend_identity", "passed", "runtime identity matched managed launch and disposable profile")
            report.add("startup_retry", "passed", "Retry started an identity-matched backend after the listener was released")

            workspace_names = ("Overview", "Briefing", "Cortex", "Reports")
            workspace_content = {
                "Overview": 'section[aria-label="Overview"]',
                "Briefing": 'section[aria-label="Briefing controls"]',
                "Cortex": 'section[aria-label="Cortex workspace"]',
                "Reports": 'section[aria-label="External activity reports"]',
            }
            for workspace in workspace_names:
                if not _click_button(driver, workspace, min(8.0, timeout)):
                    report.add(f"workspace_{workspace.lower()}", "failed", "workspace button was unavailable")
                    continue
                if driver.wait_for(
                    f"active {workspace} workspace",
                    lambda: driver.find("xpath", f"//nav[@aria-label='Workspace']//button[@aria-current='page' and normalize-space(.)='{workspace}']") is not None
                    and driver.find("css selector", workspace_content[workspace]) is not None,
                    min(15.0, timeout),
                ):
                    report.add(f"workspace_{workspace.lower()}", "passed")
                else:
                    report.add(f"workspace_{workspace.lower()}", "failed", "workspace navigation or content did not become active")

            if _click_button(driver, "Overview", min(8.0, timeout)):
                if _click_button(driver, "Collect Telemetry", min(8.0, timeout)):
                    if driver.wait_for("demo telemetry collection", lambda: not any(word in driver.text().lower() for word in ("collecting telemetry", "refreshing")), min(30.0, timeout)):
                        report.add("overview_telemetry", "passed", "demo telemetry collection returned to an idle or ready state")
                    else:
                        report.add("overview_telemetry", "failed", "demo telemetry collection did not finish")
                else:
                    report.add("overview_telemetry", "unverified", "the current Overview did not expose Collect Telemetry")

            setup_dialog = "//div[@role='dialog' and @aria-labelledby='briefing-setup-title']"
            if _click_button(driver, "Briefing", min(8.0, timeout)) and _click_button(driver, "Set up briefing", min(8.0, timeout)):
                if _wait_for_ready_element(
                    driver, "xpath", setup_dialog, min(8.0, timeout), require_enabled=False
                ) is None:
                    report.add("briefing_setup", "failed", "setup dialog did not open")
                elif _click_button(driver, "Generate Daily", min(8.0, timeout)):
                    def completed_demo_briefing() -> bool:
                        sessions = _http_json("/api/v1/briefing-sessions?limit=5")
                        return isinstance(sessions, list) and any(
                            isinstance(item, dict) and item.get("profile_id") == "daily" and item.get("run_status") == "completed"
                            for item in sessions
                        )

                    if driver.wait_for("completed demo briefing", completed_demo_briefing, min(90.0, timeout)):
                        report.add("demo_briefing", "passed", "Daily briefing was generated and read back from the backend")
                    else:
                        report.add("demo_briefing", "failed", "Daily briefing did not reach completed status")
                else:
                    report.add("demo_briefing", "failed", "Generate Daily control was unavailable")
            else:
                report.add("briefing_setup", "failed", "Briefing setup controls were unavailable")

            # Cortex streaming and cancellation need a held provider response. Demo
            # Cortex returns immediately, so end that disposable demo session and
            # start a second isolated native process against a local HTTP fixture.
            fixture = LlamaCppStreamFixture()
            first_runtime = _runtime_identity(profile_root, min(10.0, timeout))
            first_handle, first_image = _process_image_path(int(first_runtime["pid"]))
            try:
                if first_image.resolve() != _expected_backend_image(application):
                    raise SmokeFailure("demo PID is not the bundled backend executable")
                confirmed = _runtime_identity(profile_root, 5.0)
                if confirmed.get("pid") != first_runtime.get("pid") or confirmed.get("instance_id") != first_runtime.get("instance_id"):
                    raise SmokeFailure("demo runtime identity changed before closing its native session")
                close_budget = first_runtime.get("shutdown_timeout_seconds")
                if not isinstance(close_budget, (int, float)) or close_budget < 0:
                    raise SmokeFailure("demo runtime omitted its bounded shutdown timeout")
                shell_handle, shell_pid, _shell_hwnd = _native_window(driver_process.pid, application)
                try:
                    try:
                        _invoke_tray_menu_item("Quit", min(10.0, timeout), expected_pid=shell_pid)
                    except SmokeFailure as exc:
                        report.add_diagnostic("demo_tray_quit", f"real tray cleanup unavailable; exact shell handle used for bounded cleanup: {exc}")
                        _terminate_process_handle(shell_handle, "exact smoke-owned demo shell after tray automation failure")
                    bounded_close = min(float(close_budget) + 30.0, timeout + 30.0)
                    backend_exited = _wait_process_handle(first_handle, bounded_close)
                    shell_exited = _wait_process_handle(shell_handle, bounded_close)
                finally:
                    _close_handle(shell_handle)
                driver.close()
                if driver_process.poll() is None:
                    driver_process.terminate()
                    driver_process.wait(timeout=5)
                exited = backend_exited and shell_exited
            finally:
                _close_handle(first_handle)
            if not exited or not _wait_port_free(min(30.0, timeout)):
                raise SmokeFailure("verified demo backend did not exit and release 127.0.0.1:8000")
            stream_root = root / "stream-session"
            stream_env = _sanitized_environment(stream_root, demo=False, local_model_host=fixture.url)
            control_port = _available_port()
            native_port = _available_port()
            while native_port == control_port:
                native_port = _available_port()
            stream_log_path = root / "tauri-driver-stream.log"
            driver_log_paths.append(("stream_driver", stream_log_path))
            with stream_log_path.open("wb") as log_file:
                driver_process = subprocess.Popen(
                    [str(tauri_driver), "--port", str(control_port), "--native-port", str(native_port), "--native-driver", str(native_driver)],
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=stream_env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            driver = WebDriver(control_port, min(20.0, timeout))
            service_deadline = time.monotonic() + min(30.0, timeout)
            while time.monotonic() < service_deadline:
                if driver_process.poll() is not None:
                    raise SmokeFailure("fixture-session tauri-driver exited before becoming ready")
                try:
                    driver.request("GET", "/status")
                    break
                except SmokeFailure:
                    time.sleep(POLL_INTERVAL_SECONDS)
            else:
                raise SmokeFailure("fixture-session tauri-driver did not become ready")
            driver.start(application.resolve())
            if not driver.wait_for("fixture WebView", lambda: bool(driver.text()), min(45.0, timeout)):
                raise SmokeFailure("fixture-session WebView did not expose a document")
            profile_root = Path(stream_env["APEX_DATA_DIR"])
            runtime = _runtime_identity(profile_root, min(60.0, timeout))
            report.add("fixture_backend_identity", "passed", "second managed launch used its isolated profile and local provider fixture")
            if not _click_button(driver, "Cortex", min(8.0, timeout)):
                report.add("cortex_stream", "failed", "Cortex workspace was unavailable in the fixture session")
            else:
                prompt_selector = 'section[aria-label="Cortex workspace"] textarea[placeholder^="Ask "]'
                prompt = _wait_for_ready_element(
                    driver, "css selector", prompt_selector, min(20.0, timeout)
                )
                if prompt is None:
                    try:
                        state = json.dumps(driver.selector_state(prompt_selector), ensure_ascii=False)
                    except SmokeFailure as exc:
                        state = f"state unavailable: {exc}"
                    report.add_diagnostic("cortex_composer_input_state", state[:8_000])
                    report.add(
                        "cortex_stream",
                        "failed",
                        f"visible and enabled Cortex composer input was unavailable: {state[:2_000]}",
                    )
                else:
                    driver.type_text(prompt, "Return a short answer to exercise a streamed response.")
                    if not _click_button(driver, "Send", min(8.0, timeout)):
                        report.add("cortex_stream", "failed", "Cortex Send control was unavailable")
                    else:
                        preflight_result = _continue_once_if_preflight_advisory(
                            driver, fixture, min(10.0, timeout)
                        )
                        if preflight_result == "continued":
                            report.add(
                                "cortex_preflight_once",
                                "passed",
                                "the actual local-fixture Cortex turn continued through the existing one-time advisory action",
                            )
                        if preflight_result == "unavailable":
                            _capture_cortex_stream_failure(
                                report,
                                driver=driver,
                                fixture=fixture,
                                log_paths=driver_log_paths,
                            )
                            report.add(
                                "cortex_stream",
                                "failed",
                                "Preflight Advisory appeared but its Continue once action was unavailable or did not close the dialog",
                            )
                        elif not driver.wait_for(
                            "fixture first delta in WebView",
                            lambda: fixture.first_delta_sent.is_set() and "first streamed segment" in driver.text().lower(),
                            min(45.0, timeout),
                        ):
                            _capture_cortex_stream_failure(
                                report,
                                driver=driver,
                                fixture=fixture,
                                log_paths=driver_log_paths,
                            )
                            report.add("cortex_stream", "failed", "provider fixture did not produce an incremental delta visible in the native WebView")
                        else:
                            running = _http_json("/api/v1/cortex/runs?status=running&limit=5")
                            run_id = next((item.get("id") for item in running if isinstance(item, dict) and isinstance(item.get("id"), str)), None) if isinstance(running, list) else None
                            if run_id is None:
                                report.add("cortex_stream", "failed", "no running Cortex record was available while the fixture held its stream")
                            else:
                                if _wait_sse_event_type(run_id, "response.delta", timeout=min(15.0, timeout)):
                                    report.add("cortex_stream", "passed", "first provider delta rendered in WebView and appeared in the public run-event replay")
                                else:
                                    report.add("cortex_stream", "failed", "WebView rendered fixture text but run-event replay lacked response.delta")
                                if not _click_button(driver, "Stop generation", min(8.0, timeout)):
                                    report.add("cortex_cancel", "failed", "Stop generation control was unavailable while the fixture stream was held")
                                else:
                                    def cancellation_accepted() -> bool:
                                        value = _http_json(f"/api/v1/cortex/runs/{run_id}")
                                        return isinstance(value, dict) and value.get("status") in {"cancelling", "cancelled"}

                                    cancel_acknowledged = driver.wait_for(
                                        "persisted cancellation request",
                                        cancellation_accepted,
                                        min(10.0, timeout),
                                    )
                                    if not cancel_acknowledged:
                                        _capture_cortex_stream_failure(
                                            report,
                                            driver=driver,
                                            fixture=fixture,
                                            log_paths=driver_log_paths,
                                        )
                                        report.add(
                                            "cortex_cancel",
                                            "failed",
                                            "the public run record did not acknowledge cancellation before the fixture was released",
                                        )
                                    fixture.release_cancelled_stream.set()
                                    def cancelled() -> bool:
                                        value = _http_json(f"/api/v1/cortex/runs/{run_id}")
                                        return isinstance(value, dict) and value.get("status") == "cancelled"

                                    if cancel_acknowledged:
                                        if driver.wait_for("persisted cancelled Cortex run", cancelled, min(30.0, timeout)):
                                            terminal_events = _http_sse_event_types(run_id, timeout=min(15.0, timeout))
                                            if "run.completed" in terminal_events:
                                                report.add("cortex_cancel", "passed", "WebView Stop cancelled the held provider run and replay includes terminal activity")
                                            else:
                                                report.add("cortex_cancel", "failed", "run was persisted cancelled but terminal event was absent from replay")
                                        else:
                                            report.add("cortex_cancel", "failed", "Stop generation did not persist cancellation before the bound expired")
                                    else:
                                        def terminal_after_failed_cancel() -> bool:
                                            value = _http_json(f"/api/v1/cortex/runs/{run_id}")
                                            return isinstance(value, dict) and value.get("status") in {
                                                "completed", "failed", "cancelled", "interrupted"
                                            }

                                        driver.wait_for(
                                            "fixture run terminal cleanup",
                                            terminal_after_failed_cancel,
                                            min(30.0, timeout),
                                        )
            fixture.close()
            fixture = None

            # Crash recovery uses the public managed identity to identify one child, then
            # verifies its executable is inside this assembled bundle before terminating it.
            try:
                before_crash = _runtime_identity(profile_root, min(10.0, timeout))
                old_pid = int(before_crash["pid"])
                _terminate_verified_backend(old_pid, application, profile_root, before_crash["instance_id"])
                try:
                    automatically_recovered = _runtime_identity(profile_root, min(15.0, timeout))
                except SmokeFailure:
                    automatically_recovered = None
                if (
                    automatically_recovered is not None
                    and automatically_recovered["pid"] != old_pid
                    and automatically_recovered["instance_id"] != before_crash["instance_id"]
                ):
                    report.add("backend_crash_recovery", "passed", "shell restarted and matched a new managed backend identity")
                else:
                    if automatically_recovered is not None:
                        # The stale endpoint belonged to a different server after a PID
                        # transition; never terminate it or treat it as a restart.
                        raise SmokeFailure("backend did not stop after the verified child was terminated")
                    if not driver.wait_for(
                        "backend restart prompt",
                        lambda: driver.find("xpath", _button_xpath("Retry backend")) is not None,
                        min(20.0, timeout),
                    ):
                        report.add("backend_crash_recovery", "unverified", "no visible Retry backend state appeared after the owned backend stopped")
                    elif not _retry_backend(driver, min(8.0, timeout)):
                        report.add("backend_crash_recovery", "failed", "Retry backend confirmation disappeared before it could be used")
                    else:
                        after_crash = _runtime_identity(profile_root, min(45.0, timeout))
                        if after_crash["pid"] != old_pid and after_crash["instance_id"] != before_crash["instance_id"]:
                            report.add("backend_crash_recovery", "passed", "shell retried and matched a new managed backend identity")
                        else:
                            report.add("backend_crash_recovery", "failed", "retry did not establish a new backend identity")
            except (SmokeFailure, OSError, ValueError) as exc:
                report.add("backend_crash_recovery", "unverified", str(exc))

            # Closing hides the window. The same managed child and independent
            # CLI must remain usable until the user chooses tray Quit.
            final_runtime = _runtime_identity(profile_root, min(10.0, timeout))
            shutdown_budget = final_runtime.get("shutdown_timeout_seconds")
            if not isinstance(shutdown_budget, (int, float)) or shutdown_budget < 0:
                raise SmokeFailure("runtime identity omitted its bounded shutdown timeout")
            owned_handle, owned_image = _process_image_path(int(final_runtime["pid"]))
            shell_handle = 0
            try:
                if owned_image.resolve() != _expected_backend_image(application):
                    raise SmokeFailure("final backend PID is not the bundled backend executable")
                confirmed = _runtime_identity(profile_root, 5.0)
                if confirmed.get("pid") != final_runtime.get("pid") or confirmed.get("instance_id") != final_runtime.get("instance_id"):
                    raise SmokeFailure("runtime identity changed while opening the process handle; refusing to claim graceful shutdown")
                shell_handle, shell_pid, shell_hwnd = _native_window(driver_process.pid, application)
                if not _window_visible(shell_hwnd):
                    raise SmokeFailure("native APEX window was already hidden before the close-to-tray check")
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.PostMessageW.restype = wintypes.BOOL
                if not user32.PostMessageW(shell_hwnd, WM_CLOSE, 0, 0):
                    raise SmokeFailure("could not close the smoke-owned native window")
                hidden_deadline = time.monotonic() + min(15.0, timeout)
                while time.monotonic() < hidden_deadline and _window_visible(shell_hwnd):
                    if _wait_process_handle(shell_handle, 0.05):
                        break
                    time.sleep(POLL_INTERVAL_SECONDS)
                if _window_visible(shell_hwnd) or _wait_process_handle(shell_handle, 0):
                    report.add("close_to_tray", "failed", "close did not leave the same native window hidden and process alive")
                    raise SmokeFailure("window close did not hide the native window while retaining the shell process")
                after_hide = _runtime_identity(profile_root, 5.0)
                health_after_hide = _http_json("/api/v1/health/ready")
                cli = application.parent / "backend-bundle" / "apex.exe"
                if not cli.is_file():
                    report.add("close_to_tray", "unverified", "bundled CLI executable was not found for hidden-session access validation")
                    raise SmokeFailure("bundled CLI executable is unavailable")
                cli_result = subprocess.run(
                    [str(cli), "--json", "status"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=min(20.0, timeout),
                    env=env,
                    check=False,
                )
                cli_payload = json.loads(cli_result.stdout.decode("utf-8")) if cli_result.stdout else None
                if (
                    cli_result.returncode != 0
                    or not isinstance(cli_payload, dict)
                    or cli_payload.get("status") != "ready"
                    or after_hide.get("pid") != final_runtime.get("pid")
                    or after_hide.get("instance_id") != final_runtime.get("instance_id")
                    or health_after_hide != {"status": "ready", "config": "ok", "database": "ok"}
                ):
                    report.add("close_to_tray", "failed", "hidden shell lost backend identity, readiness, or independent CLI access")
                    raise SmokeFailure("backend or CLI access changed after closing the window")
                report.add("close_to_tray", "passed", "the window is hidden while the same shell, backend identity, API readiness, and CLI remain available")

                # A normal second process launch must activate the original shell.
                second = subprocess.Popen(
                    [str(application)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                try:
                    try:
                        second.wait(timeout=min(15.0, timeout))
                    except subprocess.TimeoutExpired:
                        report.add("single_instance_activation", "failed", "second native launch remained running instead of forwarding activation")
                    else:
                        activation_deadline = time.monotonic() + min(15.0, timeout)
                        while time.monotonic() < activation_deadline and not _window_visible(shell_hwnd):
                            time.sleep(POLL_INTERVAL_SECONDS)
                        same_runtime = _runtime_identity(profile_root, 5.0)
                        if (
                            _window_visible(shell_hwnd)
                            and same_runtime.get("pid") == final_runtime.get("pid")
                            and same_runtime.get("instance_id") == final_runtime.get("instance_id")
                            and not _wait_process_handle(shell_handle, 0)
                        ):
                            report.add("single_instance_activation", "passed", "second launch restored the original window and retained the original backend")
                        else:
                            report.add("single_instance_activation", "failed", "second launch did not restore the original native window and backend identity")
                finally:
                    if second.poll() is None:
                        second.terminate()
                        try:
                            second.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            second.kill()
                            second.wait(timeout=3)

                # Tray actions must pass through the Windows notification area UI.
                if _window_visible(shell_hwnd):
                    user32.PostMessageW(shell_hwnd, WM_CLOSE, 0, 0)
                    hide_deadline = time.monotonic() + min(10.0, timeout)
                    while time.monotonic() < hide_deadline and _window_visible(shell_hwnd):
                        time.sleep(POLL_INTERVAL_SECONDS)
                try:
                    _invoke_tray_menu_item("Show", min(10.0, timeout), expected_pid=shell_pid)
                    show_deadline = time.monotonic() + min(10.0, timeout)
                    while time.monotonic() < show_deadline and not _window_visible(shell_hwnd):
                        time.sleep(POLL_INTERVAL_SECONDS)
                    if _window_visible(shell_hwnd):
                        report.add("tray_show", "passed", "actual Windows tray Show action restored the original native window")
                    else:
                        report.add("tray_show", "failed", "Windows tray Show action did not restore the original window")
                except SmokeFailure as exc:
                    report.add("tray_show", "unverified", str(exc))

                try:
                    _invoke_tray_menu_item("Quit", min(10.0, timeout), expected_pid=shell_pid)
                except SmokeFailure as exc:
                    report.add("tray_quit", "unverified", str(exc))
                    tray_quit_unverified = True
                else:
                    tray_quit_unverified = False
                forced_shell_cleanup = False
                if tray_quit_unverified and not _wait_process_handle(shell_handle, 5.0):
                    _terminate_process_handle(shell_handle, "exact smoke-owned native shell after failed tray automation")
                    forced_shell_cleanup = True
                bounded_exit_wait = min(float(shutdown_budget) + 30.0, timeout + 30.0)
                backend_exited = _wait_process_handle(owned_handle, bounded_exit_wait)
                shell_exited = _wait_process_handle(shell_handle, bounded_exit_wait)
                driver.close()
                if backend_exited and shell_exited and _wait_port_free(min(float(shutdown_budget) + 30.0, timeout + 30.0)):
                    if not any(check.name == "tray_quit" for check in report.checks):
                        report.add("tray_quit", "passed", "actual Windows tray Quit stopped the shell and its identity-matched backend")
                    if forced_shell_cleanup:
                        shell_cleanup_detail = "exact smoke-owned native shell was force-terminated after tray Quit could not be verified"
                    elif tray_quit_unverified:
                        shell_cleanup_detail = "smoke-owned native shell exited, but tray Quit could not be verified"
                    else:
                        shell_cleanup_detail = "smoke-owned native shell exited after verified tray Quit"
                    report.add("native_shell_cleanup", "passed", shell_cleanup_detail)
                    report.add("owned_backend_cleanup", "passed", "identity-matched backend exited and released 127.0.0.1:8000")
                else:
                    report.add("tray_quit", "failed", "tray Quit did not stop the verified shell, backend, and API listener")
                    report.add("native_shell_cleanup", "failed", "smoke-owned native shell remained after tray Quit")
                    report.add("owned_backend_cleanup", "failed", "verified backend remained or fixed API port remained occupied")
            finally:
                _close_handle(owned_handle)
                if shell_handle:
                    _close_handle(shell_handle)
        except (SmokeFailure, OSError, ValueError, subprocess.SubprocessError) as exc:
            if not report.diagnostics:
                _capture_failure_diagnostics(
                    report,
                    stage="desktop_smoke",
                    driver=driver,
                    log_paths=driver_log_paths,
                )
            report.add("desktop_smoke", "failed", str(exc))
        finally:
            if fixture is not None:
                fixture.close()
            if held_api_port is not None:
                held_api_port.close()
            if not any(check.name == "native_shell_cleanup" for check in report.checks):
                if driver_process is None:
                    report.add("native_shell_cleanup", "unverified", "smoke ended before a native shell process was owned")
                else:
                    try:
                        cleanup_shell, _cleanup_pid, _cleanup_hwnd = _native_window(driver_process.pid, application)
                    except SmokeFailure as exc:
                        report.add("native_shell_cleanup", "unverified", f"could not locate the exact smoke-owned native shell during cleanup: {exc}")
                    else:
                        try:
                            tray_cleanup_verified = False
                            try:
                                _invoke_tray_menu_item("Quit", 3.0, expected_pid=_cleanup_pid)
                                tray_cleanup_verified = True
                            except SmokeFailure:
                                pass
                            shell_exited = _wait_process_handle(cleanup_shell, 5.0)
                            forced_shell_cleanup = False
                            if not shell_exited:
                                # This is the exact executable descendant of this
                                # smoke's driver, held by its process handle.
                                _terminate_process_handle(cleanup_shell, "smoke-owned native shell")
                                forced_shell_cleanup = True
                                shell_exited = _wait_process_handle(cleanup_shell, 5.0)
                        except SmokeFailure as exc:
                            report.add("native_shell_cleanup", "failed", str(exc))
                        else:
                            status = "passed" if shell_exited else "failed"
                            if forced_shell_cleanup:
                                detail = "exact smoke-owned native shell was force-terminated during bounded cleanup"
                            elif tray_cleanup_verified:
                                detail = "smoke-owned native shell exited after verified tray Quit during bounded cleanup"
                            else:
                                detail = "smoke-owned native shell exited during bounded cleanup; tray Quit was unverified"
                            if not shell_exited:
                                detail = "smoke-owned native shell remained after bounded cleanup"
                            report.add("native_shell_cleanup", status, detail)
                        finally:
                            _close_handle(cleanup_shell)
            if driver is not None:
                driver.close()
            if driver_process is not None and driver_process.poll() is None:
                driver_process.terminate()
                try:
                    driver_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    driver_process.kill()
                    driver_process.wait(timeout=5)
            if not any(check.name == "owned_backend_cleanup" for check in report.checks):
                try:
                    remaining = _runtime_identity(profile_root, 3.0)
                except SmokeFailure:
                    report.add("owned_backend_cleanup", "unverified", "smoke exited before the exact managed child handle and API port release could be proved")
                else:
                    try:
                        _terminate_verified_backend(
                            int(remaining["pid"]),
                            application,
                            profile_root,
                            remaining["instance_id"],
                        )
                    except (SmokeFailure, OSError, ValueError) as exc:
                        report.add("owned_backend_cleanup", "failed", f"could not stop only the identity-matched child: {exc}")
                    else:
                        if _wait_port_free(10.0):
                            report.add("owned_backend_cleanup", "passed", "exception cleanup terminated the verified child and fixed API port is free")
                        else:
                            report.add("owned_backend_cleanup", "failed", "verified child exited but 127.0.0.1:8000 remained occupied")

    if root is not None and root.exists():
        cleanup_errors = _cleanup_temp_root(root)
        if root.exists():
            detail = "disposable smoke directory remains locked after bounded cleanup"
            if cleanup_errors:
                detail += ": " + "; ".join(cleanup_errors[:3])
            report.add("disposable_profile_cleanup", "unverified", detail)
            report.add_diagnostic("disposable_profile_path", str(root))
        else:
            report.add(
                "disposable_profile_cleanup",
                "passed",
                "disposable smoke directory was removed after a bounded retry",
            )
    else:
        report.add("disposable_profile_cleanup", "passed", "disposable smoke directory was removed")

    _run_desktop_import_smoke(
        application=application, tauri_driver=tauri_driver,
        native_driver=native_driver, timeout=timeout, report=report,
    )

    for name in ("close_to_tray", "single_instance_activation", "tray_show", "tray_quit"):
        if not any(check.name == name for check in report.checks):
            report.add(name, "unverified", "smoke ended before this desktop-service check could run")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True, help="assembled APEX.exe path")
    parser.add_argument("--driver", type=Path, required=True, help="tauri-driver.exe path")
    parser.add_argument("--native-driver", type=Path, required=True, help="matching msedgedriver.exe path")
    parser.add_argument("--report", type=Path, required=True, help="JSON smoke report output path")
    parser.add_argument("--timeout", type=float, default=120.0, help="overall per-stage bound in seconds")
    args = parser.parse_args(argv)
    if not 5.0 <= args.timeout <= 600.0:
        parser.error("--timeout must be between 5 and 600 seconds")

    report = _run_smoke(
        application=args.application.expanduser().resolve(),
        tauri_driver=args.driver.expanduser().resolve(),
        native_driver=args.native_driver.expanduser().resolve(),
        timeout=args.timeout,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report.as_dict(), indent=2))
    essential_unverified = any(
        check.status == "unverified" and check.name in ESSENTIAL_CHECKS
        for check in report.checks
    )
    return 1 if report.result == "failed" or essential_unverified else 0


if __name__ == "__main__":
    raise SystemExit(main())
