"""Read-oriented application service for the future Cortex context features."""

from __future__ import annotations

from core.knowledge.store import KnowledgeStore

_service: "KnowledgeService | None" = None


def set_knowledge_service(service: "KnowledgeService | None") -> None:
    global _service
    _service = service


def get_knowledge_service() -> "KnowledgeService":
    if _service is None:
        raise RuntimeError("Knowledge service is unavailable.")
    return _service


class KnowledgeService:
    """Keeps future callers on a stable domain boundary."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def get_record(self, record_id, *, partition: str):
        return self.store.get_record(record_id, partition=partition)

    def list_records(self, *, partition: str, statuses=("active",), kind: str | None = None, entity_id=None):
        return self.store.list_records(partition=partition, statuses=statuses, kind=kind, entity_id=entity_id)

    def resolve_entity(self, alias: str):
        return self.store.resolve_entity(alias)

    def entities_mentioned_in(self, text: str):
        return self.store.entities_mentioned_in(text)

    def one_hop_relationships(self, entity_id, *, partition: str):
        return self.store.one_hop_relationships(entity_id, partition=partition)
