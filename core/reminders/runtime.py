"""Lifespan-owned access to the reminder service."""

from __future__ import annotations

from core.reminders.service import ReminderService

_service: ReminderService | None = None


def set_reminder_service(service: ReminderService | None) -> None:
    """Publish the one production reminder service for application adapters."""
    global _service
    _service = service


def get_reminder_service() -> ReminderService | None:
    """Return the active service, if normal-mode application startup completed."""
    return _service
