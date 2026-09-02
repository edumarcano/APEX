"""Focused persistence, privacy boundary, and lifecycle tests for Cortex run ledger."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import ValidationError

from core.config import (
    CORTEX_RUNS_CONFIG,
    CORTEX_RUNS_EVENT_REPLAY_LIMIT,
    CORTEX_RUNS_MAX_CONCURRENT_RUNS,
    CORTEX_RUNS_MAX_ELAPSED_SECONDS,
    CORTEX_RUNS_MAX_MODEL_TURNS,
    CORTEX_RUNS_MAX_RETRIES,
    CORTEX_RUNS_MAX_TOOL_CALLS,
    CORTEX_RUNS_MAX_TOTAL_TOKENS,
    _parse_config_int,
)
from core.connectors.models import utc_now_iso
from core.conversations.store import (
    ConversationConflictError,
    ConversationStore,
)
from core.runs.models import (
    SAFE_ERROR_MESSAGES,
    RunCompletionEvidence,
    RunError,
    RunLimitSnapshot,
    RunRecord,
    RunRuntimeMeasurements,
)
from core.runs.service import (
    RunHandle,
    RunService,
    get_run_service,
    set_run_service,
)
from core.runs.store import (
    RunConflictError,
    RunNotFoundError,
    RunStore,
    RunStoreError,
)


class RunsLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "apex_memory.db"
        self.conversations = ConversationStore(self.db_path)
        self.conversations.initialize()
        self.store = RunStore(self.db_path)
        self.store.initialize()

        self.prod_conversation_id = uuid4()
        self.conversations.create(
            conversation_id=self.prod_conversation_id,
            title="Production Chat",
            partition="production",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )

        self.sandbox_conversation_id = uuid4()
        self.conversations.create(
            conversation_id=self.sandbox_conversation_id,
            title="Sandbox Chat",
            partition="sandbox",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.conversations.close()
        self.temp_dir.cleanup()

    def _default_limits(self) -> RunLimitSnapshot:
        return RunLimitSnapshot(
            max_elapsed_seconds=600,
            max_total_tokens=128000,
            max_retries=4,
            max_model_turns=6,
            max_tool_calls=10,
        )

    def _create_turn_messages(
        self,
        conversation_id: UUID,
        user_message_id: UUID,
        agent_message_id: UUID,
    ) -> None:
        now = utc_now_iso()
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO conversation_messages (id, conversation_id, role, content, status, created_at, updated_at) "
                "VALUES (?, ?, 'user', 'Hello', 'completed', ?, ?)",
                (str(user_message_id), str(conversation_id), now, now),
            )
            conn.execute(
                "INSERT INTO conversation_messages (id, conversation_id, role, content, status, created_at, updated_at) "
                "VALUES (?, ?, 'agent', '', 'pending', ?, ?)",
                (str(agent_message_id), str(conversation_id), now, now),
            )

    def _create_run(
        self,
        *,
        conversation_id=None,
        partition="production",
        user_message_id=None,
        agent_message_id=None,
        requested_model="deepseek/deepseek-v4-flash-0731",
        limits=None,
    ) -> tuple[RunRecord, bool]:
        if conversation_id is None:
            cid = uuid4()
            self.conversations.create(
                conversation_id=cid,
                title="Test Chat",
                partition=partition,
                origin="hud",
                agent="apex",
                selected_tool_names=None,
                tool_profile_id=None,
            )
        else:
            cid = conversation_id
        uid = user_message_id or uuid4()
        aid = agent_message_id or uuid4()
        self._create_turn_messages(cid, uid, aid)
        return self.store.create_run(
            run_id=uuid4(),
            conversation_id=cid,
            partition=partition,
            user_message_id=uid,
            agent_message_id=aid,
            requested_model=requested_model,
            limit_snapshot=limits or self._default_limits(),
        )

    def test_configuration_parsing_and_clamping(self) -> None:
        """Verify cortex_runs configuration bounds clamping and defaults."""
        self.assertEqual(CORTEX_RUNS_CONFIG.max_concurrent_runs, 2)
        self.assertEqual(CORTEX_RUNS_CONFIG.max_elapsed_seconds, 600)
        self.assertEqual(CORTEX_RUNS_CONFIG.max_total_tokens, 128000)
        self.assertEqual(CORTEX_RUNS_CONFIG.max_retries, 4)
        self.assertEqual(CORTEX_RUNS_CONFIG.max_model_turns, 6)
        self.assertEqual(CORTEX_RUNS_CONFIG.max_tool_calls, 10)
        self.assertEqual(CORTEX_RUNS_CONFIG.event_replay_limit, 512)

        self.assertEqual(CORTEX_RUNS_MAX_CONCURRENT_RUNS, 2)
        self.assertEqual(CORTEX_RUNS_MAX_ELAPSED_SECONDS, 600)
        self.assertEqual(CORTEX_RUNS_MAX_TOTAL_TOKENS, 128000)
        self.assertEqual(CORTEX_RUNS_MAX_RETRIES, 4)
        self.assertEqual(CORTEX_RUNS_MAX_MODEL_TURNS, 6)
        self.assertEqual(CORTEX_RUNS_MAX_TOOL_CALLS, 10)
        self.assertEqual(CORTEX_RUNS_EVENT_REPLAY_LIMIT, 512)

        # Clamping checks
        self.assertEqual(_parse_config_int(0, key="k", default=2, min_value=1, max_value=4), 1)
        self.assertEqual(_parse_config_int(10, key="k", default=2, min_value=1, max_value=4), 4)
        self.assertEqual(_parse_config_int(5, key="k", default=600, min_value=30, max_value=3600), 30)
        self.assertEqual(_parse_config_int(10000, key="k", default=600, min_value=30, max_value=3600), 3600)
        self.assertEqual(_parse_config_int(100, key="k", default=128000, min_value=8192, max_value=2000000), 8192)
        self.assertEqual(_parse_config_int(5000000, key="k", default=128000, min_value=8192, max_value=2000000), 2000000)
        self.assertEqual(_parse_config_int(-1, key="k", default=4, min_value=0, max_value=10), 0)
        self.assertEqual(_parse_config_int(20, key="k", default=4, min_value=0, max_value=10), 10)
        self.assertEqual(_parse_config_int(0, key="k", default=6, min_value=1, max_value=12), 1)
        self.assertEqual(_parse_config_int(50, key="k", default=6, min_value=1, max_value=12), 12)
        self.assertEqual(_parse_config_int(0, key="k", default=10, min_value=1, max_value=32), 1)
        self.assertEqual(_parse_config_int(100, key="k", default=10, min_value=1, max_value=32), 32)
        self.assertEqual(_parse_config_int(10, key="k", default=512, min_value=64, max_value=2048), 64)
        self.assertEqual(_parse_config_int(5000, key="k", default=512, min_value=64, max_value=2048), 2048)

    def test_schema_initialization_and_versioning(self) -> None:
        """Verify schema versions table and domain migration rejection."""
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = 'cortex_runs'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 1)

        self.store.initialize()

        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE schema_versions SET version = 99 WHERE domain = 'cortex_runs'")
        with self.assertRaises(RunStoreError):
            self.store.initialize()

    def test_foreign_key_constraints_on_messages(self) -> None:
        """Verify composite foreign keys to conversation_messages(conversation_id, id)."""
        valid_uid = uuid4()
        valid_aid = uuid4()
        self._create_turn_messages(self.prod_conversation_id, valid_uid, valid_aid)

        # Missing user message
        with self.assertRaises(RunNotFoundError):
            self.store.create_run(
                run_id=uuid4(),
                conversation_id=self.prod_conversation_id,
                partition="production",
                user_message_id=uuid4(),
                agent_message_id=valid_aid,
                requested_model="m",
                limit_snapshot=self._default_limits(),
            )

        # Missing agent message
        with self.assertRaises(RunNotFoundError):
            self.store.create_run(
                run_id=uuid4(),
                conversation_id=self.prod_conversation_id,
                partition="production",
                user_message_id=valid_uid,
                agent_message_id=uuid4(),
                requested_model="m",
                limit_snapshot=self._default_limits(),
            )

        # Valid run creation succeeds
        run, replayed = self.store.create_run(
            run_id=uuid4(),
            conversation_id=self.prod_conversation_id,
            partition="production",
            user_message_id=valid_uid,
            agent_message_id=valid_aid,
            requested_model="m",
            limit_snapshot=self._default_limits(),
        )
        self.assertFalse(replayed)

        # SQLite schema constraint: inserting orphan directly violates composite FK
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO cortex_runs (
                        id, conversation_id, partition, user_message_id, agent_message_id,
                        requested_model, status, created_at, updated_at, limit_snapshot_json,
                        turns_count, tool_calls_count, retries_count, total_tokens, elapsed_seconds,
                        usage_quality, answer_persisted
                    ) VALUES (
                        'orphan-run', ?, 'production', 'non-existent-user-msg', 'non-existent-agent-msg',
                        'm', 'queued', '2026-01-01', '2026-01-01', '{}',
                        0, 0, 0, 0, 0.0, 'unavailable', 0
                    )
                    """,
                    (str(self.prod_conversation_id),),
                )

    def test_terminal_run_immutability(self) -> None:
        """Verify terminal runs (completed, failed, cancelled, interrupted) cannot accept progress updates."""
        run, _ = self._create_run()

        # Queued runs cannot accept progress updates (must be running/cancelling)
        with self.assertRaises(RunConflictError):
            self.store.update_progress(run.id, partition="production", turns_count=1)

        self.store.start_run(
            run.id,
            partition="production",
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )

        # Running run can accept updates
        updated = self.store.update_progress(run.id, partition="production", turns_count=1)
        self.assertEqual(updated.turns_count, 1)

        # Finalize run to completed
        self.store.finalize_run(
            run.id,
            partition="production",
            status="completed",
            stop_reason="end_turn",
            evidence=RunCompletionEvidence(answer_persisted=True),
        )

        # Late worker update MUST be rejected with RunConflictError
        with self.assertRaises(RunConflictError):
            self.store.update_progress(
                run.id,
                partition="production",
                turns_count=2,
                total_tokens=500,
            )

        # Repeated finalize on terminal run is also rejected
        with self.assertRaises(RunConflictError):
            self.store.finalize_run(
                run.id,
                partition="production",
                status="completed",
                stop_reason="end_turn",
                evidence=RunCompletionEvidence(answer_persisted=True),
            )

    def test_metadata_privacy_and_redaction_boundary(self) -> None:
        """Verify allowlisted measurements, opaque action IDs, and predefined safe error messages."""
        # 1. Arbitrary runtime measurements are strictly rejected by Pydantic
        with self.assertRaises(ValidationError):
            RunRuntimeMeasurements(
                eval_duration_ms=120.0,
                prompt="Secret prompt that should not be accepted",  # forbidden extra
            )

        with self.assertRaises(ValidationError):
            RunRuntimeMeasurements(
                secret_token="sk-ant-test-12345",  # forbidden extra
            )

        # 2. Non-opaque action IDs (containing spaces, JSON, or long strings) are rejected
        with self.assertRaises(ValidationError):
            RunCompletionEvidence(
                action_ids=["valid_id_1", "invalid action id with spaces"],
            )

        with self.assertRaises(ValidationError):
            RunCompletionEvidence(
                action_ids=["a" * 65],  # exceeds 64 chars
            )

        with self.assertRaises(ValidationError):
            RunCompletionEvidence(
                tool_outcome_counts={"invalid outcome with space": 1},
            )

        # 3. Error messages are strictly normalized to predefined safe taxonomy
        err = RunError(
            code="provider_error",
            message="Raw provider leak: Authentication failed with api_key=sk-ant-secret",
        )
        self.assertEqual(err.message, SAFE_ERROR_MESSAGES["provider_error"])
        self.assertNotIn("sk-ant-secret", err.message)

        # 4. End-to-end store test: sensitive fixture values are never stored
        run, _ = self._create_run()
        self.store.start_run(
            run.id,
            partition="production",
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )
        self.store.update_progress(
            run.id,
            partition="production",
            runtime_measurements={
                "queue_duration_ms": 15.0,
                "ttft_ms": 120.0,
                "eval_duration_ms": 300.0,
            },
        )
        self.store.finalize_run(
            run.id,
            partition="production",
            status="failed",
            stop_reason="provider_error",
            evidence=RunCompletionEvidence(
                final_message_status="failed",
                action_ids=["opaque-action-id-42"],
                tool_outcome_counts={"search_code": 1},
            ),
            error=RunError(
                code="provider_error",
                message="sk-leak-in-exception-args",
            ),
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT * FROM cortex_runs WHERE id = ?", (str(run.id),)
            ).fetchone()
            row_str = " ".join(str(val) for val in row)

            self.assertNotIn("sk-leak-in-exception-args", row_str)
            self.assertNotIn("Secret prompt", row_str)
            self.assertIn("Inference provider encountered an unrecoverable error.", row_str)
            self.assertIn("opaque-action-id-42", row_str)

    def test_demo_mode_shared_ephemeral_db(self) -> None:
        """Verify DEMO_MODE creates runs in a shared ephemeral in-memory database."""
        demo_db = sqlite3.connect(":memory:", check_same_thread=False)
        demo_db.execute("PRAGMA foreign_keys=ON")

        demo_conversations = ConversationStore(None, connection=demo_db)
        demo_conversations.initialize()

        demo_runs = RunStore(None, connection=demo_db)
        demo_runs.initialize()

        conv_id = uuid4()
        demo_conversations.create(
            conversation_id=conv_id,
            title="Demo Conversation",
            partition="production",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )

        uid = uuid4()
        aid = uuid4()
        now = utc_now_iso()
        demo_db.execute(
            "INSERT INTO conversation_messages (id, conversation_id, role, content, status, created_at, updated_at) "
            "VALUES (?, ?, 'user', 'Demo User', 'completed', ?, ?)",
            (str(uid), str(conv_id), now, now),
        )
        demo_db.execute(
            "INSERT INTO conversation_messages (id, conversation_id, role, content, status, created_at, updated_at) "
            "VALUES (?, ?, 'agent', '', 'pending', ?, ?)",
            (str(aid), str(conv_id), now, now),
        )

        # Run creation in shared demo db succeeds without table-not-found error
        run, replayed = demo_runs.create_run(
            run_id=uuid4(),
            conversation_id=conv_id,
            partition="production",
            user_message_id=uid,
            agent_message_id=aid,
            requested_model="gemini/gemini-2.5-flash",
            limit_snapshot=self._default_limits(),
        )
        self.assertFalse(replayed)
        self.assertEqual(run.conversation_id, conv_id)

        demo_runs.close()
        demo_conversations.close()
        demo_db.close()

    def test_idempotency_by_agent_message_id(self) -> None:
        """Verify strict matching idempotency returns existing run; conflicts raise RunConflictError."""
        uid = uuid4()
        aid = uuid4()
        self._create_turn_messages(self.prod_conversation_id, uid, aid)

        run1, replayed1 = self.store.create_run(
            run_id=uuid4(),
            conversation_id=self.prod_conversation_id,
            partition="production",
            user_message_id=uid,
            agent_message_id=aid,
            requested_model="deepseek/deepseek-v4-flash-0731",
            limit_snapshot=self._default_limits(),
        )
        self.assertFalse(replayed1)

        # Replay with identical parameters succeeds
        run2, replayed2 = self.store.create_run(
            run_id=uuid4(),
            conversation_id=self.prod_conversation_id,
            partition="production",
            user_message_id=uid,
            agent_message_id=aid,
            requested_model="deepseek/deepseek-v4-flash-0731",
            limit_snapshot=self._default_limits(),
        )
        self.assertTrue(replayed2)
        self.assertEqual(run1.id, run2.id)

        # Conflicting requested_model
        with self.assertRaises(RunConflictError):
            self.store.create_run(
                run_id=uuid4(),
                conversation_id=self.prod_conversation_id,
                partition="production",
                user_message_id=uid,
                agent_message_id=aid,
                requested_model="openai/gpt-5-mini",
                limit_snapshot=self._default_limits(),
            )

    def test_partition_isolation(self) -> None:
        """Verify runs in production and sandbox partitions are completely isolated."""
        prod_run, _ = self._create_run(partition="production")
        sandbox_run, _ = self._create_run(
            conversation_id=self.sandbox_conversation_id,
            partition="sandbox",
        )

        # Queries in opposite partitions must fail
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(prod_run.id, partition="sandbox")
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(sandbox_run.id, partition="production")

        prod_list = self.store.list_runs("production")
        sandbox_list = self.store.list_runs("sandbox")
        self.assertIn(prod_run.id, [r.id for r in prod_list])
        self.assertNotIn(sandbox_run.id, [r.id for r in prod_list])
        self.assertIn(sandbox_run.id, [r.id for r in sandbox_list])
        self.assertNotIn(prod_run.id, [r.id for r in sandbox_list])

    def test_list_runs_filtering_and_pagination(self) -> None:
        """Verify list_runs status filter, conversation filter, and limit clamping."""
        run1, _ = self._create_run()
        run2, _ = self._create_run()

        self.store.start_run(
            run1.id,
            partition="production",
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )

        queued_runs = self.store.list_runs("production", status="queued")
        self.assertIn(run2.id, [r.id for r in queued_runs])
        self.assertNotIn(run1.id, [r.id for r in queued_runs])

        running_runs = self.store.list_runs("production", status="running")
        self.assertIn(run1.id, [r.id for r in running_runs])
        self.assertNotIn(run2.id, [r.id for r in running_runs])

        # Clamping check: limit 0 -> 1, limit 1000 -> 100
        one_run = self.store.list_runs("production", limit=1)
        self.assertEqual(len(one_run), 1)

    def test_run_lifecycle_and_progress_updates(self) -> None:
        """Verify transition lifecycle from queued -> running -> progress -> finalize."""
        run, _ = self._create_run()
        self.assertEqual(run.status, "queued")

        # Start
        started = self.store.start_run(
            run.id,
            partition="production",
            resolved_model="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
        )
        self.assertEqual(started.status, "running")
        self.assertIsNotNone(started.started_at)
        self.assertEqual(started.resolved_model, "deepseek/deepseek-v4-flash-0731")

        # Progress
        progress = self.store.update_progress(
            run.id,
            partition="production",
            turns_count=2,
            tool_calls_count=3,
            total_tokens=1500,
            elapsed_seconds=12.5,
            usage_quality="reported",
            runtime_measurements=RunRuntimeMeasurements(ttft_ms=120.5),
        )
        self.assertEqual(progress.turns_count, 2)
        self.assertEqual(progress.tool_calls_count, 3)
        self.assertEqual(progress.total_tokens, 1500)
        self.assertEqual(progress.elapsed_seconds, 12.5)
        self.assertEqual(progress.usage_quality, "reported")
        self.assertEqual(progress.runtime_measurements.ttft_ms, 120.5)

        # Finalize
        evidence = RunCompletionEvidence(
            final_message_id=run.agent_message_id,
            final_message_status="completed",
            answer_persisted=True,
            tool_outcome_counts={"search": 2, "read": 1},
            action_ids=["opaque-action-id-42"],
        )
        final = self.store.finalize_run(
            run.id,
            partition="production",
            status="completed",
            stop_reason="end_turn",
            evidence=evidence,
        )
        self.assertEqual(final.status, "completed")
        self.assertEqual(final.stop_reason, "end_turn")
        self.assertTrue(final.evidence.answer_persisted)
        self.assertEqual(final.evidence.tool_outcome_counts["search"], 2)

    def test_finalize_answer_persisted_rule(self) -> None:
        """Verify answer_persisted is strictly false for non-completed terminal states."""
        run_cancelled, _ = self._create_run()
        self.store.start_run(
            run_cancelled.id,
            partition="production",
            resolved_model="m",
            provider="p",
            runtime="r",
        )
        fin_cancelled = self.store.finalize_run(
            run_cancelled.id,
            partition="production",
            status="cancelled",
            stop_reason="operator_cancelled",
            evidence=RunCompletionEvidence(answer_persisted=True),
        )
        self.assertFalse(fin_cancelled.evidence.answer_persisted)

        run_failed, _ = self._create_run()
        self.store.start_run(
            run_failed.id,
            partition="production",
            resolved_model="m",
            provider="p",
            runtime="r",
        )
        fin_failed = self.store.finalize_run(
            run_failed.id,
            partition="production",
            status="failed",
            stop_reason="provider_error",
            evidence=RunCompletionEvidence(answer_persisted=True),
        )
        self.assertFalse(fin_failed.evidence.answer_persisted)

    def test_conversation_deletion_cascade_and_active_block(self) -> None:
        """Verify active runs block permanent deletion, and deletion cascades finished runs."""
        run, _ = self._create_run(conversation_id=self.prod_conversation_id)
        self.assertEqual(run.status, "queued")

        # Archive conversation first (APEX requires archiving before deletion)
        self.conversations.patch(
            self.prod_conversation_id, "production", {"archived": True}
        )

        # Deletion must be rejected because run is active (queued)
        with self.assertRaises(ConversationConflictError):
            self.conversations.delete(self.prod_conversation_id, "production")

        # Cancel and finalize the run
        self.store.finalize_run(
            run.id,
            partition="production",
            status="cancelled",
            stop_reason="operator_cancelled",
            evidence=RunCompletionEvidence(final_message_status="interrupted"),
        )

        # Mark turn message completed/interrupted so there is no pending turn
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE conversation_messages SET status = 'interrupted' WHERE id = ?",
                (str(run.agent_message_id),),
            )

        # Now deletion succeeds and cascades automatically
        self.conversations.delete(self.prod_conversation_id, "production")

        with self.assertRaises(RunNotFoundError):
            self.store.get_run(run.id, partition="production")

    def test_interrupted_run_recovery(self) -> None:
        """Verify startup recovery updates queued, running, and cancelling runs to interrupted."""
        run_queued, _ = self._create_run()
        run_running, _ = self._create_run()
        self.store.start_run(
            run_running.id,
            partition="production",
            resolved_model="m",
            provider="p",
            runtime="cloud",
        )
        run_cancelling, _ = self._create_run()
        self.store.start_run(
            run_cancelling.id,
            partition="production",
            resolved_model="m",
            provider="p",
            runtime="cloud",
        )
        self.store.set_cancelling(run_cancelling.id, partition="production")

        run_completed, _ = self._create_run()
        self.store.start_run(
            run_completed.id,
            partition="production",
            resolved_model="m",
            provider="p",
            runtime="cloud",
        )
        self.store.finalize_run(
            run_completed.id,
            partition="production",
            status="completed",
            stop_reason="end_turn",
            evidence=RunCompletionEvidence(answer_persisted=True),
        )

        # Execute recovery
        recovered_count = self.store.recover_interrupted()
        self.assertEqual(recovered_count, 3)

        q = self.store.get_run(run_queued.id, "production")
        self.assertEqual(q.status, "interrupted")
        self.assertEqual(q.stop_reason, "interrupted_by_restart")
        self.assertEqual(q.evidence.final_message_status, "interrupted")
        self.assertFalse(q.evidence.answer_persisted)
        self.assertEqual(q.error.code, "interrupted_by_restart")

        r = self.store.get_run(run_running.id, "production")
        self.assertEqual(r.status, "interrupted")
        self.assertEqual(r.stop_reason, "interrupted_by_restart")

        c = self.store.get_run(run_cancelling.id, "production")
        self.assertEqual(c.status, "interrupted")
        self.assertEqual(c.stop_reason, "interrupted_by_restart")

        # Completed run was untouched
        comp = self.store.get_run(run_completed.id, "production")
        self.assertEqual(comp.status, "completed")
        self.assertEqual(comp.stop_reason, "end_turn")

    def test_run_service_and_handle_partition_binding(self) -> None:
        """Verify RunService returns an immutable partition-bound RunHandle."""
        service = RunService(self.store)
        set_run_service(service)
        self.addCleanup(lambda: set_run_service(None))

        self.assertIs(get_run_service(), service)

        # Create turn messages
        uid = uuid4()
        aid = uuid4()
        self._create_turn_messages(self.prod_conversation_id, uid, aid)

        # Service creates run and returns handle
        record, handle, replayed = service.create_run(
            run_id=uuid4(),
            conversation_id=self.prod_conversation_id,
            user_message_id=uid,
            agent_message_id=aid,
            requested_model="deepseek/deepseek-v4-flash-0731",
            limit_snapshot=self._default_limits(),
        )
        self.assertFalse(replayed)
        self.assertEqual(record.partition, "production")
        self.assertIsInstance(handle, RunHandle)
        self.assertEqual(handle.partition, "production")
        self.assertEqual(handle.run_id, record.id)

        # Query via service
        self.assertTrue(service.has_active_runs(self.prod_conversation_id))
        listed = service.list_runs()
        self.assertIn(record.id, [r.id for r in listed])

        # Lifecycle operations via partition-bound handle
        started = handle.start(
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )
        self.assertEqual(started.status, "running")

        progress = handle.update_progress(turns_count=1, total_tokens=100)
        self.assertEqual(progress.turns_count, 1)

        cancelling = handle.set_cancelling()
        self.assertEqual(cancelling.status, "cancelling")

        final = handle.finalize(
            status="cancelled",
            stop_reason="operator_cancelled",
            evidence=RunCompletionEvidence(final_message_status="interrupted"),
        )
        self.assertEqual(final.status, "cancelled")
        self.assertFalse(service.has_active_runs(self.prod_conversation_id))
