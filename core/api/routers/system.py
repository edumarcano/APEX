"""System, configuration, settings, status, diagnostics, and health routes."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from core import config, database, scanner
from core.config import DEMO_MODE, is_dev_mode
from core.agent.catalog import (
    AGENT_SPECS,
    resolve_agent_display_name,
    resolve_model_selection,
)
from core.settings import (
    LlamaCppServerStatusResponse,
    SettingsPatch,
    SettingsPersistenceError,
    SettingsResponse,
    get_settings_store,
)
from core.context_vault.runtime import get_context_vault_runtime
from core.agent.local_runtime.coordinator import (
    end_local_runtime_transition,
    try_begin_local_runtime_transition,
)
from core.agent.local_runtime.registry import get_local_runtime_backend
from core.agent.providers.llama_cpp_supervisor import (
    LlamaCppManagedServerError,
    get_llama_cpp_server_supervisor,
)
from core.mcp import get_mcp_manager, load_mcp_config
from core.api.models import RuntimeIdentityResponse

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


@router.get("/api/v1/runtime", response_model=RuntimeIdentityResponse)
def runtime_identity(request: Request) -> RuntimeIdentityResponse:
    """Identify the host only after its application lifecycle is established."""
    context = getattr(request.app.state, "host_context", None)
    if context is None or not getattr(request.app.state, "lifecycle_established", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Runtime identity is unavailable until startup completes.",
        )
    return RuntimeIdentityResponse(**context.identity.as_dict())


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
    runtime, model_id, effort = resolve_model_selection(snapshot.ask_apex)
    return {
        "ask_apex_enabled": snapshot.ask_apex.enabled,
        "market_enabled": snapshot.features.market,
        "max_recent_conversation_messages": config.MAX_RECENT_CONVERSATION_MESSAGES,
        "dev_mode_active": is_dev_mode(),
        "demo_mode_active": DEMO_MODE,
        "voice_mode": snapshot.voice.mode,
        "cortex_initial_selection": {
            "runtime": runtime,
            "agent": "apex",
            "canonical_name": AGENT_SPECS["apex"].canonical_name,
            "display_name": resolve_agent_display_name(snapshot.agent_display_name),
            "model_id": model_id,
            "effort": effort,
        },
    }


def _build_settings_response() -> SettingsResponse:
    """Assemble the public settings envelope from the runtime store."""
    store = get_settings_store()
    return SettingsResponse(
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
async def patch_runtime_settings(
    payload: SettingsPatch, request: Request
) -> SettingsResponse:
    """
    Merge dirty nested fields into the runtime settings store.

    Persists transactionally to ``config.local.json`` and publishes only after
    a successful write. Permanent persistence failures leave the active
    snapshot unchanged.
    """
    store = get_settings_store()
    previous_llama = store.get_snapshot().llama_cpp
    dirty = payload.model_dump(exclude_none=True)
    if not dirty:
        return _build_settings_response()

    transition_held = False
    vault_transition_held = False
    vault_runtime = get_context_vault_runtime()
    if payload.llama_cpp is not None:
        acquired = await asyncio.to_thread(try_begin_local_runtime_transition)
        if not acquired:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot change llama.cpp settings while a local llama.cpp "
                    "Agent is active or loading."
                ),
            ) from None
        transition_held = True

    try:
        if vault_runtime is not None and (
            payload.context_vault is not None
            or (payload.ask_apex is not None and payload.ask_apex.sandbox_mode is not None)
        ):
            await vault_runtime.acquire_settings_transition()
            vault_transition_held = True
        if payload.llama_cpp is not None:
            try:
                proposed_snapshot = await asyncio.to_thread(store.preview_patch, payload)
            except SettingsPersistenceError as exc:
                _LOGGER.exception("Settings persistence failed")
                detail = str(exc)
                if "Refusing to persist invalid settings" in detail:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=detail,
                    ) from None
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=(
                        "Failed to persist settings to config.local.json. "
                        "Active settings were not changed."
                    ),
                ) from None
            supervisor = get_llama_cpp_server_supervisor()
            try:
                await asyncio.to_thread(
                    supervisor.validate_settings_transition,
                    previous_llama,
                    proposed_snapshot.llama_cpp,
                )
            except LlamaCppManagedServerError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=str(exc),
                ) from None

        previous_snapshot = store.get_snapshot()
        try:
            committed_snapshot = await asyncio.to_thread(store.apply_patch, payload)
        except SettingsPersistenceError as exc:
            _LOGGER.exception("Settings persistence failed")
            detail = str(exc)
            if "Refusing to persist invalid settings" in detail:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=detail,
                ) from None
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Failed to persist settings to config.local.json. "
                    "Active settings were not changed."
                ),
            ) from None
        if committed_snapshot is not previous_snapshot:
            sink = getattr(request.app.state, "desktop_preferences_sink", None)
            if callable(sink):
                try:
                    sink()
                except Exception:
                    # Config is durable; native integration failures cannot undo it.
                    _LOGGER.warning(
                        "Desktop preferences publication failed.", exc_info=True
                    )
        if (
            payload.context_vault is not None
            or (payload.ask_apex is not None and payload.ask_apex.sandbox_mode is not None)
        ):
            runtime = get_context_vault_runtime()
            if runtime is not None:
                try:
                    await runtime.notify_selection_change()
                except Exception:
                    # The worker also compares the committed settings fingerprint;
                    # a missed wakeup cannot lose the durable configuration change.
                    _LOGGER.warning("Context vault settings wakeup failed.")
        if payload.llama_cpp is not None:
            current_llama = store.get_snapshot().llama_cpp
            supervisor = get_llama_cpp_server_supervisor()
            try:
                await asyncio.to_thread(
                    supervisor.on_settings_changed, previous_llama, current_llama
                )
            except LlamaCppManagedServerError as exc:
                _LOGGER.error(
                    "llama.cpp settings transition failed after persistence: %s",
                    exc,
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Settings were saved but llama.cpp could not apply them.",
                ) from None
            try:
                backend = get_local_runtime_backend("llama_cpp")
            except KeyError:
                backend = None
            if backend is not None:
                backend.invalidate_status_snapshot()
        if payload.mcp is not None:
            manager = get_mcp_manager()
            if manager is not None:
                await manager.reconfigure(load_mcp_config())
        return _build_settings_response()
    finally:
        if vault_transition_held and vault_runtime is not None:
            vault_runtime.release_settings_transition()
        if transition_held:
            await asyncio.to_thread(end_local_runtime_transition)


@router.get("/api/v1/google-calendar/calendars")
def get_google_calendar_choices() -> dict[str, Any]:
    """Return bounded, sanitized Google Calendar picker choices."""
    try:
        from clients.calendar_client import list_readable_calendars
        from clients.google_auth import get_service

        service = object() if DEMO_MODE else get_service("calendar", "v3")
        if not service:
            raise RuntimeError("calendar service unavailable")
        return list_readable_calendars(service)
    except Exception as exc:
        _LOGGER.warning("Google calendar discovery failed: error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar is unavailable.",
        ) from None


@router.get("/api/v1/llama-cpp/status", response_model=LlamaCppServerStatusResponse)
def get_llama_cpp_server_status() -> LlamaCppServerStatusResponse:
    """
    Return sanitized llama.cpp server ownership status for Runtime Settings.

    Never includes executable paths, preset paths, PIDs, or raw process output.
    """
    return get_llama_cpp_server_supervisor().status_snapshot()


@router.get("/api/v1/diagnostics")
def get_system_diagnostics() -> dict[str, float]:
    """
    Hardware utilization snapshot for the user and HUD diagnostics panels.
    """
    return scanner.sample_system_vitals()
