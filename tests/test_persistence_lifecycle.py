"""Lifecycle safety checks for supported and unsupported persistence schemas."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import threading
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

from core.conversations.store import ConversationStore
from core.conversations.retention import purge_expired_archived_conversations
from core.knowledge import get_knowledge_service
from core.retrieval.embedding import FastEmbedAdapter
from core.retrieval.models import RetrievalItem
from core.retrieval import get_retrieval_service
from core.retrieval.service import RetrievalService
from core.retrieval.store import RetrievalStore
from core.runtime_paths import RuntimePaths


class PersistenceLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "lifecycle.db"
        root = Path(self.temp_dir.name)
        self._runtime_paths = mock.patch(
            "core.runtime_paths.get_runtime_paths",
            return_value=RuntimePaths(resource_root=root, data_root=root),
        )
        self._runtime_paths.start()
        from core.api.app import app

        stale = getattr(app.state, "host_context", None)
        if stale is not None and stale.profile_lock.acquired:
            stale.release()
        app.state.host_context = None
        app.state.lifecycle_entered = False
        app.state.lifecycle_established = False
        app.state.lifecycle_cleanup_complete = False
        app.state.http_shutdown_timed_out = False

    def tearDown(self) -> None:
        from core.api.app import app

        context = getattr(app.state, "host_context", None)
        if context is not None and context.profile_lock.acquired:
            context.release()
        app.state.host_context = None
        app.state.lifecycle_entered = False
        app.state.lifecycle_established = False
        app.state.lifecycle_cleanup_complete = False
        app.state.http_shutdown_timed_out = False
        self._runtime_paths.stop()
        self.temp_dir.cleanup()

    def _seed_unsupported_core_schema(self) -> str:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute(
                    "CREATE TABLE schema_versions(domain TEXT PRIMARY KEY, version INTEGER NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO schema_versions(domain, version) VALUES ('conversations', 1)"
                )
                conn.execute("CREATE TABLE conversations(id TEXT PRIMARY KEY, title TEXT)")
                conn.execute("INSERT INTO conversations VALUES ('keep-me', 'old row')")
            return "\n".join(conn.iterdump())

    def test_unsupported_core_schema_fails_before_bootstrap_auth_or_recovery(self) -> None:
        from core.api.app import app

        before = self._seed_unsupported_core_schema()
        auth = mock.Mock()
        auth.initialize = mock.AsyncMock()
        auth.shutdown = mock.AsyncMock()

        with ExitStack() as stack:
            stack.enter_context(mock.patch("core.api.app.DEMO_MODE", False))
            stack.enter_context(mock.patch("core.api.app.database.DB_NAME", str(self.path)))
            stack.enter_context(mock.patch("core.api.app.configure_logging"))
            stack.enter_context(mock.patch("core.api.app.get_tracing_service", return_value=mock.Mock()))
            bootstrap = stack.enter_context(mock.patch("core.api.app.database.initialize_db"))
            auth_factory = stack.enter_context(
                mock.patch("core.api.app.MicrosoftTodoAuthenticationService", return_value=auth)
            )
            with self.assertRaisesRegex(RuntimeError, "conversations persistence schema"):
                with TestClient(app):
                    self.fail("unsupported core persistence must block startup")

        self.assertFalse(bootstrap.called)
        self.assertFalse(auth_factory.called)
        auth.initialize.assert_not_awaited()
        with closing(sqlite3.connect(self.path)) as conn:
            after = "\n".join(conn.iterdump())
        self.assertEqual(after, before)

    def test_unsupported_retrieval_keeps_core_startup_and_knowledge_writes_available(self) -> None:
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        conversations = ConversationStore(self.path)
        conversations.initialize()
        conversation_id = uuid4()
        conversations.create(
            conversation_id=conversation_id, title="Expired archive",
            partition="production", origin="hud", agent="apex",
            selected_tool_names=None, tool_profile_id=None,
        )
        conversations.patch(conversation_id, "production", {"archived": True})
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "UPDATE conversations SET archived_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                (str(conversation_id),),
            )
        conversations.close()

        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_versions(domain TEXT PRIMARY KEY, version INTEGER NOT NULL)"
                )
                conn.execute(
                    "INSERT INTO schema_versions(domain, version) VALUES ('retrieval', 999)"
                )
                conn.execute("CREATE TABLE retrieval_items(id TEXT PRIMARY KEY, text TEXT)")
                conn.execute("INSERT INTO retrieval_items VALUES ('preserved', 'old derived row')")

        auth = mock.Mock()
        auth.initialize = mock.AsyncMock()
        auth.shutdown = mock.AsyncMock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock()
        manager.shutdown = mock.AsyncMock()
        supervisor = mock.Mock()
        context_vault = mock.Mock()
        context_vault.start.side_effect = lambda: asyncio.create_task(asyncio.sleep(0))

        async def wait_for_report_shutdown(_folder, stop_event):
            await stop_event.wait()

        retention_sweep_finished = threading.Event()

        async def run_real_retention_sweep(store, *, retention_days, stop_event):
            try:
                return await purge_expired_archived_conversations(
                    store, retention_days=retention_days, stop_event=stop_event
                )
            finally:
                retention_sweep_finished.set()

        original_initialize = RetrievalStore.initialize
        initialize_calls: list[RetrievalStore] = []

        def track_initialize(store: RetrievalStore) -> None:
            initialize_calls.append(store)
            original_initialize(store)

        prepare_calls: list[RetrievalService] = []

        def track_prepare(service: RetrievalService, *, allow_download: bool = True):
            prepare_calls.append(service)
            return service.status()

        with ExitStack() as stack:
            stack.enter_context(mock.patch("core.api.app.DEMO_MODE", False))
            stack.enter_context(mock.patch("core.api.app.database.DB_NAME", str(self.path)))
            stack.enter_context(mock.patch("core.api.app.configure_logging"))
            stack.enter_context(mock.patch("core.api.app.get_tracing_service", return_value=mock.Mock()))
            stack.enter_context(
                mock.patch("core.api.app.MicrosoftTodoAuthenticationService", return_value=auth)
            )
            stack.enter_context(mock.patch("core.api.app.MicrosoftTodoClient", return_value=mock.Mock()))
            stack.enter_context(mock.patch("core.api.app.get_llama_cpp_server_supervisor", return_value=supervisor))
            stack.enter_context(mock.patch("core.api.app.any_local_runtime_enabled", return_value=False))
            stack.enter_context(
                mock.patch(
                    "core.api.app.load_mcp_config",
                    return_value=McpRuntimeConfig(enabled=False, servers={}),
                )
            )
            stack.enter_context(mock.patch("core.api.app.MCPClientManager", return_value=manager))
            stack.enter_context(mock.patch("core.api.app.ReminderService"))
            stack.enter_context(mock.patch("core.api.app.get_settings_store", return_value=mock.Mock()))
            stack.enter_context(mock.patch("core.api.app.ContextVaultRuntime", return_value=context_vault))
            stack.enter_context(mock.patch("core.api.app.purge_expired_archived_conversations", new=run_real_retention_sweep))
            stack.enter_context(mock.patch("core.api.app.run_activity_report_folder_poller", new=wait_for_report_shutdown))
            stack.enter_context(mock.patch("core.api.app.speaker.initialize"))
            stack.enter_context(mock.patch("core.api.app.speaker.shutdown"))
            stack.enter_context(mock.patch.object(RetrievalStore, "initialize", autospec=True, side_effect=track_initialize))
            stack.enter_context(mock.patch.object(RetrievalService, "prepare", autospec=True, side_effect=track_prepare))

            with TestClient(app) as client:
                self.assertTrue(retention_sweep_finished.wait(timeout=10))
                retrieval = get_retrieval_service()
                status = retrieval.status()
                self.assertFalse(status.enabled)
                self.assertEqual(status.error_category, "retrieval_initialization_failed")

                knowledge = get_knowledge_service().store
                source = knowledge.create_source(
                    kind="manual",
                    partition="production",
                    locator="manual/lifecycle-check",
                    original_text="Jordan prefers quiet mornings",
                )
                record = knowledge.create_record(
                    partition="production",
                    kind="preference",
                    text="Jordan prefers quiet mornings",
                    source_ids=[source.id],
                )
                self.assertEqual(record.text, "Jordan prefers quiet mornings")

                deletion = client.delete(
                    f"/api/v1/cortex/conversations/{conversation_id}"
                )
                self.assertEqual(deletion.status_code, 409)

                self.assertEqual(initialize_calls, [])
                self.assertEqual(prepare_calls, [])
                with closing(sqlite3.connect(self.path)) as conn:
                    self.assertEqual(
                        conn.execute("SELECT count(*) FROM knowledge_records").fetchone()[0],
                        1,
                    )
                    self.assertEqual(
                        conn.execute("SELECT text FROM retrieval_items WHERE id='preserved'").fetchone()[0],
                        "old derived row",
                    )
                    self.assertEqual(
                        conn.execute("SELECT count(*) FROM retrieval_items").fetchone()[0],
                        1,
                    )
                    self.assertIsNotNone(
                        conn.execute(
                            "SELECT 1 FROM conversations WHERE id = ?", (str(conversation_id),)
                        ).fetchone()
                    )

    def test_cold_start_and_ready_status_do_not_load_cached_embedding_or_managed_llama(self) -> None:
        from core import database
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        fingerprint = "cached-model:384:test"
        seed_store = RetrievalStore(self.path)
        seed_store.initialize()
        item = RetrievalItem(
            namespace="shared",
            source_type="test",
            source_id="cached-ready-entry",
            partition="shared",
            conversation_id=None,
            message_id=None,
            role=None,
            timestamp="2026-10-01T00:00:00+00:00",
            locator="shared/cached-ready-entry",
            content_hash="cached-ready-entry",
            text="Persisted semantic retrieval is ready.",
        )
        item_id = seed_store.upsert_item(item)
        seed_store.upsert_embedding(item_id, fingerprint, [1.0] + [0.0] * 383)
        seed_store.set_model_state(
            state="ready", fingerprint=fingerprint, prepared_at="2026-10-01T00:00:00+00:00"
        )
        seed_store.close()

        auth = mock.Mock()
        auth.initialize = mock.AsyncMock()
        auth.shutdown = mock.AsyncMock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock()
        manager.shutdown = mock.AsyncMock()
        supervisor = mock.Mock()
        supervisor.ensure_ready.side_effect = AssertionError(
            "managed llama.cpp must not start during application startup"
        )
        settings = mock.Mock()
        snapshot = mock.Mock()
        snapshot.device_context.location_enabled = False
        snapshot.llama_cpp.enabled = True
        snapshot.llama_cpp.managed = True
        settings.get_snapshot.return_value = snapshot
        vault_stop = asyncio.Event()
        context_vault = mock.Mock()
        context_vault.start.side_effect = lambda: asyncio.create_task(vault_stop.wait())
        context_vault.request_stop.side_effect = vault_stop.set
        registry = mock.Mock()

        async def wait_for_report_shutdown(_folder, stop_event):
            await stop_event.wait()

        with ExitStack() as stack:
            stack.enter_context(mock.patch("core.api.app.database.DB_NAME", str(self.path)))
            # Establish the real supported core schemas before the profile begins its read-only checks.
            database.initialize_db()
            stack.enter_context(mock.patch("core.api.app.DEMO_MODE", False))
            stack.enter_context(mock.patch("core.api.app.configure_logging"))
            stack.enter_context(mock.patch("core.api.app.get_tracing_service", return_value=mock.Mock()))
            stack.enter_context(
                mock.patch("core.api.app.MicrosoftTodoAuthenticationService", return_value=auth)
            )
            stack.enter_context(mock.patch("core.api.app.MicrosoftTodoClient", return_value=mock.Mock()))
            stack.enter_context(
                mock.patch("core.api.app.get_llama_cpp_server_supervisor", return_value=supervisor)
            )
            stack.enter_context(mock.patch("core.api.app.any_local_runtime_enabled", return_value=False))
            stack.enter_context(
                mock.patch("core.api.app.load_mcp_config", return_value=McpRuntimeConfig(enabled=False, servers={}))
            )
            stack.enter_context(mock.patch("core.api.app.MCPClientManager", return_value=manager))
            stack.enter_context(mock.patch("core.api.app.ReminderService"))
            stack.enter_context(mock.patch("core.api.app.get_settings_store", return_value=settings))
            stack.enter_context(mock.patch("core.api.app.ContextVaultRuntime", return_value=context_vault))
            stack.enter_context(
                mock.patch("core.api.app.run_activity_report_folder_poller", new=wait_for_report_shutdown)
            )
            stack.enter_context(mock.patch("core.api.app.speaker.initialize"))
            stack.enter_context(mock.patch("core.api.app.speaker.shutdown"))
            stack.enter_context(mock.patch("core.api.app.speaker.close_kokoro", return_value=True))
            stack.enter_context(mock.patch("core.api.app.ConnectorHttpSessions", return_value=registry))
            stack.enter_context(
                mock.patch.object(
                    FastEmbedAdapter,
                    "_load",
                    side_effect=AssertionError("cached embedding model loaded during cold startup/status"),
                )
            )

            with TestClient(app) as client:
                response = client.get("/api/v1/cortex/retrieval/status")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["state"], "ready")
                self.assertEqual(response.json()["mode"], "semantic")
                self.assertEqual(response.json()["model_fingerprint"], fingerprint)

        supervisor.ensure_ready.assert_not_called()

    def test_failed_native_close_preserves_persistence_dependencies(self) -> None:
        from core import database
        from core.api.app import app
        from core.mcp.models import McpRuntimeConfig

        for failed_resource in ("retrieval", "kokoro"):
            with self.subTest(failed_resource=failed_resource):
                self.path = Path(self.temp_dir.name) / f"{failed_resource}-close.db"
                auth = mock.Mock()
                auth.initialize = mock.AsyncMock()
                auth.shutdown = mock.AsyncMock()
                manager = mock.Mock()
                manager.start = mock.AsyncMock()
                manager.shutdown = mock.AsyncMock()
                supervisor = mock.Mock()
                settings = mock.Mock()
                settings.get_snapshot.return_value.device_context.location_enabled = False
                vault_stop = asyncio.Event()
                context_vault = mock.Mock()
                context_vault.start.side_effect = lambda: asyncio.create_task(vault_stop.wait())
                context_vault.request_stop.side_effect = vault_stop.set

                async def wait_for_report_shutdown(_folder, stop_event):
                    await stop_event.wait()

                with ExitStack() as stack:
                    stack.enter_context(mock.patch("core.api.app.database.DB_NAME", str(self.path)))
                    database.initialize_db()
                    stack.enter_context(mock.patch("core.api.app.DEMO_MODE", False))
                    stack.enter_context(mock.patch("core.api.app.configure_logging"))
                    tracing = mock.Mock()
                    stack.enter_context(mock.patch("core.api.app.get_tracing_service", return_value=tracing))
                    stack.enter_context(
                        mock.patch("core.api.app.MicrosoftTodoAuthenticationService", return_value=auth)
                    )
                    stack.enter_context(mock.patch("core.api.app.MicrosoftTodoClient", return_value=mock.Mock()))
                    stack.enter_context(
                        mock.patch("core.api.app.get_llama_cpp_server_supervisor", return_value=supervisor)
                    )
                    stack.enter_context(mock.patch("core.api.app.any_local_runtime_enabled", return_value=False))
                    stack.enter_context(
                        mock.patch("core.api.app.load_mcp_config", return_value=McpRuntimeConfig(enabled=False, servers={}))
                    )
                    stack.enter_context(mock.patch("core.api.app.MCPClientManager", return_value=manager))
                    stack.enter_context(mock.patch("core.api.app.ReminderService"))
                    stack.enter_context(mock.patch("core.api.app.get_settings_store", return_value=settings))
                    stack.enter_context(mock.patch("core.api.app.ContextVaultRuntime", return_value=context_vault))
                    stack.enter_context(
                        mock.patch("core.api.app.run_activity_report_folder_poller", new=wait_for_report_shutdown)
                    )
                    stack.enter_context(mock.patch("core.api.app.speaker.initialize"))
                    speaker_shutdown = stack.enter_context(mock.patch("core.api.app.speaker.shutdown"))
                    kokoro_close = stack.enter_context(
                        mock.patch(
                            "core.api.app.speaker.close_kokoro",
                            return_value=failed_resource != "kokoro",
                        )
                    )
                    stack.enter_context(mock.patch("core.api.app.ConnectorHttpSessions", return_value=mock.Mock()))
                    retrieval_close = stack.enter_context(
                        mock.patch.object(
                            RetrievalService, "close", return_value=failed_resource != "retrieval"
                        )
                    )
                    conversation_close = stack.enter_context(mock.patch.object(ConversationStore, "close"))

                    expected_error = (
                        "Retrieval shutdown timed out"
                        if failed_resource == "retrieval"
                        else "Kokoro shutdown timed out"
                    )
                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        with TestClient(app):
                            pass

                retrieval_close.assert_called_once_with(timeout_seconds=mock.ANY)
                if failed_resource == "retrieval":
                    kokoro_close.assert_not_called()
                else:
                    kokoro_close.assert_called_once_with(mock.ANY)
                conversation_close.assert_not_called()
                speaker_shutdown.assert_not_called()
                tracing.shutdown.assert_not_called()
                self.assertFalse(app.state.lifecycle_cleanup_complete)
                with closing(sqlite3.connect(self.path)) as conn:
                    self.assertIsNotNone(
                        conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name='conversations'"
                        ).fetchone()
                    )

                # The runtime deliberately retained its lease and stores on failure;
                # release test-owned references after proving that behavior.
                context = app.state.host_context
                if context is not None and context.profile_lock.acquired:
                    context.release()
                app.state.host_context = None
                app.state.lifecycle_entered = False
                app.state.lifecycle_established = False
                app.state.lifecycle_cleanup_complete = False
                for setter in (
                    "set_action_service",
                    "set_connector_http_sessions",
                    "set_microsoft_auth_service",
                    "set_microsoft_todo_client",
                    "set_mcp_manager",
                    "set_conversation_service",
                    "set_run_service",
                    "set_run_coordinator",
                    "set_briefing_service",
                    "set_briefing_speech_service",
                    "set_briefing_session_queries",
                    "set_retrieval_service",
                    "set_knowledge_service",
                    "set_reminder_service",
                    "set_context_vault_runtime",
                    "set_activity_service",
                    "set_activity_report_folder",
                ):
                    getattr(__import__("core.api.app", fromlist=[setter]), setter)(None)


if __name__ == "__main__":
    unittest.main()
