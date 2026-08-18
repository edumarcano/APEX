from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from core.context import ContextAssembler, ContextPolicy
from core.knowledge.service import KnowledgeService
from core.knowledge.store import KnowledgeStore
from core.retrieval.models import RetrievalItem
from core.retrieval.service import RetrievalService
from core.retrieval.store import RetrievalStore


class ContextAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "apex_memory.db"
        self.retrieval_store = RetrievalStore(path)
        self.retrieval_store.initialize()
        self.knowledge_store = KnowledgeStore(path)
        self.knowledge_store.initialize()
        self.retrieval = RetrievalService(self.retrieval_store, enabled=True)
        self.knowledge = KnowledgeService(self.knowledge_store)
        self.assembler = ContextAssembler(self.retrieval, self.knowledge)

    def tearDown(self) -> None:
        self.knowledge_store.close()
        self.retrieval_store.close()
        self.temp.cleanup()

    def test_policy_blocks_context_outside_enabled_production(self) -> None:
        conversation_id = uuid4()
        disabled = self.assembler.assemble(
            prompt="project", conversation_id=conversation_id,
            policy=ContextPolicy("felis", "production", False),
        )
        sandbox = self.assembler.assemble(
            prompt="project", conversation_id=conversation_id,
            policy=ContextPolicy("felis", "sandbox", True),
        )
        self.assertFalse(disabled.enabled)
        self.assertFalse(sandbox.enabled)

    def test_assembles_other_conversations_and_active_personal_context(self) -> None:
        current = uuid4()
        other = uuid4()
        self.retrieval_store.upsert_item(RetrievalItem(
            namespace="conversation", source_type="message", source_id="other-message",
            partition="production", conversation_id=str(other), message_id="other-message",
            role="user", timestamp="2026-01-01T00:00:00+00:00",
            locator=f"conversation/{other}/message/other-message", content_hash="other", text="Project Alpha uses SQLite.",
        ))
        self.retrieval_store.upsert_item(RetrievalItem(
            namespace="conversation", source_type="message", source_id="current-message",
            partition="production", conversation_id=str(current), message_id="current-message",
            role="user", timestamp="2026-01-01T00:00:00+00:00",
            locator=f"conversation/{current}/message/current-message", content_hash="current", text="Project Alpha hidden current branch.",
        ))
        source = self.knowledge_store.create_source(kind="manual", partition="production", locator="manual/test", original_text="Project Alpha preference")
        record = self.knowledge_store.create_record(partition="production", kind="preference", text="Project Alpha prefers concise plans.", source_ids=[source.id])

        bundle = self.assembler.assemble(
            prompt="Project Alpha", conversation_id=current,
            policy=ContextPolicy("felis", "production", True),
        )

        self.assertIn("<untrusted_retrieved_context>", bundle.rendered)
        self.assertIn("concise plans", bundle.rendered)
        self.assertIn("uses SQLite", bundle.rendered)
        self.assertNotIn("hidden current branch", bundle.rendered)
        self.assertIn(str(record.id), [reference.source_id for reference in bundle.references])


if __name__ == "__main__":
    unittest.main()
