"""Microsoft To Do authorization and sanitized status routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from clients.microsoft_auth import (
    MicrosoftTodoNotConfiguredError,
    get_microsoft_auth_service,
)
from clients.microsoft_todo_models import MicrosoftTodoAuthStatus
from core.api.models import (
    MicrosoftTodoAuthorizationResponse,
    MicrosoftTodoStatusResponse,
)

router = APIRouter(tags=["microsoft-todo"])


def _service():
    service = get_microsoft_auth_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Microsoft To Do is unavailable.")
    return service


@router.get("/api/v1/microsoft-todo/status", response_model=MicrosoftTodoStatusResponse)
def microsoft_todo_status() -> MicrosoftTodoStatusResponse:
    service = get_microsoft_auth_service()
    snapshot = service.status_snapshot() if service is not None else MicrosoftTodoAuthStatus(
        configured=False,
        state="not-configured",
    )
    return MicrosoftTodoStatusResponse.model_validate(snapshot.to_dict())


@router.post(
    "/api/v1/microsoft-todo/auth/start",
    response_model=MicrosoftTodoAuthorizationResponse,
)
async def start_microsoft_todo_authorization() -> MicrosoftTodoAuthorizationResponse:
    try:
        result = await _service().begin_device_authorization()
    except MicrosoftTodoNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Microsoft authorization could not be started.",
        ) from exc
    return MicrosoftTodoAuthorizationResponse.model_validate(result.to_dict())


@router.delete("/api/v1/microsoft-todo/auth", response_model=MicrosoftTodoStatusResponse)
async def disconnect_microsoft_todo() -> MicrosoftTodoStatusResponse:
    try:
        service = _service()
        await service.disconnect()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Microsoft authorization could not be removed.",
        ) from exc
    return MicrosoftTodoStatusResponse.model_validate(service.status_snapshot().to_dict())
