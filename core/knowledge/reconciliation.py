"""Approval-gated reconciliation operations for personal knowledge."""

from __future__ import annotations

from collections.abc import Mapping

from core.actions import ExecutionOutcome, VerificationOutcome
from core.actions.models import ActionRecord
from core.knowledge.capture import ContextCaptureError, reject_secret_text, validate_effective_at
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
            if operation not in _OPERATIONS:
                raise ContextCaptureError("reconciliation_invalid")
            capture = arguments.get("capture")
            if isinstance(capture, Mapping):
                reject_secret_text(str(capture.get("text", "")))
                validate_effective_at(capture.get("effective_at"))
                arguments["capture"] = dict(capture)
            outcome = self._knowledge.reconcile(
                action_id=action.action_id, operation=operation, partition=partition, arguments=arguments,
            )
            return ExecutionOutcome(True, "context_reconciled", outcome)
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
