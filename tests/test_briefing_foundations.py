"""Production SQLite and coordinator coverage for briefing session foundations."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock, patch

from core.api.routers.cortex import _submit_run
from core.agent.capabilities import CapabilityDescriptor
from core.agent.providers.contract import ProviderTurnResult
from core.agent.types import AgentMessage, ToolCall, ToolSelectionDiagnostics
from core.briefings.history import compare_history
from core.briefings.models import (
    BUILTIN_BRIEFING_PROFILES,
    NORMALIZATION_VERSION,
    BriefingCoverage,
    BriefingDraft,
    BriefingEvidence,
    BriefingGenerationConfiguration,
    BriefingGenerationRequest,
    BriefingItem,
    BriefingItemDraft,
    BriefingModelConfiguration,
    BriefingSectionDraft,
    build_canonical_artifact,
    render_artifact_text,
)
from core.briefings.daily import generate_briefing_generation
from core.briefings.context import saved_daily_followup_context
from core.briefings.service import BriefingGenerationOutput, BriefingHistoryContext, BriefingService, BriefingSessionQueries
from core.briefings.store import BriefingSessionConflictError, BriefingSessionStore
from core.context import ContextPolicy
from core.conversations.store import ConversationStore
from core.conversations.models import ConversationTurnRequest
from core.conversations.service import ConversationService
from core.runs.coordinator import CortexRunCoordinator
from core.runs.models import RunCompletionEvidence, RunLimitSnapshot
from core.runs.service import RunService
from core.runs.store import RunStore
from core.settings.store import RuntimeSettingsStore
from core.telemetry.models import TelemetryModuleEntry, TelemetrySnapshot


class BriefingSessionSchemaMigrationTests(unittest.TestCase):
    def test_v1_row_survives_history_column_upgrade_and_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "apex_memory.db"
            conversations = ConversationStore(db_path)
            conversations.initialize()
            run_store = RunStore(db_path)
            run_store.initialize()
            session_store = BriefingSessionStore(db_path)

            request = BriefingSessionLifecycleTests._request()
            configuration = BriefingSessionLifecycleTests._configuration(request)
            session_id = uuid4()
            conversation_id = uuid4()
            user_message_id = uuid4()
            opening_message_id = uuid4()
            run_id = uuid4()
            created_at = datetime.now(timezone.utc).replace(microsecond=0)
            output = BriefingSessionLifecycleTests._output()
            artifact = build_canonical_artifact(
                session_id=session_id,
                draft=output.draft,
                evidence=output.evidence,
                coverage=output.coverage,
                created_at=created_at,
            )

            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                conversations.create_briefing_opening(
                    connection=connection,
                    conversation_id=conversation_id,
                    partition="production",
                    origin="hud",
                    title="Daily briefing",
                    user_id=user_message_id,
                    agent_id=opening_message_id,
                    prompt="Prepare a Daily briefing.",
                    request_metadata={
                        "briefing_session_id": str(session_id),
                        "profile_id": request.profile_id,
                        "model_id": request.model_id,
                    },
                )
                _run, handle, replayed = RunService(run_store).create_run(
                    run_id=run_id,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    agent_message_id=opening_message_id,
                    requested_model=request.model_id,
                    limit_snapshot=RunLimitSnapshot(
                        max_elapsed_seconds=configuration.model.max_elapsed_seconds,
                        max_retries=configuration.model.max_retries,
                        max_model_turns=configuration.model.max_model_turns,
                        max_tool_calls=configuration.model.max_tool_calls,
                    ),
                    partition="production",
                    connection=connection,
                )
                self.assertFalse(replayed)
                conversations.finalize(
                    conversation_id=conversation_id,
                    agent_id=opening_message_id,
                    answer=render_artifact_text(artifact),
                    status="completed",
                    response_metadata={
                        "briefing_session_id": str(session_id),
                        "artifact_schema_version": artifact.schema_version,
                    },
                    connection=connection,
                )
                handle.finalize(
                    status="completed",
                    stop_reason="end_turn",
                    evidence=RunCompletionEvidence(
                        final_message_status="completed", answer_persisted=True
                    ),
                    connection=connection,
                )

            created_at_text = created_at.isoformat().replace("+00:00", "Z")
            with closing(sqlite3.connect(db_path)) as connection, connection:
                connection.execute(
                    """CREATE TABLE briefing_sessions (
                        id TEXT PRIMARY KEY NOT NULL,
                        partition TEXT NOT NULL CHECK(partition IN ('production', 'sandbox')),
                        idempotency_key TEXT NOT NULL,
                        conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(id) ON DELETE CASCADE,
                        opening_message_id TEXT NOT NULL UNIQUE REFERENCES conversation_messages(id) ON DELETE CASCADE,
                        run_id TEXT NOT NULL UNIQUE REFERENCES cortex_runs(id) ON DELETE CASCADE,
                        profile_id TEXT NOT NULL CHECK(profile_id IN ('daily', 'catch_up', 'deep')),
                        created_at TEXT NOT NULL,
                        presented_at TEXT,
                        request_json TEXT NOT NULL CHECK(json_valid(request_json)),
                        configuration_json TEXT NOT NULL CHECK(json_valid(configuration_json)),
                        artifact_json TEXT CHECK(artifact_json IS NULL OR json_valid(artifact_json)),
                        evidence_json TEXT CHECK(evidence_json IS NULL OR json_valid(evidence_json)),
                        UNIQUE(partition, idempotency_key)
                    )"""
                )
                connection.execute(
                    "INSERT INTO schema_versions(domain, version) VALUES ('briefing_sessions', 1)"
                )
                connection.execute(
                    """INSERT INTO briefing_sessions (
                        id, partition, idempotency_key, conversation_id, opening_message_id,
                        run_id, profile_id, created_at, presented_at, request_json,
                        configuration_json, artifact_json, evidence_json
                    ) VALUES (?, 'production', ?, ?, ?, ?, 'daily', ?, ?, ?, ?, ?, ?)""",
                    (
                        str(session_id), str(request.idempotency_key), str(conversation_id),
                        str(opening_message_id), str(run_id), created_at_text,
                        created_at_text, json.dumps(request.model_dump(mode="json")),
                        json.dumps(configuration.model_dump(mode="json")),
                        json.dumps(artifact.model_dump(mode="json")),
                        json.dumps([
                            item.model_dump(mode="json") for item in output.evidence
                        ]),
                    ),
                )

            session_store.initialize()

            with closing(sqlite3.connect(db_path)) as connection, connection:
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(briefing_sessions)")
                }
                version = connection.execute(
                    "SELECT version FROM schema_versions WHERE domain = 'briefing_sessions'"
                ).fetchone()[0]
            restored = session_store.get(session_id, "production")

            self.assertIn("history_json", columns)
            self.assertEqual(version, 2)
            self.assertEqual(restored.request.profile_id, "daily")
            self.assertIsNone(restored.history)
            self.assertIsNotNone(restored.artifact)
            assert restored.artifact is not None
            self.assertEqual(restored.artifact.sections[0].items[0].title, "Planning meeting")
            self.assertEqual(restored.evidence[0].content, output.evidence[0].content)
            self.assertEqual(restored.run_status, "completed")
            self.assertEqual(
                conversations.detail(conversation_id, "production").messages[-1].status,
                "completed",
            )
            self.assertEqual(run_store.get_run(run_id, "production").status, "completed")

            session_store.close()
            run_store.close()
            conversations.close()


class BriefingSessionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "apex_memory.db"
        self.conversations = ConversationStore(self.db_path)
        self.conversations.initialize()
        self.run_store = RunStore(self.db_path)
        self.run_store.initialize()
        self.session_store = BriefingSessionStore(self.db_path)
        self.session_store.initialize()
        self.run_service = RunService(self.run_store)
        self.coordinator = CortexRunCoordinator(self.run_service, max_workers=2)

    def tearDown(self) -> None:
        self.coordinator.close(timeout_seconds=2)
        self.session_store.close()
        self.run_store.close()
        self.conversations.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _request() -> BriefingGenerationRequest:
        return BriefingGenerationRequest(
            idempotency_key=uuid4(),
            profile_id="daily",
            model_id="deepseek/deepseek-v4-flash-0731",
            reasoning="high",
        )

    @staticmethod
    def _configuration(
        request: BriefingGenerationRequest,
    ) -> BriefingGenerationConfiguration:
        return BriefingGenerationConfiguration(
            profile=BUILTIN_BRIEFING_PROFILES[request.profile_id],
            model=BriefingModelConfiguration(
                model_id=request.model_id,
                provider="openrouter",
                runtime="cloud",
                reasoning="high",
                max_elapsed_seconds=30,
                max_retries=1,
                max_model_turns=2,
                max_tool_calls=1,
                output_token_limit=512,
            ),
            origin=request.origin,
        )

    @staticmethod
    def _output() -> BriefingGenerationOutput:
        evidence = BriefingEvidence(
            source="calendar",
            source_id="event-1",
            trust="observed",
            content="A planning meeting begins at 10:00.",
        )
        return BriefingGenerationOutput(
            draft=BriefingDraft(
                sections=[
                    BriefingSectionDraft(
                        title="Today",
                        items=[
                            BriefingItemDraft(
                                category="observation",
                                title="Planning meeting",
                                body="The meeting begins at 10:00.",
                                evidence_ids=[evidence.id],
                            )
                        ],
                    )
                ]
            ),
            evidence=[evidence],
            coverage=[
                BriefingCoverage(
                    source="calendar", scope="today", status="complete"
                )
            ],
        )

    def _service(self, executor):
        return BriefingService(
            store=self.session_store,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=self._configuration,
            execute_generation=executor,
        )

    def test_success_persists_artifact_opening_message_and_run_together(self) -> None:
        request = self._request()
        service = self._service(lambda *_args: self._output())

        started = service.start(request)
        self.assertIsNotNone(started.future)
        run = started.future.result(timeout=3)

        self.assertEqual(run.status, "completed")
        saved = self.session_store.get(started.session.id, "production")
        conversation = self.conversations.detail(
            saved.conversation_id, "production"
        )
        agent_message = next(message for message in conversation.messages if message.role == "agent")
        self.assertEqual(saved.run_status, "completed")
        self.assertIsNotNone(saved.artifact)
        self.assertEqual(len(saved.evidence), 1)
        self.assertEqual(agent_message.status, "completed")
        self.assertEqual(agent_message.content, render_artifact_text(saved.artifact))
        self.assertEqual(agent_message.response_metadata["briefing_session_id"], str(saved.id))
        self.assertTrue(run.evidence.answer_persisted)

    def test_deep_generator_persists_cited_investigator_result_and_limits(self) -> None:
        request = self._request().model_copy(update={"profile_id": "deep"})
        configuration = BriefingGenerationConfiguration(
            profile=BUILTIN_BRIEFING_PROFILES["deep"],
            model=BriefingModelConfiguration(
                model_id=request.model_id,
                provider="openrouter",
                runtime="cloud",
                reasoning="high",
                context_window=16_384,
                max_elapsed_seconds=60,
                max_retries=1,
                max_model_turns=6,
                max_tool_calls=8,
                output_token_limit=512,
            ),
            origin=request.origin,
        )
        service = BriefingService(
            store=self.session_store,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=lambda _request: configuration,
            execute_generation=generate_briefing_generation,
        )
        captured_at = datetime.now(timezone.utc).replace(microsecond=0)
        snapshot = TelemetrySnapshot(modules={
            "reminders": TelemetryModuleEntry(
                name="reminders",
                status="healthy",
                freshness="live",
                observed_at=captured_at.isoformat(),
                data={
                    "list_id": "personal-tasks",
                    "count": 1,
                    "records": [{
                        "id": "task-1",
                        "note": "Prepare the beta roadmap review",
                        "due": (captured_at + timedelta(days=1)).isoformat(),
                        "status": "incomplete",
                    }],
                },
            ),
        })
        descriptor = CapabilityDescriptor(
            name="get_active_reminders",
            title="Get active reminders",
            description="Read active reminders.",
            input_schema={"type": "object", "properties": {}},
            origin="native",
            risk="read",
            expose_to_agent=True,
            expose_to_mcp_server=False,
            expose_to_client_display=True,
        )
        catalog = SimpleNamespace(groups=[SimpleNamespace(tools=[SimpleNamespace(
            name="get_active_reminders",
            available=True,
            allowed_for_agent=True,
            risk="read",
            apex_family="schedule",
        )])])
        selection = SimpleNamespace(
            descriptors=(descriptor,),
            diagnostics=ToolSelectionDiagnostics(),
        )

        class InvestigatorProvider:
            def __init__(self) -> None:
                self.turns = 0

            def generate_turn(self, _messages, tools, _profile, **_kwargs):
                self.turns += 1
                if self.turns == 1:
                    if not tools:
                        raise AssertionError("Deep did not offer the selected read capability.")
                    message = AgentMessage(role="agent", tool_calls=[ToolCall(
                        id="deep-read-1",
                        name="get_active_reminders",
                        arguments={},
                    )])
                else:
                    message = AgentMessage(role="agent", content="The captured reminder result is relevant.")
                return ProviderTurnResult(message=message)

        provider = InvestigatorProvider()

        def synthesize_from_captured_evidence(*, prompt, **_kwargs):
            evidence_json = prompt.split("\nEvidence:\n", 1)[1]
            evidence_rows = json.loads(evidence_json)
            read_row = next(
                row for row in evidence_rows
                if row["source"] == "get_active_reminders"
            )
            return ProviderTurnResult(message=AgentMessage(
                role="agent",
                content=json.dumps({
                    "sections": [{
                        "title": "Investigation",
                        "items": [{
                            "category": "analysis",
                            "title": "Reminder check",
                            "body": "The bounded read result contains a due reminder.",
                            "evidence_ids": [read_row["id"]],
                        }],
                    }],
                    "limitations": [],
                }),
            ))

        settings = SimpleNamespace(get_snapshot=lambda: object())
        with (
            patch("core.briefings.daily.get_settings_store", return_value=settings),
            patch("core.briefings.daily.ContextPolicy.from_settings", return_value=SimpleNamespace(permits_retrieval=False)),
            patch("core.briefings.daily.is_dev_mode", return_value=False),
            patch("core.briefings.daily_inputs.is_dev_mode", return_value=False),
            patch("core.briefings.daily._collect_snapshot", return_value=(snapshot, None)),
            patch("core.briefings.daily._personal_inputs", return_value=([], [])),
            patch("core.briefings.daily.get_visible_model_profile", return_value=SimpleNamespace(maximum_context_window=16_384)),
            patch("core.briefings.daily.execute_single_call", side_effect=synthesize_from_captured_evidence),
            patch("core.briefings.investigation.build_tool_catalog", return_value=catalog),
            patch("core.briefings.investigation.resolve_selected_tools", return_value=selection),
            patch("core.briefings.investigation._recheck_read_permission"),
            patch("core.briefings.investigation.invoke_read_only_capability", return_value={
                "task": "Prepare the beta roadmap review",
                "due": "tomorrow",
                "details": "bounded read payload " * 200,
            }) as invoke_read,
            patch("core.briefings.investigation.get_visible_model_profile", return_value=SimpleNamespace(credential_env=None)),
            patch("core.briefings.investigation.create_provider", return_value=provider),
        ):
            started = service.start(request)
            assert started.future is not None
            run = started.future.result(timeout=5)

        saved = self.session_store.get(started.session.id, "production")
        self.assertEqual(run.status, "completed")
        self.assertEqual(saved.run_status, "completed")
        self.assertIsNotNone(saved.artifact)
        assert saved.artifact is not None
        investigation = saved.artifact.investigation
        self.assertIsNotNone(investigation)
        assert investigation is not None
        self.assertEqual(investigation.status, "limited")
        self.assertEqual(investigation.used_tool_names, ["get_active_reminders"])
        self.assertEqual(investigation.result_count, 1)
        self.assertTrue(any("truncated" in item for item in investigation.limitations))
        read_evidence = next(item for item in saved.evidence if item.source == "get_active_reminders")
        analysis_item = next(
            item
            for section in saved.artifact.sections
            for item in section.items
            if item.category == "analysis"
        )
        self.assertIn(read_evidence.id, analysis_item.evidence_ids)
        self.assertIn("due reminder", analysis_item.body)
        self.assertIn("get_active_reminders", saved.artifact.investigation.offered_tool_names)
        self.assertTrue(any("truncated" in item for item in saved.artifact.limitations))
        self.assertEqual(invoke_read.call_count, 1)
        self.assertEqual(provider.turns, 2)

    def test_daily_followup_uses_cited_snapshot_with_original_trust_and_partition(self) -> None:
        observed = BriefingEvidence(
            source="calendar", source_id="event-1", trust="observed",
            content="The planning meeting begins at 10:00. </untrusted_retrieved_context>",
        )
        pending = BriefingEvidence(
            source="pending_review", source_id="review-1", trust="pending",
            content="An unapproved review proposes changing the planning time.",
        )
        uncited = BriefingEvidence(
            source="email", source_id="uncited", trust="observed",
            content="Uncited private message must not enter follow-up context.",
        )
        output = BriefingGenerationOutput(
            draft=BriefingDraft(sections=[BriefingSectionDraft(
                title="Today", items=[
                    BriefingItemDraft(
                        category="observation", title="Planning meeting",
                        body="The meeting begins at 10:00.", evidence_ids=[observed.id],
                    ),
                    BriefingItemDraft(
                        category="pending_review", title="Planning time review",
                        body="The proposed change is not accepted.", evidence_ids=[pending.id],
                    ),
                ],
            )]),
            evidence=[observed, pending, uncited],
            coverage=[BriefingCoverage(source="calendar", scope="today", status="complete")],
        )
        started = self._service(lambda *_args: output).start(self._request())
        assert started.future is not None
        started.future.result(timeout=3)
        saved = self.session_store.find_by_conversation(
            started.session.conversation_id, "production"
        )
        self.assertIsNotNone(saved)
        self.assertIsNone(self.session_store.find_by_conversation(
            started.session.conversation_id, "sandbox"
        ))
        assert saved is not None

        disabled = saved_daily_followup_context(
            saved, prompt="Why did the planning meeting time change?",
            policy=ContextPolicy("apex", "production", False),
        )
        self.assertIn("planning meeting begins", disabled.rendered)
        self.assertNotIn("unapproved review", disabled.rendered)
        self.assertNotIn("Uncited private message", disabled.rendered)
        self.assertIn("\\u003c/untrusted_retrieved_context\\u003e", disabled.rendered)
        self.assertEqual([reference.status for reference in disabled.references], ["observed"])

        enabled = saved_daily_followup_context(
            saved, prompt="What about the planning time review?",
            policy=ContextPolicy("apex", "production", True),
        )
        self.assertIn("unapproved review", enabled.rendered)
        self.assertIn('"trust":"pending"', enabled.rendered)
        self.assertNotIn("Uncited private message", enabled.rendered)
        self.assertLessEqual(enabled.estimated_tokens, 500)
        self.assertFalse(saved_daily_followup_context(
            saved, prompt="planning", policy=ContextPolicy("apex", "sandbox", True)
        ).enabled)

    def test_deep_followup_includes_only_cited_untrusted_reads_when_policy_permits(self) -> None:
        started = self._service(lambda *_args: self._output()).start(self._request())
        assert started.future is not None
        started.future.result(timeout=3)
        saved = self.session_store.get(started.session.id, "production")
        deep_evidence = BriefingEvidence(
            source="get_active_reminders", source_id="deep-read-1", trust="untrusted",
            content="A captured read result says the task is due tomorrow.",
        )
        section = saved.artifact.sections[0]
        cited_item = BriefingItem(
            id=uuid4(), category="analysis", title="Reminder check",
            body="The task is due tomorrow.", evidence_ids=[deep_evidence.id],
        )
        artifact = saved.artifact.model_copy(update={
            "sections": [section.model_copy(update={"items": [*section.items, cited_item]})],
        })
        deep_record = saved.model_copy(update={
            "request": saved.request.model_copy(update={"profile_id": "deep"}),
            "artifact": artifact,
            "evidence": [*saved.evidence, deep_evidence],
        })

        disabled = saved_daily_followup_context(
            deep_record, prompt="What did the reminder read find?",
            policy=ContextPolicy("apex", "production", False),
        )
        enabled = saved_daily_followup_context(
            deep_record, prompt="What did the reminder read find?",
            policy=ContextPolicy("apex", "production", True),
        )

        self.assertNotIn("task is due tomorrow", disabled.rendered)
        self.assertIn("task is due tomorrow", enabled.rendered)
        self.assertIn('"trust":"untrusted"', enabled.rendered)
        self.assertEqual(enabled.references[0].status, "untrusted")

    def test_daily_followup_passes_saved_evidence_to_selected_model(self) -> None:
        started = self._service(lambda *_args: self._output()).start(self._request())
        assert started.future is not None
        started.future.result(timeout=3)
        settings = RuntimeSettingsStore(
            config_path=Path(self.temp_dir.name) / "config.json",
            local_config_path=Path(self.temp_dir.name) / "config.local.json",
        )
        conversations = ConversationService(self.conversations, history_limit=20)
        captured: dict[str, object] = {}

        def answer(_payload, **kwargs):
            captured["context"] = kwargs["context_bundle"]
            return SimpleNamespace(
                answer="The cited meeting begins at 10:00.", error=None,
                tool_trace=[], tool_outputs=[], measurements={},
                model_dump=lambda **_kwargs: {},
            )

        with (
            patch("core.api.routers.cortex.get_conversation_service", return_value=conversations),
            patch("core.api.routers.cortex.get_run_coordinator", return_value=self.coordinator),
            patch("core.api.routers.cortex.get_run_service", return_value=self.run_service),
            patch("core.api.routers.cortex.get_briefing_session_queries_optional", return_value=BriefingSessionQueries(self.session_store, lambda: "production")),
            patch("core.api.routers.cortex.get_settings_store", return_value=settings),
            patch("core.conversations.service.get_settings_store", return_value=settings),
            patch("core.api.routers.cortex.is_dev_mode", return_value=False),
            patch("core.conversations.service.is_dev_mode", return_value=False),
            patch("core.api.routers.cortex.get_retrieval_service", return_value=MagicMock()),
            patch("core.api.routers.cortex.get_knowledge_service", return_value=MagicMock()),
            patch("core.api.routers.cortex.query_agent", side_effect=answer),
        ):
            _record, future = _submit_run(
                started.session.conversation_id,
                ConversationTurnRequest(
                    user_message_id=uuid4(), agent_message_id=uuid4(),
                    prompt="When is the planning meeting?", agent="apex",
                    model_id="deepseek/deepseek-v4-flash-0731",
                ),
            )
            assert future is not None
            future.result(timeout=3)

        context = captured["context"]
        self.assertIn("A planning meeting begins at 10:00.", context.rendered)
        self.assertEqual(context.references[0].namespace, "briefing_session")

    def test_daily_followup_prioritizes_question_relevance_within_budget(self) -> None:
        evidence = [
            BriefingEvidence(
                source="news", source_id=f"item-{index}", trust="observed",
                content=(f"General briefing item {index}. " + "background " * 180)
                if index < 4 else "The orbit launch is scheduled for tomorrow.",
            )
            for index in range(5)
        ]
        output = BriefingGenerationOutput(
            draft=BriefingDraft(sections=[BriefingSectionDraft(
                title="Updates", items=[
                    BriefingItemDraft(
                        category="observation", title=f"Update {index}" if index < 4 else "Orbit launch",
                        body="A current observation.", evidence_ids=[item.id],
                    )
                    for index, item in enumerate(evidence)
                ],
            )]),
            evidence=evidence,
            coverage=[BriefingCoverage(source="news", scope="today", status="complete")],
        )
        started = self._service(lambda *_args: output).start(self._request())
        assert started.future is not None
        started.future.result(timeout=3)
        saved = self.session_store.get(started.session.id, "production")
        bundle = saved_daily_followup_context(
            saved, prompt="What time is the orbit launch?",
            policy=ContextPolicy("apex", "production", False),
        )

        self.assertIn(str(evidence[4].id), [reference.source_id for reference in bundle.references])
        self.assertLessEqual(bundle.estimated_tokens, 500)
        self.assertTrue(bundle.truncated)

    def test_demo_generation_completes_a_saved_session_without_model_execution(self) -> None:
        request = BriefingGenerationRequest(
            idempotency_key=uuid4(), profile_id="daily", model_id="demo/daily-fixture"
        )
        base = self._configuration(request)
        configuration = base.model_copy(update={
            "model": base.model.model_copy(update={"provider": "demo", "runtime": "demo"}),
            "execution_kind": "demo",
        })
        service = BriefingService(
            store=self.session_store,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=lambda _request: configuration,
            execute_generation=generate_briefing_generation,
        )

        started = service.start(request)
        assert started.future is not None
        run = started.future.result(timeout=3)
        saved = self.session_store.get(started.session.id, "production")

        self.assertEqual(run.status, "completed")
        self.assertIsNotNone(saved.artifact)
        self.assertEqual(saved.evidence[0].source, "demo")

    def test_generation_failure_keeps_session_without_artifact(self) -> None:
        def fail(*_args):
            raise RuntimeError("provider details must not be persisted")

        started = self._service(fail).start(self._request())
        run = started.future.result(timeout=3)

        saved = self.session_store.get(started.session.id, "production")
        conversation = self.conversations.detail(
            saved.conversation_id, "production"
        )
        agent_message = next(message for message in conversation.messages if message.role == "agent")
        self.assertEqual(run.status, "failed")
        self.assertEqual(saved.run_status, "failed")
        self.assertIsNone(saved.artifact)
        self.assertEqual(saved.evidence, [])
        self.assertEqual(agent_message.status, "failed")
        self.assertNotIn("provider details", str(agent_message.response_metadata))

    def test_cancelled_generation_cannot_publish_artifact(self) -> None:
        started_execution = threading.Event()
        release_execution = threading.Event()

        def wait_then_return(*_args):
            started_execution.set()
            if not release_execution.wait(timeout=3):
                raise TimeoutError("test executor release was not signaled")
            return self._output()

        started = self._service(wait_then_return).start(self._request())
        self.assertTrue(started_execution.wait(timeout=3))
        cancel = self.coordinator.cancel(started.session.run_id)
        self.assertEqual(cancel.status, "cancelling")
        release_execution.set()
        run = started.future.result(timeout=3)

        saved = self.session_store.get(started.session.id, "production")
        self.assertEqual(run.status, "cancelled")
        self.assertIsNone(saved.artifact)
        self.assertEqual(saved.evidence, [])

    def test_snapshot_write_failure_rolls_back_artifact_message_and_run_success(self) -> None:
        original_save = self.session_store.save_completed_snapshot

        def fail_after_snapshot_write(*args, **kwargs):
            original_save(*args, **kwargs)
            raise OSError("simulated disk failure")

        service = self._service(lambda *_args: self._output())
        with patch.object(
            self.session_store,
            "save_completed_snapshot",
            side_effect=fail_after_snapshot_write,
        ):
            started = service.start(self._request())
            run = started.future.result(timeout=3)

        saved = self.session_store.get(started.session.id, "production")
        conversation = self.conversations.detail(
            saved.conversation_id, "production"
        )
        agent_message = next(message for message in conversation.messages if message.role == "agent")
        self.assertEqual(run.status, "failed")
        self.assertEqual(saved.run_status, "failed")
        self.assertIsNone(saved.artifact)
        self.assertEqual(saved.evidence, [])
        self.assertEqual(agent_message.status, "failed")
        self.assertFalse(run.evidence.answer_persisted)

    def test_idempotent_retry_returns_the_same_session(self) -> None:
        request = self._request()
        service = self._service(lambda *_args: self._output())
        first = service.start(request)
        first.future.result(timeout=3)

        retry = service.start(request)

        self.assertTrue(retry.replayed)
        self.assertEqual(retry.session.id, first.session.id)
        self.assertEqual(retry.session.conversation_id, first.session.conversation_id)

    def test_frozen_history_uses_presented_completed_sessions_and_source_time(self) -> None:
        def snapshot(at: datetime, content: str) -> BriefingGenerationOutput:
            evidence = BriefingEvidence(
                source="calendar", source_id="event-1", identity_kind="provider",
                semantic_fingerprint=sha256(content.encode("utf-8")).hexdigest(),
                normalization_version=NORMALIZATION_VERSION, observed_at=at,
                trust="observed", content=content,
            )
            return BriefingGenerationOutput(
                draft=BriefingDraft(sections=[BriefingSectionDraft(
                    title="Calendar", items=[BriefingItemDraft(
                        category="observation", title="Planning event", body=content,
                        evidence_ids=[evidence.id],
                    )],
                )]),
                evidence=[evidence],
                coverage=[BriefingCoverage(
                    source="calendar", scope="Selected calendars",
                    scope_key="calendar:selected:test-v1",
                    normalization_version=NORMALIZATION_VERSION,
                    status="complete", observed_at=at,
                )],
            )

        before = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)
        newest_snapshot = datetime(2026, 9, 25, 10, tzinfo=timezone.utc)
        unpresented_snapshot = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)
        current_snapshot = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
        latest = self._service(lambda *_args: snapshot(newest_snapshot, "Later source observation.")).start(self._request())
        latest.future.result(timeout=3)
        self.session_store.mark_presented(latest.session.id, "production")

        # This session is created and presented later, but its source observation is older.
        older = self._service(lambda *_args: snapshot(before, "Stale cached source observation.")).start(self._request())
        older.future.result(timeout=3)
        self.session_store.mark_presented(older.session.id, "production")

        unopened = self._service(lambda *_args: snapshot(unpresented_snapshot, "Never shown to the user.")).start(self._request())
        unopened.future.result(timeout=3)

        def fail_generation(*_args):
            raise RuntimeError("expected failure")

        failed = self._service(fail_generation).start(self._request())
        failed.future.result(timeout=3)

        execution_started = threading.Event()
        release_execution = threading.Event()

        def cancel_before_complete(*_args):
            execution_started.set()
            if not release_execution.wait(timeout=3):
                raise TimeoutError("test executor release was not signaled")
            return snapshot(current_snapshot, "Cancelled source observation.")

        cancelled = self._service(cancel_before_complete).start(self._request())
        self.assertTrue(execution_started.wait(timeout=3))
        self.coordinator.cancel(cancelled.session.run_id)
        release_execution.set()
        cancelled.future.result(timeout=3)

        with self.assertRaises(BriefingSessionConflictError):
            self.session_store.mark_presented(failed.session.id, "production")
        with self.assertRaises(BriefingSessionConflictError):
            self.session_store.mark_presented(cancelled.session.id, "production")

        captured: dict[str, BriefingHistoryContext] = {}

        def capture_history(*args):
            captured["history"] = args[4]
            return snapshot(current_snapshot, "Current source observation.")

        current_request = self._request()
        current_service = self._service(capture_history)
        current = current_service.start(current_request)
        current.future.result(timeout=3)
        history = captured["history"]
        self.assertEqual(set(history.selection.session_ids), {latest.session.id, older.session.id})
        self.assertNotIn(unopened.session.id, history.selection.session_ids)
        self.assertNotIn(failed.session.id, history.selection.session_ids)
        self.assertNotIn(cancelled.session.id, history.selection.session_ids)

        current_output = snapshot(current_snapshot, "Current source observation.")
        compared = compare_history(
            evidence=current_output.evidence,
            coverage=current_output.coverage,
            history=history,
        )
        self.assertEqual(compared.comparison.sources[0].baseline_session_id, latest.session.id)

        self.session_store.mark_presented(current.session.id, "production")
        later = self._service(lambda *_args: snapshot(
            datetime(2026, 9, 28, 10, tzinfo=timezone.utc), "Later presented observation."
        )).start(self._request())
        later.future.result(timeout=3)
        self.session_store.mark_presented(later.session.id, "production")
        retry = current_service.start(current_request)

        self.assertTrue(retry.replayed)
        self.assertEqual(retry.session.id, current.session.id)
        self.assertIsNotNone(current.session.history)
        self.assertEqual(retry.session.history.selection, current.session.history.selection)

    def test_concurrent_same_key_requests_create_one_session(self) -> None:
        request = self._request()
        both_resolving = threading.Barrier(2)

        def resolve(request_value):
            config = self._configuration(request_value)
            both_resolving.wait(timeout=3)
            return config

        service = BriefingService(
            store=self.session_store,
            conversations=self.conversations,
            runs=self.run_service,
            coordinator=self.coordinator,
            partition_getter=lambda: "production",
            resolve_configuration=resolve,
            execute_generation=lambda *_args: self._output(),
        )
        with ThreadPoolExecutor(max_workers=2) as callers:
            results = list(callers.map(lambda _index: service.start(request), range(2)))

        self.assertEqual(results[0].session.id, results[1].session.id)
        self.assertEqual(sum(not result.replayed for result in results), 1)
        futures = [result.future for result in results if result.future is not None]
        self.assertTrue(futures)
        futures[0].result(timeout=3)
        self.assertEqual(len(self.session_store.list("production", limit=100, offset=0)), 1)


if __name__ == "__main__":
    unittest.main()
