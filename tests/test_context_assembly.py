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
            policy=ContextPolicy("apex", "production", False),
        )
        sandbox = self.assembler.assemble(
            prompt="project", conversation_id=conversation_id,
            policy=ContextPolicy("apex", "sandbox", True),
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
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertIn("<untrusted_retrieved_context>", bundle.rendered)
        self.assertIn("concise plans", bundle.rendered)
        self.assertIn("uses SQLite", bundle.rendered)
        self.assertNotIn("hidden current branch", bundle.rendered)
        self.assertIn(str(record.id), [reference.source_id for reference in bundle.references])


    def test_bounds_conversation_and_personal_record_counts(self) -> None:
        current = uuid4()
        for idx in range(5):
            other_id = uuid4()
            self.retrieval_store.upsert_item(
                RetrievalItem(
                    namespace="conversation",
                    source_type="message",
                    source_id=f"msg-{idx}",
                    partition="production",
                    conversation_id=str(other_id),
                    message_id=f"msg-{idx}",
                    role="user",
                    timestamp="2026-01-01T00:00:00+00:00",
                    locator=f"conversation/{other_id}/message/msg-{idx}",
                    content_hash=f"hash-{idx}",
                    text=f"Topic Beta conversation excerpt number {idx}",
                )
            )

        source = self.knowledge_store.create_source(
            kind="manual",
            partition="production",
            locator="manual/test",
            original_text="Topic Beta source text",
        )

        for entity_idx in range(3):
            entity = self.knowledge_store.create_entity(
                f"BetaEntity_{entity_idx}"
            )
            self.knowledge_store.add_alias(entity.id, f"Beta_{entity_idx}")
            for rec_idx in range(3):
                self.knowledge_store.create_record(
                    partition="production",
                    kind="fact",
                    text=f"Topic Beta fact {entity_idx}-{rec_idx}",
                    source_ids=[source.id],
                    subject_entity_id=entity.id,
                    predicate="has_fact",
                    object_value=f"value_{entity_idx}_{rec_idx}",
                )

        bundle = self.assembler.assemble(
            prompt="Topic Beta Beta_0 Beta_1 Beta_2",
            conversation_id=current,
            policy=ContextPolicy("apex", "production", True),
        )

        conversation_refs = [
            r for r in bundle.references if r.namespace == "conversation"
        ]
        personal_refs = [
            r for r in bundle.references if r.namespace == "personal_context"
        ]

        self.assertLessEqual(len(conversation_refs), 2)
        self.assertLessEqual(len(personal_refs), 4)

    def test_token_limit_and_truncation(self) -> None:
        current = uuid4()
        other = uuid4()
        large_text = "word " * 5000  # ~5000 tokens, exceeds 1500 limit
        self.retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation",
                source_type="message",
                source_id="large-msg",
                partition="production",
                conversation_id=str(other),
                message_id="large-msg",
                role="user",
                timestamp="2026-01-01T00:00:00+00:00",
                locator=f"conversation/{other}/message/large-msg",
                content_hash="large-hash",
                text=large_text,
            )
        )

        bundle = self.assembler.assemble(
            prompt="word",
            conversation_id=current,
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertTrue(bundle.truncated)

    def test_unresolved_conflict_labeling(self) -> None:
        current = uuid4()
        coffee = self.knowledge_store.create_entity("Coffee")
        self.knowledge_store.add_alias(coffee.id, "coffee")
        source = self.knowledge_store.create_source(
            kind="manual",
            partition="production",
            locator="manual/conflict-source",
            original_text="Conflict statement",
        )
        record = self.knowledge_store.create_record(
            partition="production",
            kind="fact",
            text="Preferred coffee roast is dark.",
            source_ids=[source.id],
            subject_entity_id=coffee.id,
            predicate="prefers_roast",
            object_value="dark",
        )
        self.knowledge_store.set_status(record.id, partition="production", status="conflicting")

        bundle = self.assembler.assemble(
            prompt="Tell me about coffee roast preferences",
            conversation_id=current,
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertIn("Unresolved personal-context conflict", bundle.rendered)
        self.assertIn("Preferred coffee roast is dark.", bundle.rendered)
        matched_ref = next(
            (r for r in bundle.references if r.source_id == str(record.id)), None
        )
        self.assertIsNotNone(matched_ref)
        self.assertEqual(matched_ref.status, "conflicting")

    def test_superseded_and_retracted_records_excluded(self) -> None:
        current = uuid4()
        source = self.knowledge_store.create_source(
            kind="manual",
            partition="production",
            locator="manual/lifecycle-source",
            original_text="Lifecycle statement",
        )
        rec_superseded = self.knowledge_store.create_record(
            partition="production",
            kind="fact",
            text="Old deprecated address.",
            source_ids=[source.id],
        )
        self.knowledge_store.set_status(rec_superseded.id, partition="production", status="superseded")

        rec_retracted = self.knowledge_store.create_record(
            partition="production",
            kind="fact",
            text="Secret key value.",
            source_ids=[source.id],
        )
        self.knowledge_store.set_status(rec_retracted.id, partition="production", status="retracted")

        bundle = self.assembler.assemble(
            prompt="address secret key",
            conversation_id=current,
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertNotIn("Old deprecated address.", bundle.rendered)
        self.assertNotIn("Secret key value.", bundle.rendered)
        ref_ids = [r.source_id for r in bundle.references]
        self.assertNotIn(str(rec_superseded.id), ref_ids)
        self.assertNotIn(str(rec_retracted.id), ref_ids)

    def test_entity_alias_deduplication_and_relationship_expansion(self) -> None:
        entity = self.knowledge_store.create_entity("Apex Core")
        self.knowledge_store.add_alias(entity.id, "Apex Core Engine")
        self.knowledge_store.add_alias(entity.id, "Apex Core")

        source = self.knowledge_store.create_source(
            kind="manual",
            partition="production",
            locator="manual/entity-source",
            original_text="Apex Core entity details",
        )
        record = self.knowledge_store.create_record(
            partition="production",
            kind="fact",
            text="Configured storage layer operates in loopback mode.",
            source_ids=[source.id],
            subject_entity_id=entity.id,
            predicate="runs_mode",
            object_value="loopback",
        )

        # Test deduplication in entities_mentioned_in
        mentioned = self.knowledge_store.entities_mentioned_in(
            "Tell me about Apex Core Engine architecture"
        )
        self.assertEqual(len(mentioned), 1)
        self.assertEqual(mentioned[0].id, entity.id)

        # Test assembly relationship expansion
        bundle = self.assembler.assemble(
            prompt="Tell me about Apex Core Engine architecture",
            conversation_id=uuid4(),
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertIn("Related personal context", bundle.rendered)
        self.assertIn("Configured storage layer operates in loopback mode.", bundle.rendered)
        self.assertIn(str(record.id), [r.source_id for r in bundle.references])

    def test_tool_preflight_retrieved_context_tokens(self) -> None:
        from core.api.cortex import build_tool_preflight
        from core.api.models import ToolPreflightRequest
        from core.settings.models import (
            AgentSettingsPatch,
            CloudSettingsPatch,
            SettingsPatch,
        )
        from core.settings import get_settings_store

        store = get_settings_store()
        try:
            # Opt-in enabled for cloud execution.
            store.apply_patch(
                SettingsPatch(
                    ask_apex=AgentSettingsPatch(
                        cloud=CloudSettingsPatch(
                            personal_context_enabled=True
                        )
                    )
                )
            )
            resp_enabled = build_tool_preflight(
                ToolPreflightRequest(
                    agent="apex",
                    prompt="Hello world",
                )
            )
            self.assertEqual(resp_enabled.breakdown.retrieved_context, 1500)

            # Opt-in disabled for cloud execution.
            store.apply_patch(
                SettingsPatch(
                    ask_apex=AgentSettingsPatch(
                        cloud=CloudSettingsPatch(
                            personal_context_enabled=False
                        )
                    )
                )
            )
            resp_disabled = build_tool_preflight(
                ToolPreflightRequest(
                    agent="apex",
                    prompt="Hello world",
                )
            )
            self.assertEqual(resp_disabled.breakdown.retrieved_context, 0)
        finally:
            store.apply_patch(
                SettingsPatch(
                    ask_apex=AgentSettingsPatch(
                        cloud=CloudSettingsPatch(
                            personal_context_enabled=False
                        )
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
