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

    def list_records(self, *, partition: str, statuses=("active",), kind: str | None = None, entity_id=None, query: str = "", limit: int = 100):
        return self.store.list_records(partition=partition, statuses=statuses, kind=kind, entity_id=entity_id, query=query, limit=limit)

    def resolve_entity(self, alias: str):
        return self.store.resolve_entity(alias)

    def entities_mentioned_in(self, text: str):
        return self.store.entities_mentioned_in(text)

    def one_hop_relationships(self, entity_id, *, partition: str):
        return self.store.one_hop_relationships(entity_id, partition=partition)

    def get_entity(self, entity_id, *, include_merged: bool = False):
        return self.store.get_entity(entity_id, include_merged=include_merged)

    def list_entities(self, *, query: str = "", limit: int = 50):
        return self.store.list_entities(query=query, limit=limit)

    def list_entities_in_partition(self, *, partition: str, query: str = "", limit: int = 50):
        return self.store.list_entities_in_partition(partition=partition, query=query, limit=limit)

    def entity_in_partition(self, entity_id, *, partition: str):
        return self.store.entity_in_partition(entity_id, partition=partition)

    def aliases_for_entity(self, entity_id):
        return self.store.aliases_for_entity(entity_id)
