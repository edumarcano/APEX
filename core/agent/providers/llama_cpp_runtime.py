"""Resolved llama.cpp runtime settings from the live settings snapshot."""

from __future__ import annotations

from core.settings.models import LlamaCppSettings
from core.settings.store import get_settings_store


def get_llama_cpp_runtime_settings() -> LlamaCppSettings:
    """Return the current resolved llama.cpp enablement and router host."""
    return get_settings_store().get_snapshot().llama_cpp


def get_llama_cpp_host() -> str:
    """Return the configured loopback llama.cpp router base URL."""
    return get_llama_cpp_runtime_settings().host


def is_llama_cpp_enabled() -> bool:
    """Return whether llama.cpp local inference is enabled in runtime settings."""
    return get_llama_cpp_runtime_settings().enabled
