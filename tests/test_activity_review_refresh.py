"""Regression coverage for activity links after a context review is refreshed."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from core.activity.models import ActivityReportContent
from core.activity.review import ActivityContextReviewService
from core.activity.service import ActivityService
from core.activity.store import ActivityStore
from core.actions import ActionService, ActionStore
from core.api.routers import activity as activity_router
from core.knowledge import KnowledgeService, KnowledgeStore
from core.knowledge.capture import CAPABILITY_NAME, ContextCaptureExecutor, ContextCaptureVerifier
from core.knowledge.store import KnowledgeConflictError
from core.knowledge.reconciliation import (
    CAPABILITY_NAME as RECONCILIATION_CAPABILITY_NAME,
    ContextReconciliationExecutor,
    ContextReconciliationVerifier,
)
from core.retrieval.store import RetrievalStore


class ActivityReviewRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path.cwd() / f".activity-review-refresh-{uuid4().hex}.db"
        RetrievalStore(self.path).initialize()
        self.knowledge_store = KnowledgeStore(self.path)
        self.knowledge_store.initialize()
        self.activity_store = ActivityStore(self.path)
        self.activity_store.initialize()
        self.activity = ActivityService(self.activity_store)
        self.actions = ActionService(ActionStore(self.path))
        conversations = SimpleNamespace()
        self.actions.register_handler(
            CAPABILITY_NAME,
            executor=ContextCaptureExecutor(self.knowledge_store, conversations),
            verifier=ContextCaptureVerifier(self.knowledge_store),
        )
        self.actions.register_handler(
            RECONCILIATION_CAPABILITY_NAME,
            executor=ContextReconciliationExecutor(self.knowledge_store),
            verifier=ContextReconciliationVerifier(self.knowledge_store),
        )
        self.knowledge = KnowledgeService(self.knowledge_store)
        self.reviews = ActivityContextReviewService(self.activity, self.knowledge, self.actions)

    def tearDown(self) -> None:
        self.activity_store.close()
        self.knowledge_store.close()
        for suffix in ("", "-shm", "-wal"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    def _report(self, *, partition: str = "production"):
        return self.activity.submit(
            client_id="codex", principal="operator", partition=partition,
            content=ActivityReportContent(
                submission_key=f"refresh-{partition}", title="Review branch", task_status="completed",
                outcome="A focused review was completed.", findings=[{"text": "The project is active."}],
            ),
        ).report

    @staticmethod
    def _capture() -> dict[str, object]:
        return {
            "kind": "fact", "text": "The project is active.", "subject": "Project",
            "predicate": "status", "object_entity": None, "object_value": "active", "effective_at": None,
        }

    def _list_activity_reviews(self, report_id, *, partition: str = "production"):
        with (
            mock.patch.object(activity_router, "get_activity_service", return_value=self.activity),
            mock.patch.object(activity_router, "get_knowledge_service", return_value=self.knowledge),
            mock.patch.object(activity_router, "get_action_service", return_value=self.actions),
            mock.patch.object(
                activity_router, "get_conversation_service",
                return_value=SimpleNamespace(partition=lambda: partition),
            ),
        ):
            return activity_router.list_activity_context_reviews(report_id)

    def _remove_activity_proposal_hash(self, review_id) -> None:
        """Model evidence written by an earlier beta.4 build."""
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                row = connection.execute(
                    "SELECT evidence_json FROM knowledge_reviews WHERE id=?", (str(review_id),),
                ).fetchone()
                evidence = json.loads(row[0])
                evidence.pop("activity_proposal_hash", None)
                connection.execute(
                    "UPDATE knowledge_reviews SET evidence_json=? WHERE id=?",
                    (json.dumps(evidence, sort_keys=True, separators=(",", ":")), str(review_id)),
                )
        finally:
            connection.close()

    def test_inbox_and_identical_retry_follow_refreshed_review_through_acceptance(self) -> None:
        report = self._report()
        capture = self._capture()
        stale = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
        )
        self._remove_activity_proposal_hash(stale.id)
        # Creating the previously unknown alias changes the frozen capture snapshot.
        self.knowledge_store.create_entity("Project")
        with self.assertRaisesRegex(KnowledgeConflictError, "review_refresh_required"):
            self.knowledge.decide_review_accept(
                self.actions, stale.id, partition="production", expected_revisions=stale.expected_revisions,
            )
        replacement = self.knowledge.decide_review_refresh(
            stale.id, partition="production", expected_revisions=stale.expected_revisions,
        )
        self.assertEqual(self.knowledge.get_review(stale.id, partition="production").decision, "stale")
        self.assertEqual((replacement.decision, replacement.reason_codes[-1]), ("pending", "refresh_revalidated"))
        for index in range(110):
            self.knowledge_store.create_review(
                partition="production", operation="capture",
                proposal={
                    "kind": "note", "text": f"Unrelated context proposal {index}",
                    "subject": None, "predicate": None, "object_entity": None,
                    "object_value": None, "effective_at": None,
                },
                evidence={}, expected_revisions={}, reason_codes=("manual_review",),
            )
        self.assertNotIn(
            replacement.id,
            {
                review.id for review in self.knowledge.list_reviews(
                    partition="production", decisions=("pending", "accepted", "rejected", "stale"), limit=100,
                )
            },
        )

        inbox_reviews = self._list_activity_reviews(report.id)
        self.assertEqual(len(inbox_reviews), 1)
        self.assertEqual((inbox_reviews[0].review.id, inbox_reviews[0].review.decision), (str(replacement.id), "pending"))
        link = self.activity_store.context_review_link(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            proposal_hash=self.reviews._proposal_hash(
                operation="capture", capture=capture, record_id=None,
            ),
        )
        self.assertEqual(link.review_id, stale.id)

        accepted = self.knowledge.decide_review_accept(
            self.actions, replacement.id, partition="production", expected_revisions=replacement.expected_revisions,
        )
        self.assertEqual(accepted.decision, "accepted")
        retried = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
        )
        self.assertEqual((retried.id, retried.decision), (replacement.id, "accepted"))
        updated_link = self.activity_store.context_review_link(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            proposal_hash=self.reviews._proposal_hash(
                operation="capture", capture=capture, record_id=None,
            ),
        )
        self.assertEqual(updated_link.review_id, replacement.id)

    def test_refresh_association_does_not_cross_knowledge_partitions(self) -> None:
        report = self._report()
        capture = self._capture()
        linked = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
        )
        self.knowledge_store.create_review(
            partition="sandbox", operation="capture", proposal=capture,
            evidence={
                **linked.evidence,
                "activity_proposal_hash": self.reviews._proposal_hash(
                    operation="capture", capture=capture, record_id=None,
                ),
            },
            expected_revisions={}, reason_codes=("external_activity", "refresh_revalidated"),
        )

        inbox_reviews = self._list_activity_reviews(report.id, partition="production")
        self.assertEqual([item.review.id for item in inbox_reviews], [str(linked.id)])
        self.assertEqual(inbox_reviews[0].review.partition, "production")

    def test_corrected_proposal_retry_matches_after_refresh_updates_expected_record_revision(self) -> None:
        original, _source, _outcome = self.knowledge_store.apply_capture(
            action_id="seed-project-status", partition="production", source_kind="manual",
            locator="manual/project-status", original_text="Project status is paused.",
            kind="fact", text="Project status is paused.", subject="Project",
            predicate="status", object_value="paused", derivation="direct",
        )
        report = self._report()
        capture = self._capture()
        stale = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            capture=capture, correction_record_id=original.id,
        )
        self.knowledge_store.set_status(original.id, partition="production", status="conflicting")
        restored = self.knowledge_store.set_status(original.id, partition="production", status="active")
        self.assertNotEqual(stale.proposal["expected_updated_at"], restored.updated_at)

        replacement = self.knowledge.decide_review_refresh(
            stale.id, partition="production", expected_revisions=stale.expected_revisions,
        )
        self.assertEqual(replacement.proposal["expected_updated_at"], restored.updated_at)
        retried = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            capture=capture, correction_record_id=original.id,
        )
        self.assertEqual((retried.id, retried.decision), (replacement.id, "pending"))
