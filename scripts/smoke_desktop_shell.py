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
    "graceful_quit",
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


def _request_native_window_close(driver_pid: int, application: Path) -> int:
    """Post WM_CLOSE only to this run's exact native executable descendant."""
    if os.name != "nt":
        raise SmokeFailure("native window close is supported on Windows only")
    expected_image = application.resolve()
    matches: list[tuple[int, int]] = []
    for pid in _descendant_process_ids(driver_pid):
        try:
            handle, image = _process_image_path(pid)
        except SmokeFailure:
            continue
        if image.resolve() != expected_image:
            _close_handle(handle)
            continue
        hwnds: list[int] = []
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL

        @enum_proc
        def collect(hwnd: int, _lparam: int) -> bool:
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid and user32.IsWindowVisible(hwnd):
                hwnds.append(int(hwnd))
            return True

        user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumWindows(collect, 0)
        if hwnds:
            matches.append((handle, hwnds[0]))
        else:
            _close_handle(handle)
    if len(matches) != 1:
        for handle, _hwnd in matches:
            _close_handle(handle)
        raise SmokeFailure(f"expected one visible smoke-owned APEX window, found {len(matches)}")
    shell_handle, hwnd = matches[0]
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    if not user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
        error = ctypes.get_last_error()
        _close_handle(shell_handle)
        raise SmokeFailure(f"could not post WM_CLOSE to the smoke-owned native window (Windows error {error})")
    return shell_handle


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


def _retry_backend(driver: WebDriver, timeout: float) -> bool:
    return _click_button(driver, "Retry backend", timeout) and _click_button(driver, "Restart backend", timeout)


def _wait_text(driver: WebDriver, text: str, timeout: float) -> bool:
    return driver.wait_for("visible text", lambda: text in driver.text(), timeout)


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
                shell_handle = _request_native_window_close(driver_process.pid, application)
                try:
                    backend_exited = _wait_process_handle(first_handle, float(close_budget) + 30.0)
                    shell_exited = _wait_process_handle(shell_handle, float(close_budget) + 30.0)
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
                                # The provider checks cancellation between SSE
                                # chunks; releasing this gate after the real UI
                                # action lets the production reader observe it.
                                fixture.release_cancelled_stream.set()
                                def cancelled() -> bool:
                                    value = _http_json(f"/api/v1/cortex/runs/{run_id}")
                                    return isinstance(value, dict) and value.get("status") == "cancelled"

                                if driver.wait_for("persisted cancelled Cortex run", cancelled, min(30.0, timeout)):
                                    terminal_events = _http_sse_event_types(run_id, timeout=min(15.0, timeout))
                                    if "run.completed" in terminal_events:
                                        report.add("cortex_cancel", "passed", "WebView Stop cancelled the held provider run and replay includes terminal activity")
                                    else:
                                        report.add("cortex_cancel", "failed", "run was persisted cancelled but terminal event was absent from replay")
                                else:
                                    report.add("cortex_cancel", "failed", "Stop generation did not persist cancellation before the bound expired")
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

            # Send WM_CLOSE to the exact app descendant while the WebDriver
            # session is still alive. Tauri's real CloseRequested handler must
            # stop the backend before exiting; DELETE /session is cleanup only.
            final_runtime = _runtime_identity(profile_root, min(10.0, timeout))
            shutdown_budget = final_runtime.get("shutdown_timeout_seconds")
            if not isinstance(shutdown_budget, (int, float)) or shutdown_budget < 0:
                raise SmokeFailure("runtime identity omitted its bounded shutdown timeout")
            owned_handle, owned_image = _process_image_path(int(final_runtime["pid"]))
            try:
                if owned_image.resolve() != _expected_backend_image(application):
                    raise SmokeFailure("final backend PID is not the bundled backend executable")
                confirmed = _runtime_identity(profile_root, 5.0)
                if confirmed.get("pid") != final_runtime.get("pid") or confirmed.get("instance_id") != final_runtime.get("instance_id"):
                    raise SmokeFailure("runtime identity changed while opening the process handle; refusing to claim graceful shutdown")
                shell_handle = _request_native_window_close(driver_process.pid, application)
                try:
                    backend_exited = _wait_process_handle(owned_handle, float(shutdown_budget) + 30.0)
                    shell_exited = _wait_process_handle(shell_handle, float(shutdown_budget) + 30.0)
                finally:
                    _close_handle(shell_handle)
                driver.close()
                exited = backend_exited and shell_exited
            finally:
                _close_handle(owned_handle)
            if exited and _wait_port_free(min(float(shutdown_budget) + 30.0, timeout + 30.0)):
                report.add("graceful_quit", "passed", "verified managed backend process exited and released 127.0.0.1:8000")
                report.add("native_shell_cleanup", "passed", "the smoke-owned native window exited through its CloseRequested handler")
                report.add("owned_backend_cleanup", "passed", "the exact identity-matched child handle signaled exit and fixed API port is free")
            else:
                report.add("graceful_quit", "failed", "verified backend process or fixed API port remained after native window close")
                report.add("native_shell_cleanup", "failed", "the smoke-owned native shell did not exit after its window close request")
                report.add("owned_backend_cleanup", "failed", "the exact identity-matched child did not exit or fixed API port remained occupied")
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
                        cleanup_shell = _request_native_window_close(driver_process.pid, application)
                    except SmokeFailure as exc:
                        report.add("native_shell_cleanup", "unverified", f"could not locate the exact smoke-owned native shell during cleanup: {exc}")
                    else:
                        try:
                            shell_exited = _wait_process_handle(cleanup_shell, 5.0)
                            if not shell_exited:
                                _terminate_process_handle(cleanup_shell, "smoke-owned native shell")
                                shell_exited = _wait_process_handle(cleanup_shell, 5.0)
                        except SmokeFailure as exc:
                            report.add("native_shell_cleanup", "failed", str(exc))
                        else:
                            status = "passed" if shell_exited else "failed"
                            detail = "smoke-owned native shell exited during bounded cleanup"
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
