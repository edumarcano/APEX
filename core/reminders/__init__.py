"""Concrete Microsoft To Do-backed reminder service runtime."""

from core.reminders.runtime import get_reminder_service, set_reminder_service
from core.reminders.service import ReminderService

__all__ = ["ReminderService", "get_reminder_service", "set_reminder_service"]
