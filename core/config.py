"""Application configuration loaded from ``config.json`` (user preferences only).

API keys and secrets remain in environment variables, not in this module.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv

__all__ = [
    "CONFIG_PATH",
    "CUSTOM_BROWSER_PATH",
    "ENV_PATH",
    "FEATURE_CALENDAR",
    "FEATURE_EMAIL",
    "FEATURE_NEWS",
    "FEATURE_SPORTS",
    "FEATURE_WEATHER",
    "GOOGLE_VOICE_ID",
    "INWORLD_VOICE_ID",
    "PRIMARY_TTS",
    "PROJECT_ROOT",
    "SYSTEM_PROMPT",
    "load_feature_flags",
    "load_module_flags",
]

_LOGGER = logging.getLogger(__name__)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "config.json"
ENV_PATH: Final[Path] = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_PATH)

_FEATURE_KEYS: Final[tuple[str, ...]] = (
    "weather",
    "sports",
    "news",
    "email",
    "calendar",
)

_MODULE_KEYS: Final[tuple[str, ...]] = (
    "football",
    "f1",
)

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
        _CONFIG_DATA: dict[str, Any] = json.load(config_file)
    if not isinstance(_CONFIG_DATA, dict):
        _LOGGER.warning("Config root must be a JSON object; using defaults.")
        _CONFIG_DATA = {}
except FileNotFoundError:
    _CONFIG_DATA = {}
except (OSError, json.JSONDecodeError) as exc:
    _LOGGER.warning("Unable to load config from %s: %s", CONFIG_PATH, exc)
    _CONFIG_DATA = {}

_DEFAULT_SYSTEM_PROMPT: Final[str] = (
    "You are a helpful system assistant. Summarize the following data into a clean, "
    "concise audio briefing under 75 words. Do not use emojis or markdown."
)
_configured_prompt = _CONFIG_DATA.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
if isinstance(_configured_prompt, str):
    SYSTEM_PROMPT: Final[str] = _configured_prompt
else:
    _LOGGER.warning("Config key 'system_prompt' must be a string; using default.")
    SYSTEM_PROMPT = _DEFAULT_SYSTEM_PROMPT

tts_settings = _CONFIG_DATA.get("tts_settings", {})
PRIMARY_TTS: Final[str] = tts_settings.get("primary_tts", "pyttsx3")
INWORLD_VOICE_ID: Final[str] = tts_settings.get("inworld_voice_id", "")
GOOGLE_VOICE_ID: Final[str] = tts_settings.get("google_voice_id", "")
CUSTOM_BROWSER_PATH: Final[str] = os.getenv("CUSTOM_BROWSER_PATH", "")


def _all_features_false() -> dict[str, bool]:
    """Return a map of every known feature key set to ``False``."""
    return dict.fromkeys(_FEATURE_KEYS, False)


def load_feature_flags() -> dict[str, bool]:
    """Load feature toggles from module-level ``_CONFIG_DATA``."""
    result = _all_features_false()
    features = _CONFIG_DATA.get("features")
    if not isinstance(features, dict):
        if features is not None:
            _LOGGER.warning('Config key "features" must be a JSON object.')
        return result

    for key in _FEATURE_KEYS:
        value = features.get(key)
        if isinstance(value, bool):
            result[key] = value
        elif value is not None:
            _LOGGER.warning('Feature %r must be a boolean; ignoring invalid value.', key)
    return result

def _all_modules_false() -> dict[str, bool]:
    """Return a map of every known module key set to ``False``."""
    return dict.fromkeys(_MODULE_KEYS, False)

def load_module_flags() -> dict[str, bool]:
    """Load granular sub-module toggles from module-level ``_CONFIG_DATA``."""
    result = _all_modules_false()
    modules = _CONFIG_DATA.get("modules")
    if not isinstance(modules, dict):
        if modules is not None:
            _LOGGER.warning('Config key "modules" must be a JSON object.')
        return result

    for key in _MODULE_KEYS:
        value = modules.get(key)
        if isinstance(value, bool):
            result[key] = value
        elif value is not None:
            _LOGGER.warning('Module %r must be a boolean; ignoring invalid value.', key)
    return result


_feature_map = load_feature_flags()

FEATURE_WEATHER: Final[bool] = bool(_feature_map.get("weather", False))
FEATURE_SPORTS: Final[bool] = bool(_feature_map.get("sports", False))
FEATURE_NEWS: Final[bool] = bool(_feature_map.get("news", False))
FEATURE_EMAIL: Final[bool] = bool(_feature_map.get("email", False))
FEATURE_CALENDAR: Final[bool] = bool(_feature_map.get("calendar", False))

_module_map = load_module_flags()

MODULE_FOOTBALL: Final[bool] = bool(_module_map.get("football", False))
MODULE_F1: Final[bool] = bool(_module_map.get("f1", False))
