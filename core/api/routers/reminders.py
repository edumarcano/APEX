"""Loopback reminder API backed by one concrete selected-list service."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status

from core.api.models import (
    CompleteReminderRequest,
    CompleteReminderResponse,
    CompletedReminderListResponse,
    CreateReminderRequest,
    CreateReminderResponse,
    DismissReminderRequest,
    ReminderListResponse,
    ReminderTaskDetail,
    ReminderTaskMutationResponse,
    ReminderTaskTargetRequest,
    ReminderTaskUpdateRequest,
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
    if code in {
        "reminder_invalid_input", "reminder_invalid_id",
        "only_remote_reminders_can_be_managed",
    }:
        status_code = 422
    elif code in {"reminder_not_found", "unknown_reminder_not_found"}:
        status_code = 404
    elif code in {"reminder_target_changed", "reminder_sync_in_progress"}:
        status_code = 409
    elif code in {"microsoft_todo_unavailable", "reminder_target_unavailable"}:
        status_code = 503
    elif code == "microsoft_todo_mutation_failed":
        status_code = 502
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


def _demo_task(task_id: str, *, completed: bool = False) -> dict[str, object]:
    return {
        "id": f"todo:{task_id}",
        "title": "Review APEX demo script" if not completed else "Archive APEX demo notes",
        "due": None,
        "importance": "normal",
        "is_completed": completed,
        "completed_at": {"date_time": "2026-08-14T09:00:00", "time_zone": "UTC"} if completed else None,
        "last_modified_at": "2026-08-14T09:00:00Z",
    }


@router.get("/api/v1/reminders/task", response_model=ReminderTaskDetail)
def get_reminder_task(
    id: str = Query(min_length=6, max_length=520, pattern=r"^todo:.*\S.*$"),
) -> ReminderTaskDetail:
    if DEMO_MODE:
        return ReminderTaskDetail.model_validate(_demo_task(id.removeprefix("todo:")))
    try:
        return ReminderTaskDetail.model_validate(_service().task_detail(id))
    except ReminderServiceError as exc:
        _raise(exc)


@router.get("/api/v1/reminders/completed", response_model=CompletedReminderListResponse)
def list_completed_reminders() -> CompletedReminderListResponse:
    if DEMO_MODE:
        return CompletedReminderListResponse(
            items=[_demo_task("demo-completed", completed=True)], source_state="live"
        )
    return CompletedReminderListResponse.model_validate(_service().completed())


def _mutation_response(
    result: dict[str, object], response: Response
) -> ReminderTaskMutationResponse:
    if result["outcome"] == "unknown":
        response.status_code = status.HTTP_202_ACCEPTED
    return ReminderTaskMutationResponse.model_validate(result)


@router.post("/api/v1/reminders/update", response_model=ReminderTaskMutationResponse)
def update_reminder_task(
    payload: ReminderTaskUpdateRequest, response: Response
) -> ReminderTaskMutationResponse:
    changes = payload.model_dump(
        include={"title", "due", "importance"}, exclude_unset=True
    )
    if "title" in changes:
        sanitized = clean_for_tts(str(changes["title"]))
        if not sanitized:
            raise HTTPException(status_code=422, detail="Reminder title is empty after sanitization.")
        changes["title"] = sanitized
    if DEMO_MODE:
        return ReminderTaskMutationResponse(
            id=payload.id, outcome="synced", action_id="demo-reminder-update"
        )
    try:
        return _mutation_response(
            _service().update_task(payload.id, payload.last_modified_at, changes), response
        )
    except ReminderServiceError as exc:
        _raise(exc)


@router.post("/api/v1/reminders/delete", response_model=ReminderTaskMutationResponse)
def delete_reminder_task(
    payload: ReminderTaskTargetRequest, response: Response
) -> ReminderTaskMutationResponse:
    if DEMO_MODE:
        return ReminderTaskMutationResponse(
            id=payload.id, outcome="synced", action_id="demo-reminder-delete"
        )
    try:
        return _mutation_response(
            _service().delete_task(payload.id, payload.last_modified_at), response
        )
    except ReminderServiceError as exc:
        _raise(exc)


@router.post("/api/v1/reminders/reopen", response_model=ReminderTaskMutationResponse)
def reopen_reminder_task(
    payload: ReminderTaskTargetRequest, response: Response
) -> ReminderTaskMutationResponse:
    if DEMO_MODE:
        return ReminderTaskMutationResponse(
            id=payload.id, outcome="synced", action_id="demo-reminder-reopen"
        )
    try:
        return _mutation_response(
            _service().reopen_task(payload.id, payload.last_modified_at), response
        )
    except ReminderServiceError as exc:
        _raise(exc)
