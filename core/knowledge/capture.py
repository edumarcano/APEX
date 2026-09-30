"""Approval-gated capture of personal context from Cortex conversations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime

from core.actions import ExecutionOutcome, VerificationOutcome
from core.actions.models import ActionRecord
from core.knowledge.store import (
    KnowledgeConflictError,
    KnowledgeNotFoundError,
    KnowledgeStore,
    KnowledgeStoreError,
)

CAPABILITY_NAME = "remember_personal_context"
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk|rk|pk)_[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+", re.I),
)


class ContextCaptureError(ValueError):
    """A capture request is invalid or unsafe to retain."""


def reject_secret_text(value: str) -> None:
    if not isinstance(value, str) or any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise ContextCaptureError("Personal context cannot contain credentials or private keys.")


def validate_effective_at(value: str | None) -> None:
    if value is None:
        return
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContextCaptureError("effective_at must be an ISO-8601 date or timestamp.") from exc


class ContextCaptureExecutor:
    def __init__(self, knowledge: KnowledgeStore) -> None:
        self._knowledge = knowledge

    def execute(self, action: ActionRecord) -> ExecutionOutcome:
        try:
            arguments = dict(action.proposal.arguments)
            provenance = arguments.get("_apex_provenance")
            if not isinstance(provenance, Mapping):
                raise ContextCaptureError("capture_provenance_invalid")
            partition = str(provenance.get("partition", ""))
            requested_review_id = arguments.pop("review_id", None)
            review = self._knowledge.review_for_action(action.action_id, partition=partition)
            if review is None or (
                requested_review_id is not None and str(review.id) != str(requested_review_id)
            ):
                raise ContextCaptureError("capture_review_link_invalid")
            if review.action_id != action.action_id:
                raise ContextCaptureError("capture_review_attempt_superseded")
            if review.operation != "capture":
                raise ContextCaptureError("capture_review_link_invalid")
            accepted = self._knowledge.accept_review(review.id, partition=partition, action_id=action.action_id)
            return ExecutionOutcome(True, "context_review_accepted", {"review_id": str(accepted.id)})
        except (
            ContextCaptureError, KnowledgeConflictError, KnowledgeNotFoundError, KnowledgeStoreError,
            KeyError, TypeError, ValueError,
        ) as exc:
            return ExecutionOutcome(False, "context_capture_rejected", {"category": type(exc).__name__})
        except Exception:
            return ExecutionOutcome(None, "context_capture_unknown", {})


class ContextCaptureVerifier:
    def __init__(self, knowledge: KnowledgeStore) -> None:
        self._knowledge = knowledge

    def verify(self, action: ActionRecord, _evidence: Mapping[str, object]) -> VerificationOutcome:
        effect = self._knowledge.capture_effect(action.action_id)
        if effect is None:
            return VerificationOutcome(False, "context_capture_missing", {})
        record, source, outcome = effect
        return VerificationOutcome(True, "context_capture_verified", {
            "record_id": str(record.id), "source_id": str(source.id), "outcome": outcome,
        })
