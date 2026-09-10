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
        source = self.knowledge_store.create_source(
            kind="manual", partition="production", locator="manual/disabled",
            original_text="Context must stay disabled.",
        )
        self.knowledge_store.create_record(
            partition="production", kind="note", text="Do not inject this record.", source_ids=[source.id],
        )
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

    def test_canonical_replacement_wins_over_a_stale_retrieval_hit(self) -> None:
        source = self.knowledge_store.create_source(
            kind="manual", partition="production", locator="manual/correction",
            original_text="The weekly planning day changed.",
        )
        old = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Weekly planning happens on Monday.",
            source_ids=[source.id],
        )
        replacement = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Weekly planning happens on Tuesday.",
            source_ids=[source.id], supersedes_record_id=old.id,
        )
        # Simulate a stale embedding surviving a correction synchronization.
        self.retrieval_store.upsert_item(RetrievalItem(
            namespace="personal_context", source_type="knowledge_record", source_id=str(old.id),
            partition="production", conversation_id=None, message_id=None, role=None,
            timestamp=old.updated_at, locator=f"knowledge/record/{old.id}", content_hash="stale-old",
            text=old.text,
        ))

        bundle = self.assembler.assemble(
            prompt="weekly planning", conversation_id=uuid4(),
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertIn(replacement.text, bundle.rendered)
        self.assertNotIn(old.text, bundle.rendered)
        self.assertNotIn(str(old.id), [reference.source_id for reference in bundle.references])

    def test_pending_challenge_labels_current_record_without_proposal_text(self) -> None:
        source = self.knowledge_store.create_source(
            kind="manual", partition="production", locator="manual/challenge",
            original_text="Coffee preference.",
        )
        current = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Preferred coffee roast is dark.",
            source_ids=[source.id],
        )
        self.knowledge_store.create_review(
            partition="production", operation="correct",
            proposal={
                "record_id": str(current.id),
                "capture": {"kind": "fact", "text": "Preferred coffee roast is light.", "effective_at": None},
            },
            evidence={"source_kind": "manual", "original_text": "A proposed preference."},
            expected_revisions={str(current.id): current.updated_at}, reason_codes=("known_conflict",),
        )

        bundle = self.assembler.assemble(
            prompt="coffee roast", conversation_id=uuid4(),
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertIn(current.text, bundle.rendered)
        self.assertIn("Pending challenge; treat this claim as uncertain", bundle.rendered)
        self.assertNotIn("Preferred coffee roast is light.", bundle.rendered)

    def test_rejected_proposals_and_stale_inactive_hits_are_not_rendered(self) -> None:
        source = self.knowledge_store.create_source(
            kind="manual", partition="production", locator="manual/inactive",
            original_text="Inactive claims.",
        )
        superseded = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Superseded stale claim.", source_ids=[source.id],
        )
        replacement = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Current claim.", source_ids=[source.id],
            supersedes_record_id=superseded.id,
        )
        retracted = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Retracted stale claim.", source_ids=[source.id],
        )
        self.knowledge_store.set_status(retracted.id, partition="production", status="retracted")
        rejected = self.knowledge_store.create_review(
            partition="production", operation="capture",
            proposal={"kind": "fact", "text": "Rejected proposed claim.", "effective_at": None},
            evidence={"source_kind": "manual", "original_text": "Rejected proposal."},
            expected_revisions={}, reason_codes=("sensitive",),
        )
        self.knowledge_store.reject_review(rejected.id, partition="production")
        for record, text in ((superseded, superseded.text), (retracted, retracted.text)):
            self.retrieval_store.upsert_item(RetrievalItem(
                namespace="personal_context", source_type="knowledge_record", source_id=str(record.id),
                partition="production", conversation_id=None, message_id=None, role=None,
                timestamp=record.updated_at, locator=f"knowledge/record/{record.id}",
                content_hash=f"stale-{record.id}", text=text,
            ))
        self.retrieval_store.upsert_item(RetrievalItem(
            namespace="personal_context", source_type="knowledge_record", source_id=str(rejected.id),
            partition="production", conversation_id=None, message_id=None, role=None,
            timestamp=rejected.created_at, locator=f"knowledge/review/{rejected.id}",
            content_hash="rejected-proposal", text="Rejected proposed claim.",
        ))

        bundle = self.assembler.assemble(
            prompt="claim", conversation_id=uuid4(), policy=ContextPolicy("apex", "production", True),
        )

        self.assertIn(replacement.text, bundle.rendered)
        self.assertNotIn(superseded.text, bundle.rendered)
        self.assertNotIn(retracted.text, bundle.rendered)
        self.assertNotIn("Rejected proposed claim.", bundle.rendered)

    def test_renders_concise_provenance_effective_time_and_inspection_pointers(self) -> None:
        source = self.knowledge_store.create_source(
            kind="manual", partition="production", locator="tool/calendar/event-1",
            original_text="Calendar event", origin="external_tool", occurred_at="2026-09-10T09:00:00+00:00",
        )
        record = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Planning starts at 9 AM.", source_ids=[source.id],
            effective_at="2026-09-10", source_derivations={source.id: "model_interpretation"},
        )

        bundle = self.assembler.assemble(
            prompt="planning", conversation_id=uuid4(), policy=ContextPolicy("apex", "production", True),
        )

        locator = f"knowledge/record/{record.id}"
        self.assertIn("provenance: external tool (model interpretation)", bundle.rendered)
        self.assertIn("effective: 2026-09-10", bundle.rendered)
        self.assertIn(f"sources: {locator}#sources", bundle.rendered)
        self.assertIn(f"history: {locator}#history", bundle.rendered)

    def test_personal_context_labels_count_against_the_token_budget(self) -> None:
        source = self.knowledge_store.create_source(
            kind="manual", partition="production", locator="manual/budget", original_text="Budget claim.",
        )
        record = self.knowledge_store.create_record(
            partition="production", kind="fact", text="Short claim.", source_ids=[source.id],
        )
        old_rendering = f"Personal context ({record.kind}): {record.text}"
        policy = ContextPolicy(
            "apex", "production", True, max_retrieved_tokens=(len(old_rendering) + 3) // 4,
            max_conversation_excerpts=0, max_personal_records=1,
        )

        bundle = self.assembler.assemble(prompt="short claim", conversation_id=uuid4(), policy=policy)

        self.assertFalse(bundle.enabled)
        self.assertTrue(bundle.truncated)

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
        initial_snap = store.get_snapshot()
        try:
            # Opt-in enabled for cloud execution.
            store.apply_patch(
                SettingsPatch(
                    ask_apex=AgentSettingsPatch(
                        selected_model="gemini-3.7-flash",
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
                        selected_model="gemini-3.7-flash",
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
                        selected_model=initial_snap.ask_apex.selected_model,
                        cloud=CloudSettingsPatch(
                            personal_context_enabled=initial_snap.ask_apex.cloud.personal_context_enabled
                        )
                    )
                )
            )

    def test_local_model_retrieval_policy_limits_and_preflight(self) -> None:
        from core.settings import get_settings_store
        from core.settings.models import (
            AgentSettingsPatch,
            LocalSettingsPatch,
            SettingsPatch,
        )
        from core.api.cortex import build_tool_preflight
        from core.api.models import ToolPreflightRequest

        store = get_settings_store()
        initial_snap = store.get_snapshot()
        try:
            # Opt-in enabled for local execution
            store.apply_patch(
                SettingsPatch(
                    ask_apex=AgentSettingsPatch(
                        selected_model="gemma-4-E2B-Q4_K_M.gguf",
                        local=LocalSettingsPatch(
                            personal_context_enabled=True,
                        ),
                    )
                )
            )
            policy = ContextPolicy.from_settings(
                agent="apex",
                partition="production",
                settings=store.get_snapshot(),
                model_id="gemma-4-E2B-Q4_K_M.gguf",
            )
            self.assertEqual(policy.max_retrieved_tokens, 400)
            self.assertEqual(policy.max_conversation_excerpts, 1)
            self.assertEqual(policy.max_personal_records, 2)

            resp_enabled = build_tool_preflight(
                ToolPreflightRequest(
                    agent="apex",
                    prompt="Check local context limit",
                    model_id="gemma-4-E2B-Q4_K_M.gguf",
                )
            )
            self.assertEqual(resp_enabled.breakdown.retrieved_context, 400)

            # Opt-in disabled for local execution
            store.apply_patch(
                SettingsPatch(
                    ask_apex=AgentSettingsPatch(
                        selected_model="gemma-4-E2B-Q4_K_M.gguf",
                        local=LocalSettingsPatch(
                            personal_context_enabled=False,
                        ),
                    )
                )
            )
            resp_disabled = build_tool_preflight(
                ToolPreflightRequest(
                    agent="apex",
                    prompt="Check local context limit",
                    model_id="gemma-4-E2B-Q4_K_M.gguf",
                )
            )
            self.assertEqual(resp_disabled.breakdown.retrieved_context, 0)
        finally:
            store.apply_patch(
                SettingsPatch(
                    ask_apex=AgentSettingsPatch(
                        selected_model=initial_snap.ask_apex.selected_model,
                        local=LocalSettingsPatch(
                            personal_context_enabled=initial_snap.ask_apex.local.personal_context_enabled,
                        ),
                    )
                )
            )

    def test_personal_records_prioritized_over_conversation_under_tight_budget(self) -> None:
        current = uuid4()
        other = uuid4()
        # Add conversation hit that takes ~350 tokens
        self.retrieval_store.upsert_item(
            RetrievalItem(
                namespace="conversation",
                source_type="message",
                source_id="msg-large",
                partition="production",
                conversation_id=str(other),
                message_id="msg-large",
                role="user",
                timestamp="2026-01-01T00:00:00+00:00",
                locator=f"conversation/{other}/message/msg-large",
                content_hash="large-hash",
                text="Earlier conversation detail " * 50,
            )
        )

        source = self.knowledge_store.create_source(
            kind="manual",
            partition="production",
            locator="manual/priority-test",
            original_text="Priority source",
        )
        entity = self.knowledge_store.create_entity("PriorityEntity")
        self.knowledge_store.add_alias(entity.id, "priority")
        record = self.knowledge_store.create_record(
            partition="production",
            kind="fact",
            text="Priority knowledge fact that must be included first.",
            source_ids=[source.id],
            subject_entity_id=entity.id,
            predicate="has_priority",
            object_value="first",
        )

        # Assemble with local policy (400 tokens)
        policy = ContextPolicy(
            agent="apex",
            partition="production",
            personal_context_enabled=True,
            max_retrieved_tokens=400,
            max_conversation_excerpts=1,
            max_personal_records=2,
        )
        bundle = self.assembler.assemble(
            prompt="priority earlier conversation detail",
            conversation_id=current,
            policy=policy,
        )

        # Personal context must be present
        self.assertIn("Priority knowledge fact", bundle.rendered)
        personal_refs = [r for r in bundle.references if r.namespace == "personal_context"]
        self.assertGreaterEqual(len(personal_refs), 1)


if __name__ == "__main__":
    unittest.main()
