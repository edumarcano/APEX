"""Telemetry snapshot and preflight routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core.telemetry.models import (
    PreflightRequest,
    PreflightResponse,
    TelemetryRefreshRequest,
    TelemetrySnapshot,
)
from core.telemetry.preflight import evaluate_preflight
from core.telemetry.service import RefreshInProgressError, get_telemetry_service

router = APIRouter(tags=["telemetry"])


@router.get(
    "/api/v1/telemetry/latest",
    response_model=TelemetrySnapshot,
    summary="Latest Telemetry Snapshot",
)
def get_latest_telemetry() -> TelemetrySnapshot:
    """Return the current in-memory telemetry snapshot, or 404 when none exists."""
    snapshot = get_telemetry_service().latest()
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No telemetry snapshot is available.",
        )
    return snapshot


@router.post(
    "/api/v1/telemetry/refresh",
    response_model=TelemetrySnapshot,
    summary="Refresh Telemetry",
)
def refresh_telemetry(body: TelemetryRefreshRequest | None = None) -> TelemetrySnapshot:
    """
    Refresh telemetry connectors and return the resulting complete snapshot.

    Competing refreshes return ``409``. Normal refresh reuses a snapshot younger
    than five minutes unless ``force`` is true.
    """
    request = body or TelemetryRefreshRequest()
    try:
        return get_telemetry_service().refresh(
            connectors=request.connectors,
            force=request.force,
        )
    except RefreshInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None


@router.post(
    "/api/v1/preflight",
    response_model=PreflightResponse,
    summary="Operational Preflight",
)
def preflight(body: PreflightRequest) -> PreflightResponse:
    """
    Evaluate advisory warnings and non-overridable blockers for a planned operation.

    Warning acknowledgements apply to this request only and are not persisted.
    """
    return evaluate_preflight(body)
