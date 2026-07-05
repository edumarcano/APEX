"""Application configuration loaded from ``config.json`` (user preferences only).

API keys and secrets remain in environment variables, not in this module.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Final, Literal, cast

from dotenv import load_dotenv

__all__ = [
    "AGENT_MAX_TOOL_CALLS",
    "AGENT_MAX_TURNS",
    "AGENT_SYSTEM_PROMPT",
    "DEFAULT_AGENT_SYSTEM_PROMPT",
    "DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT",
    "LOCAL_AGENT_SYSTEM_PROMPT",
    "ASK_APEX_ENABLED",
    "CONFIG_PATH",
    "DEFAULT_CLOUD_PROFILE",
    "MAX_SESSION_MESSAGES",
    "ACINONYX_CPU_LIMIT",
    "ACINONYX_RAM_LIMIT",
    "LYNX_CPU_LIMIT",
    "LYNX_RAM_LIMIT",
    "NEOFELIS_CPU_LIMIT",
    "NEOFELIS_RAM_LIMIT",
    "OLLAMA_ENABLED",
    "OLLAMA_HOST",
    "OLLAMA_IDLE_UNLOAD_MINUTES",
    "OLLAMA_MANUAL_UNLOAD_ENABLED",
    "OLLAMA_SINGLE_LOADED_MODEL",
    "CUSTOM_BROWSER_PATH",
    "DEMO_MODE",
    "DEMO_TTS",
    "DEV_AI_SYNTHESIS",
    "DEV_TTS_PLAYBACK",
    "ENABLE_STARTUP_GATE",
    "ENV_PATH",
    "FEATURE_CALENDAR",
    "FEATURE_EMAIL",
    "FEATURE_NEWS",
    "FEATURE_SPORTS",
    "FEATURE_WEATHER",
    "PRIMARY_TTS",
    "PROJECT_ROOT",
    "SYSTEM_PROMPT",
    "VOICE_GENDER",
    "is_dev_mode",
    "load_feature_flags",
    "load_module_flags",
]

_LOGGER = logging.getLogger(__name__)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "config.json"
ENV_PATH: Final[Path] = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_PATH)

_TRUTHY_ENV_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_FALSY_ENV_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})
_VALID_DEV_AI_SYNTHESIS: Final[frozenset[str]] = frozenset({"slm", "llm", "raw"})
_VALID_DEV_TTS_PLAYBACK: Final[frozenset[str]] = frozenset({"pyttsx3", "google", "kokoro"})
DevAiSynthesisMode = Literal["slm", "llm", "raw"]
DevTtsPlaybackMode = Literal["pyttsx3", "google", "kokoro"]


def _parse_env_bool(raw: str | None, *, key: str, default: bool) -> bool:
    """
    Normalize an environment string into a boolean.

    Strips whitespace and optional surrounding quotes. Unknown
    values log a warning and return ``default``.
    """
    if raw is None:
        return default

    normalized = raw.strip().lower().strip("'\"")
    if normalized in _TRUTHY_ENV_VALUES:
        return True
    if normalized in _FALSY_ENV_VALUES:
        return False

    _LOGGER.warning(
        "Invalid %s=%r; using default %s.",
        key,
        raw,
        default,
    )
    return default


def is_dev_mode() -> bool:
    """Return whether unified development mode is active (``DEV_MODE=true``)."""
    return _parse_env_bool(os.getenv("DEV_MODE"), key="DEV_MODE", default=False)


def _parse_dev_ai_synthesis(raw: str | None) -> DevAiSynthesisMode:
    """
    Normalize ``DEV_AI_SYNTHESIS`` for development-mode briefing routing.

    Defaults to ``raw`` when unset. Malformed values log a warning and fall
    back to ``raw``.
    """
    if raw is None:
        return "raw"

    normalized = raw.strip().lower().strip("'\"")
    if normalized in _VALID_DEV_AI_SYNTHESIS:
        return cast(DevAiSynthesisMode, normalized)

    _LOGGER.warning(
        "Invalid DEV_AI_SYNTHESIS=%r; using default raw.",
        raw,
    )
    return "raw"


def _parse_dev_tts_playback(raw: str | None) -> DevTtsPlaybackMode:
    """
    Normalize ``DEV_TTS_PLAYBACK`` for development-mode TTS routing.

    Defaults to ``pyttsx3`` when unset. Malformed values log a warning and fall
    back to ``pyttsx3``.
    """
    if raw is None:
        return "pyttsx3"

    normalized = raw.strip().lower().strip("'\"")
    if normalized in _VALID_DEV_TTS_PLAYBACK:
        return cast(DevTtsPlaybackMode, normalized)

    _LOGGER.warning(
        "Invalid DEV_TTS_PLAYBACK=%r; using default pyttsx3.",
        raw,
    )
    return "pyttsx3"


DEV_AI_SYNTHESIS: Final[DevAiSynthesisMode] = _parse_dev_ai_synthesis(
    os.getenv("DEV_AI_SYNTHESIS", "raw"),
)

DEV_TTS_PLAYBACK: Final[DevTtsPlaybackMode] = _parse_dev_tts_playback(
    os.getenv("DEV_TTS_PLAYBACK"),
)

DEMO_MODE: Final[bool] = _parse_env_bool(
    os.getenv("DEMO_MODE"),
    key="DEMO_MODE",
    default=False,
)

DEMO_TTS: Final[DevTtsPlaybackMode] = _parse_dev_tts_playback(
    os.getenv("DEMO_TTS"),
)

ENABLE_STARTUP_GATE: Final[bool] = _parse_env_bool(
    os.getenv("ENABLE_STARTUP_GATE"),
    key="ENABLE_STARTUP_GATE",
    default=True,
)


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
DEFAULT_AGENT_SYSTEM_PROMPT: Final[str] = (
    "You are a helpful cloud operations assistant. Answer direct questions "
    "using available tools when live data is required. Be concise, "
    "authoritative, and operational."
)
DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT: Final[str] = (
    "You are a helpful local operations assistant. Answer direct questions "
    "using available tools when live data is required. Be concise, "
    "authoritative, and operational."
)
_configured_prompt = _CONFIG_DATA.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
if isinstance(_configured_prompt, str):
    SYSTEM_PROMPT: Final[str] = _configured_prompt
else:
    _LOGGER.warning("Config key 'system_prompt' must be a string; using default.")
    SYSTEM_PROMPT = _DEFAULT_SYSTEM_PROMPT

_configured_agent_prompt = _CONFIG_DATA.get(
    "agent_system_prompt", DEFAULT_AGENT_SYSTEM_PROMPT
)
if isinstance(_configured_agent_prompt, str):
    AGENT_SYSTEM_PROMPT: Final[str] = _configured_agent_prompt
else:
    _LOGGER.warning("Config key 'agent_system_prompt' must be a string; using default.")
    AGENT_SYSTEM_PROMPT = DEFAULT_AGENT_SYSTEM_PROMPT

_configured_local_agent_prompt = _CONFIG_DATA.get(
    "local_agent_system_prompt", DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT
)
if isinstance(_configured_local_agent_prompt, str):
    LOCAL_AGENT_SYSTEM_PROMPT: Final[str] = _configured_local_agent_prompt
else:
    _LOGGER.warning(
        "Config key 'local_agent_system_prompt' must be a string; using default."
    )
    LOCAL_AGENT_SYSTEM_PROMPT = DEFAULT_LOCAL_AGENT_SYSTEM_PROMPT

tts_settings = _CONFIG_DATA.get("tts_settings", {})
PRIMARY_TTS: Final[str] = tts_settings.get("primary_tts", "pyttsx3")
VOICE_GENDER: Final[str] = tts_settings.get("voice_gender", "female")
CUSTOM_BROWSER_PATH: Final[str] = os.getenv("CUSTOM_BROWSER_PATH", "")


def load_feature_flags() -> dict[str, bool]:
    """Load feature toggles from module-level ``_CONFIG_DATA``."""
    result = dict.fromkeys(_FEATURE_KEYS, False)
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


def load_module_flags() -> dict[str, bool]:
    """Load granular sub-module toggles from module-level ``_CONFIG_DATA``."""
    result = dict.fromkeys(_MODULE_KEYS, False)
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

_VALID_CLOUD_PROFILES: Final[frozenset[str]] = frozenset({"comet", "nova", "pulsar"})


def _parse_config_bool(raw: Any, *, key: str, default: bool) -> bool:
    """Coerce a config value to bool with logging on invalid input."""
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    _LOGGER.warning("Config key %r must be a boolean; using default %s.", key, default)
    return default


def _parse_config_int(
    raw: Any,
    *,
    key: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    """Coerce a config value to int, clamp to bounds, and log on invalid input."""
    if isinstance(raw, bool):
        _LOGGER.warning("Config key %r must be an integer; using default %s.", key, default)
        return default
    if isinstance(raw, int):
        coerced = raw
    elif isinstance(raw, float) and raw.is_integer():
        coerced = int(raw)
    elif isinstance(raw, str):
        try:
            coerced = int(raw.strip())
        except ValueError:
            _LOGGER.warning("Config key %r must be an integer; using default %s.", key, default)
            return default
    else:
        _LOGGER.warning("Config key %r must be an integer; using default %s.", key, default)
        return default

    if coerced < min_value:
        _LOGGER.warning(
            "Config key %r=%s below minimum %s; clamping.",
            key,
            coerced,
            min_value,
        )
        return min_value
    if coerced > max_value:
        _LOGGER.warning(
            "Config key %r=%s above maximum %s; clamping.",
            key,
            coerced,
            max_value,
        )
        return max_value
    return coerced


def _parse_config_float(
    raw: Any,
    *,
    key: str,
    default: float,
    min_value: float = 0.0,
    max_value: float = 100.0,
) -> float:
    """Coerce a config value to float, clamp to bounds, and log on invalid input."""
    if isinstance(raw, bool):
        _LOGGER.warning("Config key %r must be a float; using default %s.", key, default)
        return default
    if isinstance(raw, (int, float)):
        coerced = float(raw)
    elif isinstance(raw, str):
        try:
            coerced = float(raw.strip())
        except ValueError:
            _LOGGER.warning("Config key %r must be a float; using default %s.", key, default)
            return default
    else:
        _LOGGER.warning("Config key %r must be a float; using default %s.", key, default)
        return default

    if coerced < min_value:
        _LOGGER.warning(
            "Config key %r=%s below minimum %s; clamping.",
            key,
            coerced,
            min_value,
        )
        return min_value
    if coerced > max_value:
        _LOGGER.warning(
            "Config key %r=%s above maximum %s; clamping.",
            key,
            coerced,
            max_value,
        )
        return max_value
    return coerced


def _parse_resource_gate(
    gates: Any,
    *,
    profile: str,
    default_ram: float,
    default_cpu: float,
) -> tuple[float, float]:
    """Parse RAM and CPU percentage limits for a single Ollama profile gate."""
    if not isinstance(gates, dict):
        if gates is not None:
            _LOGGER.warning(
                'Config key "ollama.resource_gates.%s" must be a JSON object; using defaults.',
                profile,
            )
        return default_ram, default_cpu

    ram = _parse_config_float(
        gates.get("ram_limit"),
        key=f"ollama.resource_gates.{profile}.ram_limit",
        default=default_ram,
    )
    cpu = _parse_config_float(
        gates.get("cpu_limit"),
        key=f"ollama.resource_gates.{profile}.cpu_limit",
        default=default_cpu,
    )
    return ram, cpu


def _parse_cloud_profile(raw: Any, *, key: str, default: str) -> str:
    """Validate a cloud profile identifier against known Gemini tiers."""
    if not isinstance(raw, str):
        if raw is not None:
            _LOGGER.warning("Config key %r must be a string; using default %r.", key, default)
        return default

    normalized = raw.strip().lower()
    if normalized in _VALID_CLOUD_PROFILES:
        return normalized

    _LOGGER.warning(
        "Config key %r=%r is not in %s; using default %r.",
        key,
        raw,
        sorted(_VALID_CLOUD_PROFILES),
        default,
    )
    return default


try:
    _ask_apex_cfg = _CONFIG_DATA.get("ask_apex", {})
    if not isinstance(_ask_apex_cfg, dict):
        _LOGGER.warning('Config key "ask_apex" must be a JSON object; using defaults.')
        _ask_apex_cfg = {}

    ASK_APEX_ENABLED: Final[bool] = _parse_config_bool(
        _ask_apex_cfg.get("enabled"),
        key="ask_apex.enabled",
        default=True,
    )
    DEFAULT_CLOUD_PROFILE: Final[str] = _parse_cloud_profile(
        _ask_apex_cfg.get("default_cloud_profile"),
        key="ask_apex.default_cloud_profile",
        default="comet",
    )
    MAX_SESSION_MESSAGES: Final[int] = _parse_config_int(
        _ask_apex_cfg.get("max_session_messages"),
        key="ask_apex.max_session_messages",
        default=6,
        min_value=2,
        max_value=20,
    )
except Exception as exc:
    _LOGGER.warning("Unable to parse ask_apex config: %s; using defaults.", exc)
    ASK_APEX_ENABLED = True
    DEFAULT_CLOUD_PROFILE = "comet"
    MAX_SESSION_MESSAGES = 6

try:
    _gemini_cfg = _CONFIG_DATA.get("gemini", {})
    if not isinstance(_gemini_cfg, dict):
        _LOGGER.warning('Config key "gemini" must be a JSON object; using defaults.')
        _gemini_cfg = {}

    AGENT_MAX_TURNS: Final[int] = _parse_config_int(
        _gemini_cfg.get("agent_max_turns"),
        key="gemini.agent_max_turns",
        default=3,
        min_value=1,
        max_value=5,
    )
    AGENT_MAX_TOOL_CALLS: Final[int] = _parse_config_int(
        _gemini_cfg.get("agent_max_tool_calls"),
        key="gemini.agent_max_tool_calls",
        default=4,
        min_value=1,
        max_value=10,
    )
except Exception as exc:
    _LOGGER.warning("Unable to parse gemini config: %s; using defaults.", exc)
    AGENT_MAX_TURNS = 3
    AGENT_MAX_TOOL_CALLS = 4

_DEFAULT_LYNX_RAM: Final[float] = 88.0
_DEFAULT_LYNX_CPU: Final[float] = 95.0
_DEFAULT_ACINONYX_RAM: Final[float] = 78.0
_DEFAULT_ACINONYX_CPU: Final[float] = 90.0
_DEFAULT_NEOFELIS_RAM: Final[float] = 68.0
_DEFAULT_NEOFELIS_CPU: Final[float] = 85.0

try:
    _ollama_cfg = _CONFIG_DATA.get("ollama", {})
    if not isinstance(_ollama_cfg, dict):
        _LOGGER.warning('Config key "ollama" must be a JSON object; using defaults.')
        _ollama_cfg = {}

    OLLAMA_ENABLED: Final[bool] = _parse_config_bool(
        _ollama_cfg.get("enabled"),
        key="ollama.enabled",
        default=True,
    )
    _configured_host = _ollama_cfg.get("host", "http://localhost:11434")
    if isinstance(_configured_host, str) and _configured_host.strip():
        OLLAMA_HOST: Final[str] = _configured_host.strip()
    else:
        if _configured_host is not None:
            _LOGGER.warning(
                'Config key "ollama.host" must be a non-empty string; using default.'
            )
        OLLAMA_HOST = "http://localhost:11434"

    OLLAMA_IDLE_UNLOAD_MINUTES: Final[int] = _parse_config_int(
        _ollama_cfg.get("idle_unload_timeout_minutes"),
        key="ollama.idle_unload_timeout_minutes",
        default=5,
        min_value=1,
        max_value=60,
    )
    # Parsed for forward compatibility; ollama_lifecycle always enforces a
    # single loaded model regardless of this flag today.
    OLLAMA_SINGLE_LOADED_MODEL: Final[bool] = _parse_config_bool(
        _ollama_cfg.get("single_loaded_model"),
        key="ollama.single_loaded_model",
        default=True,
    )
    OLLAMA_MANUAL_UNLOAD_ENABLED: Final[bool] = _parse_config_bool(
        _ollama_cfg.get("manual_unload_enabled"),
        key="ollama.manual_unload_enabled",
        default=True,
    )

    _resource_gates = _ollama_cfg.get("resource_gates", {})
    if not isinstance(_resource_gates, dict):
        if _resource_gates is not None:
            _LOGGER.warning(
                'Config key "ollama.resource_gates" must be a JSON object; using defaults.'
            )
        _resource_gates = {}

    _lynx_ram, _lynx_cpu = _parse_resource_gate(
        _resource_gates.get("lynx"),
        profile="lynx",
        default_ram=_DEFAULT_LYNX_RAM,
        default_cpu=_DEFAULT_LYNX_CPU,
    )
    LYNX_RAM_LIMIT: Final[float] = _lynx_ram
    LYNX_CPU_LIMIT: Final[float] = _lynx_cpu

    _acinonyx_ram, _acinonyx_cpu = _parse_resource_gate(
        _resource_gates.get("acinonyx"),
        profile="acinonyx",
        default_ram=_DEFAULT_ACINONYX_RAM,
        default_cpu=_DEFAULT_ACINONYX_CPU,
    )
    ACINONYX_RAM_LIMIT: Final[float] = _acinonyx_ram
    ACINONYX_CPU_LIMIT: Final[float] = _acinonyx_cpu

    _neofelis_ram, _neofelis_cpu = _parse_resource_gate(
        _resource_gates.get("neofelis"),
        profile="neofelis",
        default_ram=_DEFAULT_NEOFELIS_RAM,
        default_cpu=_DEFAULT_NEOFELIS_CPU,
    )
    NEOFELIS_RAM_LIMIT: Final[float] = _neofelis_ram
    NEOFELIS_CPU_LIMIT: Final[float] = _neofelis_cpu
except Exception as exc:
    _LOGGER.warning("Unable to parse ollama config: %s; using defaults.", exc)
    OLLAMA_ENABLED = True
    OLLAMA_HOST = "http://localhost:11434"
    OLLAMA_IDLE_UNLOAD_MINUTES = 5
    OLLAMA_SINGLE_LOADED_MODEL = True
    OLLAMA_MANUAL_UNLOAD_ENABLED = True
    LYNX_RAM_LIMIT = _DEFAULT_LYNX_RAM
    LYNX_CPU_LIMIT = _DEFAULT_LYNX_CPU
    ACINONYX_RAM_LIMIT = _DEFAULT_ACINONYX_RAM
    ACINONYX_CPU_LIMIT = _DEFAULT_ACINONYX_CPU
    NEOFELIS_RAM_LIMIT = _DEFAULT_NEOFELIS_RAM
    NEOFELIS_CPU_LIMIT = _DEFAULT_NEOFELIS_CPU
