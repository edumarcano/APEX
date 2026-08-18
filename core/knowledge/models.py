"""Typed internal contracts for APEX's source-tracked personal knowledge."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

KnowledgePartition = Literal["production", "sandbox"]
KnowledgeSourceKind = Literal["conversation_message", "manual"]
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


@dataclass(frozen=True, slots=True)
class Entity:
    id: UUID
    name: str
    normalized_name: str
    created_at: str


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
    superseded_by: tuple[UUID, ...] = field(default_factory=tuple)
