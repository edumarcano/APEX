"""Typed internal contracts for APEX's source-tracked personal knowledge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

KnowledgePartition = Literal["production", "sandbox"]
KnowledgeSourceKind = Literal["conversation_message", "manual"]
KnowledgeSourceOrigin = Literal["operator_input", "connected_service", "external_tool", "unknown"]
KnowledgeDerivation = Literal["direct", "model_interpretation", "unknown"]
KnowledgeKind = Literal[
    "idea", "preference", "decision", "goal", "fact", "constraint", "note", "observation",
]
KnowledgeStatus = Literal["active", "conflicting", "superseded", "retracted"]


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    id: UUID
    kind: KnowledgeSourceKind
    partition: KnowledgePartition
    locator: str
    original_text: str
    content_hash: str
    created_at: str
    origin: KnowledgeSourceOrigin
    occurred_at: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeHistoryEvent:
    id: UUID
    record_id: UUID
    operation: str
    actor: str
    reason_code: str
    related_record_id: UUID | None
    action_id: str | None
    review_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class KnowledgeRecordSource:
    source: KnowledgeSource
    derivation: KnowledgeDerivation
    action_id: str | None
    linked_at: str


@dataclass(frozen=True, slots=True)
class Entity:
    id: UUID
    name: str
    normalized_name: str
    created_at: str
    merged_into_entity_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRecord:
    id: UUID
    partition: KnowledgePartition
    kind: KnowledgeKind
    text: str
    status: KnowledgeStatus
    subject_entity_id: UUID | None
    predicate: str | None
    object_entity_id: UUID | None
    object_value: str | None
    effective_at: str | None
    supersedes_record_id: UUID | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class KnowledgeRecordDetail:
    record: KnowledgeRecord
    sources: tuple[KnowledgeSource, ...] = field(default_factory=tuple)
    source_links: tuple[KnowledgeRecordSource, ...] = field(default_factory=tuple)
    superseded_by: tuple[UUID, ...] = field(default_factory=tuple)
    predecessors: tuple[UUID, ...] = field(default_factory=tuple)
    history: tuple[KnowledgeHistoryEvent, ...] = field(default_factory=tuple)
