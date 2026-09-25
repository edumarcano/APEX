"""Briefing trigger, generate, and history routes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from core import database
from core.api.briefing import (
    build_briefing_target_statuses,
    generate_briefing,
    trigger_briefing,
)
from core.api.demo import mock_briefing_history
from core.api.models import (
    BriefingGenerateRequest,
    BriefingHistoryRecord,
    BriefingResponse,
    BriefingTargetStatus,
    BriefingTriggerRequest,
    classify_digest_payload,
    parse_runtime_metadata,
)
from core.config import DEMO_MODE
from core.briefings.models import (
    BriefingEvidence,
    BriefingGenerationRequest,
    BriefingSessionGenerateRequest,
    BriefingSessionDetail,
    BriefingSessionSummary,
)
from core.briefings.runtime import BriefingModelConfigurationError
from core.briefings.service import get_briefing_service, get_briefing_session_queries
from core.briefings.store import (
    BriefingSessionConflictError,
    BriefingSessionNotFoundError,
)
from core.runs.coordinator import (
    ActiveConversationRunError,
    RunCapacityError,
    RunCoordinatorClosingError,
)

router = APIRouter(tags=["briefings"])
_LOGGER = logging.getLogger(__name__)


@router.post(
    "/api/v1/briefing-sessions",
    response_model=BriefingSessionSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a saved Daily briefing session",
)
def generate_briefing_session(
    body: BriefingSessionGenerateRequest,
    response: Response,
) -> BriefingSessionSummary:
    """Admit a Daily run and return its durable session and conversation IDs."""
    if body.profile_id != "daily":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only Daily briefing sessions are available in this release.",
        )
    try:
        result = get_briefing_service().start(
            BriefingGenerationRequest(
                **body.model_dump(),
                origin="hud",
            )
        )
    except BriefingModelConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RunCapacityError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="APEX is already running at its current capacity. Try again shortly.",
        ) from None
    except ActiveConversationRunError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation already has an active run.",
        ) from None
    except RunCoordinatorClosingError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Briefing generation is shutting down.",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except BriefingSessionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Briefing generation is unavailable.",
        ) from None

    record = result.session
    response.status_code = status.HTTP_200_OK if result.replayed else status.HTTP_202_ACCEPTED
    return BriefingSessionSummary(
        id=record.id,
        profile_id=record.request.profile_id,
        model_id=record.configuration.model.model_id,
        conversation_id=record.conversation_id,
        run_id=record.run_id,
        run_status=record.run_status,
        created_at=record.created_at,
        presented_at=record.presented_at,
    )


@router.post(
    "/api/v1/trigger",
    response_model=BriefingResponse,
    operation_id="trigger_briefing_api_v1_trigger_post",
    summary="Trigger Briefing",
)
def trigger_briefing_endpoint(
    body: BriefingTriggerRequest | None = None,
) -> BriefingResponse:
    """
    HTTP entry point for a full APEX run.

    Force-refreshes telemetry, then synthesizes with an optional requested mode
    or the configured default. When ``DEMO_MODE`` is active, serves static mock
    telemetry through a staged simulation loop.
    """
    return trigger_briefing(mode=body.mode if body is not None else None)


@router.post(
    "/api/v1/briefings/generate",
    response_model=BriefingResponse,
    summary="Generate Briefing",
)
def generate_briefing_endpoint(body: BriefingGenerateRequest) -> BriefingResponse:
    """
    Synthesize a briefing from an existing telemetry snapshot.

    Requires a process-current ``snapshot_id`` and selected briefing mode.
    Performs no connector calls. Returns ``409`` when the snapshot is missing
    or no longer current.
    """
    return generate_briefing(
        snapshot_id=body.snapshot_id,
        mode=body.mode,
        cue_context=body.cue_context,
    )


def _history_record_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Build a history API record with digest quality classification."""
    digest, digest_status = classify_digest_payload(
        row.get("digest"),
        digest_parse_error=row.get("digest_parse_error"),
    )
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "briefing": row["briefing"],
        "digest": digest,
        "metadata": parse_runtime_metadata(row.get("metadata")),
        "digest_status": digest_status,
    }


@router.get("/api/v1/briefings/history", response_model=list[BriefingHistoryRecord])
def get_briefing_history() -> list[dict[str, Any]]:
    """
    Return recent briefing ledger entries for HUD history panels.

    When ``DEMO_MODE`` is active, serves a static mock ledger without querying SQLite.
    """
    if DEMO_MODE:
        return [_history_record_from_row(row) for row in mock_briefing_history()]

    try:
        rows = database.fetch_briefing_history(limit=50)
    except sqlite3.Error:
        _LOGGER.exception("Briefing history unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Briefing history unavailable.",
        ) from None

    return [_history_record_from_row(row) for row in rows]


@router.get(
    "/api/v1/briefings/targets",
    response_model=list[BriefingTargetStatus],
    summary="Get Briefing Targets",
)
def get_briefing_targets() -> list[BriefingTargetStatus]:
    """Return live availability and metadata for fixed briefing synthesis targets."""
    return build_briefing_target_statuses()


@router.get(
    "/api/v1/briefing-sessions",
    response_model=list[BriefingSessionSummary],
    summary="List saved briefing sessions",
)
def list_briefing_sessions(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[BriefingSessionSummary]:
    """Read saved session metadata from the active account partition."""
    return get_briefing_session_queries().list(limit=limit, offset=offset)


@router.get(
    "/api/v1/briefing-sessions/{session_id}",
    response_model=BriefingSessionDetail,
    summary="Get a saved briefing session",
)
def get_briefing_session(session_id: UUID) -> BriefingSessionDetail:
    """Read a session without marking it presented."""
    try:
        return get_briefing_session_queries().get(session_id)
    except BriefingSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Briefing session was not found.") from None


@router.get(
    "/api/v1/briefing-sessions/{session_id}/evidence/{evidence_id}",
    response_model=BriefingEvidence,
    summary="Get saved briefing evidence",
)
def get_briefing_evidence(session_id: UUID, evidence_id: UUID) -> BriefingEvidence:
    """Read the evidence snapshot captured with a completed session."""
    try:
        return get_briefing_session_queries().evidence(session_id, evidence_id)
    except BriefingSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Briefing evidence was not found.") from None
    except BriefingSessionConflictError:
        raise HTTPException(
            status_code=409,
            detail="Evidence is available only after a session completes.",
        ) from None


@router.post(
    "/api/v1/briefing-sessions/{session_id}/presented",
    response_model=BriefingSessionDetail,
    summary="Acknowledge a presented briefing",
)
def mark_briefing_presented(session_id: UUID) -> BriefingSessionDetail:
    """Record the first presentation time; repeated acknowledgments are idempotent."""
    try:
        return get_briefing_session_queries().mark_presented(session_id)
    except BriefingSessionNotFoundError:
        raise HTTPException(status_code=404, detail="Briefing session was not found.") from None
    except BriefingSessionConflictError:
        raise HTTPException(
            status_code=409,
            detail="Only a completed briefing session can be marked as presented.",
        ) from None
