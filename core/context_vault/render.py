"""Deterministic, privacy-limited Markdown projection for the Context vault."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from uuid import UUID

from core.context_vault.selection import ContextVaultEntityProjection, ContextVaultScopeProjection
from core.knowledge.models import ContextVaultRecordSnapshot


def _id(value: str) -> str:
    return str(UUID(value))


def _text(value: str | None) -> str:
    """Render one line of untrusted text without Markdown links or block syntax."""
    if value is None:
        return ""
    normalized = " ".join(str(value).split())
    # Escaping Markdown punctuation blocks links, embeds, headings, and code
    # delimiters. Escaped colons also prevent automatic URL links.
    return re.sub(r"([\\`*_{}\[\]()<>#+\-.!|~:$?@&;])", r"\\\1", normalized)


def _yaml_string(value: str | None) -> str:
    # JSON strings are valid YAML scalars and escape all user-controlled
    # newlines, quotes, and metadata delimiters on one line.
    return json.dumps(value, ensure_ascii=False)


class ContextVaultMarkdownRenderer:
    """Build one root note and self-contained notes for each selected scope."""

    def render(self, scopes: Iterable[ContextVaultScopeProjection]) -> dict[str, str]:
        ordered_scopes = tuple(sorted(scopes, key=lambda scope: _id(scope.id)))
        files: dict[str, str] = {"index.md": self._render_root(ordered_scopes)}
        for scope in ordered_scopes:
            scope_id = _id(scope.id)
            scope_path = f"scopes/{scope_id}"
            files[f"{scope_path}/index.md"] = self._render_scope_index(scope)

            entities = {_id(entity.id): entity for entity in scope.entities}
            records = tuple(sorted(
                scope.records,
                key=lambda item: (item.record.updated_at, str(item.record.id)),
                reverse=True,
            ))
            for entity_id, entity in sorted(entities.items()):
                files[f"{scope_path}/entities/{entity_id}.md"] = self._render_entity(
                    entity_id, entity.name, records, entities,
                )
            for item in records:
                record_id = _id(str(item.record.id))
                files[f"{scope_path}/records/{record_id}.md"] = self._render_record(
                    item, entities,
                )
        return files

    @staticmethod
    def _render_root(scopes: tuple[ContextVaultScopeProjection, ...]) -> str:
        lines = [
            "# APEX Context vault",
            "",
            "This vault contains generated copies of selected, current APEX context.",
            "APEX remains the canonical source; editing these notes does not update APEX.",
            "",
            "## File ownership",
            "",
            "APEX owns this `index.md` and notes at `scopes/<scope-id>/index.md`, "
            "`scopes/<scope-id>/entities/<entity-id>.md`, and "
            "`scopes/<scope-id>/records/<record-id>.md`. It regenerates edited owned "
            "notes on refresh and removes obsolete owned notes. Other files, including "
            "handwritten notes and `.obsidian/`, are left alone. A file already at an "
            "APEX-owned path is not adopted unless its ownership is recorded locally.",
            "",
            "## Scopes",
            "",
        ]
        if not scopes:
            lines.append("No enabled scopes are currently exported.")
        for scope in scopes:
            scope_id = _id(scope.id)
            lines.append(f"- [{_text(scope.name)}](scopes/{scope_id}/index.md)")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _render_scope_index(scope: ContextVaultScopeProjection) -> str:
        records = tuple(sorted(
            scope.records,
            key=lambda item: (item.record.updated_at, str(item.record.id)),
            reverse=True,
        ))
        entities = tuple(sorted(scope.entities, key=lambda entity: (_text(entity.name).casefold(), entity.id)))
        lines = [f"# {_text(scope.name)}", "", "This scope contains only its own selected APEX records.", ""]
        lines.extend(["## Entities", ""])
        if entities:
            lines.extend(
                f"- [{_text(entity.name)}](entities/{_id(entity.id)}.md)"
                for entity in entities
            )
        else:
            lines.append("No entities are linked to eligible records.")
        lines.extend(["", "## Records", ""])
        if records:
            lines.extend(
                f"- [{_text(item.record.kind)} · {_id(str(item.record.id))[:8]}]"
                f"(records/{_id(str(item.record.id))}.md)"
                for item in records
            )
        else:
            lines.append("No eligible records are selected.")
        return "\n".join(lines) + "\n"

    @classmethod
    def _render_record(
        cls,
        item: ContextVaultRecordSnapshot,
        entities: dict[str, ContextVaultEntityProjection],
    ) -> str:
        record = item.record
        record_id = _id(str(record.id))
        subject_id = _id(str(record.subject_entity_id)) if record.subject_entity_id else None
        object_id = _id(str(record.object_entity_id)) if record.object_entity_id else None
        metadata = []
        for link in item.source_metadata:
            source = link.source
            metadata.append({
                "id": str(source.id),
                "kind": source.kind,
                "origin": source.origin,
                "derivation": link.derivation,
            })
        metadata.sort(key=lambda source: (source["id"], source["kind"], source["origin"], source["derivation"]))
        lines = [
            "---",
            f"apex_record_id: {_yaml_string(record_id)}",
            f"kind: {_yaml_string(record.kind)}",
            f"effective_at: {_yaml_string(record.effective_at)}",
            f"updated_at: {_yaml_string(item.updated_at)}",
            f"source_ids: {json.dumps([source['id'] for source in metadata], ensure_ascii=False)}",
            f"sources: {json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))}",
            "---",
            "",
            f"# {_text(record.kind)} · {record_id[:8]}",
            "",
            "## Current APEX record",
            "",
            _text(record.text),
            "",
            "## Relationship",
            "",
        ]
        if subject_id is None and object_id is None:
            lines.append("This record has no structured entity relationship.")
        else:
            subject_label = cls._entity_link(subject_id, entities, prefix="../entities/") if subject_id else "(none)"
            predicate = _text(record.predicate)
            if object_id:
                object_label = cls._entity_link(object_id, entities, prefix="../entities/")
            else:
                object_label = _text(record.object_value) or "(empty value)"
            lines.append(f"Recorded relationship: {subject_label} — {predicate} → {object_label}.")
        lines.extend([
            "",
            "## APEX record",
            "",
            f"Record ID: `{record_id}`",
            f"Updated: {_yaml_string(item.updated_at)}",
            f"Effective: {_yaml_string(record.effective_at)}",
            f"[Inspect this record in APEX](http://127.0.0.1:8000/api/v1/cortex/context/{record_id})",
            "",
        ])
        return "\n".join(lines)

    @classmethod
    def _render_entity(
        cls,
        entity_id: str,
        entity_name: str,
        records: tuple[ContextVaultRecordSnapshot, ...],
        entities: dict[str, ContextVaultEntityProjection],
    ) -> str:
        lines = [
            f"# {_text(entity_name)}",
            "",
            f"Entity ID: `{entity_id}`",
            "",
            "## Relationships in this scope",
            "",
        ]
        found = False
        for item in records:
            record = item.record
            record_id = _id(str(record.id))
            predicate = _text(record.predicate)
            record_link = f"[record {record_id[:8]}](../records/{record_id}.md)"
            subject_id = _id(str(record.subject_entity_id)) if record.subject_entity_id else None
            object_id = _id(str(record.object_entity_id)) if record.object_entity_id else None
            if subject_id == entity_id:
                found = True
                if object_id:
                    value = cls._entity_link(object_id, entities, prefix="../entities/")
                else:
                    value = _text(record.object_value) or "(empty value)"
                lines.append(f"- Named as the subject in {record_link}: {predicate} → {value}.")
            if object_id == entity_id:
                found = True
                subject = cls._entity_link(subject_id, entities, prefix="../entities/") if subject_id else "(none)"
                lines.append(f"- Named as the object in {record_link}: {subject} — {predicate} → this entity.")
        if not found:
            lines.append("No eligible record in this scope refers to this entity.")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _entity_link(
        entity_id: str | None,
        entities: dict[str, ContextVaultEntityProjection],
        *,
        prefix: str,
    ) -> str:
        if entity_id is None:
            return "(none)"
        entity = entities.get(entity_id)
        if entity is None:
            return f"entity `{entity_id}`"
        return f"[{_text(entity.name)}]({prefix}{entity_id}.md)"
