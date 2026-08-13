"""Focused regression coverage for durable approval-gated action semantics."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from core import database
from core.actions import (
    ActionConflictError,
    ActionIntegrityError,
    ActionService,
    ActionStore,
    ActionTransitionError,
    ExecutionOutcome,
    VerificationOutcome,
)
from core.actions.models import ActionValidationError


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class _Executor:
    def __init__(self, outcome: object | Exception) -> None:
        self.outcome = outcome
        self.calls = 0
        self.arguments: object | None = None

    def execute(self, action):
        self.calls += 1
        self.arguments = action.proposal.arguments
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _Verifier:
    def __init__(self, outcome: object | Exception) -> None:
        self.outcome = outcome
        self.calls = 0

    def verify(self, _action):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class ActionKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_actions_")
        self.addCleanup(self._temp_dir.cleanup)
        self.db_path = Path(self._temp_dir.name) / "apex_memory.db"
        self.clock = _Clock()
        self.store = ActionStore(self.db_path)
        self.service = ActionService(self.store, clock=self.clock)

    def _propose(self, *, arguments=None, risk="write"):
        return self.service.propose(
            agent_key="panthera",
            capability_name="test_write",
            arguments=arguments or {"title": "Study", "nested": {"rank": 1}},
            target="Microsoft To Do / Study",
            risk=risk,
            summary="Create the Study task.",
        )

    def _register(self, execution: ExecutionOutcome, verification: VerificationOutcome):
        executor = _Executor(execution)
        verifier = _Verifier(verification)
        self.service.register_handler("test_write", executor=executor, verifier=verifier)
        return executor, verifier

    def test_database_initialization_preserves_legacy_rows_and_creates_action_tables(self) -> None:
        database_path_patch = self.db_path
        original = database.DB_NAME
        database.DB_NAME = str(database_path_patch)
        self.addCleanup(setattr, database, "DB_NAME", original)
        database.initialize_db()
        database.save_reminder("Legacy reminder")
        database.initialize_db()

        conn = sqlite3.connect(self.db_path)
        try:
            reminders = conn.execute("SELECT note FROM reminders").fetchall()
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()

        self.assertEqual(reminders, [("Legacy reminder",)])
        self.assertTrue({"actions", "action_events"}.issubset(tables))

    def test_proposal_hash_is_canonical_and_input_is_deeply_frozen(self) -> None:
        first = self._propose(arguments={"b": 2, "nested": {"a": [1, 2]}})
        second = self._propose(arguments={"nested": {"a": [1, 2]}, "b": 2})
        self.assertEqual(first.proposal.proposal_hash, second.proposal.proposal_hash)

        source = {"title": "Original", "nested": {"value": 1}}
        frozen = self._propose(arguments=source)
        source["title"] = "Changed"
        source["nested"]["value"] = 2
        self.assertEqual(frozen.proposal.arguments["title"], "Original")
        self.assertEqual(frozen.proposal.arguments["nested"]["value"], 1)

    def test_corrupted_proposal_is_rejected_before_execution(self) -> None:
        action = self._propose()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE actions SET arguments_json = ? WHERE action_id = ?",
                ('{"title":"Tampered"}', action.action_id),
            )
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(ActionIntegrityError):
            self.service.approve(action.action_id, actor="operator")
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT status, version FROM actions WHERE action_id = ?",
                (action.action_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, ("proposed", 0))

    def test_allowed_lifecycle_records_ordered_audit_history(self) -> None:
        executor, verifier = self._register(
            ExecutionOutcome(True, "write_completed", {"request_id": "safe"}),
            VerificationOutcome(True, "readback_confirmed", {"found": True}),
        )
        action = self._propose()
        approved = self.service.approve(action.action_id, actor="operator")
        completed = self.service.claim_and_execute(
            action.action_id,
            actor="worker",
            expected_version=approved.version,
        )

        self.assertEqual(completed.status, "verified")
        self.assertEqual(executor.calls, 1)
        self.assertEqual(verifier.calls, 1)
        self.assertEqual(executor.arguments["title"], "Study")
        events = self.service.events(action.action_id)
        self.assertEqual([event.sequence for event in events], list(range(5)))
        self.assertEqual([event.to_status for event in events], ["proposed", "approved", "executing", "verifying", "verified"])

    def test_invalid_transition_and_stale_version_are_rejected(self) -> None:
        action = self._propose()
        with self.assertRaises(ActionTransitionError):
            self.store.transition(
                action.action_id,
                expected_statuses=("proposed",),
                to_status="verified",
                actor="test",
                result_code="invalid_transition",
                evidence={},
                now=self.clock(),
            )
        approved = self.service.approve(action.action_id, actor="operator")
        with self.assertRaises(ActionConflictError):
            self.service.claim_and_execute(
                action.action_id,
                actor="worker",
                expected_version=approved.version - 1,
            )

    def test_pending_action_can_be_rejected(self) -> None:
        action = self._propose()

        rejected = self.service.reject(action.action_id, actor="operator")

        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(
            [event.to_status for event in self.service.events(action.action_id)],
            ["proposed", "rejected"],
        )

    def test_event_insert_failure_rolls_back_the_state_transition(self) -> None:
        action = self._propose()
        with mock.patch.object(
            ActionStore,
            "_insert_event",
            side_effect=sqlite3.DatabaseError("test event failure"),
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                self.service.approve(action.action_id, actor="operator")
        current = self.service.get(action.action_id)
        self.assertEqual(current.status, "proposed")
        self.assertEqual(current.version, 0)
        self.assertEqual(len(self.service.events(action.action_id)), 1)

    def test_concurrent_execution_claims_allow_only_one_winner(self) -> None:
        action = self._propose()
        approved = self.service.approve(action.action_id, actor="operator")
        barrier = threading.Barrier(2)

        def claim() -> str:
            local_store = ActionStore(self.db_path)
            barrier.wait()
            try:
                local_store.claim_execution(
                    action.action_id,
                    actor="worker",
                    now=self.clock(),
                    expected_version=approved.version,
                )
                return "claimed"
            except (ActionConflictError, ActionTransitionError):
                return "lost"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _unused: claim(), range(2)))

        self.assertEqual(results.count("claimed"), 1)
        self.assertEqual(results.count("lost"), 1)
        self.assertEqual(self.service.get(action.action_id).status, "executing")

    def test_failed_unknown_and_retryable_verification_outcomes(self) -> None:
        executor, verifier = self._register(
            ExecutionOutcome(None, "write_timeout", {"attempt": 1}),
            VerificationOutcome(True, "readback_confirmed", {"found": True}),
        )
        action = self._propose()
        self.service.approve(action.action_id, actor="operator")
        unknown = self.service.claim_and_execute(action.action_id, actor="worker")
        self.assertEqual(unknown.status, "outcome_unknown")
        recovered = self.service.retry_verification(action.action_id, actor="operator")
        self.assertEqual(recovered.status, "verified")
        self.assertEqual(executor.calls, 1)
        self.assertEqual(verifier.calls, 1)

        failure_executor, _ = self._register(
            ExecutionOutcome(False, "write_denied", {"reason": "policy"}),
            VerificationOutcome(True, "unused", {}),
        )
        failed = self._propose()
        self.service.approve(failed.action_id, actor="operator")
        terminal = self.service.claim_and_execute(failed.action_id, actor="worker")
        self.assertEqual(terminal.status, "execution_failed")
        self.assertEqual(failure_executor.calls, 1)

    def test_verification_failure_can_retry_without_executing_again(self) -> None:
        executor, verifier = self._register(
            ExecutionOutcome(True, "write_completed", {}),
            VerificationOutcome(False, "readback_pending", {}),
        )
        action = self._propose()
        self.service.approve(action.action_id, actor="operator")

        failed = self.service.claim_and_execute(action.action_id, actor="worker")
        self.assertEqual(failed.status, "verification_failed")

        recovered_verifier = _Verifier(VerificationOutcome(True, "readback_confirmed", {}))
        self.service.register_handler(
            "test_write",
            executor=executor,
            verifier=recovered_verifier,
        )
        recovered = self.service.retry_verification(action.action_id, actor="operator")

        self.assertEqual(recovered.status, "verified")
        self.assertEqual(executor.calls, 1)
        self.assertEqual(verifier.calls, 1)
        self.assertEqual(recovered_verifier.calls, 1)

    def test_invalid_handler_outcomes_leave_no_action_in_progress(self) -> None:
        executor = _Executor(object())
        verifier = _Verifier(VerificationOutcome(True, "unused", {}))
        self.service.register_handler("test_write", executor=executor, verifier=verifier)
        action = self._propose()
        self.service.approve(action.action_id, actor="operator")
        self.assertEqual(
            self.service.claim_and_execute(action.action_id, actor="worker").status,
            "outcome_unknown",
        )

        executor = _Executor(ExecutionOutcome(True, "write_completed", {}))
        verifier = _Verifier(object())
        self.service.register_handler("test_write", executor=executor, verifier=verifier)
        action = self._propose()
        self.service.approve(action.action_id, actor="operator")
        self.assertEqual(
            self.service.claim_and_execute(action.action_id, actor="worker").status,
            "verification_failed",
        )

    def test_expiry_boundary_and_restart_recovery_do_not_retry_execution(self) -> None:
        expired = self._propose()
        self.clock.now += timedelta(hours=24)
        self.assertEqual(self.service.approve(expired.action_id, actor="operator").status, "expired")

        expired_rejection = self._propose()
        self.clock.now += timedelta(hours=24)
        self.assertEqual(
            self.service.reject(expired_rejection.action_id, actor="operator").status,
            "expired",
        )

        approved = self._propose()
        self.service.approve(approved.action_id, actor="operator")
        self.clock.now += timedelta(days=2)
        self.assertEqual(self.service.get(approved.action_id).status, "approved")

        executing = self._propose()
        self.service.approve(executing.action_id, actor="operator")
        self.store.claim_execution(executing.action_id, actor="worker", now=self.clock())

        verifying = self._propose()
        self.service.approve(verifying.action_id, actor="operator")
        self.store.claim_execution(verifying.action_id, actor="worker", now=self.clock())
        self.store.begin_verification(
            verifying.action_id,
            actor="worker",
            code="write_completed",
            evidence={},
            now=self.clock(),
        )
        recovered = self.service.recover_interrupted()
        statuses = {item.action_id: item.status for item in recovered}
        self.assertEqual(statuses[executing.action_id], "outcome_unknown")
        self.assertEqual(statuses[verifying.action_id], "verification_failed")
        self.assertEqual(self.service.get(approved.action_id).status, "approved")

    def test_evidence_is_bounded_and_private_exceptions_are_not_persisted(self) -> None:
        with self.assertRaises(ActionValidationError):
            ExecutionOutcome(True, "too_large", {"payload": "x" * 20_000})

        executor = _Executor(RuntimeError("private-detail"))
        verifier = _Verifier(VerificationOutcome(True, "unused", {}))
        self.service.register_handler("test_write", executor=executor, verifier=verifier)
        action = self._propose()
        self.service.approve(action.action_id, actor="operator")
        with self.assertLogs("core.actions.service", level="WARNING") as captured:
            result = self.service.claim_and_execute(action.action_id, actor="worker")
        self.assertEqual(result.status, "outcome_unknown")
        self.assertNotIn("private-detail", " ".join(captured.output))
        self.assertNotIn(
            "private-detail",
            str([dict(event.evidence) for event in self.service.events(action.action_id)]),
        )


if __name__ == "__main__":
    unittest.main()
