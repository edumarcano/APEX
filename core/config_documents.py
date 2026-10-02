"""File-only readers and merge helpers for APEX configuration documents.

This module intentionally has no dependency on application configuration or
Runtime Settings normalization, so early import paths can use it safely.
"""

from __future__ import annotations

import json
import copy
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def read_json_object(path: Path, *, missing_ok: bool = True) -> dict[str, Any]:
    """Read one JSON object, optionally treating an absent layer as empty."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration root in {path} must be a JSON object")
    return payload


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a recursive JSON-object merge without mutating either input."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config_documents(
    defaults_path: Path,
    operator_path: Path | None = None,
    local_path: Path | None = None,
) -> dict[str, Any]:
    """Load defaults, separate operator config, then local runtime overrides."""
    merged = _read_layer(defaults_path)
    if operator_path is not None and operator_path != defaults_path:
        merged = deep_merge(merged, _read_layer(operator_path))
    if local_path is not None:
        merged = deep_merge(merged, _read_layer(local_path))
    return merged


def _read_layer(path: Path) -> dict[str, Any]:
    try:
        return read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Unable to load configuration from %s: %s; ignoring layer.", path, exc)
        return {}


__all__ = ["deep_merge", "load_config_documents", "read_json_object"]
