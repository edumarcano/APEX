"""Resolve immutable resource and writable data locations for an APEX run.

Path resolution is deliberately side-effect free. Callers that need to read
operator environment files should first call :func:`initialize_environment`.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Mapping

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    """Paths for immutable application resources and mutable user data."""

    resource_root: Path
    data_root: Path

    @property
    def defaults_config_path(self) -> Path:
        return self.resource_root / "config.json"

    @property
    def operator_config_path(self) -> Path:
        return self.data_root / "config.json"

    @property
    def local_config_path(self) -> Path:
        return self.data_root / "config.local.json"

    @property
    def env_path(self) -> Path:
        return self.data_root / ".env"

    @property
    def database_path(self) -> Path:
        return self.data_root / "apex_memory.db"

    @property
    def google_credentials_path(self) -> Path:
        return self.data_root / "credentials.json"

    @property
    def google_token_path(self) -> Path:
        return self.data_root / "token.json"

    @property
    def market_cache_path(self) -> Path:
        return self.data_root / "clients" / ".market_cache.json"

    @property
    def f1_cache_path(self) -> Path:
        return self.data_root / "clients" / ".f1_cache.json"

    @property
    def football_cache_path(self) -> Path:
        return self.data_root / "clients" / ".football_cache.json"

    @property
    def fastembed_cache_dir(self) -> Path:
        return self.data_root / "weights" / "fastembed"

    @property
    def kokoro_weights_dir(self) -> Path:
        return self.data_root / "core" / "weights" / "kokoro"

    @property
    def demo_telemetry_path(self) -> Path:
        return self.resource_root / "core" / "mock" / "telemetry.json"

    @property
    def demo_assistant_path(self) -> Path:
        return self.resource_root / "core" / "mock" / "assistant.json"


def resolve_runtime_paths(
    environ: Mapping[str, str] | None = None,
    *,
    resource_root: Path | str | None = None,
    frozen: bool | None = None,
    executable_path: Path | str | None = None,
) -> RuntimePaths:
    """Resolve paths without reading or creating files.

    ``APEX_DATA_DIR`` is an explicit absolute override in both source and
    frozen runs. A frozen default requires ``LOCALAPPDATA``. Relative or
    otherwise invalid nonempty selectors fail closed before any writes.
    """
    env = os.environ if environ is None else environ
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = Path(executable_path or sys.executable).expanduser().resolve()

    if resource_root is not None:
        resources = Path(resource_root).expanduser().resolve()
    elif is_frozen:
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not bundle_root:
            raise RuntimeError("Frozen APEX runtime is missing its resource directory.")
        resources = Path(bundle_root).resolve()
    else:
        resources = Path(__file__).resolve().parents[1]

    override = env.get("APEX_DATA_DIR")
    if override is not None and override.strip():
        raw_data = override.strip().strip("'\"")
        data = Path(raw_data).expanduser()
        if not data.is_absolute():
            raise ValueError("APEX_DATA_DIR must be an absolute path when set.")
        data = data.resolve()
    elif is_frozen:
        local_app_data = env.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise RuntimeError(
                "LOCALAPPDATA is required to select the default frozen APEX data directory."
            )
        base = Path(local_app_data).expanduser()
        if not base.is_absolute():
            raise ValueError("LOCALAPPDATA must be an absolute path for frozen APEX.")
        data = (base / "APEX").resolve()
    else:
        data = resources

    if is_frozen:
        _reject_installation_data(data, resources, executable.parent)
    return RuntimePaths(resource_root=resources, data_root=data)


def _reject_installation_data(
    data_root: Path, resource_root: Path, executable_dir: Path | None
) -> None:
    for label, protected in (("resource", resource_root), ("installation", executable_dir)):
        if protected is None:
            continue
        try:
            data_root.relative_to(protected)
        except ValueError:
            continue
        raise ValueError(
            f"APEX data directory cannot be inside the frozen {label} directory: {protected}"
        )


_initialization_lock = Lock()
_environment_initialized = False


def initialize_environment() -> RuntimePaths:
    """Load the selected profile's .env once, without dotenv discovery."""
    global _environment_initialized
    paths = get_runtime_paths()
    if _environment_initialized:
        return paths
    with _initialization_lock:
        if not _environment_initialized:
            load_dotenv(dotenv_path=paths.env_path, override=False)
            _environment_initialized = True
    return paths


@lru_cache(maxsize=1)
def get_runtime_paths() -> RuntimePaths:
    """Return the process-wide, cached runtime profile."""
    return resolve_runtime_paths()


__all__ = ["RuntimePaths", "get_runtime_paths", "initialize_environment", "resolve_runtime_paths"]
