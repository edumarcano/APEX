"""Typed telemetry snapshot package."""

from __future__ import annotations

from core.telemetry.models import (
    FRESHNESS_WINDOW_SECONDS,
    PreflightBlocker,
    PreflightRequest,
    PreflightResponse,
    PreflightWarning,
    TelemetryModuleEntry,
    TelemetryRefreshRequest,
    TelemetrySnapshot,
)

__all__ = [
    "FRESHNESS_WINDOW_SECONDS",
    "PreflightBlocker",
    "PreflightRequest",
    "PreflightResponse",
    "PreflightWarning",
    "RefreshInProgressError",
    "TelemetryModuleEntry",
    "TelemetryRefreshRequest",
    "TelemetryService",
    "TelemetrySnapshot",
    "evaluate_preflight",
    "get_telemetry_service",
    "reset_telemetry_service_for_tests",
]


def __getattr__(name: str):
    """Lazy exports to avoid circular imports with core.api."""
    if name in {
        "RefreshInProgressError",
        "TelemetryService",
        "get_telemetry_service",
        "reset_telemetry_service_for_tests",
    }:
        from core.telemetry import service as _service

        return getattr(_service, name)
    if name == "evaluate_preflight":
        from core.telemetry.preflight import evaluate_preflight

        return evaluate_preflight
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
