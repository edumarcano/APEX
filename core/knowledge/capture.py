"""Approval-gated capture of personal context from Cortex conversations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from core.actions import ExecutionOutcome, VerificationOutcome
from core.actions.models import ActionRecord
from core.conversations.service import ConversationService
from core.knowledge.store import KnowledgeStore
from core.knowledge.store import KnowledgeConflictError

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
    def __init__(self, knowledge: KnowledgeStore, conversations: ConversationService) -> None:
        self._knowledge = knowledge
        self._conversations = conversations

    def execute(self, action: ActionRecord) -> ExecutionOutcome:
        try:
            arguments = dict(action.proposal.arguments)
            provenance = arguments.pop("_apex_provenance")
            if not isinstance(provenance, Mapping):
                raise ContextCaptureError("capture_provenance_invalid")
            partition = str(provenance.get("partition", ""))
            source_kind = str(provenance.get("source_kind", ""))
            requested_review_id = arguments.pop("review_id", None)
            review = self._knowledge.review_for_action(action.action_id, partition=partition)
            if requested_review_id is not None and (
                review is None or str(review.id) != str(requested_review_id)
            ):
                raise ContextCaptureError("capture_review_link_invalid")
            if review is not None:
                if review.action_id != action.action_id:
                    raise ContextCaptureError("capture_review_attempt_superseded")
                accepted = self._knowledge.accept_review(review.id, partition=partition, action_id=action.action_id)
                return ExecutionOutcome(True, "context_review_accepted", {"review_id": str(accepted.id)})
            if source_kind == "conversation_message":
                conversation_id = UUID(str(provenance["conversation_id"]))
                message_id = UUID(str(provenance["message_id"]))
                frozen_text = provenance.get("original_text")
                frozen_at = provenance.get("occurred_at")
                if isinstance(frozen_text, str) and frozen_text:
                    original_text, locator = frozen_text, f"conversation/{conversation_id}/message/{message_id}"
                    source_occurred_at = str(frozen_at) if frozen_at else None
                else:
                    # Existing action records predate frozen review evidence. Keep
                    # them executable during upgrade; new proposals always freeze.
                    detail = self._conversations.store.detail(conversation_id, partition)
                    message = next((item for item in detail.messages if item.id == message_id), None)
                    if message is None or message.role != "user" or message.status != "completed":
                        raise ContextCaptureError("capture_source_unavailable")
                    original_text, locator = message.content, f"conversation/{conversation_id}/message/{message_id}"
                    source_occurred_at = str(getattr(message, "created_at", "")) or None
                derivation = "model_interpretation"
            elif source_kind == "manual":
                original_text = str(provenance["original_text"])
                locator = f"manual/action/{action.action_id}"
                source_occurred_at = None
                derivation = "direct"
            else:
                raise ContextCaptureError("capture_provenance_invalid")
            reject_secret_text(original_text)
            reject_secret_text(str(arguments.get("text", "")))
            validate_effective_at(arguments.get("effective_at"))
            # Pre-review action records are upgraded on their first use only
            # when they contain frozen, server-owned evidence.  They follow the
            # same snapshot and acceptance path as newly created proposals.
            legacy_review = self._knowledge.create_review(
                partition=partition, operation="capture", proposal=arguments,
                evidence={
                    "source_kind": source_kind, "locator": locator,
                    "original_text": original_text, "source_origin": "operator_input",
                    "derivation": derivation, "occurred_at": source_occurred_at,
                },
                expected_revisions=self._knowledge.capture_decision(partition=partition, **arguments)["expected_revisions"],
                reason_codes=("legacy_revalidation",), action_id=action.action_id,
            )
            accepted = self._knowledge.accept_review(legacy_review.id, partition=partition, action_id=action.action_id)
            return ExecutionOutcome(True, "context_review_accepted", {"review_id": str(accepted.id)})
        except (ContextCaptureError, KnowledgeConflictError, KeyError, TypeError, ValueError) as exc:
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
