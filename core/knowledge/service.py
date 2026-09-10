"""Read-oriented application service for the future Cortex context features."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

from core.knowledge.store import KnowledgeStore
from core.knowledge.capture import reject_secret_text, validate_effective_at
from core.knowledge.store import KnowledgeConflictError
from uuid import UUID

_service: "KnowledgeService | None" = None


def set_knowledge_service(service: "KnowledgeService | None") -> None:
    global _service
    _service = service


def get_knowledge_service() -> "KnowledgeService":
    if _service is None:
        raise RuntimeError("Knowledge service is unavailable.")
    return _service


class KnowledgeService:
    """Keeps future callers on a stable domain boundary."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def get_record(self, record_id, *, partition: str):
        return self.store.get_record(record_id, partition=partition)

    def list_records(self, *, partition: str, statuses=("active",), kind: str | None = None, entity_id=None, query: str = "", limit: int = 100):
        return self.store.list_records(partition=partition, statuses=statuses, kind=kind, entity_id=entity_id, query=query, limit=limit)

    def resolve_entity(self, alias: str):
        return self.store.resolve_entity(alias)

    def entities_mentioned_in(self, text: str):
        return self.store.entities_mentioned_in(text)

    def one_hop_relationships(self, entity_id, *, partition: str):
        return self.store.one_hop_relationships(entity_id, partition=partition)

    def affected_revisions(self, record_id, *, partition: str):
        return self.store.affected_revisions(record_id, partition=partition)

    def get_entity(self, entity_id, *, include_merged: bool = False):
        return self.store.get_entity(entity_id, include_merged=include_merged)

    def list_entities(self, *, query: str = "", limit: int = 50):
        return self.store.list_entities(query=query, limit=limit)

    def list_entities_in_partition(self, *, partition: str, query: str = "", limit: int = 50):
        return self.store.list_entities_in_partition(partition=partition, query=query, limit=limit)

    def entity_in_partition(self, entity_id, *, partition: str):
        return self.store.entity_in_partition(entity_id, partition=partition)

    def aliases_for_entity(self, entity_id):
        return self.store.aliases_for_entity(entity_id)

    def save_operator_context(self, *, partition: str, values: dict[str, object], sensitive: bool = False, idempotency_key: str | None = None):
        """Apply unambiguous operator input or persist a reviewable challenge."""
        reject_secret_text(str(values.get("text", "")))
        validate_effective_at(values.get("effective_at"))
        return self.store.submit_operator(
            partition=partition, values=values, sensitive=sensitive,
            idempotency_key=idempotency_key,
        )

    def correct_operator_context(self, *, partition: str, record_id: str, expected_updated_at: str, values: dict[str, object], sensitive: bool, idempotency_key: str | None):
        reject_secret_text(str(values.get("text", "")))
        return self.store.submit_operator(
            partition=partition, values=values, sensitive=sensitive,
            idempotency_key=idempotency_key, correction_record_id=record_id,
            expected_updated_at=expected_updated_at,
        )

    def create_action_review(self, *, partition: str, operation: str, proposal: dict[str, object], evidence: dict[str, object], expected_revisions: dict[str, str], reason_codes: tuple[str, ...], action_id: str):
        return self.store.create_review(
            partition=partition, operation=operation, proposal=proposal, evidence=evidence,
            expected_revisions=expected_revisions, reason_codes=reason_codes, action_id=action_id,
        )

    def get_review(self, review_id, *, partition: str):
        return self.store.get_review(review_id, partition=partition)

    def review_for_action(self, action_id: str, *, partition: str):
        return self.store.review_for_action(action_id, partition=partition)

    def link_review_action(self, review_id, *, partition: str, action_id: str):
        return self.store.link_review_action(review_id, partition=partition, action_id=action_id)

    def list_reviews(self, *, partition: str, decisions=("pending",), limit: int = 50):
        return self.store.list_reviews(partition=partition, decisions=decisions, limit=limit)

    def accept_review(self, review_id, *, partition: str, action_id: str | None = None):
        return self.store.accept_review(review_id, partition=partition, action_id=action_id)

    def reject_review(self, review_id, *, partition: str):
        return self.store.reject_review(review_id, partition=partition)

    def refresh_review(self, review_id, *, partition: str):
        return self.store.refresh_review(review_id, partition=partition)

    @staticmethod
    def _attempt_arguments(review) -> dict[str, object]:
        arguments = dict(review.proposal)
        arguments["operation"] = review.operation
        arguments["partition"] = review.partition
        arguments["review_id"] = str(review.id)
        if review.operation == "capture":
            arguments["_apex_provenance"] = {
                "source_kind": review.evidence["source_kind"], "partition": review.partition,
                "original_text": review.evidence["original_text"],
                "occurred_at": review.evidence.get("occurred_at"),
            }
        return arguments

    def _create_or_get_attempt(self, actions, review, *, replace: bool = False):
        """Reserve one review attempt before creating its executable action row."""
        reservation = self.store.reserve_review_attempt(
            review.id, partition=review.partition, action_id=str(uuid4()), replace=replace,
        )
        if reservation.decision != "pending":
            return None
        action_id = reservation.action_id
        assert action_id is not None
        try:
            return actions.get(action_id)
        except Exception as exc:
            from core.actions.store import ActionNotFoundError

            if not isinstance(exc, ActionNotFoundError):
                raise
        capability = "remember_personal_context" if reservation.operation == "capture" else "reconcile_personal_context"
        return actions.propose(
            agent_key="operator", capability_name=capability,
            arguments=self._attempt_arguments(reservation), target="Personal Context",
            risk="destructive" if reservation.operation == "retract" else "write",
            summary=f"Approve personal context {reservation.operation.replace('_', ' ')}",
            actor="operator", action_id=action_id,
        )

    @staticmethod
    def _definitive_missing(actions, action) -> bool:
        """Only a capability verifier's explicit missing result permits replacement."""
        events = actions.events(action.action_id)
        return bool(events and str(events[-1].result_code).endswith("_missing"))

    def decide_review_accept(self, actions, review_id, *, partition: str, expected_revisions: Mapping[str, str]):
        """Run one review acceptance through the action lifecycle with safe retries."""
        review = self.store.prepare_review_decision(
            review_id, partition=partition, expected_revisions=expected_revisions,
        )
        if review.decision == "rejected":
            raise KnowledgeConflictError("review_decided")
        action = self._create_or_get_attempt(actions, review) if review.decision == "pending" else None
        if review.decision == "accepted":
            if review.action_id is None:
                return review
            action = actions.get(review.action_id)
            if action.status in {"outcome_unknown", "verification_failed"}:
                checked = actions.retry_verification(action.action_id, actor="operator", expected_version=action.version)
                if checked.status != "verified":
                    raise KnowledgeConflictError("review_verification_required")
            return self.store.get_review(review_id, partition=partition)
        assert action is not None
        if action.status == "expired":
            review = self.store.prepare_review_decision(review_id, partition=partition, expected_revisions=expected_revisions)
            action = self._create_or_get_attempt(actions, review, replace=True)
            assert action is not None
        elif action.status in {"outcome_unknown", "verification_failed"}:
            checked = actions.retry_verification(action.action_id, actor="operator", expected_version=action.version)
            if checked.status == "verified":
                return self.store.get_review(review_id, partition=partition)
            if not self._definitive_missing(actions, checked):
                raise KnowledgeConflictError("review_verification_required")
            review = self.store.prepare_review_decision(review_id, partition=partition, expected_revisions=expected_revisions)
            action = self._create_or_get_attempt(actions, review, replace=True)
            assert action is not None
        elif action.status in {"executing", "verifying"}:
            raise KnowledgeConflictError("review_verification_required")
        if action.status not in {"proposed", "approved"}:
            raise KnowledgeConflictError("review_decided")
        result = actions.approve_and_execute(action.action_id, actor="operator", expected_version=action.version)
        if result.status == "expired":
            review = self.store.prepare_review_decision(
                review_id, partition=partition, expected_revisions=expected_revisions,
            )
            action = self._create_or_get_attempt(actions, review, replace=True)
            assert action is not None
            result = actions.approve_and_execute(
                action.action_id, actor="operator", expected_version=action.version,
            )
        if result.status == "verified":
            return self.store.get_review(review_id, partition=partition)
        if result.status in {"outcome_unknown", "verifying", "verification_failed"}:
            raise KnowledgeConflictError("review_verification_required")
        raise KnowledgeConflictError("review_execution_failed")

    def decide_review_reject(self, actions, review_id, *, partition: str, expected_revisions: Mapping[str, str]):
        """Reject a review and its active proposal; retries finish a partial rejection."""
        review = self.store.prepare_review_decision(
            review_id, partition=partition, expected_revisions=expected_revisions,
        )
        if review.decision in {"accepted", "rejected"}:
            return review
        if review.action_id:
            try:
                action = actions.get(review.action_id)
            except Exception as exc:
                from core.actions.store import ActionNotFoundError

                if not isinstance(exc, ActionNotFoundError):
                    raise
            else:
                if action.status == "proposed":
                    actions.reject(action.action_id, actor="operator", expected_version=action.version)
                elif action.status not in {"rejected", "expired"}:
                    raise KnowledgeConflictError("review_verification_required")
        return self.store.reject_review(review_id, partition=partition)

    def decide_review_refresh(self, review_id, *, partition: str, expected_revisions: Mapping[str, str]):
        return self.store.refresh_review(
            review_id, partition=partition, expected_revisions=expected_revisions,
        )

    def approve_linked_action(self, actions, action_id: str, *, expected_version: int):
        """Route generic approval through the durable review lifecycle."""
        action = actions.get(action_id)
        if action.version != expected_version:
            from core.actions.store import ActionConflictError

            raise ActionConflictError("Action has changed since it was read.")
        provenance = action.proposal.arguments.get("_apex_provenance", {})
        partition = str(action.proposal.arguments.get("partition") or (
            provenance.get("partition", "") if isinstance(provenance, Mapping) else ""
        ))
        if not partition:
            return actions.approve_and_execute(action_id, actor="operator", expected_version=expected_version)
        review = self.store.review_for_action(action_id, partition=partition)
        if review is None:
            return actions.approve_and_execute(action_id, actor="operator", expected_version=expected_version)
        accepted = self.decide_review_accept(
            actions, review.id, partition=partition, expected_revisions=review.expected_revisions,
        )
        if accepted.action_id is None:
            return actions.get(action_id)
        return actions.get(accepted.action_id)

    def reject_linked_action(self, actions, action_id: str, *, expected_version: int):
        """Resolve generic action rejection through the same durable review decision."""
        action = actions.get(action_id)
        if action.version != expected_version:
            from core.actions.store import ActionConflictError

            raise ActionConflictError("Action has changed since it was read.")
        provenance = action.proposal.arguments.get("_apex_provenance", {})
        partition = str(action.proposal.arguments.get("partition") or (
            provenance.get("partition", "") if isinstance(provenance, Mapping) else ""
        ))
        if not partition:
            return actions.reject(action_id, actor="operator", expected_version=expected_version)
        review = self.store.review_for_action(action_id, partition=partition)
        if review is None:
            return actions.reject(action_id, actor="operator", expected_version=expected_version)
        if review.decision == "pending":
            # A prior action rejection may have committed before the review
            # write failed.  This retry intentionally completes that decision.
            self.decide_review_reject(
                actions, review.id, partition=partition, expected_revisions=review.expected_revisions,
            )
        return actions.get(action_id)

    def pending_reviews_for_record(self, record_id, *, partition: str):
        return self.store.pending_reviews_for_record(record_id, partition=partition)
