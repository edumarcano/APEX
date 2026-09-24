"""Preview canonical production context selected for the local Context vault.

This module only reports selection. File rendering and publication belong to a
later stage and are deliberately outside this service.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from core.knowledge.models import ContextVaultRecordSnapshot, ContextVaultSelectionSnapshot, KnowledgeRecord
from core.knowledge.service import KnowledgeService
from core.settings.models import ContextVaultScopeSettings, ContextVaultSettings


@dataclass(frozen=True, slots=True)
class ContextVaultSelectionIssue:
    entity_id: str
    reason_code: str
    replacement_entity_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContextVaultPreviewRecord:
    record_id: str
    kind: str
    text: str
    status: str
    sensitive: bool
    subject_entity_id: str | None
    predicate: str | None
    object_entity_id: str | None
    object_value: str | None
    eligible: bool
    exclusion_reasons: tuple[str, ...]
    projected_path: str


@dataclass(frozen=True, slots=True)
class ContextVaultPreview:
    scope_id: str
    scope_name: str
    vault_enabled: bool
    scope_enabled: bool
    destination_configured: bool
    records: tuple[ContextVaultPreviewRecord, ...]
    selection_issues: tuple[ContextVaultSelectionIssue, ...]

    @property
    def eligible_count(self) -> int:
        return sum(record.eligible for record in self.records)


@dataclass(frozen=True, slots=True)
class ContextVaultScopeStatus:
    id: str
    name: str
    enabled: bool
    selected_entity_count: int
    record_count: int
    excluded_record_count: int
    include_sensitive: bool


@dataclass(frozen=True, slots=True)
class ContextVaultStatus:
    enabled: bool
    destination_configured: bool
    scopes: tuple[ContextVaultScopeStatus, ...]


@dataclass(frozen=True, slots=True)
class ContextVaultEntityProjection:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ContextVaultScopeProjection:
    """Internal renderer input. It is never included in the preview response."""

    id: str
    name: str
    records: tuple[ContextVaultRecordSnapshot, ...]
    entities: tuple[ContextVaultEntityProjection, ...]


class ContextVaultSelectionService:
    """Resolve scope selections against complete canonical production records."""

    def __init__(
        self,
        knowledge: KnowledgeService,
        settings: ContextVaultSettings,
        *,
        destination_configured: bool,
    ) -> None:
        self._knowledge = knowledge
        self._settings = settings
        self._destination_configured = destination_configured

    def status(self) -> ContextVaultStatus:
        return ContextVaultStatus(
            enabled=self._settings.enabled,
            destination_configured=self._destination_configured,
            scopes=tuple(
                ContextVaultScopeStatus(
                    id=str(scope.id), name=scope.name, enabled=scope.enabled,
                    selected_entity_count=len(scope.selected_entity_ids),
                    record_count=len(scope.record_ids),
                    excluded_record_count=len(scope.excluded_record_ids),
                    include_sensitive=scope.include_sensitive,
                )
                for scope in self._settings.scopes
            ),
        )

    def preview(self, scope_id: UUID) -> ContextVaultPreview:
        scope, snapshot = self._scope_snapshot(scope_id)
        entity_states = dict(snapshot.entity_states)
        selection_issues = tuple(
            ContextVaultSelectionIssue(
                entity_id=str(entity_id),
                reason_code=(
                    "entity_merged_requires_reselection"
                    if entity_states[str(entity_id)] is not None
                    else "entity_unavailable"
                ),
                replacement_entity_id=entity_states[str(entity_id)],
            )
            for entity_id in scope.selected_entity_ids
            if str(entity_id) not in entity_states or entity_states[str(entity_id)] is not None
        )

        preview_records = tuple(
            self._preview_record(
                item.record,
                vault_enabled=self._settings.enabled,
                scope=scope,
                is_pending=item.pending_review,
                operator_excluded=item.operator_excluded,
            )
            for item in snapshot.records
        )
        return ContextVaultPreview(
            scope_id=str(scope.id), scope_name=scope.name,
            vault_enabled=self._settings.enabled, scope_enabled=scope.enabled,
            destination_configured=self._destination_configured,
            records=preview_records, selection_issues=selection_issues,
        )

    @property
    def vault_enabled(self) -> bool:
        """Whether the saved global setting permits this service to publish."""
        return self._settings.enabled

    def export_scope(self, scope_id: UUID) -> ContextVaultScopeProjection:
        """Return eligible production records and their entity names for rendering."""
        scope, snapshot = self._scope_snapshot(scope_id)
        selected_records = tuple(
            item for item in snapshot.records
            if self._is_export_eligible(item, vault_enabled=self._settings.enabled, scope=scope)
        )
        entity_ids = {
            str(identifier)
            for item in selected_records
            for identifier in (item.record.subject_entity_id, item.record.object_entity_id)
            if identifier is not None
        }
        entity_names = dict(snapshot.entity_names)
        entities = tuple(
            ContextVaultEntityProjection(id=entity_id, name=entity_names[entity_id])
            for entity_id in sorted(entity_ids)
            if entity_id in entity_names
        )
        return ContextVaultScopeProjection(
            id=str(scope.id), name=scope.name, records=selected_records, entities=entities,
        )

    def export_enabled_scopes(self) -> tuple[ContextVaultScopeProjection, ...]:
        """Return enabled scopes only when the vault itself is enabled."""
        if not self._settings.enabled:
            return ()
        return tuple(
            self.export_scope(scope.id)
            for scope in self._settings.scopes
            if scope.enabled
        )

    def _scope_snapshot(
        self,
        scope_id: UUID,
    ) -> tuple[ContextVaultScopeSettings, ContextVaultSelectionSnapshot]:
        scope = next((candidate for candidate in self._settings.scopes if candidate.id == scope_id), None)
        if scope is None:
            raise KeyError("context_vault_scope_not_found")
        snapshot = self._knowledge.context_vault_selection_snapshot(
            selected_entity_ids=scope.selected_entity_ids,
            record_ids=scope.record_ids,
            excluded_record_ids=scope.excluded_record_ids,
        )
        return scope, snapshot

    @staticmethod
    def _is_export_eligible(
        item: ContextVaultRecordSnapshot,
        *,
        vault_enabled: bool,
        scope: ContextVaultScopeSettings,
    ) -> bool:
        record = item.record
        return (
            vault_enabled
            and scope.enabled
            and record.partition == "production"
            and record.status == "active"
            and not item.pending_review
            and not item.operator_excluded
            and (not record.sensitive or scope.include_sensitive)
        )

    @staticmethod
    def _preview_record(
        record: KnowledgeRecord,
        *,
        vault_enabled: bool,
        scope: ContextVaultScopeSettings,
        is_pending: bool,
        operator_excluded: bool,
    ) -> ContextVaultPreviewRecord:
        reasons: list[str] = []
        if not vault_enabled:
            reasons.append("vault_disabled")
        if not scope.enabled:
            reasons.append("scope_disabled")
        if record.status != "active":
            reasons.append(record.status)
        if is_pending:
            reasons.append("pending_review")
        if record.sensitive and not scope.include_sensitive:
            reasons.append("sensitive")
        if operator_excluded:
            reasons.append("operator_excluded")
        return ContextVaultPreviewRecord(
            record_id=str(record.id), kind=record.kind, text=record.text,
            status=record.status, sensitive=record.sensitive,
            subject_entity_id=str(record.subject_entity_id) if record.subject_entity_id else None,
            predicate=record.predicate,
            object_entity_id=str(record.object_entity_id) if record.object_entity_id else None,
            object_value=record.object_value,
            eligible=not reasons, exclusion_reasons=tuple(reasons),
            projected_path=f"records/{record.id}.md",
        )
