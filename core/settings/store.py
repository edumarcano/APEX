"""Process-wide runtime settings store with transactional persistence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from core.settings.models import RuntimeSettingsSnapshot, SettingsPatch
from core.settings.normalize import (
    apply_patch_to_snapshot,
    normalize_layer,
    patch_to_ondisk,
    recursive_overlay,
    snapshot_from_merged,
)

_LOGGER = logging.getLogger(__name__)

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG_PATH: Path = _PROJECT_ROOT / "config.json"
_DEFAULT_LOCAL_CONFIG_PATH: Path = _PROJECT_ROOT / "config.local.json"

_REPLACE_MAX_ATTEMPTS = 3
_REPLACE_BACKOFF_SECONDS = (0.05, 0.1, 0.2)


class SettingsPersistenceError(RuntimeError):
    """Raised when a settings patch cannot be persisted atomically."""


class RuntimeSettingsStore:
    """
    Thread-safe settings store.

    Loads ``config.json`` then overlays ``config.local.json``, publishes an
    immutable snapshot, and persists dirty patches transactionally.
    """

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        local_config_path: Path | None = None,
    ) -> None:
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._local_config_path = local_config_path or _DEFAULT_LOCAL_CONFIG_PATH
        self._lock = threading.RLock()
        self._snapshot: RuntimeSettingsSnapshot = RuntimeSettingsSnapshot()
        self._base_ondisk: dict[str, Any] = {}
        self._local_ondisk: dict[str, Any] = {}
        self._load_warning: str | None = None
        self._local_file_present = False
        self.reload()

    @property
    def load_warning(self) -> str | None:
        """Diagnostic warning from the most recent load, if any."""
        with self._lock:
            return self._load_warning

    @property
    def local_file_present(self) -> bool:
        """Whether ``config.local.json`` existed at the last successful load/write."""
        with self._lock:
            return self._local_file_present

    def get_snapshot(self) -> RuntimeSettingsSnapshot:
        """Return the published immutable snapshot."""
        with self._lock:
            return self._snapshot

    def reload(self) -> RuntimeSettingsSnapshot:
        """Reload base and local layers, overlay, validate, and publish."""
        with self._lock:
            warning: str | None = None
            base_raw, base_warning = self._load_json_file(
                self._config_path, missing_ok=True
            )
            if base_warning:
                warning = base_warning
                base_raw = {}

            base_normalized = normalize_layer(base_raw, layer_name="config.json")
            self._base_ondisk = base_normalized

            local_normalized: dict[str, Any] = {}
            local_present = self._local_config_path.is_file()
            if local_present:
                local_raw, local_warning = self._load_json_file(
                    self._local_config_path, missing_ok=False
                )
                if local_warning:
                    warning = local_warning
                    local_normalized = {}
                    local_present = False
                    _LOGGER.warning(
                        "Discarding config.local.json and using tracked defaults: %s",
                        local_warning,
                    )
                else:
                    validation_errors: list[str] = []
                    local_normalized = normalize_layer(
                        local_raw,
                        layer_name="config.local.json",
                        validation_errors=validation_errors,
                    )
                    if validation_errors:
                        warning = (
                            "Invalid config.local.json; using tracked defaults: "
                            + "; ".join(validation_errors)
                        )
                        local_normalized = {}
                        local_present = False
                        _LOGGER.warning(warning)
            else:
                local_normalized = {}

            merged = recursive_overlay(base_normalized, local_normalized)
            snapshot = snapshot_from_merged(merged)

            self._local_ondisk = local_normalized
            self._local_file_present = local_present and bool(
                self._local_config_path.is_file()
            )
            self._load_warning = warning
            self._snapshot = snapshot
            return snapshot

    def apply_patch(self, patch: SettingsPatch) -> RuntimeSettingsSnapshot:
        """
        Merge dirty fields, validate, persist to ``config.local.json``, then publish.

        On permanent persistence failure the prior snapshot remains active.
        """
        with self._lock:
            current = self._snapshot
            merged_snapshot = apply_patch_to_snapshot(current, patch)

            patch_ondisk = patch_to_ondisk(patch)
            if not patch_ondisk:
                return current

            next_local = recursive_overlay(self._local_ondisk, patch_ondisk)

            prior_snapshot = self._snapshot
            prior_local = copy_dict(self._local_ondisk)
            prior_present = self._local_file_present

            try:
                self._atomic_write_local(next_local)
            except SettingsPersistenceError:
                self._snapshot = prior_snapshot
                self._local_ondisk = prior_local
                self._local_file_present = prior_present
                raise

            self._local_ondisk = next_local
            self._local_file_present = True
            self._snapshot = merged_snapshot
            return merged_snapshot

    def _load_json_file(
        self, path: Path, *, missing_ok: bool
    ) -> tuple[dict[str, Any], str | None]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            if missing_ok:
                return {}, None
            return {}, f"Missing configuration file: {path}"
        except (OSError, json.JSONDecodeError) as exc:
            message = f"Unable to load configuration from {path}: {exc}"
            _LOGGER.warning(message)
            return {}, message

        if not isinstance(data, dict):
            message = f"Configuration root in {path} must be a JSON object"
            _LOGGER.warning(message)
            return {}, message
        return data, None

    def _atomic_write_local(self, payload: dict[str, Any]) -> None:
        directory = self._local_config_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd: int | None = None
        temp_path: Path | None = None
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=".config.local.",
                suffix=".tmp",
                dir=str(directory),
            )
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            last_error: Exception | None = None
            for attempt in range(_REPLACE_MAX_ATTEMPTS):
                try:
                    os.replace(temp_path, self._local_config_path)
                    temp_path = None
                    return
                except PermissionError as exc:
                    last_error = exc
                    if attempt < _REPLACE_MAX_ATTEMPTS - 1:
                        time.sleep(_REPLACE_BACKOFF_SECONDS[attempt])
                        continue
                    break
                except OSError as exc:
                    last_error = exc
                    break

            raise SettingsPersistenceError(
                "Failed to persist settings to "
                f"{self._local_config_path}: {last_error}"
            ) from last_error
        except SettingsPersistenceError:
            raise
        except OSError as exc:
            raise SettingsPersistenceError(
                f"Failed to persist settings to {self._local_config_path}: {exc}"
            ) from exc
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def copy_dict(value: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-ish copy of a JSON-compatible dict."""
    return json.loads(json.dumps(value))


_STORE: RuntimeSettingsStore | None = None
_STORE_LOCK = threading.Lock()


def get_settings_store(
    *,
    config_path: Path | None = None,
    local_config_path: Path | None = None,
    force_new: bool = False,
) -> RuntimeSettingsStore:
    """
    Return the process-wide settings store.

    When ``force_new`` is true, or custom paths are provided, construct a fresh
    store (used by tests). Otherwise reuse the singleton initialized for the
    default project paths.
    """
    global _STORE
    if force_new or config_path is not None or local_config_path is not None:
        return RuntimeSettingsStore(
            config_path=config_path,
            local_config_path=local_config_path,
        )

    with _STORE_LOCK:
        if _STORE is None:
            _STORE = RuntimeSettingsStore()
        return _STORE


def reset_settings_store_for_tests() -> None:
    """Clear the process singleton (test helper)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = None
