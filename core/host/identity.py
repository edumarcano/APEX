"""Stable, privacy-preserving identity for one APEX host process."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Literal

from core.host.profile_lock import ProfileLock
from core.runtime_paths import RuntimePaths

HostingMode = Literal["standalone", "managed"]
SHUTDOWN_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, slots=True)
class HostIdentity:
    """Public, non-secret facts that identify a running APEX host."""

    app_id: Literal["apex"]
    app_version: str
    build_id: str
    instance_id: str
    pid: int
    hosting_mode: HostingMode
    launch_id: str | None
    data_root_fingerprint: str
    shutdown_timeout_seconds: int = SHUTDOWN_TIMEOUT_SECONDS

    def as_dict(self) -> dict[str, object]:
        """Return the stable control-protocol representation."""
        return {
            "app_id": self.app_id,
            "app_version": self.app_version,
            "build_id": self.build_id,
            "instance_id": self.instance_id,
            "pid": self.pid,
            "hosting_mode": self.hosting_mode,
            "launch_id": self.launch_id,
            "data_root_fingerprint": self.data_root_fingerprint,
            "shutdown_timeout_seconds": self.shutdown_timeout_seconds,
        }


@dataclass(slots=True)
class HostContext:
    """Identity and exclusive profile lease owned by a host process."""

    identity: HostIdentity
    profile_lock: ProfileLock

    def release(self) -> None:
        """Release the profile lease during safe process cleanup."""
        self.profile_lock.release()


def _application_version() -> str:
    try:
        version = importlib.metadata.version("apex")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("APEX distribution version metadata is unavailable.") from exc
    if not version or any(ord(char) < 32 for char in version):
        raise RuntimeError("APEX distribution version metadata is invalid.")
    return version


def _build_id(paths: RuntimePaths, *, frozen: bool, version: str) -> str:
    if not frozen:
        return f"source:{version}"

    manifest_path = paths.resource_root / "build-info.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        value = manifest["build_id"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Frozen APEX build manifest is missing or invalid.") from exc
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or "/" in value
        or "\\" in value
    ):
        raise RuntimeError("Frozen APEX build manifest is missing or invalid.")
    if any(ord(char) < 32 for char in value):
        raise RuntimeError("Frozen APEX build manifest is missing or invalid.")
    return value


def create_host_identity(
    paths: RuntimePaths,
    *,
    hosting_mode: HostingMode = "standalone",
    launch_id: str | None = None,
    frozen: bool | None = None,
    shutdown_timeout_seconds: int = SHUTDOWN_TIMEOUT_SECONDS,
) -> HostIdentity:
    """Create an identity without exposing the selected profile path."""
    if hosting_mode not in ("standalone", "managed"):
        raise ValueError("hosting_mode must be standalone or managed.")
    if hosting_mode == "managed" and launch_id is None:
        raise ValueError("managed hosting requires a launch_id UUID.")
    if hosting_mode == "standalone" and launch_id is not None:
        raise ValueError("standalone hosting must not have a launch_id.")
    if (
        isinstance(shutdown_timeout_seconds, bool)
        or not isinstance(shutdown_timeout_seconds, int)
        or not 1 <= shutdown_timeout_seconds <= 3600
    ):
        raise ValueError("shutdown_timeout_seconds must be between 1 and 3600 seconds.")
    if launch_id is not None:
        try:
            launch_id = str(uuid.UUID(launch_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("launch_id must be a UUID or None.") from exc
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    data_root = paths.data_root.expanduser().resolve(strict=False)
    normalized_root = os.path.normcase(str(data_root))
    fingerprint = hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()
    version = _application_version()
    return HostIdentity(
        app_id="apex",
        app_version=version,
        build_id=_build_id(paths, frozen=is_frozen, version=version),
        instance_id=str(uuid.uuid4()),
        pid=os.getpid(),
        hosting_mode=hosting_mode,
        launch_id=launch_id,
        data_root_fingerprint=fingerprint,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )


def create_host_context(
    paths: RuntimePaths,
    *,
    hosting_mode: HostingMode = "standalone",
    launch_id: str | None = None,
    frozen: bool | None = None,
    shutdown_timeout_seconds: int = SHUTDOWN_TIMEOUT_SECONDS,
) -> HostContext:
    """Acquire the profile lease before constructing runtime identity."""
    from core.data_import.guard import refuse_pending_import

    refuse_pending_import(paths.data_root)
    lease = ProfileLock(paths.data_root)
    lease.acquire()
    try:
        identity = create_host_identity(
            paths,
            hosting_mode=hosting_mode,
            launch_id=launch_id,
            frozen=frozen,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
    except BaseException:
        lease.release()
        raise
    return HostContext(identity=identity, profile_lock=lease)


__all__ = [
    "HostContext",
    "HostIdentity",
    "HostingMode",
    "SHUTDOWN_TIMEOUT_SECONDS",
    "create_host_context",
    "create_host_identity",
]
