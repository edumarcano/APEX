"""Application-owned action service access for API and Cortex adapters."""

from __future__ import annotations

from core.actions.service import ActionService

_service: ActionService | None = None


def set_action_service(service: ActionService | None) -> None:
    """Publish the action service for the lifetime of the local API process."""
    global _service
    _service = service


def get_action_service() -> ActionService | None:
    """Return the active action service, if the application has started it."""
    return _service
