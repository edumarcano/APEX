"""Focused persistence coverage for durable Cortex conversation trees."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from core.conversations.store import (
    ConversationBusyError,
    ConversationConflictError,
    ConversationStore,
)


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
            agent="cloud",
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
            agent="cloud",
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
                agent="cloud",
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
        user, agent, _, _ = self._begin(prompt="Remove me")
        self.store.finalize(
            conversation_id=self.conversation_id,
            agent_id=agent.id,
            answer="Gone",
            status="completed",
            response_metadata={},
        )
        self.store.patch(self.conversation_id, "production", {"archived": True})
        self.store.delete(self.conversation_id, "production")
        with self.assertRaises(Exception):
            self.store.detail(self.conversation_id, "production")
        with self.assertRaises(Exception):
            self.store.detail(self.conversation_id, "sandbox")

    def test_delete_rejects_active_and_pending_conversations(self) -> None:
        with self.assertRaises(ConversationConflictError):
            self.store.delete(self.conversation_id, "production")
        self._begin(prompt="Pending")
        self.store.patch(self.conversation_id, "production", {"archived": True})
        with self.assertRaises(ConversationConflictError):
            self.store.delete(self.conversation_id, "production")


if __name__ == "__main__":
    unittest.main()
