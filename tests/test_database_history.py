"""Characterization coverage for briefing ledger persistence and malformed rows."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
from unittest import mock

from core import database


class DatabaseHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_db_hist_")
        self.addCleanup(self._temp_dir.cleanup)
        self.db_path = Path(self._temp_dir.name) / "apex_memory.db"
        self._db_name_patch = mock.patch.object(database, "DB_NAME", str(self.db_path))
        self._db_name_patch.start()
        self.addCleanup(self._db_name_patch.stop)
        database.initialize_db()

    def test_legacy_briefing_table_is_dropped_transactionally_and_idempotently(self) -> None:
        from core.briefings.store import BriefingSessionStore
        from core.conversations.store import ConversationStore
        from core.runs.store import RunStore

        session_store = BriefingSessionStore(self.db_path)
        conversation_store = ConversationStore(self.db_path)
        run_store = RunStore(self.db_path)
        conversation_store.initialize()
        run_store.initialize()
        session_store.initialize()

        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute(
                "CREATE TABLE briefings (id INTEGER PRIMARY KEY, briefing TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO briefings(briefing) VALUES ('legacy transcript')")
            conn.execute("CREATE TABLE preserved_data (value TEXT NOT NULL)")
            conn.execute("INSERT INTO preserved_data(value) VALUES ('keep me')")
            conn.execute(
                "INSERT INTO briefing_sessions (id, partition, idempotency_key, conversation_id, "
                "opening_message_id, run_id, profile_id, created_at, request_json, configuration_json) "
                "VALUES ('session-1', 'production', 'key-1', 'conversation-1', 'message-1', "
                "'run-1', 'daily', '2026-09-26T10:00:00Z', '{}', '{}')"
            )

        with mock.patch(
            "core.actions.store.initialize_action_schema",
            side_effect=RuntimeError("simulated later migration failure"),
        ), self.assertRaises(RuntimeError):
            database.initialize_db()

        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            self.assertIsNotNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='briefings'").fetchone()
            )
            self.assertEqual(conn.execute("SELECT briefing FROM briefings").fetchone()[0], "legacy transcript")

        database.initialize_db()
        database.initialize_db()
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            self.assertIsNone(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='briefings'").fetchone()
            )
            self.assertEqual(conn.execute("SELECT value FROM preserved_data").fetchone()[0], "keep me")
            self.assertEqual(conn.execute("SELECT id FROM briefing_sessions").fetchall(), [("session-1",)])
        session_store.close()
        run_store.close()
        conversation_store.close()

    def test_utc_writes_and_naive_legacy_reads(self) -> None:
        database.log_run()
        last = database.get_last_run()
        self.assertIsNotNone(last)
        assert last is not None
        self.assertIsNotNone(last.tzinfo)

        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            with conn:
                conn.execute("DELETE FROM runs")
                conn.execute(
                    "INSERT INTO runs (timestamp) VALUES (?)",
                    ((datetime.now() - timedelta(minutes=10)).isoformat(),),
                )
        finally:
            conn.close()

        legacy = database.get_last_run()
        self.assertIsNotNone(legacy)
        assert legacy is not None
        self.assertIsNotNone(legacy.tzinfo)
        elapsed = datetime.now(timezone.utc) - legacy.astimezone(timezone.utc)
        self.assertLess(elapsed, timedelta(hours=1))
        self.assertGreater(elapsed, timedelta(minutes=1))

    def test_verified_sync_cannot_overwrite_a_local_dismissal(self) -> None:
        reminder_id = database.save_reminder("Review race handling")
        self.assertTrue(database.link_reminder_action(reminder_id, "action-1"))
        database.set_reminder_sync_state(reminder_id, "dismissed")

        updated = database.mark_reminder_synced(
            reminder_id,
            list_id="list-1",
            task_id="task-1",
            action_id="action-1",
        )

        self.assertFalse(updated)
        row = database.get_local_reminder(reminder_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["is_read"])
        self.assertEqual(row["sync_state"], "dismissed")

    def test_reminder_cutover_migrates_legacy_rows_without_deleting_them(self) -> None:
        legacy_path = Path(self._temp_dir.name) / "legacy_reminders.db"
        conn = sqlite3.connect(str(legacy_path))
        try:
            conn.execute(
                "CREATE TABLE reminders (id INTEGER PRIMARY KEY, note TEXT, is_read INTEGER DEFAULT 0)"
            )
            conn.execute("INSERT INTO reminders(id, note, is_read) VALUES (1, 'Unread', 0)")
            conn.execute("INSERT INTO reminders(id, note, is_read) VALUES (2, 'Read', 1)")
            conn.commit()
        finally:
            conn.close()

        with mock.patch.object(database, "DB_NAME", str(legacy_path)):
            database.initialize_db()
            rows = database.fetch_local_reminders()
            self.assertEqual(rows[0]["id"], 1)
            self.assertEqual(rows[0]["sync_state"], "pending")
            with database._connection() as migrated:
                archived = migrated.execute(
                    "SELECT sync_state FROM reminders WHERE id = 2"
                ).fetchone()
                self.assertEqual(archived[0], "dismissed")
                self.assertIsNotNone(
                    migrated.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'microsoft_todo_reminder_cache'"
                    ).fetchone()
                )


if __name__ == "__main__":
    unittest.main()
