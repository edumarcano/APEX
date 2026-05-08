"""Application configuration loaded from ``config.json`` (user preferences only).

API keys and secrets remain in environment variables, not in this module.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

__all__ = [
    "FEATURE_CALENDAR",
    "FEATURE_EMAIL",
    "FEATURE_NEWS",
    "FEATURE_SPORTS",
    "FEATURE_WEATHER",
    "load_feature_flags",
]

_LOGGER = logging.getLogger(__name__)

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent
_DEFAULT_CONFIG_PATH: Final[Path] = _PROJECT_ROOT / "config.json"

_FEATURE_KEYS: Final[tuple[str, ...]] = (
    "weather",
    "sports",
    "news",
    "email",
    "calendar",
)


def _all_features_false() -> dict[str, bool]:
    """Return a map of every known feature key set to ``False``."""
    return dict.fromkeys(_FEATURE_KEYS, False)


def load_feature_flags(config_path: Path | None = None) -> dict[str, bool]:
    """Load feature toggles from ``config.json``.

    Looks beside this module (project root) unless ``config_path`` is given.

    If the file is missing, unreadable, invalid JSON, or structurally wrong,
    returns all ``False`` so callers avoid crashes. Individual keys that are
    absent or non-boolean are treated as ``False``.

    Args:
        config_path: Optional explicit path to a JSON file. Defaults to
            ``<project_root>/config.json``.

    Returns:
        Mapping of internal feature names to boolean enabled flags.
    """
    path = _DEFAULT_CONFIG_PATH if config_path is None else Path(config_path)
    path = path.expanduser().resolve()
    result = _all_features_false()

    if not path.is_file():
        _LOGGER.warning("Config file not found at %s; feature flags default to False.", path)
        return result

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        _LOGGER.warning("Could not read config file %s: %s", path, exc)
        return result

    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        _LOGGER.warning("Invalid JSON in %s: %s", path, exc)
        return result

    if not isinstance(data, dict):
        _LOGGER.warning("Config root must be a JSON object; got %s.", type(data).__name__)
        return result

    features = data.get("features")
    if not isinstance(features, dict):
        _LOGGER.warning('Config must contain a JSON object at key "features".')
        return result

    for key in _FEATURE_KEYS:
        value = features.get(key)
        if isinstance(value, bool):
            result[key] = value
        elif value is not None:
            _LOGGER.warning('Feature %r must be a boolean; ignoring invalid value.', key)

    return result


_feature_map = load_feature_flags()

FEATURE_WEATHER: Final[bool] = _feature_map["weather"]
FEATURE_SPORTS: Final[bool] = _feature_map["sports"]
FEATURE_NEWS: Final[bool] = _feature_map["news"]
FEATURE_EMAIL: Final[bool] = _feature_map["email"]
FEATURE_CALENDAR: Final[bool] = _feature_map["calendar"]
