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

    def add(self, name: str, status: str, detail: str | None = None) -> None:
        self.checks.append(Check(name, status, detail))

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
        }


class SmokeFailure(RuntimeError):
    pass


class LlamaCppStreamFixture:
    """Loopback OpenAI-compatible stream used to hold a real run at a boundary."""

    def __init__(self) -> None:
        self.first_delta_sent = threading.Event()
        self.release_cancelled_stream = threading.Event()
        self.request_count = 0
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
                self.rfile.read(length)
                with fixture._lock:
                    request_number = fixture.request_count
                    fixture.request_count += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    if request_number == 0:
                        self._chunk("The native WebView received the first streamed segment.")
                        # requests.iter_lines buffers 512 bytes by default. Pad
                        # the first transport read so this delta is observable
                        # before the fixture waits for the UI cancellation.
                        self._write_chunk(b":" + b" " * 600 + b"\n\n")
                        fixture.first_delta_sent.set()
                        if not fixture.release_cancelled_stream.wait(timeout=90):
                            self._write_chunk(b"0\r\n\r\n")
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
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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
            if isinstance(value, dict) and value.get("error"):
                raise SmokeFailure(f"WebDriver command failed: {value.get('message', value['error'])}")
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
        except SmokeFailure as exc:
            if "no such element" in str(exc).lower():
                return None
            raise
        if not isinstance(result, dict):
            return None
        element_id = result.get(ELEMENT_KEY)
        return element_id if isinstance(element_id, str) else None

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
    try:
        with opener.open(request, timeout=timeout) as response:
            for raw_line in response:
                if raw_line.startswith(b"event:") and raw_line[6:].decode("utf-8", "replace").strip() == expected:
                    return True
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
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
        False,
        pid,
    )
    if not handle:
        raise SmokeFailure(f"could not open the verified backend child process {pid}")
    capacity = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(capacity.value)
    if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise SmokeFailure(f"could not verify backend child image path (Windows error {error})")
    return handle, Path(buffer.value)


def _terminate_verified_backend(pid: int, application_root: Path, profile: Path, instance_id: object) -> None:
    handle, image = _process_image_path(pid)
    try:
        try:
            image.resolve().relative_to(application_root.resolve())
        except ValueError:
            raise SmokeFailure("runtime identity PID image is outside the assembled application directory") from None
        current = _runtime_identity(profile, 5.0)
        if current.get("pid") != pid or current.get("instance_id") != instance_id:
            raise SmokeFailure("managed runtime identity changed before termination; refusing to target a reused PID")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        if not kernel32.TerminateProcess(handle, 0xD35C):
            error = ctypes.get_last_error()
            raise SmokeFailure(f"could not terminate verified backend child (Windows error {error})")
        if kernel32.WaitForSingleObject(handle, 10_000) != WAIT_OBJECT_0:
            raise SmokeFailure("verified backend child did not exit after termination")
    finally:
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


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


def _wait_process_handle(handle: int, timeout: float) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == WAIT_OBJECT_0


def _click_button(driver: WebDriver, label: str, timeout: float) -> bool:
    element = driver.find("xpath", _button_xpath(label))
    if element is None:
        if not driver.wait_for("button", lambda: driver.find("xpath", _button_xpath(label)) is not None, timeout):
            return False
        element = driver.find("xpath", _button_xpath(label))
    if element is None:
        return False
    driver.click(element)
    return True


def _retry_backend(driver: WebDriver, timeout: float) -> bool:
    return _click_button(driver, "Retry backend", timeout) and _click_button(driver, "Restart backend", timeout)


