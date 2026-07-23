"""System, configuration, settings, status, diagnostics, and health routes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, status

from core import config, database, scanner
from core.api.models import PipelineStatusSnapshot
from core.api.state import global_pipeline_state
from core.config import DEMO_MODE, DEV_AI_SYNTHESIS, is_dev_mode
from core.settings import (
    SETTINGS_SCHEMA_VERSION,
    SettingsPatch,
    SettingsPersistenceError,
    SettingsResponse,
    get_settings_store,
)

router = APIRouter(tags=["system"])
_LOGGER = logging.getLogger(__name__)


@router.get("/")
def health_check() -> dict[str, Any]:
    """
    Return a minimal health payload for monitoring and readiness probes.
    """
    return {"status": "online", "system": "APEX"}


@router.get("/api/v1/health/live")
def liveness() -> dict[str, str]:
    """Return process liveness without checking dependencies."""
    return {"status": "live"}


@router.get("/api/v1/health/ready")
def readiness() -> dict[str, str]:
    """
    Verify configuration loading and a lightweight database query.

    Does not require optional external providers (connectors, OAuth, Ollama).
    """
    try:
        get_settings_store().get_snapshot()
    except Exception:
        _LOGGER.exception("Readiness failed: configuration unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration unavailable.",
        ) from None

    try:
        database.probe_db()
    except sqlite3.Error:
        _LOGGER.exception("Readiness failed: database unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable.",
        ) from None

    return {"status": "ready", "config": "ok", "database": "ok"}


@router.get("/api/v1/config")
def get_global_config() -> dict[str, Any]:
    """Expose global system configurations to the frontend HUD on boot."""
    snapshot = get_settings_store().get_snapshot()
    return {
        "default_profile": snapshot.assistant.default_profile,
        "ask_apex_enabled": snapshot.assistant.enabled,
        "market_enabled": snapshot.features.market,
        "max_session_messages": config.MAX_SESSION_MESSAGES,
        "dev_mode_active": is_dev_mode(),
        "demo_mode_active": DEMO_MODE,
        "synthesis_strategy": (
            "demo" if DEMO_MODE else DEV_AI_SYNTHESIS if is_dev_mode() else "cloud"
        ),
        "synthesis_profile": (
            None if DEMO_MODE or (is_dev_mode() and DEV_AI_SYNTHESIS == "raw") else
            "acinonyx" if is_dev_mode() and DEV_AI_SYNTHESIS == "local" else "comet"
        ),
        "briefing_default_mode": snapshot.briefing.default_mode,
        "voice_mode": snapshot.voice.mode,
    }


def _build_settings_response() -> SettingsResponse:
    """Assemble the public settings envelope from the runtime store."""
    store = get_settings_store()
    return SettingsResponse(
        schema_version=SETTINGS_SCHEMA_VERSION,
        settings=store.get_snapshot(),
        local_file_present=store.local_file_present,
        local_override_active=store.local_override_active,
        load_warning=store.load_warning,
        dev_mode_active=is_dev_mode(),
        demo_mode_active=DEMO_MODE,
    )


@router.get("/api/v1/settings", response_model=SettingsResponse)
def get_runtime_settings() -> SettingsResponse:
    """Return resolved editable settings and read-only runtime mode state."""
    return _build_settings_response()


@router.patch("/api/v1/settings", response_model=SettingsResponse)
def patch_runtime_settings(payload: SettingsPatch) -> SettingsResponse:
    """
    Merge dirty nested fields into the runtime settings store.

    Persists transactionally to ``config.local.json`` and publishes only after
    a successful write. Permanent persistence failures leave the active
    snapshot unchanged.
    """
    store = get_settings_store()
    dirty = payload.model_dump(exclude_none=True)
    if not dirty:
        return _build_settings_response()
    try:
        store.apply_patch(payload)
    except SettingsPersistenceError:
        _LOGGER.exception("Settings persistence failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Failed to persist settings to config.local.json. "
                "Active settings were not changed."
            ),
        ) from None
    return _build_settings_response()


@router.get("/api/v1/status", response_model=PipelineStatusSnapshot)
def get_pipeline_diagnostic_status() -> PipelineStatusSnapshot:
    """
    Diagnostic snapshot keyed off global_pipeline_state for operators and probes.
    """
    snapshot = global_pipeline_state.get_state()
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No active pipeline run. System is OFFLINE.",
        )
    return PipelineStatusSnapshot(**snapshot)


@router.get("/api/v1/diagnostics")
def get_system_diagnostics() -> dict[str, float]:
    """
    Hardware utilization snapshot for operators and HUD diagnostics panels.
    """
    return scanner.sample_system_vitals()
