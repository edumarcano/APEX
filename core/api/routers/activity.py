"""Loopback-only routes for receiving and inspecting external activity reports."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError

from core.activity import (
    ActivityClientDisabledError,
    ActivityConflictError,
    ActivityNotFoundError,
    ActivityPermissionError,
    ActivityStoreError,
    ActivitySubmissionRequest,
    get_activity_service,
)
from core.activity.boundary import read_bounded_activity_body, require_local_submission_headers
from core.activity.review import ActivityContextReviewError, ActivityContextReviewService
from core.api.models import (
    ActivityContextProposalRequest,
    ActivityReportResponse,
    ActivitySubmissionResponse,
    ContextReviewResponse,
)
from core.actions.runtime import get_action_service
from core.config import DEMO_MODE
from core.conversations import get_conversation_service
from core.knowledge import get_knowledge_service
from core.knowledge.store import KnowledgeConflictError, KnowledgeNotFoundError

router = APIRouter(tags=["activity"])

_LOCAL_ACTIVITY_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)
_LOCAL_ACTIVITY_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _response(report) -> ActivityReportResponse:
    return ActivityReportResponse(
        id=str(report.id), partition=report.partition, client_id=report.client_id,
        client_display_name=report.client_display_name, principal=report.principal,
        received_at=report.received_at, disposition=report.disposition, report=report.content,
    )


def _error(error: Exception) -> HTTPException:
    if isinstance(error, ActivityNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity report was not found.")
    if isinstance(error, ActivityConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The submission key was already used for different report content.")
    if isinstance(error, ActivityClientDisabledError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity client is disabled or unavailable.")
    if isinstance(error, ActivityPermissionError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity submission is not permitted for this client and partition.")
    if isinstance(error, ActivityStoreError):
        if str(error) == "report_too_large":
            return HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Activity report exceeds the 256 KiB limit.")
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Activity report is invalid.")
    if isinstance(error, ActivityContextReviewError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Activity context proposal is invalid.")
    if isinstance(error, KnowledgeNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Context record was not found.")
    if isinstance(error, KnowledgeConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Context changed or cannot be reconciled.")
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Activity inbox is unavailable.")


@router.post("/api/v1/activity/reports", response_model=ActivitySubmissionResponse, status_code=status.HTTP_201_CREATED)
async def submit_activity_report(request: Request) -> ActivitySubmissionResponse:
    """Receive one local, operator-attributed report without changing knowledge."""
    if DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity submissions are unavailable in demo mode.")
    try:
        require_local_submission_headers(
            request,
            allowed_hosts=_LOCAL_ACTIVITY_HOSTS,
            allowed_origins=_LOCAL_ACTIVITY_ORIGINS,
            port=8000,
        )
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Activity submissions require application/json.")
        payload = ActivitySubmissionRequest.model_validate_json(await read_bounded_activity_body(request))
        receipt = get_activity_service().submit(
            client_id=payload.client_id, principal="operator",
            partition=get_conversation_service().partition(), content=payload.report,
        )
        report = _response(receipt.report)
        return ActivitySubmissionResponse(**report.model_dump(), duplicate=receipt.duplicate)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Activity report is invalid.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/api/v1/activity/reports", response_model=list[ActivityReportResponse])
def list_activity_reports(
    client_id: str | None = Query(default=None, min_length=1, max_length=64),
    disposition: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[ActivityReportResponse]:
    """List report receipts in the current production or sandbox partition."""
    try:
        reports = get_activity_service().list(
            partition=get_conversation_service().partition(), client_id=client_id,
            disposition=disposition, limit=limit,
        )
        return [_response(report) for report in reports]
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/api/v1/activity/reports/{report_id}", response_model=ActivityReportResponse)
def get_activity_report(report_id: UUID) -> ActivityReportResponse:
    """Read one immutable report in the current partition."""
    try:
        return _response(get_activity_service().get(report_id, partition=get_conversation_service().partition()))
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/api/v1/activity/reports/{report_id}/context-proposals", response_model=ContextReviewResponse)
def propose_activity_context(report_id: UUID, payload: ActivityContextProposalRequest) -> ContextReviewResponse:
    """Create a pending context review from server-resolved immutable activity evidence."""
    if DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Activity context proposals are unavailable in demo mode.")
    actions = get_action_service()
    if actions is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Personal context review is unavailable.")
    try:
        capture = payload.model_dump(exclude={"finding_reference", "correction_record_id"})
        review = ActivityContextReviewService(
            get_activity_service(), get_knowledge_service(), actions,
        ).propose(
            report_id=report_id, partition=get_conversation_service().partition(),
            finding_reference=payload.finding_reference, capture=capture,
            correction_record_id=payload.correction_record_id,
        )
        return ContextReviewResponse(
            id=str(review.id), partition=review.partition, operation=review.operation,
            proposal=review.proposal, evidence=review.evidence,
            expected_revisions=review.expected_revisions, reason_codes=list(review.reason_codes),
            decision=review.decision, action_id=review.action_id, decision_at=review.decision_at,
            created_at=review.created_at,
        )
    except Exception as exc:
        raise _error(exc) from exc