def _wait_text(driver: WebDriver, text: str, timeout: float) -> bool:
    return driver.wait_for("visible text", lambda: text in driver.text(), timeout)


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

    app_root = application.parent.resolve()
    profile_root: Path | None = None
    driver_process: subprocess.Popen[bytes] | None = None
    driver: WebDriver | None = None
    fixture: LlamaCppStreamFixture | None = None
    held_api_port: socket.socket | None = None
    with tempfile.TemporaryDirectory(prefix="apex-desktop-smoke-") as temp_name:
        root = Path(temp_name)
        profile_root = root / "profile"
        env = _sanitized_environment(root)
        control_port = _available_port()
        native_port = _available_port()
        while native_port == control_port:
            native_port = _available_port()
        log_path = root / "tauri-driver.log"
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
                report.add("startup_conflict", "failed", "native shell did not show an actionable 127.0.0.1:8000 conflict with Retry backend")
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

            if _click_button(driver, "Briefing", min(8.0, timeout)) and _click_button(driver, "Set up briefing", min(8.0, timeout)):
                if not _wait_text(driver, "Set up your briefing", min(8.0, timeout)):
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
                if first_image.resolve().parent != app_root.resolve():
                    raise SmokeFailure("demo backend PID image is outside the assembled application directory")
                confirmed = _runtime_identity(profile_root, 5.0)
                if confirmed.get("pid") != first_runtime.get("pid") or confirmed.get("instance_id") != first_runtime.get("instance_id"):
                    raise SmokeFailure("demo runtime identity changed before closing its native session")
                driver.close()
                if driver_process.poll() is None:
                    driver_process.terminate()
                    driver_process.wait(timeout=5)
                exited = _wait_process_handle(first_handle, float(first_runtime["shutdown_timeout_seconds"]) + 30.0)
            finally:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(first_handle)
            if not exited or not _wait_port_free(min(30.0, timeout)):
                raise SmokeFailure("verified demo backend did not exit and release 127.0.0.1:8000")
            stream_root = root / "stream-session"
            stream_env = _sanitized_environment(stream_root, demo=False, local_model_host=fixture.url)
            control_port = _available_port()
            native_port = _available_port()
            while native_port == control_port:
                native_port = _available_port()
            with (root / "tauri-driver-stream.log").open("wb") as log_file:
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
                prompt = driver.find("css selector", "textarea[placeholder^='Ask ']")
                if prompt is None:
                    report.add("cortex_stream", "failed", "Cortex composer input was unavailable")
                else:
                    driver.type_text(prompt, "Return a short answer to exercise a streamed response.")
                    if not _click_button(driver, "Send", min(8.0, timeout)):
                        report.add("cortex_stream", "failed", "Cortex Send control was unavailable")
                    elif not driver.wait_for(
                        "fixture first delta in WebView",
                        lambda: fixture.first_delta_sent.is_set() and "first streamed segment" in driver.text().lower(),
                        min(45.0, timeout),
                    ):
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
                _terminate_verified_backend(old_pid, app_root, profile_root, before_crash["instance_id"])
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

            # Closing the WebDriver session closes the app window. Keep a Windows
            # process handle to the identity-matched child so PID reuse cannot
            # turn an HTTP failure into false evidence of shutdown.
            final_runtime = _runtime_identity(profile_root, min(10.0, timeout))
            shutdown_budget = final_runtime.get("shutdown_timeout_seconds")
            if not isinstance(shutdown_budget, (int, float)) or shutdown_budget < 0:
                raise SmokeFailure("runtime identity omitted its bounded shutdown timeout")
            owned_handle, owned_image = _process_image_path(int(final_runtime["pid"]))
            try:
                if owned_image.resolve().parent != app_root.resolve():
                    raise SmokeFailure("final backend PID image is outside the assembled application directory")
                confirmed = _runtime_identity(profile_root, 5.0)
                if confirmed.get("pid") != final_runtime.get("pid") or confirmed.get("instance_id") != final_runtime.get("instance_id"):
                    raise SmokeFailure("runtime identity changed while opening the process handle; refusing to claim graceful shutdown")
                driver.close()
                exited = _wait_process_handle(owned_handle, float(shutdown_budget) + 30.0)
            finally:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(owned_handle)
            if exited and _wait_port_free(min(float(shutdown_budget) + 30.0, timeout + 30.0)):
                report.add("graceful_quit", "passed", "verified managed backend process exited and released 127.0.0.1:8000")
                report.add("owned_backend_cleanup", "passed", "the exact identity-matched child handle signaled exit and fixed API port is free")
            else:
                report.add("graceful_quit", "failed", "verified backend process or fixed API port remained after native window close")
                report.add("owned_backend_cleanup", "failed", "the exact identity-matched child did not exit or fixed API port remained occupied")
        except (SmokeFailure, OSError, ValueError, subprocess.SubprocessError) as exc:
            report.add("desktop_smoke", "failed", str(exc))
        finally:
            if fixture is not None:
                fixture.close()
            if held_api_port is not None:
                held_api_port.close()
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
                            app_root,
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
