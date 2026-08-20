"""Focused coverage for selected-list reminders and the retained local outbox."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from clients.microsoft_todo_client import MicrosoftTodoUpstreamError
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
        self.assertEqual(view["items"][0]["importance"], "normal")
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
        self.client.list_tasks.side_effect = MicrosoftTodoUpstreamError("offline")

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

    def test_linked_active_sync_cannot_be_dismissed_locally(self) -> None:
        local_id = database.save_reminder("Wait for verified sync")
        self.assertTrue(database.link_reminder_action(local_id, "action-1"))
        self.actions.get.return_value = SimpleNamespace(status="executing")

        with self.assertRaisesRegex(ReminderServiceError, "reminder_sync_in_progress"):
            self._service().complete(f"local:{local_id}")

        row = database.get_local_reminder(local_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row["is_read"])
        self.assertEqual(row["sync_state"], "pending")

    def test_explicit_resync_replaces_a_proposal_for_a_previous_list(self) -> None:
        local_id = database.save_reminder("Move to the current list")
        self.assertTrue(database.link_reminder_action(local_id, "action-old"))
        self.client.get_status.return_value = SimpleNamespace(state="connected")
        self.actions.get.return_value = SimpleNamespace(
            status="proposed",
            action_id="action-old",
            version=0,
            proposal=SimpleNamespace(arguments={"list_id": "list-old"}),
        )
        service = self._service("list-new")
        replacement = SimpleNamespace(status="execution_failed", action_id="action-new")
        with mock.patch.object(service, "_propose_create", return_value=replacement) as propose:
            result = service.sync([f"local:{local_id}"])

        self.assertEqual(result, [{"id": f"local:{local_id}", "outcome": "failed", "action_id": "action-new"}])
        propose.assert_called_once_with(
            "Move to the current list", list_id="list-new", local_id=local_id
        )
        self.actions.approve_and_execute.assert_not_called()

    def test_task_detail_reads_only_the_selected_list(self) -> None:
        self.client.get_status.return_value = SimpleNamespace(state="connected")
        self.client.get_task.return_value = SimpleNamespace(
            id="task-a", title="Review plan", importance="high", is_completed=False,
            due=SimpleNamespace(date_time="2026-08-15T09:00:00", time_zone="UTC"),
            completed_at=None, last_modified_at="stamp-a",
        )

        detail = self._service("list-a").task_detail("todo:task-a")

        self.assertEqual(detail["id"], "todo:task-a")
        self.assertEqual(detail["importance"], "high")
        self.assertEqual(detail["due"], {"date_time": "2026-08-15T09:00:00", "time_zone": "UTC"})
        self.client.get_task.assert_called_once_with("list-a", "task-a")

    def test_completed_read_is_live_bounded_and_does_not_touch_cache(self) -> None:
        self.client.get_status.return_value = SimpleNamespace(state="connected")
        self.client.list_tasks.return_value = SimpleNamespace(tasks=[
            SimpleNamespace(id="active", title="Active", importance="normal", is_completed=False, due=None, completed_at=None, last_modified_at="a"),
            SimpleNamespace(id="done", title="Done", importance="normal", is_completed=True, due=None, completed_at=SimpleNamespace(date_time="2026-08-14T09:00:00", time_zone="UTC"), last_modified_at="b"),
        ])

        result = self._service("list-a").completed()

        self.assertEqual(result["source_state"], "live")
        self.assertEqual([item["id"] for item in result["items"]], ["todo:done"])
        self.client.list_tasks.assert_called_once_with("list-a", include_completed=True, max_results=50)
        self.assertIsNone(database.fetch_microsoft_todo_reminder_cache("list-a"))

    def test_update_uses_an_immediate_operator_action_with_the_observed_timestamp(self) -> None:
        self.client.get_status.return_value = SimpleNamespace(state="connected")
        proposal = SimpleNamespace(action_id="action-1", version=2)
        verified = SimpleNamespace(status="verified", action_id="action-1")
        self.actions.propose.return_value = proposal
        self.actions.approve_and_execute.return_value = verified

        result = self._service("list-a").update_task(
            "todo:task-a", "stamp-a", {"title": "Review updated", "due": None}
        )

        self.assertEqual(result, {"id": "todo:task-a", "outcome": "synced", "action_id": "action-1"})
        self.actions.propose.assert_called_once_with(
            agent_key="operator", capability_name="update_microsoft_todo_task",
            arguments={"list_id": "list-a", "task_id": "task-a", "last_modified_at": "stamp-a", "title": "Review updated", "due": None},
            target="Update Microsoft To Do Task", risk="write",
            summary="Approve Update Microsoft To Do Task", actor="operator",
        )
        self.actions.approve_and_execute.assert_called_once_with("action-1", actor="operator", expected_version=2)

    def test_ambiguous_delete_returns_unknown_without_replaying(self) -> None:
        self.client.get_status.return_value = SimpleNamespace(state="connected")
        proposal = SimpleNamespace(action_id="action-1", version=0)
        unknown = SimpleNamespace(status="outcome_unknown", action_id="action-1")
        self.actions.propose.return_value = proposal
        self.actions.approve_and_execute.return_value = unknown

        result = self._service("list-a").delete_task("todo:task-a", "stamp-a")

        self.assertEqual(result["outcome"], "unknown")
        self.actions.propose.assert_called_once()
        self.actions.approve_and_execute.assert_called_once()
