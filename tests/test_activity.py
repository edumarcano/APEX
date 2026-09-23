"""Focused persistence, service, API, and CLI coverage for external activity."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from core.activity import (
    ActivityConflictError,
    ActivityReportContent,
    ActivitySubmissionRequest,
    ActivityService,
    ActivityStore,
    ActivityStoreError,
)
from core.activity.review import ActivityContextReviewError, ActivityContextReviewService
from core.activity.mailbox import MailboxStatus
from core.actions import ActionService, ActionStore
from core.knowledge import KnowledgeService, KnowledgeStore
from core.knowledge.capture import CAPABILITY_NAME, ContextCaptureExecutor, ContextCaptureVerifier
from core.knowledge.reconciliation import (
    CAPABILITY_NAME as RECONCILIATION_CAPABILITY_NAME,
    ContextReconciliationExecutor,
    ContextReconciliationVerifier,
)
from core.retrieval.store import RetrievalStore
from core.api.app import app
from core.api.routers import activity as activity_router
from src.apex import cli

def _report(*, key: str = "report-1", outcome: str = "Done") -> ActivityReportContent:
    return ActivityReportContent(
        submission_key=key, title="Review branch", task_status="completed", outcome=outcome,
        findings=[{"text": "All focused checks passed."}],
    )


def _activity_request(payload: dict[str, object]) -> Request:
    body = json.dumps(payload).encode("utf-8")
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http", "http_version": "1.1", "method": "POST",
            "scheme": "http", "path": "/api/v1/activity/reports",
            "raw_path": b"/api/v1/activity/reports", "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:8000"), (b"content-type", b"application/json")],
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
        },
        receive,
    )


class ActivityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ActivityStore(None)
        self.store.initialize()
        self.service = ActivityService(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def test_submission_is_idempotent_and_conflicting_reuse_is_rejected(self) -> None:
        first = self.service.submit(client_id="codex", principal="operator", partition="production", content=_report())
        retry = self.service.submit(client_id="codex", principal="operator", partition="production", content=_report())

        self.assertFalse(first.duplicate)
        self.assertTrue(retry.duplicate)
        self.assertEqual(first.report.id, retry.report.id)
        self.assertEqual(len(self.service.list(partition="production")), 1)
        with self.assertRaises(ActivityConflictError):
            self.service.submit(client_id="codex", principal="operator", partition="production", content=_report(outcome="Changed"))

    def test_concurrent_duplicate_submissions_create_one_receipt(self) -> None:
        def submit():
            return self.service.submit(client_id="codex", principal="operator", partition="production", content=_report(key="concurrent"))

        with ThreadPoolExecutor(max_workers=6) as executor:
            receipts = list(executor.map(lambda _: submit(), range(6)))
        self.assertEqual({receipt.report.id for receipt in receipts}, {receipts[0].report.id})
        self.assertEqual(sum(not receipt.duplicate for receipt in receipts), 1)
        self.assertEqual(len(self.service.list(partition="production")), 1)

    def test_separate_store_connections_share_the_duplicate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.db"
            first = ActivityStore(path)
            second = ActivityStore(path)
            first.initialize()
            second.initialize()
            first_service = ActivityService(first)
            second_service = ActivityService(second)

            with ThreadPoolExecutor(max_workers=2) as executor:
                receipts = list(executor.map(
                    lambda service: service.submit(client_id="codex", principal="operator", partition="production", content=_report(key="cross-connection")),
                    (first_service, second_service),
                ))
            self.assertEqual({receipt.report.id for receipt in receipts}, {receipts[0].report.id})
            self.assertEqual(sum(not receipt.duplicate for receipt in receipts), 1)
            first.close()
            second.close()

    def test_restart_retains_immutable_report_and_receipt_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.db"
            first_store = ActivityStore(path)
            first_store.initialize()
            first_service = ActivityService(first_store)
            receipt = first_service.submit(client_id="codex", principal="operator", partition="production", content=_report())
            first_store.close()

            reopened_store = ActivityStore(path)
            reopened_store.initialize()
            report = reopened_store.get(receipt.report.id, partition="production")
            self.assertEqual(report.content.outcome, "Done")
            self.assertEqual(report.client_display_name, "codex")
            self.assertEqual(report.disposition, "new")
            reopened_store.close()

    def test_source_id_uses_the_shared_lowercase_identifier_contract(self) -> None:
        receipt = self.service.submit(
            client_id="grok-bot_2", principal="operator", partition="production", content=_report(),
        )
        self.assertEqual(receipt.report.client_display_name, "grok-bot_2")
        with self.assertRaises(ActivityStoreError):
            self.service.submit(
                client_id="Grok Bot", principal="operator", partition="production", content=_report(key="bad-id"),
            )
        with self.assertRaises(ValidationError):
            ActivitySubmissionRequest.model_validate({
                "client_id": "Grok Bot", "report": _report(key="bad-envelope").model_dump(mode="json"),
            })

    def test_source_id_is_part_of_the_idempotency_scope(self) -> None:
        codex = self.service.submit(
            client_id="codex", principal="operator", partition="production", content=_report(key="same-key"),
        )
        grok = self.service.submit(
            client_id="grok-bot", principal="operator", partition="production", content=_report(key="same-key"),
        )
        self.assertNotEqual(codex.report.id, grok.report.id)
        self.assertEqual({item.client_id for item in self.service.list(partition="production")}, {"codex", "grok-bot"})

    def test_existing_display_name_snapshots_are_preserved(self) -> None:
        self.store.submit(
            partition="production", client_id="codex", client_display_name="Codex",
            principal="operator", content=_report(key="legacy"),
        )
        listed = self.service.list(partition="production")
        self.assertEqual(listed[0].client_display_name, "Codex")

    def test_disposition_is_reversible_without_mutating_the_report(self) -> None:
        report = self.service.submit(
            client_id="codex", principal="operator", partition="production", content=_report(),
        ).report
        dismissed = self.service.set_disposition(
            report.id, partition="production", disposition="dismissed",
        )
        reopened = self.service.set_disposition(
            report.id, partition="production", disposition="new",
        )
        self.assertEqual((dismissed.disposition, reopened.disposition), ("dismissed", "new"))
        self.assertEqual(reopened.content.model_dump(), report.content.model_dump())

    def test_oversized_serialized_report_is_rejected_before_storage(self) -> None:
        large = ActivityReportContent(
            submission_key="large", title="Large", task_status="completed", outcome="Done",
            artifact_references=["a" * 2048 for _ in range(100)], markdown_body="m" * 200_000,
        )
        with self.assertRaisesRegex(ActivityStoreError, "report_too_large"):
            self.service.submit(client_id="codex", principal="operator", partition="production", content=large)
        self.assertEqual(self.service.list(partition="production"), [])

    def test_finding_references_resolve_only_immutable_report_locations(self) -> None:
        receipt = self.service.submit(client_id="codex", principal="operator", partition="production", content=_report())
        self.assertEqual(
            self.service.resolve_finding_reference(receipt.report.id, partition="production", reference="/findings/0"),
            "All focused checks passed.",
        )
        with self.assertRaisesRegex(ValueError, "finding_reference_invalid"):
            self.service.resolve_finding_reference(receipt.report.id, partition="production", reference="/outcome")

        markdown_body = "\n# Notes\n\n"
        fallback = ActivityReportContent(
            submission_key="fallback", title="Fallback", task_status="completed",
            outcome="No findings", markdown_body=markdown_body,
        )
        fallback_receipt = self.service.submit(
            client_id="codex", principal="operator", partition="production", content=fallback,
        )
        self.assertEqual(
            self.service.resolve_finding_reference(
                fallback_receipt.report.id, partition="production", reference="/outcome",
            ),
            "No findings",
        )
        self.assertEqual(
            self.service.resolve_finding_reference(
                fallback_receipt.report.id, partition="production", reference="/markdown_body",
            ),
            markdown_body,
        )

class ActivityContextReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "activity-review.db"
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
        self.tempdir.cleanup()

    def _receipt(self):
        return self.activity.submit(
            client_id="codex", principal="operator", partition="production",
            content=_report(),
        ).report

    def _table_count(self, table: str) -> int:
        connection = sqlite3.connect(self.path)
        try:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()

    def test_finding_proposal_is_pending_idempotent_and_preserves_external_evidence(self) -> None:
        report = self._receipt()
        capture = {"kind": "fact", "text": "Focused checks passed.", "subject": None,
                   "predicate": None, "object_entity": None, "object_value": None, "effective_at": None}
        first = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
        )
        retry = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
        )
        self.assertEqual(first.id, retry.id)
        self.assertEqual(first.decision, "pending")
        self.assertEqual(self.knowledge.list_records(partition="production"), [])
        self.assertEqual(first.evidence["source_kind"], "external_activity")
        self.assertEqual(first.evidence["original_text"], "All focused checks passed.")
        accepted = self.knowledge.decide_review_accept(
            self.actions, first.id, partition="production", expected_revisions=first.expected_revisions,
        )
        self.assertEqual(accepted.decision, "accepted")
        record = self.knowledge.list_records(partition="production")[0]
        source = self.knowledge.get_record(record.id, partition="production").source_links[0].source
        self.assertEqual((source.kind, source.origin, source.original_text), (
            "external_activity", "external_tool", "All focused checks passed.",
        ))

    def test_external_finding_can_correct_existing_context_through_review(self) -> None:
        original, _source, _outcome = self.knowledge_store.apply_capture(
            action_id="seed", partition="production", source_kind="manual", locator="manual/seed",
            original_text="The project is paused.", kind="fact", text="The project is paused.",
            subject="Project", predicate="status", object_value="paused", derivation="direct",
        )
        report = self._receipt()
        review = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            capture={"kind": "fact", "text": "The project is active.", "subject": "Project",
                     "predicate": "status", "object_entity": None, "object_value": "active", "effective_at": None},
            correction_record_id=original.id,
        )
        self.assertEqual((review.operation, review.decision), ("correct", "pending"))
        accepted = self.knowledge.decide_review_accept(
            self.actions, review.id, partition="production", expected_revisions=review.expected_revisions,
        )
        self.assertEqual(accepted.decision, "accepted")
        records = self.knowledge.list_records(partition="production", statuses=("active",))
        self.assertEqual([record.text for record in records], ["The project is active."])

        retry = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            capture={"kind": "fact", "text": "The project is active.", "subject": "Project",
                     "predicate": "status", "object_entity": None, "object_value": "active", "effective_at": None},
            correction_record_id=original.id,
        )
        self.assertEqual((retry.id, retry.decision), (review.id, "accepted"))
        self.assertEqual(self._table_count("activity_context_review_links"), 1)
        self.assertEqual(self._table_count("knowledge_reviews"), 1)
        self.assertEqual(self._table_count("actions"), 1)

    def test_secret_external_evidence_is_rejected_before_linking_or_review(self) -> None:
        report = self.activity.submit(
            client_id="codex", principal="operator", partition="production",
            content=ActivityReportContent(
                submission_key="secret-evidence", title="Unsafe", task_status="completed", outcome="Done",
                findings=[{"text": "api_key=not-for-context"}],
            ),
        ).report
        with self.assertRaises(ActivityContextReviewError):
            self.reviews.propose(
                report_id=report.id, partition="production", finding_reference="/findings/0",
                capture={"kind": "note", "text": "Use this result.", "subject": None,
                         "predicate": None, "object_entity": None, "object_value": None, "effective_at": None},
            )
        self.assertEqual(self._table_count("activity_context_review_links"), 0)
        self.assertEqual(self._table_count("knowledge_reviews"), 0)
        self.assertEqual(self._table_count("actions"), 0)

    def test_retry_recovers_an_interrupted_review_or_action_creation(self) -> None:
        report = self._receipt()
        capture = {"kind": "note", "text": "Keep this result.", "subject": None,
                   "predicate": None, "object_entity": None, "object_value": None, "effective_at": None}
        proposal_hash = self.reviews._proposal_hash(operation="capture", capture=capture, record_id=None)
        reserved, created = self.activity_store.reserve_context_review_link(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            proposal_hash=proposal_hash, review_id=uuid4(), action_id=str(uuid4()),
        )
        self.assertTrue(created)
        recovered_review = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
        )
        self.assertEqual(recovered_review.id, reserved.review_id)
        self.assertEqual(self.actions.get(reserved.action_id).action_id, reserved.action_id)

        connection = sqlite3.connect(self.path)
        try:
            with connection:
                connection.execute("DELETE FROM action_events WHERE action_id=?", (reserved.action_id,))
                connection.execute("DELETE FROM actions WHERE action_id=?", (reserved.action_id,))
        finally:
            connection.close()
        retried_review = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
        )
        self.assertEqual(retried_review.id, recovered_review.id)
        self.assertEqual(self.actions.get(reserved.action_id).action_id, reserved.action_id)

    def test_concurrent_service_instances_share_the_reserved_action(self) -> None:
        report = self._receipt()
        capture = {"kind": "note", "text": "Keep this result.", "subject": None,
                   "predicate": None, "object_entity": None, "object_value": None, "effective_at": None}
        barrier = threading.Barrier(2)
        delegate = self.actions

        class _BarrierActions:
            def __init__(self) -> None:
                self._waited = threading.local()

            def get(self, action_id: str):
                from core.actions.store import ActionNotFoundError

                try:
                    return delegate.get(action_id)
                except ActionNotFoundError:
                    if not getattr(self._waited, "missing_action", False):
                        self._waited.missing_action = True
                        barrier.wait(timeout=5)
                    raise

            def propose(self, **kwargs):
                return delegate.propose(**kwargs)

        guarded_actions = _BarrierActions()
        services = (
            ActivityContextReviewService(self.activity, self.knowledge, guarded_actions),
            ActivityContextReviewService(self.activity, self.knowledge, guarded_actions),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            reviews = list(executor.map(
                lambda service: service.propose(
                    report_id=report.id, partition="production", finding_reference="/findings/0", capture=capture,
                ),
                services,
            ))
        self.assertEqual({review.id for review in reviews}, {reviews[0].id})
        self.assertEqual(self._table_count("activity_context_review_links"), 1)
        self.assertEqual(self._table_count("knowledge_reviews"), 1)
        self.assertEqual(self._table_count("actions"), 1)

    def test_declared_model_finding_keeps_model_interpretation_derivation(self) -> None:
        report = self.activity.submit(
            client_id="codex", principal="operator", partition="production",
            content=ActivityReportContent(
                submission_key="model-finding", title="Model result", task_status="completed", outcome="Done",
                findings=[{"text": "The model inferred a preference.", "derivation": "model_interpretation"}],
                occurred_at="2026-09-21T12:00:00+00:00",
            ),
        ).report
        review = self.reviews.propose(
            report_id=report.id, partition="production", finding_reference="/findings/0",
            capture={"kind": "preference", "text": "Prefer short updates.", "subject": None,
                     "predicate": None, "object_entity": None, "object_value": None, "effective_at": None},
        )
        self.assertEqual(
            (review.evidence["derivation"], review.evidence["occurred_at"]),
            ("model_interpretation", "2026-09-21T12:00:00+00:00"),
        )


class ActivityAsyncSubmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = ActivityStore(None)
        self.store.initialize()
        self.service = ActivityService(self.store)

    def tearDown(self) -> None:
        self.store.close()

    async def test_json_submission_keeps_event_loop_responsive_during_storage(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class BlockingService:
            def submit(_self, **kwargs):
                entered.set()
                release.wait(3)
                try:
                    return self.service.submit(**kwargs)
                finally:
                    finished.set()

        conversation = SimpleNamespace(partition=lambda: "production")
        request = _activity_request({
            "client_id": "codex", "report": _report(key="async-api").model_dump(mode="json"),
        })
        with mock.patch.object(activity_router, "DEMO_MODE", False), mock.patch.object(
            activity_router, "get_activity_service", return_value=BlockingService(),
        ), mock.patch.object(activity_router, "get_conversation_service", return_value=conversation):
            submission = asyncio.create_task(activity_router.submit_activity_report(request))
            self.assertTrue(await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), timeout=4))
            loop_progress = asyncio.Event()
            asyncio.get_running_loop().call_soon(loop_progress.set)
            try:
                await asyncio.wait_for(loop_progress.wait(), timeout=1)
                self.assertFalse(finished.is_set(), "storage completed before the event loop could progress")
            finally:
                release.set()
            response = await submission

        self.assertFalse(response.duplicate)
        self.assertEqual(response.report.outcome, "Done")
        self.assertEqual(len(self.service.list(partition="production")), 1)


class ActivityApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=True)
        self.store = ActivityStore(None)
        self.store.initialize()
        self.service = ActivityService(self.store)

    def tearDown(self) -> None:
        self.store.close()

    def test_mailbox_status_and_scan_use_only_the_configured_folder(self) -> None:
        status = MailboxStatus(
            enabled=True, state="ready", folder_available=True,
            last_scan_at="2026-09-21T00:00:00+00:00",
            last_imported_count=1, last_error=None,
        )
        mailbox = SimpleNamespace(
            status=mock.Mock(return_value=status),
            scan_now=mock.AsyncMock(return_value=status),
        )
        with mock.patch.object(activity_router, "get_activity_mailbox", return_value=mailbox):
            current = self.client.get("/api/v1/activity/mailbox/status")
            scanned = self.client.post(
                "/api/v1/activity/mailbox/scan",
                json={"folder_path": "C:\\caller-selected-folder"},
            )

        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["state"], "ready")
        self.assertEqual(scanned.status_code, 200)
        self.assertEqual(scanned.json()["last_imported_count"], 1)
        mailbox.scan_now.assert_awaited_once_with()

    def test_local_submission_list_and_detail_stay_in_current_partition(self) -> None:
        conversation = SimpleNamespace(partition=lambda: "production")
        payload = {"client_id": "codex", "report": _report().model_dump(mode="json")}
        with mock.patch.object(activity_router, "DEMO_MODE", False), mock.patch.object(activity_router, "get_activity_service", return_value=self.service), mock.patch.object(activity_router, "get_conversation_service", return_value=conversation):
            created = self.client.post(
                "/api/v1/activity/reports",
                headers={"Host": "127.0.0.1:8000"},
                json=payload,
            )
            listed = self.client.get("/api/v1/activity/reports?disposition=new")
            detail = self.client.get(f"/api/v1/activity/reports/{created.json()['id']}")

        self.assertEqual(created.status_code, 201)
        self.assertFalse(created.json()["duplicate"])
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(detail.json()["report"]["findings"][0]["text"], "All focused checks passed.")

    def test_demo_submission_is_rejected_without_reaching_store(self) -> None:
        with mock.patch.object(activity_router, "DEMO_MODE", True):
            response = self.client.post(
                "/api/v1/activity/reports",
                headers={"Host": "127.0.0.1:8000"},
                json={"client_id": "codex", "report": _report().model_dump(mode="json")},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.service.list(partition="production"), [])

    def test_submission_rejects_invalid_claimed_source_id_at_the_http_boundary(self) -> None:
        with mock.patch.object(activity_router, "DEMO_MODE", False):
            response = self.client.post(
                "/api/v1/activity/reports",
                headers={"Host": "127.0.0.1:8000"},
                json={"client_id": "Grok Bot", "report": _report().model_dump(mode="json")},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.list(partition="production"), [])

    def test_local_submission_rejects_untrusted_origin_and_oversized_body(self) -> None:
        payload = {"client_id": "codex", "report": _report().model_dump(mode="json")}
        with mock.patch.object(activity_router, "DEMO_MODE", False):
            origin = self.client.post(
                "/api/v1/activity/reports",
                headers={"Host": "127.0.0.1:8000", "Origin": "http://outside.example"},
                json=payload,
            )
            oversized = self.client.post(
                "/api/v1/activity/reports",
                headers={"Host": "127.0.0.1:8000", "Content-Type": "application/json"},
                content=b"x" * (256 * 1024 + 1),
            )
        self.assertEqual(origin.status_code, 403)
        self.assertEqual(oversized.status_code, 413)

    def test_operator_can_create_a_pending_review_from_server_resolved_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity-api-review.db"
            RetrievalStore(path).initialize()
            knowledge_store = KnowledgeStore(path)
            knowledge_store.initialize()
            activity_store = ActivityStore(path)
            activity_store.initialize()
            activity_service = ActivityService(activity_store)
            report = activity_service.submit(
                client_id="codex", principal="operator", partition="production", content=_report(),
            ).report
            actions = ActionService(ActionStore(path))
            conversations = SimpleNamespace()
            actions.register_handler(
                CAPABILITY_NAME, executor=ContextCaptureExecutor(knowledge_store, conversations),
                verifier=ContextCaptureVerifier(knowledge_store),
            )
            actions.register_handler(
                RECONCILIATION_CAPABILITY_NAME, executor=ContextReconciliationExecutor(knowledge_store),
                verifier=ContextReconciliationVerifier(knowledge_store),
            )
            conversation = SimpleNamespace(partition=lambda: "production")
            with mock.patch.object(activity_router, "DEMO_MODE", False), mock.patch.object(
                activity_router, "get_activity_service", return_value=activity_service,
            ), mock.patch.object(activity_router, "get_conversation_service", return_value=conversation), mock.patch.object(
                activity_router, "get_knowledge_service", return_value=KnowledgeService(knowledge_store),
            ), mock.patch.object(activity_router, "get_action_service", return_value=actions):
                response = self.client.post(
                    f"/api/v1/activity/reports/{report.id}/context-proposals",
                    json={"finding_reference": "/findings/0", "kind": "note", "text": "Keep this result."},
                )
                links = self.client.get(
                    f"/api/v1/activity/reports/{report.id}/context-reviews",
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["decision"], "pending")
            self.assertEqual(response.json()["evidence"]["original_text"], "All focused checks passed.")
            self.assertEqual(links.status_code, 200)
            self.assertEqual(links.json()[0]["finding_reference"], "/findings/0")
            self.assertEqual(links.json()[0]["review"]["id"], response.json()["id"])
            activity_store.close()
            knowledge_store.close()

    def test_operator_can_change_a_report_disposition_without_changing_knowledge(self) -> None:
        report = self.service.submit(
            client_id="codex", principal="operator", partition="production", content=_report(),
        ).report
        conversation = SimpleNamespace(partition=lambda: "production")
        with mock.patch.object(activity_router, "get_activity_service", return_value=self.service), mock.patch.object(
            activity_router, "get_conversation_service", return_value=conversation,
        ):
            response = self.client.patch(
                f"/api/v1/activity/reports/{report.id}", json={"disposition": "dismissed"},
            )
            reopened = self.client.patch(
                f"/api/v1/activity/reports/{report.id}", json={"disposition": "new"},
            )
        self.assertEqual((response.status_code, reopened.status_code), (200, 200))
        self.assertEqual((response.json()["disposition"], reopened.json()["disposition"]), ("dismissed", "new"))
        self.assertEqual(reopened.json()["report"], report.content.model_dump(mode="json"))

    def test_secret_activity_evidence_returns_invalid_proposal_without_linking(self) -> None:
        report = self.service.submit(
            client_id="codex", principal="operator", partition="production",
            content=ActivityReportContent(
                submission_key="api-secret", title="Unsafe", task_status="completed", outcome="Done",
                findings=[{"text": "api_key=not-for-context"}],
            ),
        ).report
        conversation = SimpleNamespace(partition=lambda: "production")
        with mock.patch.object(activity_router, "DEMO_MODE", False), mock.patch.object(
            activity_router, "get_activity_service", return_value=self.service,
        ), mock.patch.object(activity_router, "get_conversation_service", return_value=conversation), mock.patch.object(
            activity_router, "get_action_service", return_value=SimpleNamespace(),
        ), mock.patch.object(
            activity_router, "get_knowledge_service", return_value=SimpleNamespace(),
        ):
            response = self.client.post(
                f"/api/v1/activity/reports/{report.id}/context-proposals",
                json={"finding_reference": "/findings/0", "kind": "note", "text": "Use this result."},
            )
        self.assertEqual(response.status_code, 422)


class _CliClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []
        self.review_decision = "pending"

    def request(self, method: str, path: str, *, payload=None, long_running: bool = False):
        self.calls.append((method, path, payload))
        if path.endswith("/context-proposals"):
            return {"id": "review-1", "decision": self.review_decision}
        if method == "POST":
            return {"id": "report-1", "received_at": "2026-09-21T00:00:00Z", "duplicate": False}
        return []


class ActivityCliTests(unittest.TestCase):
    def test_submit_and_json_import_use_the_local_report_contract(self) -> None:
        parser = cli.build_parser()
        client = _CliClient()
        args = parser.parse_args([
            "activity", "submit", "--client", "codex", "--submission-key", "key-1",
            "--title", "Report", "--task-status", "completed", "--outcome", "Done", "--finding", "Check passed",
        ])
        self.assertEqual(args.handler(args, client, True), 0)
        self.assertEqual(client.calls[0][1], "/api/v1/activity/reports")
        self.assertEqual(client.calls[0][2]["report"]["findings"], [{"text": "Check passed"}])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(_report(key="key-2").model_dump(mode="json")), encoding="utf-8")
            imported = parser.parse_args(["activity", "import", str(path), "--client", "codex"])
            self.assertEqual(imported.handler(imported, client, True), 0)
        self.assertEqual(client.calls[1][2]["report"]["submission_key"], "key-2")

    def test_propose_context_uses_an_activity_finding_reference(self) -> None:
        parser = cli.build_parser()
        client = _CliClient()
        args = parser.parse_args([
            "activity", "propose-context", "report-1", "--finding-reference", "/findings/0",
            "Result is ready.", "--kind", "note", "--correct-record", "record-1",
        ])
        self.assertEqual(args.handler(args, client, True), 0)
        self.assertEqual(client.calls[0], (
            "POST", "/api/v1/activity/reports/report-1/context-proposals", {
                "text": "Result is ready.", "kind": "note", "finding_reference": "/findings/0",
                "correction_record_id": "record-1",
            },
        ))
        self.assertFalse(hasattr(args, "sensitive"))
        self.assertFalse(hasattr(args, "idempotency_key"))

    def test_propose_context_renders_an_existing_decided_review(self) -> None:
        parser = cli.build_parser()
        client = _CliClient()
        client.review_decision = "accepted"
        args = parser.parse_args([
            "activity", "propose-context", "report-1", "--finding-reference", "/findings/0",
            "Result is ready.", "--kind", "note",
        ])
        self.assertEqual(args.handler(args, client, True), 0)
