"""Characterization coverage for briefing ledger persistence and malformed rows."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
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

    def test_save_and_fetch_briefing_history_round_trip(self) -> None:
        digest = {
            "confidence_score": 90.0,
            "failed_connectors": [],
            "insights": ["Stay hydrated"],
        }
        metadata = {
            "dev_mode_active": False,
            "demo_mode_active": False,
            "synthesis_strategy": "cloud",
            "tts_strategy": "google",
            "active_tts_engine": "google",
            "system_load_throttled": False,
        }
        database.save_briefing("Morning briefing.", digest, metadata)
        rows = database.fetch_briefing_history(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["briefing"], "Morning briefing.")
        self.assertEqual(rows[0]["digest"]["confidence_score"], 90.0)
        self.assertEqual(rows[0]["metadata"]["synthesis_strategy"], "cloud")
        self.assertIsInstance(rows[0]["id"], int)
        self.assertTrue(rows[0]["timestamp"])

    def test_malformed_digest_and_metadata_json_are_tolerated(self) -> None:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        try:
            conn.execute(
                "INSERT INTO briefings (timestamp, briefing, digest_json, metadata_json) "
                "VALUES (?, ?, ?, ?)",
                ("2026-07-12T12:00:00", "Legacy row", "{not-json", "also-not-json"),
            )
            conn.execute(
                "INSERT INTO briefings (timestamp, briefing, digest_json, metadata_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    "2026-07-12T13:00:00",
                    "Valid digest only",
                    json.dumps({"confidence_score": 50.0}),
                    None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        rows = database.fetch_briefing_history(limit=10)
        by_briefing = {row["briefing"]: row for row in rows}
        self.assertEqual(by_briefing["Legacy row"]["digest"], {})
        self.assertIsNone(by_briefing["Legacy row"]["metadata"])
        self.assertEqual(
            by_briefing["Valid digest only"]["digest"]["confidence_score"], 50.0
        )
        self.assertIsNone(by_briefing["Valid digest only"]["metadata"])

    def test_prune_keeps_fifty_most_recent(self) -> None:
        for index in range(55):
            database.save_briefing(
                f"Briefing {index}",
                {"confidence_score": float(index)},
                None,
            )
        database.prune_historical_ledger()
        rows = database.fetch_briefing_history(limit=100)
        self.assertEqual(len(rows), 50)
        scores = [row["digest"]["confidence_score"] for row in rows]
        self.assertEqual(max(scores), 54.0)
        self.assertEqual(min(scores), 5.0)

    def test_reminder_lifecycle(self) -> None:
        first = database.save_reminder("Charge laptop")
        second = database.save_reminder("Review notes")
        unread = database.fetch_unread_reminders()
        self.assertEqual(unread, [(first, "Charge laptop"), (second, "Review notes")])
        database.mark_reminders_read([first])
        unread_after = database.fetch_unread_reminders()
        self.assertEqual(unread_after, [(second, "Review notes")])


if __name__ == "__main__":
    unittest.main()
