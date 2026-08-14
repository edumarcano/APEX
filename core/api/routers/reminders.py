"""Loopback reminder API backed by one concrete selected-list service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from core.api.models import (
    CompleteReminderRequest,
    CompleteReminderResponse,
    CreateReminderRequest,
    CreateReminderResponse,
    DismissReminderRequest,
    ReminderListResponse,
    SyncRemindersRequest,
    SyncRemindersResponse,
)
from core.api.tts import clean_for_tts
from core.config import DEMO_MODE
from core.reminders import get_reminder_service
from core.reminders.service import ReminderServiceError

router = APIRouter(tags=["reminders"])


def _service():
    service = get_reminder_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Reminder service is unavailable.")
    return service


def _raise(exc: ReminderServiceError) -> None:
    code = exc.code
    if code in {"reminder_invalid_input", "reminder_invalid_id"}:
        status_code = 422
    elif code in {"reminder_not_found", "unknown_reminder_not_found"}:
        status_code = 404
    elif code in {"reminder_target_changed", "reminder_sync_in_progress"}:
        status_code = 409
    elif code in {"microsoft_todo_unavailable", "reminder_target_unavailable"}:
        status_code = 503
    else:
        status_code = 409
    detail: dict[str, object] = {"code": code}
    if exc.action_id:
        detail["action_id"] = exc.action_id
    raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/api/v1/reminders", response_model=ReminderListResponse)
def list_reminders() -> ReminderListResponse:
    if DEMO_MODE:
        return ReminderListResponse(
            items=[
                {"id": "local:991", "note": "Review APEX demo script", "source": "local", "sync_state": "pending"},
                {"id": "local:992", "note": "Charge backup operations hardware", "source": "local", "sync_state": "pending"},
            ],
            source_state="unavailable", cache_timestamp=None, pending_sync_count=2,
        )
    return ReminderListResponse.model_validate(_service().list().to_dict())


@router.post(
    "/api/v1/reminders",
    response_model=CreateReminderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reminder(payload: CreateReminderRequest, response: Response) -> CreateReminderResponse:
    sanitized = clean_for_tts(payload.text)
    if not sanitized:
        raise HTTPException(status_code=422, detail="Reminder text is empty after sanitization.")
    if DEMO_MODE:
        return CreateReminderResponse(id="local:999", outcome="pending")
    try:
        result = _service().create(sanitized)
    except ReminderServiceError as exc:
        _raise(exc)
    outcome = result["outcome"]
    if outcome == "failed":
        raise HTTPException(status_code=502, detail={"code": "microsoft_todo_create_failed", "action_id": result["action_id"]})
    if outcome == "unknown":
        response.status_code = status.HTTP_202_ACCEPTED
    return CreateReminderResponse.model_validate(result)


@router.post("/api/v1/reminders/complete", response_model=CompleteReminderResponse)
def complete_reminder(payload: CompleteReminderRequest) -> CompleteReminderResponse:
    if DEMO_MODE:
        return CompleteReminderResponse(id=payload.id, outcome="dismissed")
    try:
        return CompleteReminderResponse.model_validate(_service().complete(payload.id))
    except ReminderServiceError as exc:
        _raise(exc)


@router.post("/api/v1/reminders/sync", response_model=SyncRemindersResponse)
def sync_reminders(payload: SyncRemindersRequest) -> SyncRemindersResponse:
    if DEMO_MODE:
        return SyncRemindersResponse(items=[{"id": item, "outcome": "failed"} for item in payload.ids])
    try:
        return SyncRemindersResponse(items=_service().sync(payload.ids))
    except ReminderServiceError as exc:
        _raise(exc)


@router.post("/api/v1/reminders/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_reminder(payload: DismissReminderRequest) -> Response:
    if DEMO_MODE:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        _service().dismiss_unknown(payload.id)
    except ReminderServiceError as exc:
        _raise(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
