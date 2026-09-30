"""Reminder route speech-text preparation coverage."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import Response

from core.api.models import CreateReminderRequest, ReminderTaskUpdateRequest
from core.api.routers import reminders


class ReminderSpeechPreparationTests(unittest.TestCase):
    def test_create_prepares_markup_and_preserves_unicode_before_persistence(self) -> None:
        service = mock.Mock()
        service.create.return_value = {"id": "todo:created", "outcome": "synced"}
        payload = CreateReminderRequest(text="**Café** [agenda](https://example.test)")

        with mock.patch.object(reminders, "DEMO_MODE", False), mock.patch.object(
            reminders, "_service", return_value=service
        ):
            response = reminders.create_reminder(payload, Response())

        self.assertEqual(response.outcome, "synced")
        service.create.assert_called_once_with("Café agenda")

    def test_update_prepares_markup_and_preserves_unicode_title(self) -> None:
        service = mock.Mock()
        service.update_task.return_value = {
            "id": "todo:task-1",
            "outcome": "synced",
            "action_id": "update-1",
        }
        payload = ReminderTaskUpdateRequest(
            id="todo:task-1",
            last_modified_at="revision-1",
            title="**naïve résumé**",
        )

        with mock.patch.object(reminders, "DEMO_MODE", False), mock.patch.object(
            reminders, "_service", return_value=service
        ):
            response = reminders.update_reminder_task(payload, Response())

        self.assertEqual(response.outcome, "synced")
        self.assertEqual(service.update_task.call_args.args[2], {"title": "naïve résumé"})


if __name__ == "__main__":
    unittest.main()
