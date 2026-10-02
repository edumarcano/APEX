"""Focused persistence coverage for durable Cortex conversation trees."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from core.conversations.store import (
    ConversationBusyError,
    ConversationConflictError,
    ConversationStore,
    ConversationStoreError,
)
from core.conversations.retention import purge_expired_archived_conversations
from core.briefings.store import BriefingSessionStore
from core.connectors.models import utc_now_iso
from core.retrieval import RetrievalStore
from core.retrieval.models import RetrievalItem
from core.runs import RunStore
from core.runs.models import RunLimitSnapshot


class ConversationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ConversationStore(Path(self.temp_dir.name) / "apex_memory.db")
        self.store.initialize()
        self.conversation_id = uuid4()
        self.store.create(
            conversation_id=self.conversation_id,
            title="A conversation",
            partition="production",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def _begin(self, *, user_id=None, agent_id=None, parent_id=None, prompt="Hello"):
        return self.store.begin_turn(
            conversation_id=self.conversation_id,
            partition="production",
            user_id=user_id or uuid4(),
            agent_id=agent_id or uuid4(),
            parent_id=parent_id,
            prompt=prompt,
            agent="apex",
            request_metadata={"selected_tool_names": None},
            selected_tool_names=None,
            tool_profile_id=None,
            history_limit=6,
        )

    def test_persists_tree_and_reconstructs_completed_parent_path(self) -> None:
        user, agent, history, replayed = self._begin()
        self.assertFalse(replayed)
        self.assertEqual(history, [])
        self.store.finalize(
            conversation_id=self.conversation_id,
            agent_id=agent.id,
            answer="Hi",
            status="completed",
            response_metadata={"tool_outputs": [{"name": "example"}]},
        )
        second_user, second_agent, history, _ = self._begin(parent_id=agent.id, prompt="Again")
        self.assertEqual([message.content for message in history], ["Hello", "Hi"])
        detail = self.store.detail(self.conversation_id, "production")
        self.assertEqual(detail.active_leaf_message_id, second_agent.id)
        stored_agent = next(message for message in detail.messages if message.id == agent.id)
        self.assertEqual(stored_agent.response_metadata, {"tool_outputs": [{"name": "example"}]})
        self.assertEqual(second_user.parent_message_id, agent.id)

    def test_exact_replay_does_not_create_a_second_message(self) -> None:
        user_id, agent_id = uuid4(), uuid4()
        user, agent, _, _ = self._begin(user_id=user_id, agent_id=agent_id)
        self.store.finalize(conversation_id=self.conversation_id, agent_id=agent.id, answer="Hi", status="completed", response_metadata={})
        replay_user, replay_agent, history, replayed = self._begin(user_id=user_id, agent_id=agent_id)
        self.assertTrue(replayed)
        self.assertEqual(replay_user.id, user.id)
        self.assertEqual(replay_agent.id, agent.id)
        self.assertEqual(history, [])
        with self.assertRaises(ConversationConflictError):
            self._begin(user_id=user_id, agent_id=agent_id, prompt="Different")

    def test_replay_rejects_conflicting_parent(self) -> None:
        user_id, agent_id = uuid4(), uuid4()
        user, agent, _, _ = self._begin(user_id=user_id, agent_id=agent_id)
        self.store.finalize(
            conversation_id=self.conversation_id,
            agent_id=agent.id,
            answer="Hi",
            status="completed",
            response_metadata={},
        )
        with self.assertRaises(ConversationConflictError):
            self.store.begin_turn(
                conversation_id=self.conversation_id,
                partition="production",
                user_id=user_id,
                agent_id=agent_id,
                parent_id=uuid4(),
                prompt=user.content,
                agent="apex",
                request_metadata={"selected_tool_names": None},
                selected_tool_names=None,
                tool_profile_id=None,
                history_limit=6,
            )

    def test_retry_reuses_completed_user_and_creates_agent_sibling(self) -> None:
        user, first_agent, _, _ = self._begin()
        self.store.finalize(
            conversation_id=self.conversation_id,
            agent_id=first_agent.id,
            answer="First answer",
            status="completed",
            response_metadata={},
        )
        retry_user, retry_agent, history, replayed = self._begin(
            user_id=user.id,
            parent_id=user.parent_message_id,
            prompt=user.content,
        )
        self.assertFalse(replayed)
        self.assertEqual(retry_user.id, user.id)
        self.assertNotEqual(retry_agent.id, first_agent.id)
        self.assertEqual(retry_agent.parent_message_id, user.id)
        self.assertEqual(history, [])
        self.assertEqual(
            len([message for message in self.store.detail(self.conversation_id, "production").messages if message.role == "user"]),
            1,
        )

    def test_rejects_parallel_turn_and_recovers_pending_turn(self) -> None:
        _, agent, _, _ = self._begin()
        with self.assertRaises(ConversationBusyError):
            self._begin(prompt="Parallel")
        self.assertEqual(self.store.recover_interrupted(), 1)
        detail = self.store.detail(self.conversation_id, "production")
        interrupted = next(message for message in detail.messages if message.role == "agent")
        stored_user = next(message for message in detail.messages if message.role == "user")
        self.assertEqual(interrupted.status, "interrupted")
        retry_user, retry_agent, _, _ = self._begin(user_id=stored_user.id, parent_id=stored_user.parent_message_id, prompt=stored_user.content)
        self.assertEqual(retry_user.id, stored_user.id)
        self.assertEqual(retry_agent.parent_message_id, retry_user.id)

    def test_partition_isolated_and_archive_blocks_turns(self) -> None:
        with self.assertRaises(Exception):
            self.store.detail(self.conversation_id, "sandbox")
        self.store.patch(self.conversation_id, "production", {"archived": True})
        with self.assertRaises(ConversationConflictError):
            self._begin()

    def test_delete_removes_archived_conversation_and_message_tree(self) -> None:
        retrieval_store = RetrievalStore(self.store._db_path)
        retrieval_store.initialize()
        self.addCleanup(retrieval_store.close)
        user, agent, _, _ = self._begin(prompt="Remove me")
        self.store.finalize(
            conversation_id=self.conversation_id,
            agent_id=agent.id,
            answer="Gone",
            status="completed",
            response_metadata={},
        )
        timestamp = utc_now_iso()
        linked_id = retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation", source_type="message", source_id=str(user.id),
                partition="production", conversation_id=str(self.conversation_id),
                message_id=str(user.id), role="user", timestamp=timestamp,
                locator=f"conversation/{self.conversation_id}/message/{user.id}",
                content_hash="linked-delete-test", text="Remove linked message",
            )
        )
        orphan_id = retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation", source_type="summary", source_id="orphan",
                partition="production", conversation_id=str(self.conversation_id),
                message_id=None, role=None, timestamp=timestamp,
                locator=f"conversation/{self.conversation_id}/summary",
                content_hash="orphan-delete-test", text="Remove conversation summary",
            )
        )
        retained_id = retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation", source_type="summary", source_id="retained",
                partition="production", conversation_id=None, message_id=None,
                role=None, timestamp=timestamp, locator="conversation/retained",
                content_hash="retained-delete-test", text="Keep unrelated summary",
            )
        )
        for item_id in (linked_id, orphan_id, retained_id):
            retrieval_store.upsert_embedding(item_id, "test-model", [1.0, 0.0])
        self.store.patch(self.conversation_id, "production", {"archived": True})
        self.store.delete(self.conversation_id, "production")
        self.assertEqual(retrieval_store.counts(), (1, 1))
        with retrieval_store._connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT item_id FROM retrieval_items_fts ORDER BY item_id"
                ).fetchall(),
                [(retained_id,)],
            )
        with self.assertRaises(Exception):
            self.store.detail(self.conversation_id, "production")
        with self.assertRaises(Exception):
            self.store.detail(self.conversation_id, "sandbox")

    def test_delete_remains_available_when_retrieval_domain_is_absent(self) -> None:
        self.store.patch(self.conversation_id, "production", {"archived": True})
        with self.store._connection() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'retrieval_items'"
                ).fetchone()
            )

        self.store.delete(self.conversation_id, "production")
        with self.assertRaises(Exception):
            self.store.detail(self.conversation_id, "production")

    def test_unsupported_retrieval_schema_blocks_manual_and_automatic_deletion(self) -> None:
        for has_conversation_id in (False, True):
            for deletion_path in ("manual", "retention"):
                with self.subTest(
                    has_conversation_id=has_conversation_id, deletion_path=deletion_path
                ):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        store = ConversationStore(Path(temp_dir) / "apex_memory.db")
                        store.initialize()
                        conversation_id = uuid4()
                        store.create(
                            conversation_id=conversation_id, title="Preserve me",
                            partition="production", origin="hud", agent="apex",
                            selected_tool_names=None, tool_profile_id=None,
                        )
                        user, agent, _, _ = store.begin_turn(
                            conversation_id=conversation_id, partition="production",
                            user_id=uuid4(), agent_id=uuid4(), parent_id=None,
                            prompt="Keep this message", agent="apex", request_metadata={},
                            selected_tool_names=None, tool_profile_id=None, history_limit=6,
                        )
                        store.finalize(
                            conversation_id=conversation_id, agent_id=agent.id,
                            answer="Keep this answer", status="completed",
                            response_metadata={},
                        )
                        store.patch(conversation_id, "production", {"archived": True})
                        archived_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
                        with closing(sqlite3.connect(store._db_path)) as conn, conn:
                            conn.execute(
                                "UPDATE conversations SET archived_at = ? WHERE id = ?",
                                (archived_at.isoformat(), str(conversation_id)),
                            )
                            conn.execute(
                                "INSERT INTO schema_versions(domain, version) VALUES ('retrieval', 999)"
                            )
                            if has_conversation_id:
                                conn.execute(
                                    "CREATE TABLE retrieval_items(id TEXT PRIMARY KEY, conversation_id TEXT, text TEXT)"
                                )
                                conn.execute(
                                    "INSERT INTO retrieval_items VALUES ('preserved', ?, 'private derived text')",
                                    (str(conversation_id),),
                                )
                            else:
                                conn.execute(
                                    "CREATE TABLE retrieval_items(id TEXT PRIMARY KEY, text TEXT)"
                                )
                                conn.execute(
                                    "INSERT INTO retrieval_items VALUES ('preserved', 'private derived text')"
                                )

                        with store._connection() as conn:
                            before = (
                                conn.execute(
                                    "SELECT id, archived_at FROM conversations WHERE id = ?",
                                    (str(conversation_id),),
                                ).fetchall(),
                                conn.execute(
                                    "SELECT id, content, status FROM conversation_messages WHERE conversation_id = ? ORDER BY id",
                                    (str(conversation_id),),
                                ).fetchall(),
                                conn.execute("SELECT * FROM retrieval_items").fetchall(),
                                conn.execute(
                                    "SELECT domain, version FROM schema_versions WHERE domain = 'retrieval'"
                                ).fetchall(),
                            )
                        with self.assertRaises(ConversationConflictError):
                            if deletion_path == "manual":
                                store.delete(conversation_id, "production")
                            else:
                                asyncio.run(
                                    purge_expired_archived_conversations(
                                        store, retention_days=30, stop_event=asyncio.Event()
                                    )
                                )
                        with store._connection() as conn:
                            after = (
                                conn.execute(
                                    "SELECT id, archived_at FROM conversations WHERE id = ?",
                                    (str(conversation_id),),
                                ).fetchall(),
                                conn.execute(
                                    "SELECT id, content, status FROM conversation_messages WHERE conversation_id = ? ORDER BY id",
                                    (str(conversation_id),),
                                ).fetchall(),
                                conn.execute("SELECT * FROM retrieval_items").fetchall(),
                                conn.execute(
                                    "SELECT domain, version FROM schema_versions WHERE domain = 'retrieval'"
                                ).fetchall(),
                            )
                        self.assertEqual(after, before)
                        store.close()

    def test_unsupported_retrieval_validation_precedes_message_delete_triggers(self) -> None:
        for deletion_path in ("manual", "retention"):
            with self.subTest(deletion_path=deletion_path):
                with tempfile.TemporaryDirectory() as temp_dir:
                    store = ConversationStore(Path(temp_dir) / "apex_memory.db")
                    store.initialize()
                    retrieval_store = RetrievalStore(store._db_path)
                    retrieval_store.initialize()
                    conversation_id = uuid4()
                    store.create(
                        conversation_id=conversation_id, title="Trigger guard",
                        partition="production", origin="hud", agent="apex",
                        selected_tool_names=None, tool_profile_id=None,
                    )
                    user, agent, _, _ = store.begin_turn(
                        conversation_id=conversation_id, partition="production",
                        user_id=uuid4(), agent_id=uuid4(), parent_id=None,
                        prompt="Keep trigger-linked text", agent="apex", request_metadata={},
                        selected_tool_names=None, tool_profile_id=None, history_limit=6,
                    )
                    store.finalize(
                        conversation_id=conversation_id, agent_id=agent.id,
                        answer="Keep it", status="completed", response_metadata={},
                    )
                    retrieval_id = retrieval_store.upsert_item(
                        RetrievalItem(
                            namespace="conversation", source_type="message", source_id=str(user.id),
                            partition="production", conversation_id=str(conversation_id),
                            message_id=str(user.id), role="user", timestamp=utc_now_iso(),
                            locator=f"conversation/{conversation_id}/message/{user.id}",
                            content_hash="trigger-guard", text="private retrieval text",
                        )
                    )
                    store.patch(conversation_id, "production", {"archived": True})
                    with closing(sqlite3.connect(store._db_path)) as conn, conn:
                        conn.execute(
                            "UPDATE conversations SET archived_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                            (str(conversation_id),),
                        )
                        conn.execute(
                            "UPDATE schema_versions SET version = 999 WHERE domain = 'retrieval'"
                        )
                        conn.execute(
                            """CREATE TRIGGER abort_message_delete BEFORE DELETE ON conversation_messages
                            BEGIN SELECT RAISE(ABORT, 'message deletion reached'); END"""
                        )

                    with self.assertRaises(ConversationConflictError) as raised:
                        if deletion_path == "manual":
                            store.delete(conversation_id, "production")
                        else:
                            asyncio.run(
                                purge_expired_archived_conversations(
                                    store, retention_days=30, stop_event=asyncio.Event()
                                )
                            )
                    self.assertNotIn("message deletion reached", str(raised.exception))
                    with store._connection() as conn:
                        self.assertIsNotNone(
                            conn.execute(
                                "SELECT 1 FROM conversation_messages WHERE id = ?", (str(user.id),)
                            ).fetchone()
                        )
                        self.assertIsNotNone(
                            conn.execute(
                                "SELECT 1 FROM retrieval_items WHERE id = ?", (retrieval_id,)
                            ).fetchone()
                        )
                    retrieval_store.close()
                    store.close()

    def test_delete_rejects_active_and_pending_conversations(self) -> None:
        with self.assertRaises(ConversationConflictError):
            self.store.delete(self.conversation_id, "production")
        self._begin(prompt="Pending")
        self.store.patch(self.conversation_id, "production", {"archived": True})
        with self.assertRaises(ConversationConflictError):
            self.store.delete(self.conversation_id, "production")

    def _set_archived_at(self, conversation_id, partition, archived_at: datetime) -> None:
        with closing(sqlite3.connect(self.store._db_path)) as conn, conn:
            conn.execute(
                "UPDATE conversations SET archived_at = ? WHERE id = ? AND partition = ?",
                (archived_at.isoformat(), str(conversation_id), partition),
            )

    def test_repeated_archive_preserves_age_and_restore_starts_new_period(self) -> None:
        self.store.patch(self.conversation_id, "production", {"archived": True})
        original = self.store.get_summary(self.conversation_id, "production").archived_at
        self._set_archived_at(
            self.conversation_id,
            "production",
            datetime.now(timezone.utc) - timedelta(days=29),
        )
        expired_timestamp = self.store.get_summary(self.conversation_id, "production").archived_at

        repeated = self.store.patch(self.conversation_id, "production", {"archived": True})
        self.assertEqual(repeated.archived_at, expired_timestamp)

        self.store.patch(self.conversation_id, "production", {"archived": False})
        rearchived = self.store.patch(self.conversation_id, "production", {"archived": True})
        self.assertNotEqual(rearchived.archived_at, expired_timestamp)
        self.assertNotEqual(original, expired_timestamp)

    def test_purge_uses_archive_age_and_covers_both_partitions(self) -> None:
        sandbox_id = uuid4()
        recent_id = uuid4()
        self.store.create(
            conversation_id=sandbox_id,
            title="Sandbox conversation",
            partition="sandbox",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )
        self.store.create(
            conversation_id=recent_id,
            title="Recently archived conversation",
            partition="production",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )
        self.store.patch(self.conversation_id, "production", {"archived": True})
        self.store.patch(sandbox_id, "sandbox", {"archived": True})
        self.store.patch(recent_id, "production", {"archived": True})
        self._set_archived_at(
            self.conversation_id,
            "production",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self._set_archived_at(
            sandbox_id,
            "sandbox",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self._set_archived_at(
            recent_id,
            "production",
            datetime(2026, 1, 3, tzinfo=timezone.utc),
        )
        now = datetime(2026, 2, 1, tzinfo=timezone.utc)

        self.assertEqual(
            self.store.purge_expired_archived(retention_days=30, now=now), 2
        )
        with self.assertRaises(Exception):
            self.store.get_summary(self.conversation_id, "production")
        with self.assertRaises(Exception):
            self.store.get_summary(sandbox_id, "sandbox")
        self.store.get_summary(recent_id, "production")

    def test_purge_skips_recent_pending_and_active_conversations(self) -> None:
        now = datetime(2026, 2, 1, tzinfo=timezone.utc)
        run_store = RunStore(self.store._db_path)
        self.addCleanup(run_store.close)
        run_store.initialize()
        user, agent, _, _ = self._begin()
        run_store.create_run(
            run_id=uuid4(),
            conversation_id=self.conversation_id,
            partition="production",
            user_message_id=user.id,
            agent_message_id=agent.id,
            requested_model="test-model",
            limit_snapshot=RunLimitSnapshot(
                max_elapsed_seconds=600,
                max_retries=4,
                max_model_turns=6,
                max_tool_calls=10,
            ),
        )
        with closing(sqlite3.connect(self.store._db_path)) as conn, conn:
            conn.execute(
                "UPDATE conversation_messages SET status = 'completed' WHERE id = ?",
                (str(agent.id),),
            )
        self.store.patch(self.conversation_id, "production", {"archived": True})
        self._set_archived_at(
            self.conversation_id,
            "production",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        pending_id = uuid4()
        self.store.create(
            conversation_id=pending_id,
            title="Pending conversation",
            partition="production",
            origin="hud",
            agent="apex",
            selected_tool_names=None,
            tool_profile_id=None,
        )
        self.store.begin_turn(
            conversation_id=pending_id,
            partition="production",
            user_id=uuid4(),
            agent_id=uuid4(),
            parent_id=None,
            prompt="Pending",
            agent="apex",
            request_metadata={},
            selected_tool_names=None,
            tool_profile_id=None,
            history_limit=6,
        )
        self.store.patch(pending_id, "production", {"archived": True})
        self._set_archived_at(
            pending_id, "production", datetime(2026, 1, 1, tzinfo=timezone.utc)
        )

        self.assertEqual(
            self.store.purge_expired_archived(retention_days=30, now=now), 0
        )
        self.store.get_summary(self.conversation_id, "production")
        self.store.get_summary(pending_id, "production")

    def test_purge_enforces_minimum_retention_and_bounded_batches(self) -> None:
        with self.assertRaises(ValueError):
            self.store.purge_expired_archived(retention_days=13)

        now = datetime(2026, 2, 1, tzinfo=timezone.utc)
        self.store.patch(self.conversation_id, "production", {"archived": True})
        self._set_archived_at(
            self.conversation_id,
            "production",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        for _ in range(100):
            conversation_id = uuid4()
            self.store.create(
                conversation_id=conversation_id,
                title="Archived conversation",
                partition="production",
                origin="hud",
                agent="apex",
                selected_tool_names=None,
                tool_profile_id=None,
            )
            self.store.patch(conversation_id, "production", {"archived": True})
            self._set_archived_at(
                conversation_id,
                "production",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

        self.assertEqual(
            self.store.purge_expired_archived(retention_days=30, limit=1000, now=now),
            100,
        )
        self.assertEqual(
            self.store.purge_expired_archived(retention_days=30, now=now), 1
        )

    def test_retention_sweep_drains_multiple_batches_and_honors_shutdown(self) -> None:
        archived_at = "2000-01-01T00:00:00+00:00"
        created_at = "1999-12-01T00:00:00+00:00"
        expired_ids = [uuid4() for _ in range(205)]
        with closing(sqlite3.connect(self.store._db_path)) as conn, conn:
            conn.executemany(
                """
                INSERT INTO conversations (
                    id, title, partition, origin, agent, created_at, updated_at, archived_at
                ) VALUES (?, 'Expired', 'production', 'hud', 'apex', ?, ?, ?)
                """,
                [
                    (str(conversation_id), created_at, created_at, archived_at)
                    for conversation_id in expired_ids
                ],
            )

        deleted = asyncio.run(
            purge_expired_archived_conversations(
                self.store,
                retention_days=30,
                stop_event=asyncio.Event(),
            )
        )
        self.assertEqual(deleted, len(expired_ids))
        with self.store._connection() as conn:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE archived_at IS NOT NULL"
            ).fetchone()[0]
        self.assertEqual(remaining, 0)

        async def stop_between_batches() -> tuple[int, int]:
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()

            class StopAfterBatch:
                calls = 0

                def purge_expired_archived(self, **_kwargs: object) -> int:
                    self.calls += 1
                    loop.call_soon_threadsafe(stop_event.set)
                    return 100

            fake_store = StopAfterBatch()
            deleted_before_stop = await purge_expired_archived_conversations(
                fake_store,  # type: ignore[arg-type]
                retention_days=30,
                stop_event=stop_event,
            )
            return deleted_before_stop, fake_store.calls

        deleted_before_stop, batches_before_stop = asyncio.run(stop_between_batches())
        self.assertEqual(deleted_before_stop, 100)
        self.assertEqual(batches_before_stop, 1)

    def test_retention_purge_cascades_run_briefing_and_retrieval_data(self) -> None:
        run_store = RunStore(self.store._db_path)
        run_store.initialize()
        self.addCleanup(run_store.close)
        briefing_store = BriefingSessionStore(self.store._db_path)
        briefing_store.initialize()
        self.addCleanup(briefing_store.close)
        retrieval_store = RetrievalStore(self.store._db_path)
        retrieval_store.initialize()
        self.addCleanup(retrieval_store.close)

        user, agent, _, _ = self._begin(prompt="Retained source text")
        run, _ = run_store.create_run(
            run_id=uuid4(),
            conversation_id=self.conversation_id,
            partition="production",
            user_message_id=user.id,
            agent_message_id=agent.id,
            requested_model="test-model",
            limit_snapshot=RunLimitSnapshot(
                max_elapsed_seconds=600,
                max_retries=4,
                max_model_turns=6,
                max_tool_calls=10,
            ),
        )
        now = utc_now_iso()
        briefing_id = uuid4()
        with closing(sqlite3.connect(self.store._db_path)) as conn, conn:
            conn.execute(
                "UPDATE conversation_messages SET status = 'completed' WHERE id = ?",
                (str(agent.id),),
            )
            conn.execute(
                "UPDATE cortex_runs SET status = 'completed' WHERE id = ?",
                (str(run.id),),
            )
            conn.execute(
                """
                INSERT INTO briefing_sessions (
                    id, partition, idempotency_key, conversation_id,
                    opening_message_id, run_id, profile_id, created_at,
                    request_json, configuration_json
                ) VALUES (?, 'production', 'retention-test', ?, ?, ?, 'daily', ?, '{}', '{}')
                """,
                (
                    str(briefing_id),
                    str(self.conversation_id),
                    str(user.id),
                    str(run.id),
                    now,
                ),
            )
        message_retrieval_id = retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation",
                source_type="message",
                source_id=str(user.id),
                partition="production",
                conversation_id=str(self.conversation_id),
                message_id=str(user.id),
                role="user",
                timestamp=now,
                locator=f"conversation/{self.conversation_id}/message/{user.id}",
                content_hash="retention-test",
                text=user.content,
            )
        )
        related_id = retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation", source_type="summary", source_id="retention-orphan",
                partition="production", conversation_id=str(self.conversation_id),
                message_id=None, role=None, timestamp=now,
                locator=f"conversation/{self.conversation_id}/summary",
                content_hash="retention-orphan", text="Remove archived summary",
            )
        )
        unrelated_id = retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation", source_type="summary", source_id="retention-unrelated",
                partition="production", conversation_id=None, message_id=None,
                role=None, timestamp=now, locator="conversation/unrelated",
                content_hash="retention-unrelated", text="Keep unrelated summary",
            )
        )
        for item_id in (
            message_retrieval_id,
            related_id,
            unrelated_id,
        ):
            retrieval_store.upsert_embedding(item_id, "test-model", [1.0, 0.0])
        self.store.patch(self.conversation_id, "production", {"archived": True})
        self._set_archived_at(
            self.conversation_id,
            "production",
            datetime(2000, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(
            asyncio.run(
                purge_expired_archived_conversations(
                    self.store,
                    retention_days=30,
                    stop_event=asyncio.Event(),
                )
            ),
            1,
        )
        self.assertEqual(retrieval_store.counts(), (1, 1))
        with retrieval_store._connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT item_id FROM retrieval_items_fts ORDER BY item_id"
                ).fetchall(),
                [(unrelated_id,)],
            )
        with self.assertRaises(Exception):
            run_store.get_run(run.id, partition="production")
        with self.assertRaises(Exception):
            briefing_store.get(briefing_id, "production")


class ConversationMigrationTests(unittest.TestCase):
    def test_v1_history_is_rejected_without_rewriting_data(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "apex_memory.db"
        conversation_id, user_id, agent_id = uuid4(), uuid4(), uuid4()
        timestamp = "2026-09-01T12:00:00+00:00"

        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE schema_versions (domain TEXT PRIMARY KEY NOT NULL, version INTEGER NOT NULL);
                CREATE TABLE conversations (
                    id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL, partition TEXT NOT NULL,
                    origin TEXT NOT NULL, agent TEXT NOT NULL, selected_tool_names_json TEXT,
                    tool_profile_id TEXT, active_leaf_message_id TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, archived_at TEXT);
                CREATE TABLE conversation_messages (
                    id TEXT PRIMARY KEY NOT NULL, conversation_id TEXT NOT NULL,
                    parent_message_id TEXT, role TEXT NOT NULL, content TEXT NOT NULL,
                    status TEXT NOT NULL, agent TEXT, request_metadata_json TEXT,
                    response_metadata_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                """
            )
            conn.execute("INSERT INTO schema_versions VALUES ('conversations', 1)")
            conn.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(conversation_id), "Existing history", "production", "hud", "legacy",
                    json.dumps(["get_weather_forecast"]), "daily", str(agent_id), timestamp,
                    timestamp, None,
                ),
            )
            conn.execute(
                "INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(user_id), str(conversation_id), None, "user", "Weather?", "completed", None,
                 json.dumps({"model_id": "z-ai/glm-5.3-flash"}), None, timestamp, timestamp),
            )
            conn.execute(
                "INSERT INTO conversation_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(agent_id), str(conversation_id), str(user_id), "agent", "Checking.", "pending", "legacy",
                 json.dumps({"model_id": "z-ai/glm-5.3-flash"}),
                 json.dumps({"agent_used": {"key": "legacy", "provider": "openrouter", "model_id": "z-ai/glm-5.3-flash", "runtime": "cloud"}}),
                 timestamp, timestamp),
            )

        store = ConversationStore(path)
        self.addCleanup(store.close)
        with self.assertRaisesRegex(ConversationStoreError, "Unsupported conversations persistence schema"):
            store.initialize()
        with closing(sqlite3.connect(path)) as conn:
            self.assertEqual(conn.execute("SELECT version FROM schema_versions WHERE domain='conversations'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT agent FROM conversations WHERE id=?", (str(conversation_id),)).fetchone()[0], "legacy")
            self.assertEqual(conn.execute("SELECT response_metadata_json FROM conversation_messages WHERE id=?", (str(agent_id),)).fetchone()[0], json.dumps({"agent_used": {"key": "legacy", "provider": "openrouter", "model_id": "z-ai/glm-5.3-flash", "runtime": "cloud"}}))


if __name__ == "__main__":
    unittest.main()
