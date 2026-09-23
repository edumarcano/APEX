"""Turn selected immutable activity evidence into existing context reviews."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from uuid import UUID, uuid4

from core.activity.models import ActivityContextReviewLink
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

    @classmethod
    def _review_proposal_hash(cls, review) -> str | None:
        """Reconstruct the activity idempotency key from a frozen review."""
        if review.operation == "capture":
            capture = review.proposal
            record_id = None
        elif review.operation == "correct":
            capture = review.proposal.get("capture")
            try:
                record_id = UUID(str(review.proposal.get("record_id", "")))
            except (TypeError, ValueError):
                return None
            if not isinstance(capture, Mapping):
                return None
        else:
            return None
        if not isinstance(capture, Mapping):
            return None
        return cls._proposal_hash(operation=review.operation, capture=capture, record_id=record_id)

    @classmethod
    def _belongs_to_link(cls, review, link: ActivityContextReviewLink) -> bool:
        evidence = review.evidence
        if (
            evidence.get("activity_id") != str(link.report_id)
            or evidence.get("finding_reference") != link.finding_reference
            or cls._review_proposal_hash(review) != link.proposal_hash
        ):
            return False
        stored_hash = evidence.get("activity_proposal_hash")
        return stored_hash is None or stored_hash == link.proposal_hash

    def _latest_refreshed_review(self, link: ActivityContextReviewLink, current_review):
        """Find a deliberate refresh descended from the linked frozen proposal.

        Refreshes preserve review evidence and proposal contents. The activity
        proposal hash added to new evidence makes the association explicit;
        recomputing the hash also supports reviews created before that field was
        introduced.
        """
        if not self._belongs_to_link(current_review, link):
            return None
        candidates = self._knowledge.list_refreshed_activity_reviews(
            partition=link.partition,
            activity_id=str(link.report_id),
            finding_reference=link.finding_reference,
            proposal_hash=link.proposal_hash,
            after_created_at=current_review.created_at,
        )
        matching = [
            review for review in candidates
            if review.id != current_review.id
            and self._belongs_to_link(review, link)
        ]
        if not matching:
            return None
        return max(matching, key=lambda review: (review.created_at, str(review.id)))

    def resolve_linked_review(
        self, link: ActivityContextReviewLink, *, partition: str, update_link: bool = False,
    ):
        """Resolve the newest refreshed review and optionally advance its retry link."""
        if partition not in {"production", "sandbox"} or link.partition != partition:
            return None
        current_link = self._activity.store.context_review_link(
            report_id=link.report_id, partition=partition,
            finding_reference=link.finding_reference, proposal_hash=link.proposal_hash,
        )
        if current_link is None:
            return None
        try:
            current_review = self._knowledge.get_review(current_link.review_id, partition=partition)
        except KnowledgeNotFoundError:
            return None
        replacement = self._latest_refreshed_review(current_link, current_review)
        if replacement is None:
            return current_review
        if not update_link:
            return replacement
        rebound = self._activity.store.rebind_context_review_link(
            report_id=current_link.report_id, partition=partition,
            finding_reference=current_link.finding_reference,
            proposal_hash=current_link.proposal_hash,
            expected_review_id=current_link.review_id,
            review_id=replacement.id,
            action_id=replacement.action_id or str(uuid4()),
        )
        try:
            return self._knowledge.get_review(rebound.review_id, partition=partition)
        except KnowledgeNotFoundError:
            # Keep the old durable link usable if a concurrently removed review
            # leaves a transient pointer that cannot be read.
            return current_review

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
                existing_review = self.resolve_linked_review(
                    existing_link, partition=partition, update_link=True,
                )
                if existing_review is None:
                    # A prior process reserved the durable retry identity but was
                    # interrupted before persisting its review. Continue below.
                    pass
                else:
                    existing_link = self._activity.store.context_review_link(
                        report_id=report.id, partition=partition, finding_reference=finding_reference,
                        proposal_hash=proposal_hash,
                    ) or existing_link
                    if not self._review_matches_intent(
                        existing_review, operation=operation, capture=values, record_id=correction_record_id,
                    ):
                        raise ActivityContextReviewError("activity_context_proposal_conflict")
                    if existing_review.action_id is None:
                        self._ensure_action(existing_link, existing_review)
                        existing_review = self._knowledge.link_review_action(
                            existing_review.id, partition=partition, action_id=existing_link.action_id,
                        )
                    elif (
                        existing_review.action_id == existing_link.action_id
                        and "refresh_revalidated" not in existing_review.reason_codes
                    ):
                        self._ensure_action(existing_link, existing_review)
                    return existing_review

            locator = f"activity/{report.id}{finding_reference}"
            evidence: dict[str, object] = {
                "source_kind": "external_activity", "locator": locator, "original_text": original_text,
                "source_origin": "external_tool", "derivation": derivation,
                "occurred_at": self._occurrence(report), "activity_id": str(report.id),
                "finding_reference": finding_reference, "activity_proposal_hash": proposal_hash,
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
