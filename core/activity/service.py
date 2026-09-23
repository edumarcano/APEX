"""Source attribution boundary for local external activity receipts."""

from __future__ import annotations

from uuid import UUID

from core.activity.models import ActivityReportContent, is_valid_activity_client_id
from core.activity.store import ActivityNotFoundError, ActivityStore, ActivityStoreError

_service: "ActivityService | None" = None


class ActivityUnavailableError(ActivityStoreError):
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
        *,
        demo_mode: bool = False,
    ) -> None:
        self.store = store
        self._demo_mode = demo_mode

    def submit(self, *, client_id: str, principal: str, partition: str, content: ActivityReportContent):
        if self._demo_mode:
            raise ActivityUnavailableError("activity_unavailable_in_demo")
        if not is_valid_activity_client_id(client_id):
            raise ActivityStoreError("activity_client_id_invalid")
        return self.store.submit(
            partition=partition, client_id=client_id,
            client_display_name=client_id, principal=principal, content=content,
        )

    def list(self, *, partition: str, client_id: str | None = None, disposition: str | None = None, limit: int = 50):
        return self.store.list(partition=partition, client_id=client_id, disposition=disposition, limit=limit)

    def get(self, report_id: UUID, *, partition: str):
        return self.store.get(report_id, partition=partition)

    def set_disposition(self, report_id: UUID, *, partition: str, disposition: str):
        return self.store.set_disposition(report_id, partition=partition, disposition=disposition)

    def context_review_links(self, report_id: UUID, *, partition: str):
        return self.store.context_review_links(report_id, partition=partition)

    def resolve_finding_reference(self, report_id: UUID, *, partition: str, reference: str) -> str:
        """Resolve immutable report evidence for the future context-review branch."""
        return self.store.get(report_id, partition=partition).content.resolve_finding_reference(reference)

    def resolve_finding_evidence(self, report_id: UUID, *, partition: str, reference: str):
        return self.store.get(report_id, partition=partition).content.resolve_finding_evidence(reference)
