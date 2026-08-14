"""Focused coverage for selected-list reminders and the retained local outbox."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import database
from core.reminders.service import ReminderService, ReminderServiceError


class ReminderServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory(prefix="apex_reminders_")
        self.addCleanup(self._temp_dir.cleanup)
        db_path = Path(self._temp_dir.name) / "apex_memory.db"
        patch = mock.patch.object(database, "DB_NAME", str(db_path))
        patch.start()
        self.addCleanup(patch.stop)
        database.initialize_db()
        self.client = mock.Mock()
        self.actions = mock.Mock()

    def _service(self, list_id: str = "list-a") -> ReminderService:
        settings = SimpleNamespace(
            get_snapshot=lambda: SimpleNamespace(
                microsoft_todo=SimpleNamespace(reminder_list_id=list_id)
            )
        )
        patch = mock.patch("core.reminders.service.get_settings_store", return_value=settings)
        patch.start()
        self.addCleanup(patch.stop)
        return ReminderService(self.client, self.actions)

    def test_unselected_list_keeps_legacy_rows_visible_as_pending(self) -> None:
        local_id = database.save_reminder("Review offline work")
        service = self._service("")

        view = service.list().to_dict()

        self.assertEqual(view["source_state"], "unavailable")
        self.assertEqual(view["pending_sync_count"], 1)
        self.assertEqual(view["items"][0]["id"], f"local:{local_id}")
        self.client.list_tasks.assert_not_called()

    def test_live_read_replaces_only_selected_list_cache(self) -> None:
        self.client.get_status.return_value = SimpleNamespace(state="connected")
        self.client.list_tasks.return_value = SimpleNamespace(
            tasks=[
                SimpleNamespace(id="task-a", title="Remote task", last_modified_at="2026-08-13T12:00:00Z"),
            ]
        )
        service = self._service("list-a")

        view = service.list().to_dict()

        self.assertEqual(view["source_state"], "live")
        self.assertEqual(view["items"][0]["id"], "todo:task-a")
        self.assertIsNotNone(database.fetch_microsoft_todo_reminder_cache("list-a"))
        self.assertIsNone(database.fetch_microsoft_todo_reminder_cache("list-b"))
        self.client.list_tasks.assert_called_once_with(
            "list-a", include_completed=False, max_results=50
        )

    def test_failed_read_uses_matching_cache_as_stale(self) -> None:
        database.replace_microsoft_todo_reminder_cache(
            "list-a",
            fetched_at="2026-08-13T12:00:00Z",
            tasks=[{"id": "task-a", "title": "Cached task", "last_modified_at": "stamp"}],
        )
        database.replace_microsoft_todo_reminder_cache(
            "list-b",
            fetched_at="2026-08-13T12:00:00Z",
            tasks=[{"id": "task-b", "title": "Wrong list", "last_modified_at": "stamp"}],
        )
        self.client.get_status.return_value = SimpleNamespace(state="connected")
        self.client.list_tasks.side_effect = RuntimeError("offline")

        view = self._service("list-a").list().to_dict()

        self.assertEqual(view["source_state"], "stale")
        self.assertEqual([item["id"] for item in view["items"]], ["todo:task-a"])

    def test_known_offline_quick_add_queues_one_pending_local_row(self) -> None:
        self.client.get_status.return_value = SimpleNamespace(state="disconnected")

        result = self._service().create("  Plan   review  ")

        self.assertEqual(result["outcome"], "pending")
        self.assertEqual(database.fetch_local_reminders()[0]["note"], "Plan review")
        self.actions.propose.assert_not_called()

    def test_unknown_local_row_requires_review_before_dismissal(self) -> None:
        local_id = database.save_reminder("Inspect uncertain task")
        database.set_reminder_sync_state(local_id, "unknown")
        service = self._service("")

        with self.assertRaisesRegex(ReminderServiceError, "unknown_reminder_requires_review"):
            service.complete(f"local:{local_id}")
        service.dismiss_unknown(f"local:{local_id}")
        self.assertEqual(database.fetch_local_reminders(), [])
