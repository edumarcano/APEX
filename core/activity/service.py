"""Authorization and partition boundary for local external activity receipts."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from core.activity.models import ActivityClientRegistration, ActivityReportContent
from core.activity.store import ActivityNotFoundError, ActivityStore, ActivityStoreError

_service: "ActivityService | None" = None


class ActivityPermissionError(ActivityStoreError):
    pass


class ActivityClientDisabledError(ActivityPermissionError):
    pass


def set_activity_service(service: "ActivityService | None") -> None:
    global _service
    _service = service


def get_activity_service() -> "ActivityService":
    if _service is None:
        raise RuntimeError("Activity service is unavailable.")
    return _service


class ActivityService:
    """Accept untrusted reports without coupling them to trusted knowledge."""

    def __init__(
        self,
        store: ActivityStore,
        registrations: tuple[ActivityClientRegistration, ...],
        *,
        registration_loader: Callable[[], tuple[ActivityClientRegistration, ...]] | None = None,
        demo_mode: bool = False,
    ) -> None:
        self.store = store
        self._registrations = {registration.id: registration for registration in registrations}
        self._registration_loader = registration_loader
        self._demo_mode = demo_mode

    def submit(self, *, client_id: str, principal: str, partition: str, content: ActivityReportContent):
        if self._demo_mode:
            raise ActivityPermissionError("activity_unavailable_in_demo")
        registrations = (
            {registration.id: registration for registration in self._registration_loader()}
            if self._registration_loader is not None
            else self._registrations
        )
        registration = registrations.get(client_id)
        if registration is None or not registration.enabled:
            raise ActivityClientDisabledError("activity_client_disabled")
        if registration.partition != partition:
            raise ActivityPermissionError("activity_client_partition_mismatch")
        if "activity:submit" not in registration.permissions or principal not in registration.allowed_principals:
            raise ActivityPermissionError("activity_submission_not_permitted")
        return self.store.submit(
            partition=partition, client_id=registration.id,
            client_display_name=registration.display_name, principal=principal, content=content,
        )

    def list(self, *, partition: str, client_id: str | None = None, disposition: str | None = None, limit: int = 50):
        return self.store.list(partition=partition, client_id=client_id, disposition=disposition, limit=limit)

    def get(self, report_id: UUID, *, partition: str):
        return self.store.get(report_id, partition=partition)

    def resolve_finding_reference(self, report_id: UUID, *, partition: str, reference: str) -> str:
        """Resolve immutable report evidence for the future context-review branch."""
        return self.store.get(report_id, partition=partition).content.resolve_finding_reference(reference)

    def resolve_finding_evidence(self, report_id: UUID, *, partition: str, reference: str):
        return self.store.get(report_id, partition=partition).content.resolve_finding_evidence(reference)
