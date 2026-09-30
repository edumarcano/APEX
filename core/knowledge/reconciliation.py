"""Approval-gated reconciliation operations for personal knowledge."""

from __future__ import annotations

from collections.abc import Mapping

from core.actions import ExecutionOutcome, VerificationOutcome
from core.actions.models import ActionRecord
from core.knowledge.capture import ContextCaptureError
from core.knowledge.store import KnowledgeConflictError, KnowledgeNotFoundError, KnowledgeStore, KnowledgeStoreError

CAPABILITY_NAME = "reconcile_personal_context"
_OPERATIONS = {"correct", "retract", "restore", "set_current", "add_alias", "merge_entities"}


class ContextReconciliationExecutor:
    def __init__(self, knowledge: KnowledgeStore) -> None:
        self._knowledge = knowledge

    def execute(self, action: ActionRecord) -> ExecutionOutcome:
        try:
            arguments = dict(action.proposal.arguments)
            operation = str(arguments.pop("operation", ""))
            partition = str(arguments.pop("partition", ""))
            requested_review_id = arguments.pop("review_id", None)
            review = self._knowledge.review_for_action(action.action_id, partition=partition)
            if review is None or (
                requested_review_id is not None and str(review.id) != str(requested_review_id)
            ):
                raise ContextCaptureError("reconciliation_review_link_invalid")
            if review.action_id != action.action_id:
                raise ContextCaptureError("reconciliation_review_attempt_superseded")
            if review.operation != operation or operation not in _OPERATIONS:
                raise ContextCaptureError("reconciliation_review_link_invalid")
            accepted = self._knowledge.accept_review(review.id, partition=partition, action_id=action.action_id)
            return ExecutionOutcome(True, "context_review_accepted", {"review_id": str(accepted.id)})
        except (ContextCaptureError, KnowledgeConflictError, KnowledgeNotFoundError, KnowledgeStoreError, TypeError, ValueError) as exc:
            return ExecutionOutcome(False, "context_reconciliation_rejected", {"category": type(exc).__name__})
        except Exception:
            return ExecutionOutcome(None, "context_reconciliation_unknown", {})


class ContextReconciliationVerifier:
    def __init__(self, knowledge: KnowledgeStore) -> None:
        self._knowledge = knowledge

    def verify(self, action: ActionRecord, _evidence: Mapping[str, object]) -> VerificationOutcome:
        effect = self._knowledge.reconciliation_effect(action.action_id)
        if effect is None:
            return VerificationOutcome(False, "context_reconciliation_missing", {})
        return VerificationOutcome(True, "context_reconciliation_verified", effect)
