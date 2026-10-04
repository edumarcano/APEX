"""Exercise the native Windows device-location preference in an assembled APEX app.

This is a foreground, operator-visible smoke. It uses a disposable APEX profile,
the real Windows location permission signal, and the application's accessible UI.
It never changes Windows privacy settings or manufactures a native permission.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

if __package__:
    from .smoke_desktop_shell import (
        POLL_INTERVAL_SECONDS,
        SmokeFailure,
        WebDriver,
        _api_port_available,
        _available_port,
        _cleanup_temp_root,
        _click_button,
        _close_handle,
        _invoke_tray_menu_item,
        _native_window,
        _runtime_identity,
        _sanitized_environment,
        _terminate_process_handle,
        _terminate_verified_backend,
        _wait_for_ready_element,
        _wait_port_free,
        _wait_process_handle,
    )
else:
    from smoke_desktop_shell import (
        POLL_INTERVAL_SECONDS,
        SmokeFailure,
        WebDriver,
        _api_port_available,
        _available_port,
        _cleanup_temp_root,
        _click_button,
        _close_handle,
        _invoke_tray_menu_item,
        _native_window,
        _runtime_identity,
        _sanitized_environment,
        _terminate_process_handle,
        _terminate_verified_backend,
        _wait_for_ready_element,
        _wait_port_free,
        _wait_process_handle,
    )

API_ORIGIN = "http://127.0.0.1:8000"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PERMISSIONS = {"unknown", "granted", "denied", "revoked", "unsupported"}
AVAILABILITIES = {"unknown", "available", "unavailable", "timed_out", "unsupported"}
LOCATION_TOGGLE = "Use device location for Weather"


class SmokeReport:
    def __init__(self) -> None:
        self.checks: list[dict[str, str]] = []
        self.observations: dict[str, object] = {}

    def add(self, name: str, status: str, detail: str) -> None:
        self.checks.append({"name": name, "status": status, "detail": detail})

    @property
    def result(self) -> str:
        if any(item["status"] == "failed" for item in self.checks):
            return "failed"
        if any(item["status"] == "unverified" for item in self.checks):
            return "unverified"
        return "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "result": self.result,
            "checks": self.checks,
            "observations": self.observations,
        }


def _http_json(method: str, path: str, body: object | None = None, timeout: float = 5.0) -> object:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        API_ORIGIN + path,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure(f"API {method} {path} failed: {type(exc).__name__}") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise SmokeFailure(f"API response exceeded the size limit: {path}")
    try:
        result = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure(f"API {method} {path} returned invalid JSON: {type(exc).__name__}") from None
    if not isinstance(result, dict):
        raise SmokeFailure(f"API {method} {path} did not return an object")
    return result


def _device_status() -> dict[str, object]:
    value = _http_json("GET", "/api/v1/device-context")
    if not isinstance(value, dict):
        raise SmokeFailure("device-context status was not an object")
    permission = value.get("permission")
    availability = value.get("availability")
    if permission not in PERMISSIONS or availability not in AVAILABILITIES:
        raise SmokeFailure("device-context status contained an unsupported state")
    return value


def _wait_device_enabled(expected: bool, timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last = _device_status()
        if last.get("enabled") is expected:
            return last
        time.sleep(POLL_INTERVAL_SECONDS)
    raise SmokeFailure(f"device-context enabled state did not become {str(expected).lower()}")


def _switch_checked(driver: WebDriver, label: str) -> bool:
    result = driver._command(
        "POST",
        "/execute/sync",
        {
            "script": "const e = document.querySelector('[role=\\\"switch\\\"][aria-label=\\\"' + arguments[0] + '\\\"]'); return e ? e.getAttribute('aria-checked') === 'true' : null;",
            "args": [label],
        },
    )
    if not isinstance(result, bool):
        raise SmokeFailure(f"the {label} switch was not available")
    return result


def _click_switch(driver: WebDriver, label: str, timeout: float) -> None:
    locator = f"//*[@role='switch' and @aria-label='{label}']"
    element = _wait_for_ready_element(driver, "xpath", locator, timeout)
    if element is None:
        raise SmokeFailure(f"could not find the {label} switch")
    driver.click(element)


def _open_desktop_settings(driver: WebDriver, timeout: float) -> None:
    if not _click_button(driver, "Open settings", timeout):
        raise SmokeFailure("could not open Settings from the APEX window")
    desktop_tab = _wait_for_ready_element(
        driver, "xpath", "//*[@role='tab' and normalize-space(.)='Desktop']", timeout
    )
    if desktop_tab is None:
        raise SmokeFailure("could not find the Desktop Settings tab")
    driver.click(desktop_tab)
    if not _wait_for_ready_element(
        driver, "xpath", f"//*[@role='switch' and @aria-label='{LOCATION_TOGGLE}']", timeout
    ):
        raise SmokeFailure("the device-location switch did not appear in Desktop Settings")


def _save_settings(driver: WebDriver, timeout: float) -> None:
    if not _click_button(driver, "Save changes", timeout):
        raise SmokeFailure("Save changes was not available")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if "All settings in sync with runtime" in driver.text():
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise SmokeFailure("Settings did not return to the saved state after Save changes")


def _foreground_owned_window(hwnd: int) -> None:
    if os.name != "nt":
        raise SmokeFailure("foreground activation requires Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    if not user32.IsWindow(hwnd):
        raise SmokeFailure("the smoke-owned APEX window no longer exists")
    if not user32.SetForegroundWindow(hwnd):
        raise SmokeFailure("Windows did not foreground the smoke-owned APEX window")


def _focus_owned_window(driver_process: subprocess.Popen[bytes], application: Path) -> None:
    handle, _pid, hwnd = _native_window(driver_process.pid, application)
    try:
        _foreground_owned_window(hwnd)
    finally:
        _close_handle(handle)


def _start_driver(
    application: Path,
    tauri_driver: Path,
    native_driver: Path,
    profile_root: Path,
    timeout: float,
) -> tuple[subprocess.Popen[bytes], WebDriver]:
    env = _sanitized_environment(profile_root, demo=False)
    env["TARGET_LOCATION"] = "London"
    local_profile = Path(env["APEX_DATA_DIR"])
    (local_profile / "config.local.json").write_text(
        json.dumps(
            {
                "features": {
                    "weather": True,
                    "sports": False,
                    "email": False,
                    "calendar": False,
                    "market": False,
                },
                "modules": {"football": False, "f1": False},
                "ask_apex": {"enabled": False},
                "ollama": {"enabled": False},
                "llama_cpp": {"enabled": False},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    control_port = _available_port()
    native_port = _available_port()
    while native_port == control_port:
        native_port = _available_port()
    log_path = profile_root / "tauri-driver.log"
    log_file = log_path.open("wb")
    try:
        process = subprocess.Popen(
            [
                str(tauri_driver), "--port", str(control_port),
                "--native-port", str(native_port), "--native-driver", str(native_driver),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log_file.close()
    driver = WebDriver(control_port, min(20.0, timeout))
    deadline = time.monotonic() + min(30.0, timeout)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SmokeFailure("tauri-driver exited before accepting WebDriver commands")
        try:
            driver.request("GET", "/status")
            driver.start(application)
            return process, driver
        except SmokeFailure:
            time.sleep(POLL_INTERVAL_SECONDS)
    raise SmokeFailure("tauri-driver did not become ready within the startup bound")


def _quit_app(driver: WebDriver, driver_process: subprocess.Popen[bytes], application: Path, timeout: float) -> None:
    _handle, pid, _hwnd = _native_window(driver_process.pid, application)
    try:
        _invoke_tray_menu_item("Quit", min(timeout, 10.0), expected_pid=pid)
    finally:
        _close_handle(_handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            driver.close()
        except SmokeFailure:
            pass
        if _api_port_available():
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise SmokeFailure("APEX did not release its managed API port after tray Quit")


def _contains_private_coordinate_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.casefold() in {"latitude", "longitude", "coordinates", "lat", "lon", "lng"}:
                return True
            if _contains_private_coordinate_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_private_coordinate_key(child) for child in value)
    return False


def _run_smoke(
    *, application: Path, tauri_driver: Path, native_driver: Path,
    timeout: float, expected_permission: str | None,
) -> SmokeReport:
    report = SmokeReport()
    if os.name != "nt":
        report.add("windows_host", "failed", "native device-location smoke requires Windows")
        return report
    for label, path in (("application", application), ("tauri-driver", tauri_driver), ("msedgedriver", native_driver)):
        if not path.is_file():
            report.add("smoke_inputs", "failed", f"{label} executable was not found")
            return report
    report.add("smoke_inputs", "passed", "assembled app and existing WebDriver tools are available")
    if not _api_port_available():
        report.add("api_port_available", "failed", "127.0.0.1:8000 is occupied; existing listener left untouched")
        return report
    report.add("api_port_available", "passed", "127.0.0.1:8000 was free before launch")

    root = Path(tempfile.mkdtemp(prefix="apex-device-location-smoke-"))
    profile = root / "profile"
    driver_process: subprocess.Popen[bytes] | None = None
    driver: WebDriver | None = None
    try:
        driver_process, driver = _start_driver(application, tauri_driver, native_driver, root, timeout)
        identity = _runtime_identity(profile, min(timeout, 45.0))
        report.add("managed_backend_identity", "passed", "API belongs to the managed child using the disposable profile")
        initial = _wait_device_enabled(False, min(timeout, 45.0))
        if initial.get("permission") != "unknown":
            raise SmokeFailure("fresh native device-context permission was not unknown")
        settings_state = _http_json("GET", "/api/v1/settings")
        if settings_state.get("demo_mode_active") is not False or settings_state.get("dev_mode_active") is not False:
            raise SmokeFailure("the smoke profile did not start in normal, non-demo mode")
        report.add("startup_device_context", "passed", "native app started disabled with unknown permission")
        report.observations["startup"] = {
            "enabled": initial.get("enabled"), "permission": initial.get("permission"),
            "availability": initial.get("availability"), "source": initial.get("source"),
        }

        _open_desktop_settings(driver, min(timeout, 45.0))
        _focus_owned_window(driver_process, application)
        _click_switch(driver, LOCATION_TOGGLE, min(timeout, 20.0))
        if not _switch_checked(driver, LOCATION_TOGGLE):
            raise SmokeFailure("the location switch did not enter its enabled draft state")
        still_off = _device_status()
        if still_off.get("enabled") is not False:
            raise SmokeFailure("editing the switch changed runtime state before Save changes")
        if (still_off.get("permission"), still_off.get("availability")) != (
            initial.get("permission"), initial.get("availability")
        ):
            raise SmokeFailure("opening Settings or editing the switch changed native state before Save changes")
        report.add("draft_is_not_active", "passed", "runtime stayed disabled until Save changes")
        _save_settings(driver, min(timeout, 45.0))
        enabled = _wait_device_enabled(True, min(timeout, 30.0))
        if (enabled.get("permission"), enabled.get("availability")) != (
            initial.get("permission"), initial.get("availability")
        ):
            raise SmokeFailure("saving the preference changed native state without the explicit check action")
        report.add("save_does_not_request_permission", "passed", "saved enabled state remained permission-unknown")

        # The only native permission query in the smoke is this focused UI action.
        _focus_owned_window(driver_process, application)
        if not _click_button(driver, "Check location permission", min(timeout, 20.0)):
            raise SmokeFailure("the explicit Check location permission action was unavailable")
        report.add("explicit_permission_action", "passed", "permission check was requested through its visible Settings button")
        deadline = time.monotonic() + min(35.0, timeout)
        observed = enabled
        while time.monotonic() < deadline:
            observed = _device_status()
            if observed.get("permission") != "unknown" or observed.get("availability") != "unknown":
                break
            time.sleep(POLL_INTERVAL_SECONDS)
        permission = observed.get("permission")
        availability = observed.get("availability")
        report.observations["native_permission"] = permission
        report.observations["native_availability"] = availability
        if permission == "unknown" and availability == "unknown":
            report.add("native_permission_observed", "unverified", "Windows permission state remained unknown after the explicit check")
        else:
            report.add("native_permission_observed", "passed", f"Windows reported permission={permission}, availability={availability}")
        if expected_permission is not None and permission != expected_permission:
            report.add("expected_permission", "failed", f"expected {expected_permission}; Windows reported {permission}")
        elif expected_permission is not None:
            report.add("expected_permission", "passed", f"Windows reported the requested {expected_permission} state")
        else:
            report.add("expected_permission", "unverified", "no permission state was requested for this run")

        if permission == "granted":
            try:
                weather = _http_json(
                    "POST", "/api/v1/telemetry/refresh",
                    {"connectors": ["weather"], "force": True}, timeout=min(90.0, timeout),
                )
                if _contains_private_coordinate_key(weather):
                    report.add("weather_response_privacy", "failed", "public Weather response contained a coordinate key")
                else:
                    report.add("weather_response_privacy", "passed", "public Weather response contained no coordinate keys")
                modules = weather.get("modules") if isinstance(weather, dict) else None
                weather_module = modules.get("weather") if isinstance(modules, dict) else None
                weather_state = weather_module.get("status") if isinstance(weather_module, dict) else "unavailable"
                after_weather = _device_status()
                report.observations["weather"] = {
                    "provider_status": weather_state,
                    "location_source": after_weather.get("source"),
                    "location_freshness": after_weather.get("freshness"),
                }
                if after_weather.get("source") == "device" and after_weather.get("freshness") == "fresh":
                    report.add("native_location_acquisition", "passed", "Weather refresh produced a fresh device-derived location")
                else:
                    report.add("native_location_acquisition", "unverified", "Weather refresh completed without a fresh device location; configured fallback may have been used")
                if weather_state != "healthy":
                    report.add("weather_provider", "unverified", f"Weather provider status was {weather_state}; location acquisition is reported separately")
                else:
                    report.add("weather_provider", "passed", "Weather provider returned a healthy result")
            except (SmokeFailure, OSError, ValueError) as exc:
                report.add("weather_refresh", "unverified", f"Weather refresh did not complete: {type(exc).__name__}")
        else:
            report.add("weather_refresh", "unverified", "permission was not granted, so no location-dependent Weather refresh was attempted")

        # Verify disable clears the session fix and reports the configured fallback.
        _focus_owned_window(driver_process, application)
        if _switch_checked(driver, LOCATION_TOGGLE):
            _click_switch(driver, LOCATION_TOGGLE, min(timeout, 20.0))
        _save_settings(driver, min(timeout, 45.0))
        disabled = _wait_device_enabled(False, min(timeout, 30.0))
        if disabled.get("freshness") != "none" or disabled.get("source") != "configured":
            raise SmokeFailure("disabling location did not clear freshness and restore the configured fallback")
        report.add("disable_clears_location", "passed", "saved disable cleared fix freshness and selected the configured fallback")

        # Restart with the same disposable profile after saving opt-in again.
        _click_switch(driver, LOCATION_TOGGLE, min(timeout, 20.0))
        _save_settings(driver, min(timeout, 45.0))
        _wait_device_enabled(True, min(timeout, 30.0))
        _quit_app(driver, driver_process, application, min(timeout, 20.0))
        driver.close()
        driver_process.terminate()
        try:
            driver_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            driver_process.kill()
            driver_process.wait(timeout=5)
        driver_process, driver = _start_driver(application, tauri_driver, native_driver, root, timeout)
        restarted = _wait_device_enabled(True, min(timeout, 45.0))
        if restarted.get("permission") != "unknown":
            raise SmokeFailure("restarted app did not remain permission-unknown until a new user action")
        report.add("restart_requires_user_action", "passed", "saved opt-in persisted while permission returned to unknown")

        _open_desktop_settings(driver, min(timeout, 45.0))
        _focus_owned_window(driver_process, application)
        if _switch_checked(driver, LOCATION_TOGGLE):
            _click_switch(driver, LOCATION_TOGGLE, min(timeout, 20.0))
        _save_settings(driver, min(timeout, 45.0))
        final_status = _wait_device_enabled(False, min(timeout, 30.0))
        if final_status.get("freshness") != "none" or final_status.get("source") != "configured":
            raise SmokeFailure("final saved disable did not clear location freshness")
        report.add("final_disable", "passed", "location ended disabled with configured fallback and no fresh fix")
        _quit_app(driver, driver_process, application, min(timeout, 20.0))
    except (SmokeFailure, OSError, ValueError, subprocess.SubprocessError) as exc:
        report.add("device_location_smoke", "failed", str(exc))
    finally:
        if driver is not None:
            try:
                driver.close()
            except SmokeFailure:
                pass
        if driver_process is not None and driver_process.poll() is None:
            try:
                shell_handle, shell_pid, _shell_hwnd = _native_window(driver_process.pid, application)
            except SmokeFailure:
                shell_handle = None
                shell_pid = None
            if shell_handle is not None:
                try:
                    try:
                        _invoke_tray_menu_item("Quit", 5.0, expected_pid=shell_pid or 0)
                    except SmokeFailure:
                        _terminate_process_handle(shell_handle, "smoke-owned native shell")
                    _wait_process_handle(shell_handle, 5.0)
                finally:
                    _close_handle(shell_handle)
            driver_process.terminate()
            try:
                driver_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                driver_process.kill()
                driver_process.wait(timeout=5)
        try:
            identity = _runtime_identity(profile, 3.0)
        except SmokeFailure:
            pass
        else:
            try:
                _terminate_verified_backend(int(identity["pid"]), application, profile, identity["instance_id"])
            except (SmokeFailure, OSError, ValueError) as exc:
                report.add("owned_backend_cleanup", "failed", f"could not clean up the identity-matched backend: {type(exc).__name__}")
            else:
                if not _wait_port_free(10.0):
                    report.add("owned_backend_cleanup", "failed", "verified backend exited but port 8000 remained occupied")
        _cleanup_temp_root(root)
        if root.exists():
            report.add("disposable_profile_cleanup", "unverified", "disposable profile remains locked after bounded cleanup")
        else:
            report.add("disposable_profile_cleanup", "passed", "disposable profile was removed")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, required=True, help="absolute assembled APEX.exe path")
    parser.add_argument("--driver", type=Path, required=True, help="absolute tauri-driver.exe path")
    parser.add_argument("--native-driver", type=Path, required=True, help="absolute msedgedriver.exe path")
    parser.add_argument("--report", type=Path, required=True, help="JSON report output path")
    parser.add_argument("--timeout", type=float, default=120.0, help="bounded per-stage timeout in seconds (5..600)")
    parser.add_argument("--expected-permission", choices=sorted(PERMISSIONS), help="assert an observed Windows permission state")
    args = parser.parse_args(argv)
    for name, value in (("application", args.application), ("driver", args.driver), ("native-driver", args.native_driver)):
        if not value.is_absolute():
            parser.error(f"--{name} must be an absolute path")
    if not 5.0 <= args.timeout <= 600.0:
        parser.error("--timeout must be between 5 and 600 seconds")
    report = _run_smoke(
        application=args.application.resolve(), tauri_driver=args.driver.resolve(),
        native_driver=args.native_driver.resolve(), timeout=args.timeout,
        expected_permission=args.expected_permission,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report.as_dict(), indent=2))
    return 1 if report.result == "failed" else 2 if report.result == "unverified" else 0


if __name__ == "__main__":
    raise SystemExit(main())
