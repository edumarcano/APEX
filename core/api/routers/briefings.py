"""Briefing trigger and history routes."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, status

from core import database
from core.api.briefing import trigger_briefing
from core.api.demo import mock_briefing_history
from core.api.models import (
    BriefingHistoryRecord,
    BriefingResponse,
    classify_digest_payload,
    parse_runtime_metadata,
)
from core.config import DEMO_MODE

router = APIRouter(tags=["briefings"])
_LOGGER = logging.getLogger(__name__)


@router.post(
    "/api/v1/trigger",
    response_model=BriefingResponse,
    operation_id="trigger_briefing_api_v1_trigger_post",
    summary="Trigger Briefing",
)
def trigger_briefing_endpoint() -> BriefingResponse:
    """
    HTTP entry point for a full APEX run.

    Mirrors main.start_apex execution order. When ``DEMO_MODE`` is active,
    serves static mock telemetry through a staged simulation loop.
    """
    return trigger_briefing()


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
