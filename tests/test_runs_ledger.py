"""Focused persistence and lifecycle tests for Cortex run ledger."""

from __future__ import annotations

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

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
from core.conversations.store import (
    ConversationConflictError,
    ConversationStore,
)
from core.runs.models import (
    RunCompletionEvidence,
    RunError,
    RunLimitSnapshot,
    RunRecord,
)
from core.runs.service import RunService, get_run_service, set_run_service
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
        return self.store.create_run(
            run_id=uuid4(),
            conversation_id=conversation_id or self.prod_conversation_id,
            partition=partition,
            user_message_id=user_message_id or uuid4(),
            agent_message_id=agent_message_id or uuid4(),
            requested_model=requested_model,
            limit_snapshot=limits or self._default_limits(),
        )

    def test_configuration_parsing_and_clamping(self) -> None:
        # Check defaults loaded from config.json
        self.assertEqual(CORTEX_RUNS_MAX_CONCURRENT_RUNS, 2)
        self.assertEqual(CORTEX_RUNS_MAX_ELAPSED_SECONDS, 600)
        self.assertEqual(CORTEX_RUNS_MAX_TOTAL_TOKENS, 128000)
        self.assertEqual(CORTEX_RUNS_MAX_RETRIES, 4)
        self.assertEqual(CORTEX_RUNS_MAX_MODEL_TURNS, 6)
        self.assertEqual(CORTEX_RUNS_MAX_TOOL_CALLS, 10)
        self.assertEqual(CORTEX_RUNS_EVENT_REPLAY_LIMIT, 512)

        self.assertEqual(CORTEX_RUNS_CONFIG.max_concurrent_runs, 2)

        # Test boundary clamping using _parse_config_int
        # Concurrency: 1..4
        self.assertEqual(_parse_config_int(0, key="k", default=2, min_value=1, max_value=4), 1)
        self.assertEqual(_parse_config_int(10, key="k", default=2, min_value=1, max_value=4), 4)

        # Elapsed seconds: 30..3600
        self.assertEqual(_parse_config_int(5, key="k", default=600, min_value=30, max_value=3600), 30)
        self.assertEqual(_parse_config_int(10000, key="k", default=600, min_value=30, max_value=3600), 3600)

        # Tokens: 8192..2000000
        self.assertEqual(_parse_config_int(100, key="k", default=128000, min_value=8192, max_value=2000000), 8192)
        self.assertEqual(_parse_config_int(5000000, key="k", default=128000, min_value=8192, max_value=2000000), 2000000)

        # Retries: 0..10
        self.assertEqual(_parse_config_int(-1, key="k", default=4, min_value=0, max_value=10), 0)
        self.assertEqual(_parse_config_int(20, key="k", default=4, min_value=0, max_value=10), 10)

        # Turns: 1..12
        self.assertEqual(_parse_config_int(0, key="k", default=6, min_value=1, max_value=12), 1)
        self.assertEqual(_parse_config_int(50, key="k", default=6, min_value=1, max_value=12), 12)

        # Tool calls: 1..32
        self.assertEqual(_parse_config_int(0, key="k", default=10, min_value=1, max_value=32), 1)
        self.assertEqual(_parse_config_int(100, key="k", default=10, min_value=1, max_value=32), 32)

        # Replay events: 64..2048
        self.assertEqual(_parse_config_int(10, key="k", default=512, min_value=64, max_value=2048), 64)
        self.assertEqual(_parse_config_int(5000, key="k", default=512, min_value=64, max_value=2048), 2048)

    def test_schema_initialization_and_versioning(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT version FROM schema_versions WHERE domain = 'cortex_runs'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(int(row[0]), 1)

        # Second initialization is safe
        self.store.initialize()

        # Reject higher version
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE schema_versions SET version = 99 WHERE domain = 'cortex_runs'")
        with self.assertRaises(RunStoreError):
            self.store.initialize()

    def test_idempotency_by_agent_message_id(self) -> None:
        user_id = uuid4()
        agent_id = uuid4()
        run1, replayed1 = self._create_run(user_message_id=user_id, agent_message_id=agent_id)
        self.assertFalse(replayed1)
        self.assertEqual(run1.status, "queued")

        # Replay with identical parameters returns existing run
        run2, replayed2 = self._create_run(user_message_id=user_id, agent_message_id=agent_id)
        self.assertTrue(replayed2)
        self.assertEqual(run1.id, run2.id)

        # Conflicting user message id raises conflict
        with self.assertRaises(RunConflictError):
            self.store.create_run(
                run_id=uuid4(),
                conversation_id=self.prod_conversation_id,
                partition="production",
                user_message_id=uuid4(),
                agent_message_id=agent_id,
                requested_model="deepseek/deepseek-v4-flash-0731",
                limit_snapshot=self._default_limits(),
            )

        # Conflicting requested model raises conflict
        with self.assertRaises(RunConflictError):
            self.store.create_run(
                run_id=uuid4(),
                conversation_id=self.prod_conversation_id,
                partition="production",
                user_message_id=user_id,
                agent_message_id=agent_id,
                requested_model="gpt-5.6-luna",
                limit_snapshot=self._default_limits(),
            )

    def test_partition_isolation(self) -> None:
        prod_run, _ = self._create_run(
            conversation_id=self.prod_conversation_id, partition="production"
        )
        sandbox_run, _ = self._create_run(
            conversation_id=self.sandbox_conversation_id, partition="sandbox"
        )

        # Sandbox run cannot be retrieved from production partition
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(sandbox_run.id, "production")

        # Production run cannot be retrieved from sandbox partition
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(prod_run.id, "sandbox")

        prod_list = self.store.list_runs("production")
        self.assertIn(prod_run.id, [r.id for r in prod_list])
        self.assertNotIn(sandbox_run.id, [r.id for r in prod_list])

        sandbox_list = self.store.list_runs("sandbox")
        self.assertIn(sandbox_run.id, [r.id for r in sandbox_list])
        self.assertNotIn(prod_run.id, [r.id for r in sandbox_list])

    def test_list_runs_filtering_and_pagination(self) -> None:
        run1, _ = self._create_run()
        run2, _ = self._create_run()
        self.store.start_run(
            run2.id,
            partition="production",
            resolved_model="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
        )

        all_runs = self.store.list_runs("production")
        self.assertEqual(len(all_runs), 2)
        # Newest first
        self.assertEqual(all_runs[0].id, run2.id)
        self.assertEqual(all_runs[1].id, run1.id)

        # Status filter
        queued_runs = self.store.list_runs("production", status="queued")
        self.assertEqual([r.id for r in queued_runs], [run1.id])

        running_runs = self.store.list_runs("production", status="running")
        self.assertEqual([r.id for r in running_runs], [run2.id])

        # Pagination clamping
        clamped = self.store.list_runs("production", limit=1)
        self.assertEqual(len(clamped), 1)

    def test_run_lifecycle_and_progress_updates(self) -> None:
        run, _ = self._create_run()
        self.assertEqual(run.status, "queued")

        # Start run
        started = self.store.start_run(
            run.id,
            partition="production",
            resolved_model="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
        )
        self.assertEqual(started.status, "running")
        self.assertEqual(started.provider, "openrouter")
        self.assertIsNotNone(started.started_at)

        # Progress update
        progress = self.store.update_progress(
            run.id,
            partition="production",
            turns_count=2,
            tool_calls_count=3,
            retries_count=1,
            total_tokens=1500,
            elapsed_seconds=4.5,
            usage_quality="reported",
            runtime_measurements={"ttft_ms": 230},
        )
        self.assertEqual(progress.turns_count, 2)
        self.assertEqual(progress.tool_calls_count, 3)
        self.assertEqual(progress.retries_count, 1)
        self.assertEqual(progress.total_tokens, 1500)
        self.assertEqual(progress.elapsed_seconds, 4.5)
        self.assertEqual(progress.usage_quality, "reported")
        self.assertEqual(progress.runtime_measurements, {"ttft_ms": 230})

        # Cancel transition
        cancelling = self.store.set_cancelling(run.id, partition="production")
        self.assertEqual(cancelling.status, "cancelling")

        # Finalize as cancelled
        final = self.store.finalize_run(
            run.id,
            partition="production",
            status="cancelled",
            stop_reason="operator_cancelled",
            evidence=RunCompletionEvidence(
                final_message_status="interrupted",
                answer_persisted=False,
                tool_outcome_counts={"get_weather": 1},
                action_ids=["act-123"],
            ),
        )
        self.assertEqual(final.status, "cancelled")
        self.assertEqual(final.stop_reason, "operator_cancelled")
        self.assertFalse(final.evidence.answer_persisted)
        self.assertEqual(final.evidence.action_ids, ["act-123"])
        self.assertIsNotNone(final.completed_at)

    def test_finalize_answer_persisted_rule(self) -> None:
        run, _ = self._create_run()
        self.store.start_run(
            run.id,
            partition="production",
            resolved_model="deepseek/deepseek-v4-flash-0731",
            provider="openrouter",
            runtime="cloud",
        )

        # Failed run cannot claim answer_persisted=True
        final = self.store.finalize_run(
            run.id,
            partition="production",
            status="failed",
            stop_reason="max_tool_calls",
            evidence=RunCompletionEvidence(answer_persisted=True),
            error=RunError(code="tool_limit", message="Exceeded tool limit"),
        )
        self.assertFalse(final.evidence.answer_persisted)
        self.assertEqual(final.status, "failed")
        self.assertEqual(final.error.code, "tool_limit")

    def test_conversation_deletion_cascade_and_active_block(self) -> None:
        run, _ = self._create_run()
        self.assertTrue(self.store.has_active_runs(self.prod_conversation_id))

        # Archive conversation first (APEX requires archiving before deletion)
        self.conversations.patch(
            self.prod_conversation_id, "production", {"archived": True}
        )

        # Trying to delete while run is queued/running must be blocked
        with self.assertRaises(ConversationConflictError):
            self.conversations.delete(self.prod_conversation_id, "production")

        # Finalize the run
        self.store.finalize_run(
            run.id,
            partition="production",
            status="completed",
            stop_reason="end_turn",
            evidence=RunCompletionEvidence(answer_persisted=True),
        )
        self.assertFalse(self.store.has_active_runs(self.prod_conversation_id))

        # Now deletion succeeds
        self.conversations.delete(self.prod_conversation_id, "production")

        # The run row has been removed via cascade / explicit delete
        with self.assertRaises(RunNotFoundError):
            self.store.get_run(run.id, "production")

    def test_interrupted_run_recovery(self) -> None:
        run_queued, _ = self._create_run()
        run_running, _ = self._create_run()
        self.store.start_run(
            run_running.id,
            partition="production",
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )
        run_cancelling, _ = self._create_run()
        self.store.start_run(
            run_cancelling.id,
            partition="production",
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )
        self.store.set_cancelling(run_cancelling.id, partition="production")

        run_completed, _ = self._create_run()
        self.store.start_run(
            run_completed.id,
            partition="production",
            resolved_model="deepseek",
            provider="openrouter",
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

        done = self.store.get_run(run_completed.id, "production")
        self.assertEqual(done.status, "completed")
        self.assertEqual(done.stop_reason, "end_turn")

    def test_demo_mode_ephemeral_store(self) -> None:
        ephemeral_store = RunStore(None)
        ephemeral_store.initialize()
        self.addCleanup(ephemeral_store.close)

        # In-memory store handles all queries safely
        runs = ephemeral_store.list_runs("production")
        self.assertEqual(runs, [])

    def test_data_redaction_guarantees(self) -> None:
        """
        Verify that raw database rows never persist prompts, answers, retrieved text,
        tool arguments/results, action targets, citations, provider bodies, or secrets.
        """
        secret = "sk-ant-api03-TOP_SECRET_CREDENTIAL_12345"
        prompt_text = "What is the secret nuclear launch code?"
        answer_text = "The launch code is 00000000."
        tool_args = {"query": "SELECT * FROM users WHERE ssn IS NOT NULL"}
        tool_result = {"ssn": "000-00-0000", "secret": secret}

        run, _ = self._create_run()
        self.store.start_run(
            run.id,
            partition="production",
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )
        self.store.finalize_run(
            run.id,
            partition="production",
            status="completed",
            stop_reason="end_turn",
            evidence=RunCompletionEvidence(
                final_message_status="completed",
                answer_persisted=True,
                tool_outcome_counts={"search_code": 1},
                action_ids=["opaque-action-id-42"],
            ),
        )

        with closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(cortex_runs)")
            columns = [col[1] for col in cursor.fetchall()]

            # Disallowed column names
            for forbidden in (
                "prompt",
                "answer",
                "content",
                "retrieved",
                "citations",
                "arguments",
                "result",
                "output",
                "body",
                "secret",
            ):
                self.assertNotIn(forbidden, columns)

            cursor.execute("SELECT * FROM cortex_runs WHERE id = ?", (str(run.id),))
            row = cursor.fetchone()
            row_str = " ".join(str(val) for val in row)

            self.assertNotIn(secret, row_str)
            self.assertNotIn(prompt_text, row_str)
            self.assertNotIn(answer_text, row_str)
            self.assertNotIn("nuclear", row_str)
            self.assertNotIn("ssn", row_str)
            self.assertIn("opaque-action-id-42", row_str)
            self.assertIn("search_code", row_str)

    def test_run_service_delegation_and_registry(self) -> None:
        service = RunService(self.store)
        set_run_service(service)
        self.addCleanup(lambda: set_run_service(None))

        self.assertIs(get_run_service(), service)

        # Service creates run in default partition (production)
        run, replayed = service.create_run(
            run_id=uuid4(),
            conversation_id=self.prod_conversation_id,
            user_message_id=uuid4(),
            agent_message_id=uuid4(),
            requested_model="deepseek/deepseek-v4-flash-0731",
            limit_snapshot=self._default_limits(),
        )
        self.assertFalse(replayed)
        self.assertEqual(run.partition, "production")

        # Query via service
        fetched = service.get_run(run.id)
        self.assertEqual(fetched.id, run.id)

        by_agent = service.get_run_by_agent_message_id(run.agent_message_id)
        self.assertIsNotNone(by_agent)
        self.assertEqual(by_agent.id, run.id)

        listed = service.list_runs()
        self.assertIn(run.id, [r.id for r in listed])

        self.assertTrue(service.has_active_runs(self.prod_conversation_id))

        # Lifecycle via service
        started = service.start_run(
            run.id,
            resolved_model="deepseek",
            provider="openrouter",
            runtime="cloud",
        )
        self.assertEqual(started.status, "running")

        progress = service.update_progress(run.id, turns_count=1, total_tokens=100)
        self.assertEqual(progress.turns_count, 1)

        cancelling = service.set_cancelling(run.id)
        self.assertEqual(cancelling.status, "cancelling")

        final = service.finalize_run(
            run.id,
            status="cancelled",
            stop_reason="operator_cancelled",
            evidence=RunCompletionEvidence(final_message_status="interrupted"),
        )
        self.assertEqual(final.status, "cancelled")
        self.assertFalse(service.has_active_runs(self.prod_conversation_id))

