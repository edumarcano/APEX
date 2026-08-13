"""Loopback API for inspecting and resolving durable action proposals."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Query

from core.actions.models import ActionEvent, ActionRecord, thaw_json
from core.actions.runtime import get_action_service
from core.actions.service import ActionService
from core.actions.store import (
    ActionConflictError,
    ActionIntegrityError,
    ActionNotFoundError,
    ActionStoreError,
    ActionTransitionError,
)
from core.api.models import (
    ActionDetailResponse,
    ActionEventResponse,
    ActionMutationRequest,
    ActionProposalResponse,
    ActionResponse,
    ActionStatusResponse,
)
from core.config import DEMO_MODE

router = APIRouter(tags=["actions"])
_LOGGER = logging.getLogger(__name__)


def _service() -> ActionService:
    service = get_action_service()
    if service is None:
        raise HTTPException(status_code=503, detail="Action service is unavailable.")
    return service


def _record_response(record: ActionRecord) -> ActionResponse:
    proposal = record.proposal
    return ActionResponse(
        action_id=record.action_id,
        proposal=ActionProposalResponse(
            agent_key=proposal.agent_key,
            capability_name=proposal.capability_name,
            arguments=thaw_json(proposal.arguments), target=proposal.target,
            risk=proposal.risk, summary=proposal.summary,
            proposed_at=proposal.proposed_at, expires_at=proposal.expires_at,
            proposal_hash=proposal.proposal_hash,
        ),
        status=record.status, version=record.version, updated_at=record.updated_at,
    )


def _event_response(event: ActionEvent) -> ActionEventResponse:
    return ActionEventResponse(
        action_id=event.action_id, sequence=event.sequence,
        from_status=event.from_status, to_status=event.to_status,
        occurred_at=event.occurred_at, actor=event.actor,
        result_code=event.result_code, evidence=thaw_json(event.evidence),
    )


def _detail_response(
    service: ActionService,
    record: ActionRecord,
) -> ActionDetailResponse:
    base = _record_response(record)
    return ActionDetailResponse(
        **base.model_dump(),
        events=[_event_response(event) for event in service.events(record.action_id)],
    )


def _raise_action_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, ActionNotFoundError):
        raise HTTPException(status_code=404, detail="Action does not exist.") from exc
    if isinstance(exc, (ActionConflictError, ActionTransitionError)):
        raise HTTPException(status_code=409, detail="Action is no longer in the requested state.") from exc
    if isinstance(exc, (sqlite3.Error, ActionStoreError, ActionIntegrityError)):
        _LOGGER.error("Action persistence failed category=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Action persistence failed.") from exc
    raise exc


def _require_normal_mode() -> None:
    if DEMO_MODE:
        raise HTTPException(status_code=403, detail="Actions are unavailable in demo mode.")


@router.get("/api/v1/actions", response_model=list[ActionResponse])
def list_actions(
    status_filter: list[ActionStatusResponse] | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=50),
) -> list[ActionResponse]:
    if DEMO_MODE:
        return []
    try:
        service = _service()
        service.expire_due()
        return [
            _record_response(record)
            for record in service.list(statuses=status_filter, limit=limit)
        ]
    except Exception as exc:
        _raise_action_error(exc)


@router.get("/api/v1/actions/{action_id}", response_model=ActionDetailResponse)
def get_action(action_id: str) -> ActionDetailResponse:
    if DEMO_MODE:
        raise HTTPException(status_code=404, detail="Action does not exist.")
    try:
        service = _service()
        service.expire_due()
        return _detail_response(service, service.get(action_id))
    except Exception as exc:
        _raise_action_error(exc)


@router.post("/api/v1/actions/{action_id}/approve", response_model=ActionResponse)
def approve_action(action_id: str, payload: ActionMutationRequest) -> ActionResponse:
    _require_normal_mode()
    try:
        return _record_response(_service().approve_and_execute(
            action_id, actor="operator", expected_version=payload.expected_version
        ))
    except Exception as exc:
        _raise_action_error(exc)


@router.post("/api/v1/actions/{action_id}/reject", response_model=ActionResponse)
def reject_action(action_id: str, payload: ActionMutationRequest) -> ActionResponse:
    _require_normal_mode()
    try:
        return _record_response(_service().reject(
            action_id, actor="operator", expected_version=payload.expected_version
        ))
    except Exception as exc:
        _raise_action_error(exc)


@router.post("/api/v1/actions/{action_id}/verify", response_model=ActionResponse)
def verify_action(action_id: str, payload: ActionMutationRequest) -> ActionResponse:
    _require_normal_mode()
    try:
        return _record_response(_service().retry_verification(
            action_id, actor="operator", expected_version=payload.expected_version
        ))
    except Exception as exc:
        _raise_action_error(exc)
