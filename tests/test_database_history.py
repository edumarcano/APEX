"""Characterization coverage for database bootstrap and retired history tables."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
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

    def test_repeated_bootstrap_preserves_incidental_historical_tables(self) -> None:
        with closing(sqlite3.connect(str(self.db_path))) as conn, conn:
            conn.execute("CREATE TABLE briefings (id INTEGER PRIMARY KEY, briefing TEXT NOT NULL)")
            conn.execute("INSERT INTO briefings(briefing) VALUES ('legacy transcript')")
            conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, timestamp TEXT)")
            conn.execute("INSERT INTO runs(timestamp) VALUES ('historical cooldown')")

        database.initialize_db()
        database.initialize_db()

        with closing(sqlite3.connect(str(self.db_path))) as conn:
            self.assertEqual(conn.execute("SELECT briefing FROM briefings").fetchone()[0], "legacy transcript")
            self.assertEqual(conn.execute("SELECT timestamp FROM runs").fetchone()[0], "historical cooldown")

        fresh_path = Path(self._temp_dir.name) / "fresh.db"
        with mock.patch.object(database, "DB_NAME", str(fresh_path)):
            database.initialize_db()
        with closing(sqlite3.connect(str(fresh_path))) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("runs", names)
        self.assertNotIn("briefings", names)

    def test_bootstrap_failure_rolls_back_reminder_and_action_ddl(self) -> None:
        failed_path = Path(self._temp_dir.name) / "failed.db"
        with mock.patch.object(database, "DB_NAME", str(failed_path)), mock.patch(
            "core.actions.store.initialize_action_schema",
            side_effect=RuntimeError("injected action bootstrap failure"),
        ), self.assertRaisesRegex(RuntimeError, "injected action bootstrap failure"):
            database.initialize_db()

        with closing(sqlite3.connect(str(failed_path))) as conn:
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({"reminders", "microsoft_todo_reminder_cache", "actions", "action_events"} & names)

    def test_legacy_reminder_schema_is_rejected_without_rewriting_rows(self) -> None:
        legacy_path = Path(self._temp_dir.name) / "legacy_reminders.db"
        with closing(sqlite3.connect(str(legacy_path))) as conn, conn:
            conn.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY, note TEXT, is_read INTEGER DEFAULT 0)")
            conn.execute("INSERT INTO reminders(id, note, is_read) VALUES (1, 'Unread', 0)")

        with mock.patch.object(database, "DB_NAME", str(legacy_path)):
            with self.assertRaisesRegex(RuntimeError, "missing required columns"):
                database.initialize_db()
        with closing(sqlite3.connect(str(legacy_path))) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
            self.assertEqual(columns, {"id", "note", "is_read"})
            self.assertEqual(conn.execute("SELECT note, is_read FROM reminders WHERE id=1").fetchone(), ("Unread", 0))

    def test_reminder_sync_cannot_overwrite_a_local_dismissal(self) -> None:
        reminder_id = database.save_reminder("Review race handling")
        self.assertTrue(database.link_reminder_action(reminder_id, "action-1"))
        database.set_reminder_sync_state(reminder_id, "dismissed")
        updated = database.mark_reminder_synced(
            reminder_id, list_id="list-1", task_id="task-1", action_id="action-1"
        )
        self.assertFalse(updated)
        row = database.get_local_reminder(reminder_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["is_read"])
        self.assertEqual(row["sync_state"], "dismissed")


if __name__ == "__main__":
    unittest.main()
