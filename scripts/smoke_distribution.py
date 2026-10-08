"""Exercise the per-user Windows installer in an explicitly disposable profile.

This controller is included only in the build-only frozen smoke probe. It must
never be added to the production backend bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
try:
    import winreg
except ImportError:  # Keep report/unit-test imports available on non-Windows hosts.
    winreg = None  # type: ignore[assignment]
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

APP_ID = "com.edumarcano.apex"
APP_NAME = "APEX"
DEFAULT_VERSION = "2.1.0"
PREVIOUS_FIXTURE_BASE = "31fdd21757a1822ac0223956c20595ff5a13d307"
INSTALL_SUBDIR = Path("Programs") / APP_NAME
DATA_SUBDIR = Path(APP_NAME)
PROFILE_MARKER = ".apex-distribution-smoke-profile"
INSTALL_TIMEOUT = 300
PROCESS_TIMEOUT = 30
_owned_host: tuple[subprocess.Popen[bytes], Any, Any, str] | None = None
_owned_process_identity: tuple[int, str, str] | None = None
_owned_install: Path | None = None


@dataclass
class Check:
    name: str
    status: str
    detail: str | None = None


class Report:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, name: str, status: str, detail: str | None = None) -> None:
        self.checks.append(Check(name, status, detail))

    def as_dict(self, *, mode: str) -> dict[str, object]:
        statuses = {item.status for item in self.checks}
        return {
            "schema_version": 1,
            "mode": mode,
            "result": "failed" if "failed" in statuses else (
                "unverified" if "unverified" in statuses else "passed"
            ),
            "checks": [item.__dict__ for item in self.checks],
        }


class DistributionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: Sequence[str], *, cwd: Path, timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise DistributionError(f"{Path(command[0]).name} exceeded its {timeout}s bound") from exc


def _windows_only() -> None:
    if os.name != "nt":
        raise DistributionError("installed distribution smoke runs only on Windows")


def _profile_root() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise DistributionError("LOCALAPPDATA is not available")
    return Path(value).resolve()


def _guard_disposable_profile(profile: Path) -> None:
    # Canonicalize both sides before enforcing containment. Windows CI may
    # expose temp directories through junction aliases, so a raw profile path
    # can appear outside USERPROFILE even when both resolve inside it.
    profile = profile.resolve()
    if os.environ.get("APEX_DISTRIBUTION_SMOKE_PROFILE") != "1":
        raise DistributionError(
            "refusing installer execution without APEX_DISTRIBUTION_SMOKE_PROFILE=1 in a disposable Windows account"
        )
    marker = profile / PROFILE_MARKER
    if not marker.is_file() or marker.is_symlink():
        raise DistributionError(f"disposable profile marker is missing: {PROFILE_MARKER}")
    marker_value = marker.read_text(encoding="utf-8").strip()
    marker_match = re.fullmatch(r"APEX-DISTRIBUTION-SMOKE:([A-Za-z0-9._-]{8,80}):([A-Z0-9-]{8,80})", marker_value)
    if not marker_match:
        raise DistributionError("disposable profile marker has an invalid value")
    current_sid = _current_sid()
    operator_sid = os.environ.get("APEX_DISTRIBUTION_SMOKE_OPERATOR_SID", "").strip().upper()
    if not operator_sid:
        raise DistributionError("refusing installer execution without the protected operator SID")
    hosted_ci = (
        os.environ.get("GITHUB_ACTIONS", "").casefold() == "true"
        and os.environ.get("RUNNER_ENVIRONMENT", "").casefold() == "github-hosted"
        and operator_sid == "S-1-0-0"
    )
    if current_sid.upper() == operator_sid and not hosted_ci:
        raise DistributionError("refusing to run an installer in the operator's Windows account")
    if marker_match.group(2) != current_sid.upper():
        raise DistributionError("disposable profile marker is not bound to the current Windows account")
    user_profile = Path(os.environ.get("USERPROFILE", "")).resolve()
    if not user_profile.is_absolute() or not profile.is_relative_to(user_profile):
        raise DistributionError("LOCALAPPDATA is outside the current Windows user profile")
    profile_record = _run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
        "$p=Get-CimInstance Win32_UserProfile | Where-Object SID -eq $sid; "
        "if($p){[pscustomobject]@{SID=$p.SID;LocalPath=$p.LocalPath;Special=$p.Special} | ConvertTo-Json -Compress}",
    ], cwd=user_profile, timeout=20)
    if profile_record.returncode != 0:
        raise DistributionError("could not verify the Windows user profile registration")
    try:
        identity = json.loads(profile_record.stdout)
    except json.JSONDecodeError as exc:
        raise DistributionError("could not verify the Windows user profile registration") from exc
    if (
        not isinstance(identity, dict)
        or identity.get("SID", "").upper() != current_sid.upper()
        or Path(str(identity.get("LocalPath", ""))).resolve() != user_profile
        or identity.get("Special") is not False
    ):
        raise DistributionError("current Windows profile is not a verified ordinary disposable account profile")


def _current_sid() -> str:
    result = _run([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
    ], cwd=Path.cwd(), timeout=20)
    value = (result.stdout or "").strip()
    if result.returncode != 0 or not re.fullmatch(r"S-1-[0-9-]+", value, re.IGNORECASE):
        raise DistributionError("could not verify the current Windows account SID")
    return value


def _registry_uninstall() -> dict[str, Any] | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall") as root:
            names = [winreg.EnumKey(root, index) for index in range(winreg.QueryInfoKey(root)[0])]
    except FileNotFoundError:
        return None
    for key_name in names:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{key_name}") as key:
                result: dict[str, Any] = {}
                for name in ("DisplayName", "DisplayVersion", "InstallLocation", "UninstallString", "QuietUninstallString", "Publisher", "DisplayIcon"):
                    try:
                        result[name] = winreg.QueryValueEx(key, name)[0]
                    except FileNotFoundError:
                        result[name] = None
                if result.get("DisplayName") == APP_NAME:
                    return result
        except OSError:
            continue
    return None


def _registered_install_location(registration: dict[str, Any]) -> Path:
    """Parse only a whole, quoted or unquoted InstallLocation filesystem path."""
    raw = registration.get("InstallLocation")
    if not isinstance(raw, str) or not raw.strip():
        raise DistributionError("uninstall registration has no valid install location")
    value = raw.strip()
    if value.startswith('"') or value.endswith('"'):
        if len(value) < 2 or value[0] != '"' or value[-1] != '"':
            raise DistributionError("uninstall registration has malformed install-location quoting")
        value = value[1:-1]
        if not value or '"' in value:
            raise DistributionError("uninstall registration has malformed install-location quoting")
    elif '"' in value:
        raise DistributionError("uninstall registration has malformed install-location quoting")
    if not value or value != value.strip():
        raise DistributionError("uninstall registration has an invalid install location")
    location = Path(value)
    if not location.is_absolute():
        raise DistributionError("uninstall registration has a non-absolute install location")
    return location.resolve()


def _has_start_menu_entry() -> bool:
    menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return bool(list(menu.glob("APEX*.lnk")) or list((menu / APP_NAME).glob("*.lnk")))


def _run_entry() -> str | None:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            try:
                value, _kind = winreg.QueryValueEx(key, APP_NAME)
                return str(value)
            except FileNotFoundError:
                return None
    except FileNotFoundError:
        return None


def _port_8000_available() -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", 8000))
        except OSError:
            return False
    return True


def _process_inventory() -> dict[tuple[int, str], str]:
    """Return (PID, normalized image path) -> process creation timestamp."""
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "$ErrorActionPreference='Stop'; Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ExecutablePath,CreationDate | ConvertTo-Json -Compress",
    ]
    result = _run(command, cwd=Path.cwd(), timeout=PROCESS_TIMEOUT)
    if result.returncode != 0:
        raise DistributionError("could not inspect Windows process ownership")
    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise DistributionError("Windows process inventory returned invalid JSON") from exc
    records = raw if isinstance(raw, list) else [raw]
    inventory: dict[tuple[int, str], str] = {}
    for row in records:
        if not isinstance(row, dict) or not row.get("ExecutablePath"):
            continue
        try:
            pid = int(row["ProcessId"])
        except (TypeError, ValueError):
            continue
        normalized = os.path.normcase(os.path.abspath(str(row["ExecutablePath"])))
        inventory[(pid, normalized)] = str(row.get("CreationDate") or "")
    return inventory


def _assert_owned_processes_unchanged(before: dict[tuple[int, str], str], after: dict[tuple[int, str], str], install_root: Path) -> None:
    root = os.path.normcase(os.path.abspath(str(install_root)))
    retained = {
        identity: created for identity, created in before.items()
        if identity[1] == root or identity[1].startswith(root + os.sep)
    }
    missing = [identity for identity, created in retained.items() if after.get(identity) != created]
    if missing:
        raise DistributionError("installer terminated or replaced a process running from the installed tree")


def _processes_under_install(inventory: dict[tuple[int, str], str], install_root: Path) -> list[tuple[int, str, str]]:
    root = os.path.normcase(os.path.abspath(str(install_root)))
    return [
        (pid, image, created)
        for (pid, image), created in inventory.items()
        if image == root or image.startswith(root + os.sep)
    ]


def _installer(executable: Path, arguments: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = _run([str(executable), *arguments], cwd=cwd, timeout=INSTALL_TIMEOUT)
    if result.returncode != 0:
        raise DistributionError(f"{executable.name} exited with code {result.returncode}")
    return result


def _wait_for_uninstall_completion(install: Path, *, timeout: float = INSTALL_TIMEOUT) -> None:
    """Wait for NSIS self-deletion to remove both its registration and install tree."""
    deadline = time.monotonic() + timeout
    while True:
        registration = _registry_uninstall()
        if registration is None and not install.exists():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DistributionError("uninstaller did not remove its registration and installed program tree")
        time.sleep(min(0.1, remaining))


def _installed_paths(profile: Path) -> tuple[Path, Path, Path, Path]:
    install = profile / INSTALL_SUBDIR
    data = profile / DATA_SUBDIR
    return install, data, install / "apex-desktop.exe", install / "backend-bundle"


def _locate_installed_executables(install: Path) -> tuple[Path, Path, Path]:
    desktop = install / "apex-desktop.exe"
    backend = install / "backend-bundle" / "apex-backend.exe"
    cli = install / "backend-bundle" / "apex.exe"
    for path in (desktop, backend, cli):
        if not path.is_file():
            raise DistributionError(f"installed executable is missing: {path.relative_to(install)}")
    return desktop, backend, cli


def _bundle_build_info(bundle: Path) -> dict[str, Any]:
    path = bundle / "_internal" / "build-info.json"
    if not path.is_file():
        raise DistributionError("installed backend build metadata is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionError("installed backend build metadata is invalid") from exc
    if not isinstance(value, dict):
        raise DistributionError("installed backend build metadata is not an object")
    return value


def _bundle_app_version(build_info: dict[str, Any]) -> Any:
    version_key = "app_version" if "app_version" in build_info else "application_version"
    return build_info.get(version_key)


def _validate_previous_build(manifest: dict[str, Any], build_info: dict[str, Any], expected_version: str) -> None:
    if (
        _bundle_app_version(build_info) != expected_version
        or build_info.get("commit") != manifest.get("fixture_commit")
        or build_info.get("build_id") != manifest.get("backend_build_id")
    ):
        raise DistributionError("synthetic previous payload does not match its fixture commit, version, and bundle build ID")


def _data_root_fingerprint(path: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()


def _validate_runtime_identity(
    identity: dict[str, Any], *, app_version: str, build_info: dict[str, Any],
    data_root: Path, pid: int, launch_id: str,
) -> None:
    if (
        identity.get("app_id") != "apex"
        or identity.get("app_version") != app_version
        or identity.get("build_id") != build_info.get("build_id")
        or identity.get("pid") != pid
        or identity.get("launch_id") != launch_id
        or identity.get("hosting_mode") != "managed"
        or identity.get("data_root_fingerprint") != _data_root_fingerprint(data_root)
    ):
        raise DistributionError("installed backend runtime identity differs from its expected version, bundle, process, or data root")


def _has_embedded_manifest(executable: Path) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.LoadLibraryExW.restype = ctypes.c_void_p
    handle = kernel32.LoadLibraryExW(str(executable), None, 0x00000002)
    if not handle:
        return False
    try:
        kernel32.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        kernel32.FindResourceW.restype = ctypes.c_void_p
        return bool(kernel32.FindResourceW(handle, ctypes.c_void_p(1), ctypes.c_void_p(24)))
    finally:
        kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
        kernel32.FreeLibrary.restype = ctypes.c_int
        kernel32.FreeLibrary(ctypes.c_void_p(handle))


def _shortcut_app_id(shortcut: Path, *, cwd: Path) -> str:
    # A PowerShell single-quoted literal is safe when embedded in this trusted
    # script after doubling every quote from the path. This avoids relying on
    # `-Command` positional argument binding, which does not bind trailing
    # tokens to `$args` as callers often expect.
    literal_path = str(shortcut.resolve()).replace("'", "''")
    script = (
        f"$shortcutPath = '{literal_path}'; "
        "$shell=New-Object -ComObject Shell.Application; "
        "$item=$shell.Namespace([System.IO.Path]::GetDirectoryName($shortcutPath))."
        "ParseName([System.IO.Path]::GetFileName($shortcutPath)); "
        "if($null -eq $item){throw 'Shortcut metadata item unavailable'}; "
        "$id=$item.ExtendedProperty('System.AppUserModel.ID'); "
        "if($null -ne $id){[Console]::Write([string]$id)}"
    )
    result = _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=cwd,
        timeout=20,
    )
    if result.returncode != 0:
        raise DistributionError("could not read the Start Menu shortcut AppUserModelID property")
    return result.stdout.strip()


def _validate_registration(
    profile: Path, install: Path, expected_version: str, *, expected_startup: bool = False,
) -> None:
    registration = _registry_uninstall()
    if not registration:
        raise DistributionError("APEX uninstall registration is missing")
    if registration.get("DisplayName") != APP_NAME:
        raise DistributionError("uninstall registration has an unexpected display name")
    if registration.get("DisplayVersion") != expected_version:
        raise DistributionError("uninstall registration does not match the expected version")
    try:
        location = _registered_install_location(registration)
    except DistributionError as exc:
        raise DistributionError("uninstall registration has an invalid install location") from exc
    if location != install.resolve():
        raise DistributionError("uninstall registration points outside the expected per-user install root")
    run_value, approval = _run_value_and_approval()
    if expected_startup:
        expected_command = f'"{(install / "apex-desktop.exe").resolve()}" --autostart'
        if run_value != expected_command or (approval is not None and (len(approval) != 12 or approval[0] not in {2, 6})):
            raise DistributionError("enabled APEX startup preference is not effective in Windows sign-in state")
    elif run_value is not None or approval is not None:
        raise DistributionError("unexpected APEX startup Run registration exists")
    menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    links = list(menu.glob("APEX*.lnk")) + list((menu / APP_NAME).glob("*.lnk"))
    if not links:
        raise DistributionError("APEX Start Menu shortcut is missing")
    # The NSIS shortcut is expected to carry the same AppUserModelID used by
    # the executable manifest so Windows groups installed notifications.
    shortcut_id = _shortcut_app_id(links[0], cwd=profile)
    if shortcut_id != APP_ID:
        raise DistributionError("Start Menu shortcut does not expose the expected APEX AppUserModelID")
    # LoadLibraryEx/FindResource avoids depending on SDK tools on clean hosts.
    if not _has_embedded_manifest(install / "apex-desktop.exe"):
        raise DistributionError("installed executable has no inspectable embedded Windows application manifest")


def _verify_fixture(probe: Path, operation: str, profile: Path, cwd: Path) -> dict[str, Any]:
    result = _run([str(probe), "import-fixture", operation, str(profile)], cwd=cwd, timeout=90)
    if result.returncode != 0:
        raise DistributionError(f"frozen production-data rehearsal {operation} failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DistributionError("frozen production-data rehearsal returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise DistributionError("frozen production-data rehearsal returned an invalid result")
    return value


def _installed_host(backend: Path, data: Path, cwd: Path, expected_version: str) -> tuple[subprocess.Popen[bytes], Any, Any, str]:
    # Importing this existing controller reuses the production host protocol,
    # bounded output readers and graceful shutdown sequence.
    from scripts.smoke_backend_bundle import _next_startup_envelope, _sanitized_environment, _spawn_host

    env = _sanitized_environment(cwd, data, initialize_local_config=False)
    env["LOCALAPPDATA"] = str(data.parent)
    env["APPDATA"] = os.environ.get("APPDATA", str(data.parent / "Roaming"))
    process, frames, _stdout, stderr, launch_id = _spawn_host(
        backend, data, cwd, environment=env,
    )
    global _owned_host, _owned_process_identity
    _owned_host = (process, frames, stderr, launch_id)
    deadline = time.monotonic() + 5
    inventory: dict[tuple[int, str], str] = {}
    identity: tuple[int, str] | None = None
    while time.monotonic() < deadline and process.poll() is None:
        inventory = _process_inventory()
        identity = next((key for key in inventory if key[0] == process.pid), None)
        if identity is not None:
            break
        time.sleep(0.1)
    if identity is None or os.path.normcase(str(backend.resolve())) != identity[1]:
        raise DistributionError("could not bind the installed backend process to its exact image path")
    _owned_process_identity = (identity[0], identity[1], inventory[identity])
    starting = _next_startup_envelope(frames, process, stderr, stage="installed backend starting")
    ready = _next_startup_envelope(frames, process, stderr, stage="installed backend ready")
    if starting.get("type") != "starting" or ready.get("type") != "ready" or ready.get("request_id") != launch_id:
        raise DistributionError("installed backend did not reach managed readiness")
    identity = ready.get("payload")
    if not isinstance(identity, dict):
        raise DistributionError("installed backend readiness identity was malformed")
    build_info = _bundle_build_info(backend.parent)
    try:
        bundle_manifest = json.loads((backend.parent / "bundle-manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionError("installed backend bundle manifest is missing or invalid") from exc
    if not isinstance(bundle_manifest, dict) or bundle_manifest.get("build_id") != build_info.get("build_id"):
        raise DistributionError("installed backend build metadata does not match its bundle manifest")
    _validate_runtime_identity(
        identity, app_version=expected_version, build_info=build_info, data_root=data,
        pid=process.pid, launch_id=launch_id,
    )
    return process, frames, stderr, launch_id


def _stop_installed_host(state: tuple[subprocess.Popen[bytes], Any, Any, str]) -> None:
    global _owned_host, _owned_process_identity
    from scripts.smoke_backend_bundle import _stop_host

    process, frames, stderr, launch_id = state
    _stop_host(process, frames, stderr, launch_id)
    _owned_host = None
    _owned_process_identity = None


def _cleanup_owned_install() -> None:
    """On a failed run, stop only the exact probe-launched host and uninstall only its root."""
    global _owned_host, _owned_process_identity, _owned_install
    failure: list[str] = []
    if _owned_host is not None:
        process = _owned_host[0]
        expected = _owned_process_identity
        try:
            current = _process_inventory()
            if expected and current.get((expected[0], expected[1])) == expected[2] and process.poll() is None:
                _stop_installed_host(_owned_host)
            elif process.poll() is None:
                failure.append("owned backend identity changed; it was left running")
        except Exception:
            failure.append("could not safely stop the exact probe-owned backend process")
        finally:
            _owned_host = None
            _owned_process_identity = None
    install = _owned_install
    if install is not None and install.is_dir():
        registration = _registry_uninstall()
        if registration:
            try:
                location = _registered_install_location(registration)
            except Exception:
                failure.append("owned installer cleanup skipped because its registration path is malformed")
            else:
                if location == install.resolve():
                    try:
                        remaining = _processes_under_install(_process_inventory(), install)
                        if remaining:
                            failure.append("owned installer cleanup skipped because a process remains in the installed program tree")
                        else:
                            executable = _uninstall_command(registration, expected_install=install)
                            _installer(executable, ["/S"], cwd=install.parent)
                            _wait_for_uninstall_completion(install)
                    except Exception:
                        failure.append("could not remove the exact run-owned installation through its uninstaller")
    _owned_install = None
    if failure:
        raise DistributionError("; ".join(failure))


def _uninstall_command(registration: dict[str, Any], *, expected_install: Path) -> Path:
    raw = registration.get("QuietUninstallString") or registration.get("UninstallString")
    if not isinstance(raw, str) or not raw.strip():
        raise DistributionError("registered per-user uninstaller is missing")
    match = re.match(r'^\s*"?(.+?\.exe)"?(?:\s|$)', raw, re.IGNORECASE)
    if not match:
        raise DistributionError("registered uninstaller path is malformed")
    executable = Path(match.group(1)).resolve()
    install_location = _registered_install_location(registration)
    if install_location != expected_install.resolve():
        raise DistributionError("registered per-user uninstaller is outside the expected installed tree")
    if not executable.is_file() or not executable.is_relative_to(install_location):
        raise DistributionError("registered uninstaller is outside the expected installed tree")
    return executable


def _assert_preservation(probe: Path, data: Path, expected: dict[str, Any], cwd: Path) -> None:
    actual = _verify_fixture(probe, "verify", data, cwd)
    fields = (
        "conversation", "knowledge", "report", "historical_news", "historical_news_readable",
        "speech_audio_bytes", "speech_audio_readable", "action_status", "action_events",
        "action_effects", "vault_ownership", "credentials_and_managed_files",
        "external_model_references", "ollama_disabled", "microsoft_encrypted_cache",
    )
    for field in fields:
        if actual.get(field) != expected.get(field):
            raise DistributionError(f"installed profile preservation failed for {field}")
    if actual.get("action_effects") != 1 or actual.get("action_status") != "outcome_unknown":
        raise DistributionError("fixture action effect or non-replay status changed")


def _preservation_fingerprints(data: Path) -> dict[str, str]:
    paths = {
        "config.json": data / "config.json",
        "config.local.json": data / "config.local.json",
        ".env": data / ".env",
        "credentials.json": data / "credentials.json",
        "embedding_fixture": data / "weights" / "fastembed" / "fixture-model.bin",
        "kokoro_fixture": data / "core" / "weights" / "kokoro" / "fixture-model.bin",
        "market_cache": data / "clients" / ".market_cache.json",
        "vault_file": data.parent / "external-context-vault" / "fixture.md",
        "dpapi_cache": data.parent / "local-app-data" / "APEX" / "auth" / "microsoft_todo_token_cache.bin",
    }
    if any(not path.is_file() for path in paths.values()):
        raise DistributionError("production preservation fixture is missing required files")
    return {name: _sha256(path) for name, path in paths.items()}


def _window_state_file() -> Path:
    filename = "window-state.json"
    roots = (
        Path(os.environ.get("APPDATA", "")) / APP_ID,
        Path(os.environ.get("LOCALAPPDATA", "")) / APP_ID,
        Path(os.environ.get("APPDATA", "")) / APP_NAME,
        Path(os.environ.get("LOCALAPPDATA", "")) / APP_NAME,
    )
    matches = [root / filename for root in roots if (root / filename).is_file()]
    if len(matches) != 1:
        raise DistributionError("could not identify exactly one Tauri window-state file")
    return matches[0]


def _run_installed_ui_checks(
    probe: Path,
    install: Path,
    report_root: Path,
    args: argparse.Namespace,
    *,
    suffix: str,
) -> None:
    if not args.driver or not args.native_driver:
        raise DistributionError("interactive mode requires --driver and --native-driver")
    desktop_report = report_root / f"desktop-{suffix}.json"
    location_report = report_root / f"location-{suffix}.json"
    commands = (
        [
            str(probe), "--desktop-smoke-suite", "--application", str(install / "apex-desktop.exe"),
            "--driver", str(args.driver), "--native-driver", str(args.native_driver), "--report", str(desktop_report),
            "--fastembed-cache", str(args.fastembed_cache), "--kokoro-assets", str(args.kokoro_assets),
        ],
        [
            str(probe), "--location-smoke-suite", "--application", str(install / "apex-desktop.exe"),
            "--driver", str(args.driver), "--native-driver", str(args.native_driver), "--report", str(location_report),
            "--foreground-wait", "120", "--manual-permission-wait", "120",
        ],
    )
    for command, report_path in zip(commands, (desktop_report, location_report), strict=True):
        result = _run(command, cwd=report_root, timeout=1800)
        if result.returncode != 0 or not report_path.is_file():
            raise DistributionError("installed WebView or foreground-location controller failed")
        try:
            evidence = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DistributionError("installed WebView or location controller returned an invalid report") from exc
        if not isinstance(evidence, dict) or evidence.get("result") != "passed":
            raise DistributionError("installed WebView or location controller reported failed or unverified checks")


def _powershell(command: str, *, cwd: Path, timeout: int = 20) -> str:
    result = _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=cwd, timeout=timeout,
    )
    if result.returncode != 0:
        raise DistributionError("Windows desktop-services query failed")
    return result.stdout.strip()


def _notification_history(cwd: Path) -> dict[str, Any]:
    # This WinRT reflection path reads actual toast history for APEX's AUMID.
    # It does not grant notification-listener permission or alter OS settings.
    command = rf'''
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$aumid = '{APP_ID}'
$managerType = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
$notifier = $managerType::CreateToastNotifier($aumid)
$settingProperty = $notifier.GetType().GetProperty('Setting')
if ($null -eq $settingProperty) {{ throw 'toast setting property unavailable' }}
$setting = $settingProperty.GetValue($notifier)
if ($null -eq $setting) {{ throw 'toast setting unavailable' }}
$historyProperty = $managerType.GetProperty('History')
if ($null -eq $historyProperty) {{ throw 'toast history unavailable' }}
$history = $historyProperty.GetValue($null)
$collection = $history.GetHistory($aumid)
$records = [System.Collections.Generic.List[string]]::new()
if ($null -ne $collection) {{
  $index = 0
  foreach ($toast in $collection) {{
    if ($index -ge 128) {{ throw 'toast history exceeded 128 records' }}
    $content = $toast.GetType().GetProperty('Content').GetValue($toast)
    if ($null -eq $content) {{ throw 'toast content unavailable' }}
    $xml = $content.GetType().GetMethod('GetXml').Invoke($content, @())
    if ([string]::IsNullOrWhiteSpace([string]$xml)) {{ throw 'toast XML empty' }}
    $records.Add([string]$xml)
    $index++
  }}
}}
[pscustomobject]@{{ setting = [string]$setting; records = @($records.ToArray()) }} | ConvertTo-Json -Depth 5 -Compress
'''
    raw = _powershell(command, cwd=cwd, timeout=30)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DistributionError("WinRT notification history returned invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("setting"), str):
        raise DistributionError("WinRT notification history omitted the actual OS notification setting")
    records = value.get("records")
    if records is None:
        records = []
    elif isinstance(records, str):
        records = [records]
    if not isinstance(records, list) or not all(isinstance(item, str) for item in records):
        raise DistributionError("WinRT notification history returned malformed records")
    if len(records) > 128:
        raise DistributionError("WinRT notification history exceeded its bounded record limit")
    return {"setting": value["setting"], "records": records}


def _added_toasts(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    previous = before.get("records")
    current = after.get("records")
    if not isinstance(previous, list) or not isinstance(current, list):
        raise DistributionError("notification history snapshot was malformed")
    remaining = Counter(hashlib.sha256(item.encode("utf-8")).hexdigest() for item in previous)
    added: list[str] = []
    for item in current:
        signature = hashlib.sha256(item.encode("utf-8")).hexdigest()
        if remaining[signature]:
            remaining[signature] -= 1
        else:
            added.append(item)
    return added


def _require_generic_apex_toast(raw: str) -> None:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DistributionError("new APEX toast history entry contained invalid XML") from exc
    text = [html.unescape(node.text or "") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "text"]
    if text != ["APEX", "An APEX run has completed."]:
        raise DistributionError("new APEX toast history entry did not contain the approved generic completion text")


def _patch_runtime_settings(payload: dict[str, Any], cwd: Path) -> dict[str, Any]:
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/settings",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
    except (OSError, TimeoutError) as exc:
        raise DistributionError("installed Runtime Settings preference update failed") from exc
    if len(raw) > 1024 * 1024:
        raise DistributionError("installed Runtime Settings response exceeded its size limit")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DistributionError("installed Runtime Settings returned invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("settings"), dict):
        raise DistributionError("installed Runtime Settings response omitted settings")
    return value["settings"]


def _run_value_and_approval() -> tuple[str | None, bytes | None]:
    if winreg is None:
        raise DistributionError("Windows startup state inspection is unavailable")
    run_value: str | None = None
    approval: bytes | None = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            try:
                run_value = str(winreg.QueryValueEx(key, APP_NAME)[0])
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run") as key:
            try:
                value, kind = winreg.QueryValueEx(key, APP_NAME)
                if kind != winreg.REG_BINARY:
                    raise DistributionError("Windows startup approval has an unexpected registry type")
                approval = bytes(value)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass
    return run_value, approval


def _set_run_value(value: str) -> None:
    """Write the named startup value only inside the guarded disposable HKCU."""
    if winreg is None:
        raise DistributionError("Windows startup state mutation is unavailable")
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, value)
    except OSError as exc:
        raise DistributionError("could not create the isolated startup ownership fixture") from exc


def _remove_run_value_if_matches(expected: str) -> None:
    if winreg is None:
        raise DistributionError("Windows startup state mutation is unavailable")
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            current, _kind = winreg.QueryValueEx(key, APP_NAME)
            if current != expected:
                raise DistributionError("startup ownership fixture changed unexpectedly")
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        raise DistributionError("startup ownership fixture disappeared before cleanup") from None
    except OSError as exc:
        raise DistributionError("could not remove the exact isolated startup ownership fixture") from exc


def _remove_approval_if_matches(expected: bytes) -> None:
    if winreg is None:
        raise DistributionError("Windows startup state mutation is unavailable")
    path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            current, kind = winreg.QueryValueEx(key, APP_NAME)
            if kind != winreg.REG_BINARY or bytes(current) != expected:
                raise DistributionError("startup approval changed outside the owned fixture")
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DistributionError("could not remove the exact isolated startup approval value") from exc


def _startup_enabled_for(executable: Path) -> bool:
    command, approval = _run_value_and_approval()
    expected = f'"{executable.resolve()}" --autostart'
    if command != expected:
        return False
    if approval is None:
        return True
    return len(approval) == 12 and approval[0] in {2, 6}


def _set_startup_approval_disabled() -> None:
    """Create a Task Manager-style disabled startup state in the guarded test HKCU."""
    if winreg is None:
        raise DistributionError("Windows startup state mutation is unavailable")
    path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_BINARY, bytes([3]) + bytes(11))
    except OSError as exc:
        raise DistributionError("could not create the isolated Windows startup-mismatch fixture") from exc


def _native_desktop_services_status(driver: Any) -> dict[str, Any]:
    result = driver._command("POST", "/execute/async", {
        "script": (
            "const done=arguments[arguments.length-1]; "
            "const invoke=window.__TAURI_INTERNALS__?.invoke; "
            "if(!invoke){done({smoke_error:'tauri_invoke_unavailable'});return;} "
            "invoke('desktop_services_status').then(done).catch(()=>done({smoke_error:'status_query_failed'}));"
        ),
        "args": [],
    })
    if not isinstance(result, dict) or result.get("smoke_error"):
        raise DistributionError("installed native desktop-services status command did not return effective OS state")
    requested = result.get("requested")
    startup = result.get("startup")
    notifications = result.get("notifications")
    if not isinstance(requested, dict) or not isinstance(startup, dict) or not isinstance(notifications, dict):
        raise DistributionError("installed native desktop-services status omitted requested or effective fields")
    return result


def _windows_for_pid(pid: int) -> list[int]:
    import ctypes
    from ctypes import wintypes as win_types

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [win_types.HWND, ctypes.POINTER(win_types.DWORD)]
    user32.GetWindowThreadProcessId.restype = win_types.DWORD
    user32.GetWindowTextLengthW.argtypes = [win_types.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [win_types.HWND, win_types.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [win_types.HWND]
    user32.IsWindowVisible.restype = win_types.BOOL
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(win_types.BOOL, win_types.HWND, win_types.LPARAM)

    @callback_type
    def collect(hwnd: int, _lparam: int) -> bool:
        window_pid = win_types.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value == APP_NAME:
            found.append(int(hwnd))
        return True

    user32.EnumWindows.argtypes = [callback_type, win_types.LPARAM]
    user32.EnumWindows.restype = win_types.BOOL
    user32.EnumWindows(collect, 0)
    return found


def _completion_briefing(timeout: float) -> str:
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/briefing-sessions",
        data=json.dumps({
            "idempotency_key": str(uuid.uuid4()), "profile_id": "daily",
            "model_id": "demo/daily-fixture", "origin": "hud",
        }, separators=(",", ":")).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=min(20.0, timeout)) as response:
            accepted = json.loads(response.read(1024 * 1024 + 1))
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise DistributionError("production Briefing completion fixture could not be accepted") from exc
    if not isinstance(accepted, dict) or not isinstance(accepted.get("id"), str):
        raise DistributionError("production Briefing completion fixture returned no session ID")
    session_id = accepted["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/v1/briefing-sessions?limit=50",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10) as response:
                sessions = json.loads(response.read(1024 * 1024 + 1))
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise DistributionError("production Briefing completion fixture status query failed") from exc
        if isinstance(sessions, list):
            match = next((item for item in sessions if isinstance(item, dict) and item.get("id") == session_id), None)
            if match and match.get("run_status") == "completed":
                return session_id
            if match and match.get("run_status") in {"failed", "cancelled", "interrupted"}:
                raise DistributionError("production Briefing completion fixture did not complete")
        time.sleep(0.25)
    raise DistributionError("production Briefing completion fixture exceeded its time bound")


def _run_installed_services_gate(
    desktop: Path, data: Path, work: Path, args: argparse.Namespace, *, expected_version: str,
) -> Path:
    """Exercise installed desktop preference reconciliation and real toast history."""
    from scripts import smoke_desktop_shell as desktop_smoke

    if not _port_8000_available():
        raise DistributionError("port 8000 is occupied before the installed desktop-services gate")
    env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LOCALAPPDATA", "APPDATA", "USERPROFILE", "TEMP", "TMP")
        if os.environ.get(key)
    }
    system_root = env.get("SYSTEMROOT", r"C:\Windows")
    env["PATH"] = os.pathsep.join((str(Path(system_root) / "System32"), system_root))
    env.update({
        "APEX_DATA_DIR": str(data.resolve()), "DEMO_MODE": "true", "DEV_MODE": "false",
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONUTF8": "1",
    })
    control_port, native_port = desktop_smoke._available_port(), desktop_smoke._available_port()
    while native_port == control_port:
        native_port = desktop_smoke._available_port()
    driver_log = work / "installed-services-tauri-driver.log"
    with driver_log.open("wb") as log:
        driver_process = subprocess.Popen(
            [str(args.driver), "--port", str(control_port), "--native-port", str(native_port), "--native-driver", str(args.native_driver)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    driver = desktop_smoke.WebDriver(control_port, 20.0)
    shell_handle: int | None = None
    shell_pid: int | None = None
    shell_hwnd: int | None = None
    shell_identity: tuple[int, str, str] | None = None
    hidden_process: subprocess.Popen[bytes] | None = None
    hidden_identity: tuple[int, str, str] | None = None
    try:
        service_deadline = time.monotonic() + 30
        while time.monotonic() < service_deadline:
            if driver_process.poll() is not None:
                raise DistributionError("tauri-driver exited before the installed services session")
            try:
                driver.request("GET", "/status")
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise DistributionError("tauri-driver did not become ready for the installed services session")
        driver.start(desktop.resolve())
        if not driver.wait_for("installed APEX WebView", lambda: bool(driver.text()), 45):
            raise DistributionError("installed APEX WebView did not expose its document")
        shell_handle, shell_pid, shell_hwnd = desktop_smoke._native_window(driver_process.pid, desktop)
        shell_inventory = _process_inventory()
        shell_process_key = next((key for key in shell_inventory if key[0] == shell_pid), None)
        expected_shell_path = os.path.normcase(os.path.abspath(str(desktop.resolve())))
        if shell_process_key is None or shell_process_key[1] != expected_shell_path:
            raise DistributionError("could not bind installed shell to its exact process image and creation time")
        shell_identity = (shell_process_key[0], shell_process_key[1], shell_inventory[shell_process_key])
        runtime = desktop_smoke._runtime_identity(data, 45)
        if runtime.get("app_version") != expected_version:
            raise DistributionError("installed desktop shell runtime version does not match the requested version")
        current = _patch_runtime_settings({"desktop": {"launch_on_startup": False, "completion_notifications": False}}, work)
        desktop_settings = current.get("desktop")
        if not isinstance(desktop_settings, dict) or desktop_settings.get("launch_on_startup") is not False or desktop_settings.get("completion_notifications") is not False:
            raise DistributionError("installed Runtime Settings did not persist the requested disabled baseline")
        disabled_deadline = time.monotonic() + 15
        native_status: dict[str, Any] | None = None
        while time.monotonic() < disabled_deadline:
            native_status = _native_desktop_services_status(driver)
            requested_state = native_status["requested"]
            actual_state = native_status["startup"]
            if requested_state.get("launch_on_startup") is False and actual_state.get("actual_enabled") is False:
                break
            time.sleep(0.25)
        if native_status is None or native_status["requested"].get("launch_on_startup") is not False or native_status["startup"].get("actual_enabled") is not False:
            raise DistributionError("installed native desktop-services status did not confirm the requested disabled startup state")
        run_command, approval = _run_value_and_approval()
        if run_command is not None or approval is not None:
            raise DistributionError("disabled startup preference left a Windows sign-in registration or approval value")
        if not _click_for_driver(driver, "Open settings", 8) or not _click_for_driver(driver, "Desktop", 8):
            raise DistributionError("installed Settings UI did not expose the Desktop preference page")
        if not driver.wait_for("desktop settings rendered", lambda: "Startup registration" in driver.text() and "Windows notifications" in driver.text(), 15):
            raise DistributionError("installed Settings UI did not expose requested and effective desktop service status")
        _notification_history(work)
        enabled = _patch_runtime_settings({"desktop": {"launch_on_startup": True, "completion_notifications": True}}, work)
        requested = enabled.get("desktop")
        if not isinstance(requested, dict) or requested.get("launch_on_startup") is not True or requested.get("completion_notifications") is not True:
            raise DistributionError("installed Runtime Settings did not persist the requested enabled preferences")
        preference_deadline = time.monotonic() + 15
        native_status = None
        while time.monotonic() < preference_deadline:
            native_status = _native_desktop_services_status(driver)
            requested_state = native_status["requested"]
            actual_state = native_status["startup"]
            if requested_state.get("launch_on_startup") is True and actual_state.get("actual_enabled") is True and not actual_state.get("error_code"):
                break
            time.sleep(0.25)
        if (
            native_status is None
            or native_status["requested"].get("launch_on_startup") is not True
            or native_status["startup"].get("actual_enabled") is not True
            or native_status["startup"].get("error_code")
        ):
            raise DistributionError("enabled startup preference did not become effective in the Windows sign-in state")
        history = _notification_history(work)
        if history["setting"].casefold() != "enabled":
            raise DistributionError("Windows reports APEX completion notifications are disabled")
        if not driver.wait_for("effective desktop preferences", lambda: "Saved startup preference" in driver.text() and "Enabled" in driver.text(), 15):
            raise DistributionError("installed Settings UI did not reflect the enabled requested and effective preferences")

        # Simulate an operator disabling this test account's APEX sign-in entry
        # in Task Manager, then reopen the production Desktop page so its
        # native status command refreshes actual OS state without reconciling it.
        _set_startup_approval_disabled()
        if not _click_for_driver(driver, "Close", 8):
            raise DistributionError("could not close the isolated Settings panel to refresh OS startup state")
        if not _click_for_driver(driver, "Open settings", 8) or not _click_for_driver(driver, "Desktop", 8):
            raise DistributionError("could not reopen the installed Desktop page after the startup mismatch fixture")
        mismatch = _native_desktop_services_status(driver)
        if (
            mismatch["requested"].get("launch_on_startup") is not True
            or mismatch["startup"].get("actual_enabled") is not False
            or not driver.wait_for("startup mismatch surfaced", lambda: "Disabled; requested enabled" in driver.text(), 10)
        ):
            raise DistributionError("installed UI reported startup success while Windows marked the requested entry disabled")
        if not _click_for_driver(driver, "Retry desktop services", 8):
            raise DistributionError("installed Desktop page did not expose its startup reconciliation action")
        retry_deadline = time.monotonic() + 15
        while time.monotonic() < retry_deadline:
            native_status = _native_desktop_services_status(driver)
            if native_status["startup"].get("actual_enabled") is True and not native_status["startup"].get("error_code"):
                break
            time.sleep(0.25)
        if native_status is None or native_status["startup"].get("actual_enabled") is not True or native_status["startup"].get("error_code"):
            raise DistributionError("Retry desktop services did not restore the effective Windows sign-in state")

        before_hidden = history
        desktop_smoke._hide_native_window(shell_hwnd, 10)
        _completion_briefing(90)
        deadline = time.monotonic() + 20
        additions: list[str] = []
        while time.monotonic() < deadline:
            additions = _added_toasts(before_hidden, _notification_history(work))
            if additions:
                break
            time.sleep(0.5)
        if len(additions) != 1:
            raise DistributionError(f"hidden successful completion produced {len(additions)} APEX notification-history entries; expected exactly one")
        _require_generic_apex_toast(additions[0])
        desktop_smoke._show_native_window(shell_pid, shell_hwnd, 10)

        before_visible = _notification_history(work)
        _completion_briefing(90)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if _added_toasts(before_visible, _notification_history(work)):
                raise DistributionError("visible successful completion produced an APEX notification")
            time.sleep(0.5)

        desktop_smoke._invoke_tray_menu_item("Quit", 10, expected_pid=shell_pid)
        driver.close()
        if shell_handle is not None:
            desktop_smoke._close_handle(shell_handle)
            shell_handle = None
        if not _port_8000_available():
            raise DistributionError("installed desktop shell did not release its managed backend after Quit")
        if _processes_under_install(_process_inventory(), desktop.parent):
            raise DistributionError("installed shell process remained in the program tree after its owned tray Quit")

        hidden_log = work / "installed-autostart.log"
        with hidden_log.open("wb") as log:
            hidden_process = subprocess.Popen(
                [str(desktop), "--autostart"], cwd=work, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        expected_image = os.path.normcase(os.path.abspath(str(desktop.resolve())))
        identity_deadline = time.monotonic() + 15
        while time.monotonic() < identity_deadline:
            inventory = _process_inventory()
            identity = next((key for key in inventory if key[0] == hidden_process.pid), None)
            if identity:
                if identity[1] != expected_image:
                    raise DistributionError("autostart shell PID resolved to an unexpected image path")
                hidden_identity = (identity[0], identity[1], inventory[identity])
                break
            if hidden_process.poll() is not None:
                raise DistributionError("installed --autostart shell exited before creating its hidden window")
            time.sleep(0.25)
        if hidden_identity is None:
            raise DistributionError("could not bind hidden autostart shell to its PID, path, and creation time")
        window_deadline = time.monotonic() + 30
        windows: list[int] = []
        while time.monotonic() < window_deadline and not windows:
            windows = _windows_for_pid(hidden_process.pid)
            if not windows and hidden_process.poll() is not None:
                raise DistributionError("installed --autostart shell exited before exposing its native window")
            time.sleep(0.25)
        if len(windows) != 1:
            raise DistributionError("installed --autostart shell did not expose exactly one native APEX window")
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = ctypes.c_int
        if user32.IsWindowVisible(ctypes.c_void_p(windows[0])):
            raise DistributionError("installed --autostart shell showed its main window instead of starting hidden")
        desktop_smoke._invoke_tray_menu_item("Show", 10, expected_pid=hidden_process.pid)
        visible_deadline = time.monotonic() + 10
        while time.monotonic() < visible_deadline and not user32.IsWindowVisible(ctypes.c_void_p(windows[0])):
            time.sleep(0.25)
        if not user32.IsWindowVisible(ctypes.c_void_p(windows[0])):
            raise DistributionError("actual APEX tray Show did not reveal the hidden autostart window")
        desktop_smoke._invoke_tray_menu_item("Quit", 10, expected_pid=hidden_process.pid)
        try:
            hidden_process.wait(timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise DistributionError("hidden autostart shell did not exit after its owned tray Quit") from exc
        if not _port_8000_available():
            raise DistributionError("hidden autostart shell did not release its managed backend after Quit")
        return _window_state_file()
    finally:
        if shell_handle is not None:
            desktop_smoke._close_handle(shell_handle)
        if driver is not None:
            driver.close()
        if shell_identity is not None:
            current = _process_inventory()
            if current.get((shell_identity[0], shell_identity[1])) == shell_identity[2]:
                try:
                    desktop_smoke._invoke_tray_menu_item("Quit", 5, expected_pid=shell_identity[0])
                except Exception:
                    raise DistributionError("could not safely quit the exact owned installed shell process") from None
        if driver_process.poll() is None:
            driver_process.terminate()
            try:
                driver_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # The direct process is this controller-owned tauri-driver; do
                # not terminate any shell/backend process by reused PID.
                driver_process.kill()
        if hidden_process is not None and hidden_process.poll() is None:
            current = _process_inventory()
            identity = hidden_identity
            if identity is None:
                expected_image = os.path.normcase(os.path.abspath(str(desktop.resolve())))
                key = next((key for key in current if key[0] == hidden_process.pid), None)
                if key is not None and key[1] == expected_image:
                    identity = (key[0], key[1], current[key])
            if identity and current.get((identity[0], identity[1])) == identity[2]:
                try:
                    desktop_smoke._invoke_tray_menu_item("Quit", 5, expected_pid=hidden_process.pid)
                    hidden_process.wait(timeout=10)
                except Exception:
                    raise DistributionError("could not safely quit the exact owned hidden startup process") from None


def _click_for_driver(driver: Any, label: str, timeout: float) -> bool:
    from scripts.smoke_desktop_shell import _click_button

    return _click_button(driver, label, timeout)


def _run_distribution(args: argparse.Namespace, report: Report) -> None:
    global _owned_install
    _windows_only()
    profile = _profile_root()
    _guard_disposable_profile(profile)
    install, data, _desktop, bundle = _installed_paths(profile)
    expected_empty = (install, data)
    if (
        any(path.exists() for path in expected_empty)
        or _registry_uninstall() is not None
        or any(_run_value_and_approval())
        or _has_start_menu_entry()
    ):
        raise DistributionError("the disposable profile already has an APEX installation or data profile")
    if not _port_8000_available():
        raise DistributionError("port 8000 is already owned; refusing to start the installed backend")

    installer = args.installer.resolve(strict=True)
    previous = args.previous_installer.resolve(strict=True)
    probe_arg = args.probe.resolve(strict=True)
    probe = probe_arg / "apex-bundle-probe.exe" if probe_arg.is_dir() else probe_arg
    if not all(path.is_file() for path in (installer, previous, probe)):
        raise DistributionError("installer, previous installer, and frozen probe must be existing files")
    if not args.fastembed_cache or not args.fastembed_cache.is_dir() or not args.kokoro_assets or not args.kokoro_assets.is_dir():
        raise DistributionError("strict distribution smoke requires external FastEmbed and Kokoro test assets")
    if args.mode == "interactive" and not all(
        path is not None and path.is_file() for path in (args.driver, args.native_driver)
    ):
        raise DistributionError("interactive mode requires --driver and --native-driver")
    if installer == previous or _sha256(installer) == _sha256(previous):
        raise DistributionError("previous test installer must differ from the current installer")
    if not args.expected_version or not re.fullmatch(r"\d+\.\d+\.\d+", args.expected_version):
        raise DistributionError("expected version must be a numeric three-part version")

    # The test installer must be an explicitly identified synthetic build, not
    # a released installer. Its sidecar binds the artifact hash and provenance.
    previous_manifest = previous.with_suffix(previous.suffix + ".fixture.json")
    if not previous_manifest.is_file():
        raise DistributionError("synthetic previous installer provenance sidecar is missing")
    manifest = json.loads(previous_manifest.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("kind") != "synthetic_upgrade_fixture"
        or manifest.get("installer_name") != previous.name
        or manifest.get("installer_sha256") != _sha256(previous)
        or manifest.get("base_commit") != PREVIOUS_FIXTURE_BASE
        or not re.fullmatch(r"[a-f0-9]{40}", str(manifest.get("fixture_commit", "")))
        or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("overlay_sha256", "")))
        or manifest.get("app_version") != args.previous_version
        or not isinstance(manifest.get("backend_build_id"), str)
        or not manifest.get("backend_build_id")
    ):
        raise DistributionError("previous installer provenance does not bind this synthetic 2.0.0 fixture")
    report.add("synthetic_previous_installer_provenance", "passed")

    with tempfile.TemporaryDirectory(prefix="apex-distribution-smoke-") as temporary:
        cwd = Path(temporary).resolve()
        _owned_install = install
        old = _installer(previous, ["/S"], cwd=cwd)
        report.add("silent_install_previous", "passed")
        if old.returncode != 0:
            raise DistributionError("synthetic previous installer failed")
        old_registration = _registry_uninstall()
        if not old_registration or old_registration.get("DisplayVersion") != args.previous_version:
            raise DistributionError("synthetic previous installer did not register version 2.0.0")
        _locate_installed_executables(install)
        previous_build_info = _bundle_build_info(bundle)
        _validate_previous_build(manifest, previous_build_info, args.previous_version)

        _, data, _desktop, _bundle = _installed_paths(profile)
        expected = _verify_fixture(probe, "seed", data, cwd)
        baseline = _verify_fixture(probe, "verify", data, cwd)
        preserved_files = _preservation_fingerprints(data)
        sentinel = data / "distribution-smoke-sentinel.json"
        sentinel_bytes = json.dumps({"token": "synthetic-only", "created": "distribution-smoke"}, sort_keys=True).encode()
        sentinel.write_bytes(sentinel_bytes)
        report.add("production_fixture_seeded", "passed")

        window_state: Path | None = None
        window_state_bytes: bytes | None = None
        if args.mode == "interactive":
            window_state = _run_installed_services_gate(
                install / "apex-desktop.exe", data, cwd, args, expected_version=args.previous_version,
            )
            window_state_bytes = window_state.read_bytes()
            if not isinstance(json.loads(window_state_bytes), dict):
                raise DistributionError("Tauri window-state settings are malformed")
            report.add("previous_installed_startup_and_notification_delivery", "passed")
            report.add("previous_requested_and_effective_desktop_preferences", "passed")
            report.add("previous_hidden_completion_toast_and_visible_suppression", "passed")
            report.add("previous_hidden_autostart_and_tray_recovery", "passed")
            preserved_files = _preservation_fingerprints(data)
        else:
            report.add("tauri_window_state_upgrade_and_uninstall", "unverified", "CI mode has no interactive WebView2 window")
            report.add("installed_startup_and_notification_delivery", "unverified", "CI mode does not start the installed WebView or inspect OS notification history")
            report.add("requested_effective_preferences_and_toast_history", "unverified", "interactive Windows mode is required")
            report.add("hidden_autostart_and_tray_recovery", "unverified", "interactive Windows mode is required")

        _, backend, cli = _locate_installed_executables(install)
        old_backend_hash = _sha256(backend)
        host = _installed_host(backend, data, cwd, args.previous_version)
        before = _process_inventory()
        blocked = _run([str(installer), "/S"], cwd=cwd, timeout=INSTALL_TIMEOUT)
        after = _process_inventory()
        _assert_owned_processes_unchanged(before, after, install)
        if blocked.returncode == 0:
            raise DistributionError("installer returned success while an installed backend process was still running")
        if host[0].poll() is not None:
            raise DistributionError("upgrade attempt terminated the installed backend")
        old_after_block = _registry_uninstall()
        if not old_after_block or old_after_block.get("DisplayVersion") != args.previous_version:
            raise DistributionError("running-process refusal changed the installed version")
        if _sha256(backend) != old_backend_hash:
            raise DistributionError("running-process refusal replaced the installed backend")
        _stop_installed_host(host)
        report.add("running_installed_binary_refused_without_termination", "passed", f"installer exit={blocked.returncode}; owner process identity remained live")

        _installer(installer, ["/S"], cwd=cwd)
        registration = _registry_uninstall()
        if not registration or registration.get("DisplayVersion") != args.expected_version:
            raise DistributionError("upgrade did not register the expected current version")
        _locate_installed_executables(install)
        _validate_registration(profile, install, args.expected_version, expected_startup=args.mode == "interactive")
        _assert_preservation(probe, data, baseline, cwd)
        if _preservation_fingerprints(data) != preserved_files:
            raise DistributionError("upgrade changed a settings, credential, model, cache, or vault sentinel")
        if window_state is not None and window_state.read_bytes() != window_state_bytes:
            raise DistributionError("upgrade changed the persisted Tauri window state")
        if sentinel.read_bytes() != sentinel_bytes:
            raise DistributionError("upgrade changed the synthetic credential/settings sentinel")
        report.add("upgrade_registration_and_start_menu", "passed")
        report.add("upgrade_preserved_domain_data_audio_vault_actions_and_settings", "passed")
        if window_state is not None:
            report.add("upgrade_preserved_tauri_window_state", "passed")

        backend_report = cwd / "backend-bundle-smoke.json"
        suite_args = [
            str(probe), "--run-suite", "--bundle", str(bundle), "--probe", str(probe),
            "--strict", "--require-idle-release", "--fastembed-cache", str(args.fastembed_cache.resolve()),
            "--kokoro-assets", str(args.kokoro_assets.resolve()), "--inference-timeout", "600",
            "--report", str(backend_report),
        ]
        suite = _run(suite_args, cwd=cwd, timeout=1800)
        if suite.returncode != 0 or not backend_report.is_file():
            raise DistributionError("full strict frozen backend smoke did not complete successfully")
        backend_result = json.loads(backend_report.read_text(encoding="utf-8"))
        if not isinstance(backend_result, dict) or backend_result.get("result") != "passed":
            raise DistributionError("full strict frozen backend smoke reported a non-passing result")
        report.add("strict_frozen_backend_and_idle_release_smoke", "passed")

        if args.mode == "interactive":
            if window_state is None:
                raise DistributionError("current installed UI test did not have a previous window-state baseline")
            window_state = _run_installed_services_gate(
                install / "apex-desktop.exe", data, cwd, args, expected_version=args.expected_version,
            )
            window_state_bytes = window_state.read_bytes()
            if not isinstance(json.loads(window_state_bytes), dict):
                raise DistributionError("current installed Tauri window-state settings are malformed")
            report.add("current_installed_startup_hidden_and_notification_history", "passed")
            report.add("current_requested_and_effective_desktop_preferences", "passed")
            report.add("current_hidden_completion_toast_and_visible_suppression", "passed")
            preserved_files = _preservation_fingerprints(data)
            _assert_preservation(probe, data, baseline, cwd)
            _run_installed_ui_checks(probe, install, cwd, args, suffix="current")
            report.add("installed_webview_tray_and_foreground_location", "passed")

        # Verify the installed CLI from an unrelated working directory and
        # launch a real frozen managed backend against the installed data root.
        host = _installed_host(backend, data, cwd, args.expected_version)
        cli_result = _run([str(cli), "status"], cwd=cwd, timeout=60)
        if cli_result.returncode != 0:
            raise DistributionError("installed CLI status failed from an unrelated working directory")
        report.add("installed_cli_from_unrelated_cwd", "passed")
        _stop_installed_host(host)
        report.add("installed_headless_backend_from_unrelated_cwd", "passed")

        registration = _registry_uninstall()
        assert registration is not None
        if _processes_under_install(_process_inventory(), install):
            raise DistributionError("uninstall skipped because an installed program process remains active")
        uninstaller = _uninstall_command(registration, expected_install=install)
        prior_approval = _run_value_and_approval()[1]
        foreign_startup_command = '"C:\\Windows\\System32\\notepad.exe" --distribution-smoke-foreign-value'
        _set_run_value(foreign_startup_command)
        _installer(uninstaller, ["/S"], cwd=cwd)
        _wait_for_uninstall_completion(install)
        after_uninstall_run, after_uninstall_approval = _run_value_and_approval()
        if after_uninstall_run != foreign_startup_command:
            raise DistributionError("uninstall removed or changed a same-named startup command it did not own")
        report.add("uninstall_preserved_foreign_startup_command", "passed")
        _remove_run_value_if_matches(foreign_startup_command)
        if after_uninstall_approval is not None:
            if prior_approval is None or after_uninstall_approval != prior_approval:
                raise DistributionError("uninstall left an unexpected startup approval value")
            _remove_approval_if_matches(prior_approval)
        if any(_run_value_and_approval()):
            raise DistributionError("uninstall left per-user startup entries after fixture cleanup")
        if install.exists():
            raise DistributionError("uninstall left files under the owned installed program directory")
        if not data.is_dir() or sentinel.read_bytes() != sentinel_bytes:
            raise DistributionError("uninstall removed or changed operator data/settings")
        menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if list(menu.glob("APEX*.lnk")) or list((menu / APP_NAME).glob("*.lnk")):
            raise DistributionError("uninstall left an owned Start Menu shortcut")
        _assert_preservation(probe, data, baseline, cwd)
        if _preservation_fingerprints(data) != preserved_files:
            raise DistributionError("uninstall changed a settings, credential, model, cache, or vault sentinel")
        if window_state is not None and window_state.read_bytes() != window_state_bytes:
            raise DistributionError("uninstall removed or changed the persisted Tauri window state")
        report.add("uninstall_removed_owned_programs_preserved_data", "passed")

        _installer(installer, ["/S"], cwd=cwd)
        registration = _registry_uninstall()
        if not registration or registration.get("DisplayVersion") != args.expected_version:
            raise DistributionError("reinstall did not register the current version")
        _assert_preservation(probe, data, baseline, cwd)
        if _preservation_fingerprints(data) != preserved_files:
            raise DistributionError("reinstall changed a settings, credential, model, cache, or vault sentinel")
        if window_state is not None and window_state.read_bytes() != window_state_bytes:
            raise DistributionError("reinstall removed or changed the persisted Tauri window state")
        if sentinel.read_bytes() != sentinel_bytes:
            raise DistributionError("reinstall changed preserved data/settings")
        report.add("reinstall_reused_preserved_profile", "passed")

    if args.mode == "ci":
        report.add(
            "installed_webview_tray_startup_notifications_and_foreground_location",
            "unverified",
            "CI mode exercises silent installation and headless runtime; the interactive Windows gate is required for WebView, tray, notification delivery, startup behavior, and foreground location",
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True, help="current per-user NSIS installer")
    parser.add_argument("--previous-installer", type=Path, required=True, help="synthetic previous 2.0.0 test installer")
    parser.add_argument("--probe", type=Path, required=True, help="build-only frozen probe executable or directory")
    parser.add_argument("--fastembed-cache", type=Path, help="external test-only FastEmbed cache")
    parser.add_argument("--kokoro-assets", type=Path, help="external test-only Kokoro assets directory")
    parser.add_argument("--mode", choices=("ci", "interactive"), default="ci")
    parser.add_argument("--report", type=Path, required=True, help="JSON result report")
    parser.add_argument("--expected-version", default=DEFAULT_VERSION)
    parser.add_argument("--previous-version", default="2.0.0")
    parser.add_argument("--driver", type=Path, help="interactive mode tauri-driver executable")
    parser.add_argument("--native-driver", type=Path, help="interactive mode matching WebView2 driver executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    global _owned_install
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = Report()
    try:
        _run_distribution(args, report)
    except DistributionError as exc:
        report.add("distribution_lifecycle", "failed", str(exc)[:2048])
        if _owned_install is not None:
            try:
                _cleanup_owned_install()
            except DistributionError as cleanup_error:
                report.add("owned_install_cleanup", "failed", str(cleanup_error)[:512])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Filesystem and JSON exceptions commonly embed absolute user paths or
        # data snippets. Keep the public report useful without exposing them.
        report.add("distribution_lifecycle", "failed", f"{type(exc).__name__}: operation failed")
        if _owned_install is not None:
            try:
                _cleanup_owned_install()
            except DistributionError as cleanup_error:
                report.add("owned_install_cleanup", "failed", str(cleanup_error)[:512])
    result = report.as_dict(mode=args.mode)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 1 if result["result"] == "failed" else (2 if result["result"] == "unverified" and args.mode == "interactive" else 0)


if __name__ == "__main__":
    raise SystemExit(main())
