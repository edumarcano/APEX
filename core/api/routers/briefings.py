"""Briefing trigger and history routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from core import database
from core.api.briefing import trigger_briefing
from core.api.demo import mock_briefing_history
from core.api.models import BriefingHistoryRecord, BriefingResponse, parse_digest_payload, parse_runtime_metadata
from core.config import DEMO_MODE

router = APIRouter(tags=["briefings"])


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


@router.get("/api/v1/briefings/history", response_model=list[BriefingHistoryRecord])
def get_briefing_history() -> list[dict[str, Any]]:
    """
    Return recent briefing ledger entries for HUD history panels.

    When ``DEMO_MODE`` is active, serves a static mock ledger without querying SQLite.
    """
    if DEMO_MODE:
        return mock_briefing_history()

    rows = database.fetch_briefing_history(limit=50)
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "briefing": row["briefing"],
            "digest": parse_digest_payload(row["digest"]),
            "metadata": parse_runtime_metadata(row.get("metadata")),
        }
        for row in rows
    ]
