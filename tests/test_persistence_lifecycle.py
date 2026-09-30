"""Lifecycle safety checks for supported and unsupported persistence schemas."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.knowledge import get_knowledge_service
from core.retrieval import get_retrieval_service
from core.retrieval.service import RetrievalService
from core.retrieval.store import RetrievalStore


class PersistenceLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "lifecycle.db"

    def tearDown(self) -> None:
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

        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute(
                    "CREATE TABLE schema_versions(domain TEXT PRIMARY KEY, version INTEGER NOT NULL)"
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
            stack.enter_context(mock.patch("core.api.app.purge_expired_archived_conversations", new=mock.AsyncMock(return_value=0)))
            stack.enter_context(mock.patch("core.api.app.run_activity_report_folder_poller", new=wait_for_report_shutdown))
            stack.enter_context(mock.patch("core.api.app.speaker.initialize"))
            stack.enter_context(mock.patch("core.api.app.speaker.shutdown"))
            stack.enter_context(mock.patch.object(RetrievalStore, "initialize", autospec=True, side_effect=track_initialize))
            stack.enter_context(mock.patch.object(RetrievalService, "prepare", autospec=True, side_effect=track_prepare))

            with TestClient(app):
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


if __name__ == "__main__":
    unittest.main()
