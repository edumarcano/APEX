from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from core import database
from core.activity.store import ActivityStore
from core.briefings.store import BriefingSessionStore
from core.conversations.store import ConversationStore
from core.retrieval.store import RetrievalStore
from core.runs.store import RunStore


class PersistenceBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="apex_persistence_")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "apex_memory.db"

    def test_current_domains_bootstrap_repeatedly_without_schema_changes(self) -> None:
        with mock.patch.object(database, "DB_NAME", str(self.path)):
            database.initialize_db()
            conversations = ConversationStore(self.path)
            runs = RunStore(self.path)
            retrieval = RetrievalStore(self.path)
            briefings = BriefingSessionStore(self.path)
            activity = ActivityStore(self.path)
            self.addCleanup(conversations.close)
            self.addCleanup(runs.close)
            self.addCleanup(retrieval.close)
            self.addCleanup(briefings.close)
            self.addCleanup(activity.close)
            conversations.initialize()
            runs.initialize()
            retrieval.initialize()
            briefings.initialize()
            activity.initialize()
            database.initialize_db()
            first_versions = self._versions()
            conversations.initialize()
            runs.initialize()
            retrieval.initialize()
            briefings.initialize()
            activity.initialize()
            database.initialize_db()
            self.assertEqual(self._versions(), first_versions)

        with closing(sqlite3.connect(self.path)) as conn:
            versions = dict(conn.execute("SELECT domain, version FROM schema_versions"))
            self.assertEqual(
                versions,
                {
                    "conversations": 2,
                    "cortex_runs": 2,
                    "retrieval": 2,
                    "briefing_sessions": 2,
                    "briefing_speech": 1,
                    "activity": 2,
                },
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def _versions(self) -> dict[str, int]:
        with closing(sqlite3.connect(self.path)) as conn:
            return dict(conn.execute("SELECT domain, version FROM schema_versions"))

    def test_shared_in_memory_demo_connection_bootstraps_repeatedly(self) -> None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.addCleanup(conn.close)
        conn.execute("PRAGMA foreign_keys=ON")
        database.initialize_db(include_actions=False, connection=conn)
        stores = [
            ConversationStore(None, connection=conn),
            RunStore(None, connection=conn),
            RetrievalStore(None, connection=conn),
            BriefingSessionStore(None, connection=conn),
            ActivityStore(None, connection=conn),
        ]
        for store in stores:
            store.initialize()
        database.initialize_db(include_actions=False, connection=conn)
        for store in stores:
            store.initialize()
            store.close()
        # Store.close releases only its borrowed handle, preserving the caller's
        # shared DEMO_MODE connection for the rest of the lifespan.
        self.assertEqual(conn.execute("SELECT 1").fetchone()[0], 1)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("reminders", names)
        self.assertIn("microsoft_todo_reminder_cache", names)
        self.assertIn("conversations", names)
        self.assertIn("cortex_runs", names)
        self.assertIn("briefing_speech_audio_chunks", names)
        self.assertIn("activity_context_review_links", names)
        self.assertNotIn("actions", names)
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_retrieval_bootstrap_ddl_and_version_roll_back_together(self) -> None:
        store = RetrievalStore(self.path)
        self.addCleanup(store.close)
        with mock.patch.object(
            RetrievalStore, "_create_triggers", side_effect=RuntimeError("injected failure")
        ), self.assertRaisesRegex(RuntimeError, "injected failure"):
            store.initialize()

        with closing(sqlite3.connect(self.path)) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(
            {"schema_versions", "retrieval_items", "retrieval_embeddings", "retrieval_model_state", "retrieval_items_fts"}
            & names
        )

    def test_partial_current_run_schema_is_rejected_without_repair(self) -> None:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TABLE schema_versions(domain TEXT, version INTEGER)")
            conn.execute("INSERT INTO schema_versions VALUES ('cortex_runs', 2)")
            conn.execute("CREATE TABLE cortex_runs(id TEXT PRIMARY KEY)")

        store = RunStore(self.path)
        self.addCleanup(store.close)
        with self.assertRaisesRegex(RuntimeError, "missing required columns"):
            store.initialize()
        with closing(sqlite3.connect(self.path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(cortex_runs)")}
            self.assertEqual(columns, {"id"})
            self.assertEqual(conn.execute("SELECT version FROM schema_versions WHERE domain='cortex_runs'").fetchone()[0], 2)

    def test_briefing_speech_late_failure_rolls_back_session_and_speech_ddl(self) -> None:
        store = BriefingSessionStore(self.path)
        self.addCleanup(store.close)
        with mock.patch(
            "core.briefings.store.utc_now_iso", side_effect=RuntimeError("injected recovery failure")
        ), self.assertRaisesRegex(RuntimeError, "injected recovery failure"):
            store.initialize()

        with closing(sqlite3.connect(self.path)) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(
            {"schema_versions", "briefing_sessions", "briefing_speech", "briefing_speech_audio_chunks"}
            & names
        )


if __name__ == "__main__":
    unittest.main()
