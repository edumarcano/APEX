"""Turn selected immutable activity evidence into existing context reviews."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from uuid import UUID, uuid4

from core.activity.service import ActivityService
from core.knowledge.capture import CAPABILITY_NAME as CAPTURE_CAPABILITY_NAME
from core.knowledge.capture import ContextCaptureError, reject_secret_text, validate_effective_at
from core.knowledge.reconciliation import CAPABILITY_NAME as RECONCILIATION_CAPABILITY_NAME
from core.knowledge.store import KnowledgeNotFoundError


class ActivityContextReviewError(ValueError):
    """An activity finding cannot be proposed as context."""


class ActivityContextReviewService:
    """Build only pending reviews; acceptance stays in the context review lifecycle."""

    def __init__(self, activity: ActivityService, knowledge, actions, *, demo_mode: bool = False) -> None:
        self._activity = activity
        self._knowledge = knowledge
        self._actions = actions
        self._demo_mode = demo_mode
        self._lock = threading.RLock()

    @staticmethod
    def _proposal_hash(*, operation: str, capture: Mapping[str, object], record_id: UUID | None) -> str:
        """Hash stable operator intent, never a revision snapshot calculated by APEX."""
        encoded = json.dumps(
            {"operation": operation, "record_id": str(record_id) if record_id else None, "capture": dict(capture)},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _occurrence(report) -> str | None:
        occurred_at = report.content.occurred_at
        return occurred_at.isoformat() if occurred_at is not None else None

    @staticmethod
    def _review_matches_intent(review, *, operation: str, capture: Mapping[str, object], record_id: UUID | None) -> bool:
        if review.operation != operation:
            return False
        if operation == "capture":
            return review.proposal == dict(capture)
        return (
            review.proposal.get("record_id") == str(record_id)
            and review.proposal.get("capture") == dict(capture)
        )

    @staticmethod
    def _action_arguments(review) -> dict[str, object]:
        arguments = dict(review.proposal)
        if review.operation == "capture":
            arguments["_apex_provenance"] = {
                "source_kind": review.evidence["source_kind"], "partition": review.partition,
                "locator": review.evidence["locator"], "original_text": review.evidence["original_text"],
                "source_origin": review.evidence["source_origin"], "occurred_at": review.evidence.get("occurred_at"),
                "derivation": review.evidence.get("derivation", "unknown"),
            }
        arguments["review_id"] = str(review.id)
        return arguments

    @classmethod
    def _matches_linked_action(cls, action, review) -> bool:
        capability = CAPTURE_CAPABILITY_NAME if review.operation == "capture" else RECONCILIATION_CAPABILITY_NAME
        return (
            action.proposal.agent_key == "operator"
            and action.proposal.capability_name == capability
            and dict(action.proposal.arguments) == cls._action_arguments(review)
            and action.proposal.target == "Personal Context"
            and action.proposal.risk == "write"
            and action.proposal.summary == f"Approve personal context {review.operation}"
        )

    def _ensure_action(self, link, review) -> None:
        try:
            action = self._actions.get(link.action_id)
            if not self._matches_linked_action(action, review):
                raise ActivityContextReviewError("activity_context_action_conflict")
            return
        except Exception as exc:
            from core.actions.store import ActionNotFoundError

            if not isinstance(exc, ActionNotFoundError):
                raise
        capability = CAPTURE_CAPABILITY_NAME if review.operation == "capture" else RECONCILIATION_CAPABILITY_NAME
        try:
            self._actions.propose(
                agent_key="operator", capability_name=capability, arguments=self._action_arguments(review),
                target="Personal Context", risk="write", summary=f"Approve personal context {review.operation}",
                actor="operator", action_id=link.action_id,
            )
        except sqlite3.IntegrityError as conflict:
            try:
                action = self._actions.get(link.action_id)
            except Exception as exc:
                from core.actions.store import ActionNotFoundError

                if isinstance(exc, ActionNotFoundError):
                    raise conflict from exc
                raise
            if not self._matches_linked_action(action, review):
                raise ActivityContextReviewError("activity_context_action_conflict")

    def propose(
        self, *, report_id: UUID, partition: str, finding_reference: str,
        capture: Mapping[str, object], correction_record_id: UUID | None = None,
    ):
        if self._demo_mode:
            raise ActivityContextReviewError("activity_unavailable_in_demo")
        values = dict(capture)
        operation = "correct" if correction_record_id else "capture"
        proposal_hash = self._proposal_hash(
            operation=operation, capture=values, record_id=correction_record_id,
        )
        try:
            reject_secret_text(str(values.get("text", "")))
            validate_effective_at(values.get("effective_at"))
            report = self._activity.get(report_id, partition=partition)
            original_text, derivation = self._activity.resolve_finding_evidence(
                report_id, partition=partition, reference=finding_reference,
            )
            reject_secret_text(original_text)
        except (ContextCaptureError, ValueError) as exc:
            raise ActivityContextReviewError("activity_context_proposal_invalid") from exc

        with self._lock:
            existing_link = self._activity.store.context_review_link(
                report_id=report.id, partition=partition, finding_reference=finding_reference,
                proposal_hash=proposal_hash,
            )
            if existing_link is not None:
                try:
                    existing_review = self._knowledge.get_review(existing_link.review_id, partition=partition)
                except KnowledgeNotFoundError:
                    # A prior process reserved the durable retry identity but was
                    # interrupted before persisting its review. Continue below.
                    pass
                else:
                    if not self._review_matches_intent(
                        existing_review, operation=operation, capture=values, record_id=correction_record_id,
                    ):
                        raise ActivityContextReviewError("activity_context_proposal_conflict")
                    self._ensure_action(existing_link, existing_review)
                    return existing_review

            locator = f"activity/{report.id}{finding_reference}"
            evidence: dict[str, object] = {
                "source_kind": "external_activity", "locator": locator, "original_text": original_text,
                "source_origin": "external_tool", "derivation": derivation,
                "occurred_at": self._occurrence(report), "activity_id": str(report.id),
                "finding_reference": finding_reference,
                "external_origin": {
                    "client_id": report.client_id, "client_display_name": report.client_display_name,
                    "principal": report.principal,
                },
            }
            if operation == "capture":
                proposal: dict[str, object] = values
                decision = self._knowledge.store.capture_decision(partition=partition, **proposal)
                expected_revisions = decision["expected_revisions"]
                reason_codes = ("external_activity", "approval_requested", *decision["reason_codes"])
            else:
                assert correction_record_id is not None
                detail = self._knowledge.get_record(correction_record_id, partition=partition)
                proposal = {
                    "operation": operation, "record_id": str(correction_record_id), "capture": values,
                    "partition": partition, "expected_updated_at": detail.record.updated_at,
                }
                evidence["predecessor_source_ids"] = [str(link.source.id) for link in detail.source_links]
                expected_revisions = self._knowledge.store.review_snapshot(
                    partition=partition, operation=operation, proposal=proposal,
                )
                reason_codes = ("external_activity", "correction")

            link, _created = self._activity.store.reserve_context_review_link(
                report_id=report.id, partition=partition, finding_reference=finding_reference,
                proposal_hash=proposal_hash, review_id=uuid4(), action_id=str(uuid4()),
            )
            try:
                review = self._knowledge.get_review(link.review_id, partition=partition)
            except KnowledgeNotFoundError:
                review = self._knowledge.create_action_review(
                    partition=partition, operation=operation, proposal=proposal, evidence=evidence,
                    expected_revisions=expected_revisions, reason_codes=reason_codes,
                    action_id=link.action_id, review_id=link.review_id,
                )
            if not self._review_matches_intent(
                review, operation=operation, capture=values, record_id=correction_record_id,
            ):
                raise ActivityContextReviewError("activity_context_proposal_conflict")
            self._ensure_action(link, review)
            return review
