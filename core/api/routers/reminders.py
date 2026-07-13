"""Reminder CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core import database
from core.api.models import (
    CreateReminderRequest,
    CreateReminderResponse,
    MarkReadRequest,
    MarkReadResponse,
    ReminderRecord,
)
from core.api.tts import clean_for_tts
from core.config import DEMO_MODE

router = APIRouter(tags=["reminders"])


@router.get("/api/v1/reminders", response_model=list[ReminderRecord])
def list_unread_reminders() -> list[ReminderRecord]:
    """
    Return all unread reminders as structured records for HUD refresh.

    Returns:
        List of reminder row IDs paired with their note text.
    """
    if DEMO_MODE:
        return [
            ReminderRecord(id=991, note="Review APEX demo script"),
            ReminderRecord(id=992, note="Charge backup operations hardware"),
        ]

    records = database.fetch_unread_reminders()
    return [{"id": row_id, "note": note} for row_id, note in records]


@router.post(
    "/api/v1/reminders",
    status_code=status.HTTP_201_CREATED,
    response_model=CreateReminderResponse,
)
def create_reminder(payload: CreateReminderRequest) -> CreateReminderResponse:
    """
    Persist a sanitized reminder for inclusion in future briefings.

    Args:
        payload: Request body containing the raw reminder text.

    Returns:
        The database row ID assigned to the new reminder.

    Raises:
        HTTPException: When sanitization yields empty text.
    """
    sanitized_text = clean_for_tts(payload.text)
    if not sanitized_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reminder text is empty after TTS sanitization.",
        )
    if DEMO_MODE:
        return CreateReminderResponse(id=999)
    row_id = database.save_reminder(sanitized_text)
    return CreateReminderResponse(id=row_id)


@router.post(
    "/api/v1/reminders/read",
    status_code=status.HTTP_200_OK,
    response_model=MarkReadResponse,
)
def mark_reminders_read(payload: MarkReadRequest) -> MarkReadResponse:
    """
    Mark one or more reminders as read by SQLite row ID.

    Args:
        payload: Request body listing reminder IDs to update.

    Returns:
        Success outcome label after the database write completes.
    """
    if DEMO_MODE:
        return MarkReadResponse()
    database.mark_reminders_read(payload.ids)
    return MarkReadResponse()
