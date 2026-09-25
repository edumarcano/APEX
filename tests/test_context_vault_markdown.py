from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from core.context_vault.publisher import (
    ContextVaultPublicationError,
    ContextVaultPublicationStateStore,
    ContextVaultPublisher,
)
from core.context_vault.render import ContextVaultMarkdownRenderer
from core.context_vault.selection import ContextVaultSelectionService
from core.context_vault.service import compare_scope_projection
from core.knowledge.service import KnowledgeService
from core.knowledge.store import KnowledgeStore
from core.retrieval.store import RetrievalStore
from core.settings.models import ContextVaultScopeSettings, ContextVaultSettings


class ContextVaultMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="apex_vault_markdown_")
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / "apex.db"
        self.retrieval = RetrievalStore(self.database_path)
        self.retrieval.initialize()
        self.store = KnowledgeStore(self.database_path)
        self.store.initialize()
        self.knowledge = KnowledgeService(self.store)
        self.renderer = ContextVaultMarkdownRenderer()

    def tearDown(self) -> None:
        self.store.close()
        self.retrieval.close()
        self.temp_dir.cleanup()

    def _record(
        self,
        *,
        entity_id: UUID,
        text: str,
        source_text: str = "Private evidence text",
        locator: str = "file:///C:/private/source.md",
        predicate: str = "includes",
        object_value: str = "Launch plan",
    ):
        source = self.store.create_source(
            kind="external_activity",
            partition="production",
            locator=locator,
            original_text=source_text,
            origin="connected_service",
        )
        record = self.store.create_record(
            partition="production",
            kind="decision",
            text=text,
            source_ids=(source.id,),
            subject_entity_id=entity_id,
            predicate=predicate,
            object_value=object_value,
        )
        return record, source

    @staticmethod
    def _service(knowledge, *scopes, enabled: bool = True):
        return ContextVaultSelectionService(
            knowledge,
            ContextVaultSettings(enabled=enabled, scopes=tuple(scopes)),
            destination_configured=True,
        )

    def _projection(self, scope_id: UUID, record_id: UUID) -> dict[str, str]:
        return {
            "index.md": "# APEX Context vault\n",
            f"scopes/{scope_id}/index.md": "# Project\n",
            f"scopes/{scope_id}/records/{record_id}.md": "# Record\n",
        }

    def _publisher(self, name: str = "vault") -> ContextVaultPublisher:
        return ContextVaultPublisher(self.root / name, self.database_path)

    def test_renderer_is_deterministic_and_keeps_links_inside_each_scope(self) -> None:
        subject = self.store.create_entity("Project Northstar")
        object_entity = self.store.create_entity("Budget Review")
        source = self.store.create_source(
            kind="manual", partition="production", locator="manual/relationship",
            original_text="Private source detail", origin="operator_input",
        )
        record = self.store.create_record(
            partition="production", kind="fact", text="The project needs review.",
            source_ids=(source.id,), subject_entity_id=subject.id,
            predicate="requires", object_entity_id=object_entity.id,
        )
        first_scope = ContextVaultScopeSettings(
            id=uuid4(), name="Northstar", enabled=True, record_ids=(record.id,),
        )
        second_scope = ContextVaultScopeSettings(
            id=uuid4(), name="Finance", enabled=True, record_ids=(record.id,),
        )
        selection = self._service(self.knowledge, second_scope, first_scope)
        first = selection.export_enabled_scopes()
        files = self.renderer.render(first)

        self.assertEqual(files, self.renderer.render(first))
        record_note = files[f"scopes/{first_scope.id}/records/{record.id}.md"]
        self.assertIn(f"../entities/{subject.id}.md", record_note)
        self.assertIn(f"../entities/{object_entity.id}.md", record_note)
        self.assertIn("Recorded relationship:", record_note)
        self.assertIn("— requires →", record_note)
        self.assertIn(f"records/{record.id}.md", files[f"scopes/{first_scope.id}/index.md"])
        self.assertIn(f"records/{record.id}.md", files[f"scopes/{second_scope.id}/index.md"])
        self.assertIn("scopes/", files["index.md"])
        self.assertNotIn(f"scopes/{second_scope.id}", files[f"scopes/{first_scope.id}/index.md"])
        self.assertNotIn(f"scopes/{first_scope.id}", files[f"scopes/{second_scope.id}/index.md"])

    def test_export_omits_source_payload_and_escapes_claim_text(self) -> None:
        entity = self.store.create_entity("Research Project")
        claim = "# forged\n---\nsource_url: https://secret.invalid ![[hidden]] [click](https://secret.invalid) <iframe>"
        record, source = self._record(
            entity_id=entity.id,
            text=claim,
            source_text="Raw evidence must stay local",
            locator="C:\\Users\\person\\private\\source.md https://private.invalid",
        )
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Research", enabled=True, record_ids=(record.id,),
        )
        service = self._service(self.knowledge, scope)
        projection = self.renderer.render(service.export_enabled_scopes())
        exported = "\n".join(projection.values())
        note = projection[f"scopes/{scope.id}/records/{record.id}.md"]
        preview = service.preview(scope.id)

        self.assertIn(str(source.id), note)
        self.assertIn('"kind":"external_activity"', note)
        self.assertIn('"origin":"connected_service"', note)
        self.assertIn('"derivation":"unknown"', note)
        self.assertIn("Inspect this record in APEX", note)
        self.assertNotIn("Raw evidence must stay local", exported)
        self.assertNotIn("C:\\Users\\person\\private\\source.md", exported)
        self.assertNotIn("private.invalid", exported)
        self.assertNotIn("secret.invalid)", exported)
        self.assertNotIn("![[hidden]]", exported)
        self.assertNotIn("source_url:", exported)
        self.assertIn(r"\# forged", note)
        self.assertIn(r"\!\[\[hidden\]\]", note)
        self.assertIn(r"\[click\]\(https\://secret\.invalid\)", note)
        self.assertNotIn("Raw evidence must stay local", repr(preview))
        self.assertFalse(hasattr(preview.records[0], "source_metadata"))

    def test_export_contains_only_current_eligible_records(self) -> None:
        entity = self.store.create_entity("Eligibility Project")
        active, _ = self._record(entity_id=entity.id, text="Eligible claim")
        conflicting, _ = self._record(entity_id=entity.id, text="Conflicting claim")
        sensitive, _ = self._record(entity_id=entity.id, text="Sensitive claim")
        pending, _ = self._record(entity_id=entity.id, text="Pending claim")
        excluded, _ = self._record(entity_id=entity.id, text="Excluded claim")
        self.store.set_status(conflicting.id, partition="production", status="conflicting")
        current_sensitive = self.store.set_sensitive(
            sensitive.id, partition="production", sensitive=True,
            expected_updated_at=sensitive.updated_at,
        )
        self.store.create_review(
            partition="production", operation="retract",
            proposal={"record_id": str(pending.id)}, evidence={},
            expected_revisions={str(pending.id): pending.updated_at},
            reason_codes=("operator_review",),
        )
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Eligibility", enabled=True,
            selected_entity_ids=(entity.id,), excluded_record_ids=(excluded.id,),
        )

        projection = self.renderer.render(self._service(self.knowledge, scope).export_enabled_scopes())
        scope_files = {path for path in projection if path.startswith(f"scopes/{scope.id}/")}

        self.assertIn(f"scopes/{scope.id}/records/{active.id}.md", scope_files)
        self.assertNotIn(f"scopes/{scope.id}/records/{conflicting.id}.md", scope_files)
        self.assertNotIn(f"scopes/{scope.id}/records/{current_sensitive.id}.md", scope_files)
        self.assertNotIn(f"scopes/{scope.id}/records/{pending.id}.md", scope_files)
        self.assertNotIn(f"scopes/{scope.id}/records/{excluded.id}.md", scope_files)

    def test_preview_diff_reports_modified_notes_and_removed_excluded_or_retracted_records(self) -> None:
        entity = self.store.create_entity("Projection Project")
        record, _ = self._record(entity_id=entity.id, text="Original claim")
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Projection", enabled=True,
            selected_entity_ids=(entity.id,), include_sensitive=True,
        )
        selection = self._service(self.knowledge, scope)
        first_preview = selection.preview(scope.id)
        assert first_preview.scope_projection is not None
        publisher = self._publisher("projection-vault")
        publisher.publish(self.renderer.render((first_preview.scope_projection,)))
        baseline = dict(publisher.state().owned_files)

        current = self.store.get_record(record.id, partition="production").record
        self.store.set_sensitive(
            record.id, partition="production", sensitive=True,
            expected_updated_at=current.updated_at,
        )
        updated_preview = self._service(self.knowledge, scope).preview(scope.id)
        updated = compare_scope_projection(
            self.renderer, scope_id=str(scope.id), projections=updated_preview.comparison_projections,
            owned_file_hashes=baseline,
        )
        self.assertEqual(updated.state, "compared")
        self.assertIn(
            (f"scopes/{scope.id}/records/{record.id}.md", "updated"),
            tuple((change.path, change.action) for change in updated.changes),
        )

        renamed_scope = scope.model_copy(update={"name": "Renamed projection"})
        renamed_preview = selection.preview_candidate(renamed_scope)
        renamed = compare_scope_projection(
            self.renderer, scope_id=str(scope.id), projections=renamed_preview.comparison_projections,
            owned_file_hashes=baseline,
        )
        self.assertIn(("index.md", "updated"), tuple((change.path, change.action) for change in renamed.changes))
        self.assertIn(
            (f"scopes/{scope.id}/index.md", "updated"),
            tuple((change.path, change.action) for change in renamed.changes),
        )

        excluded_scope = scope.model_copy(update={"excluded_record_ids": (record.id,)})
        excluded_preview = self._service(self.knowledge, excluded_scope).preview(scope.id)
        excluded = compare_scope_projection(
            self.renderer, scope_id=str(scope.id), projections=excluded_preview.comparison_projections,
            owned_file_hashes=baseline,
        )
        excluded_changes = {(change.path, change.action) for change in excluded.changes}
        self.assertIn((f"scopes/{scope.id}/records/{record.id}.md", "removed"), excluded_changes)
        self.assertIn((f"scopes/{scope.id}/entities/{entity.id}.md", "removed"), excluded_changes)
        self.assertIn((f"scopes/{scope.id}/index.md", "updated"), excluded_changes)

        self.store.set_status(record.id, partition="production", status="retracted")
        retracted_preview = self._service(self.knowledge, scope).preview(scope.id)
        retracted = compare_scope_projection(
            self.renderer, scope_id=str(scope.id), projections=retracted_preview.comparison_projections,
            owned_file_hashes=baseline,
        )
        self.assertIn(
            (f"scopes/{scope.id}/records/{record.id}.md", "removed"),
            tuple((change.path, change.action) for change in retracted.changes),
        )

    def test_preview_diff_marks_new_scope_and_absent_export_baseline_as_additions(self) -> None:
        entity = self.store.create_entity("New projection project")
        record, _ = self._record(entity_id=entity.id, text="New claim")
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="New scope", enabled=True, record_ids=(record.id,),
        )
        preview = self._service(self.knowledge, scope).preview_candidate(scope)
        assert preview.scope_projection is not None
        additions = compare_scope_projection(
            self.renderer, scope_id=str(scope.id), projections=preview.comparison_projections,
            owned_file_hashes=None,
        )
        self.assertEqual(additions.state, "no_prior_export")
        self.assertTrue(additions.changes)
        self.assertTrue(all(change.action == "added" for change in additions.changes))
        self.assertIn("index.md", {change.path for change in additions.changes})

        existing = self._publisher("other-scope-vault")
        existing.publish({"index.md": "# Prior export\n"})
        baseline = dict(existing.state().owned_files)
        new_scope = compare_scope_projection(
            self.renderer, scope_id=str(scope.id), projections=preview.comparison_projections,
            owned_file_hashes=baseline,
        )
        self.assertEqual(new_scope.state, "compared")
        self.assertTrue(new_scope.changes)
        self.assertIn(("index.md", "updated"), tuple((change.path, change.action) for change in new_scope.changes))
        self.assertTrue(all(
            change.action == "added" for change in new_scope.changes if change.path != "index.md"
        ))

    def test_reading_absent_publisher_state_does_not_create_a_baseline_table(self) -> None:
        state = ContextVaultPublicationStateStore.read_last_successful_projection(
            self.database_path, str(self.root / "unpublished-vault"),
        )
        self.assertIsNone(state)
        connection = sqlite3.connect(self.database_path)
        try:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='context_vault_publication_state'",
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(exists)

    def test_publisher_is_noop_for_unchanged_notes_and_preserves_mtimes(self) -> None:
        scope_id, record_id = uuid4(), uuid4()
        files = self._projection(scope_id, record_id)
        publisher = self._publisher()
        first = publisher.publish(files)
        path = self.root / "vault" / f"scopes/{scope_id}/records/{record_id}.md"
        original_mtime = path.stat().st_mtime_ns

        second = publisher.publish(files)

        self.assertEqual(first.changed_file_count, len(files))
        self.assertEqual(second.changed_file_count, 0)
        self.assertEqual(path.stat().st_mtime_ns, original_mtime)
        self.assertFalse(publisher.state().pending)

    def test_publisher_removes_obsolete_owned_files_and_preserves_handwritten_files(self) -> None:
        scope_id, record_id = uuid4(), uuid4()
        publisher = self._publisher()
        first_files = self._projection(scope_id, record_id)
        publisher.publish(first_files)
        vault = self.root / "vault"
        handwritten = vault / "handwritten.md"
        obsidian_settings = vault / ".obsidian" / "app.json"
        unknown_scope_note = vault / f"scopes/{scope_id}/records/handwritten.md"
        handwritten.write_text("Keep this note", encoding="utf-8")
        obsidian_settings.parent.mkdir(parents=True)
        obsidian_settings.write_text("{}", encoding="utf-8")
        unknown_scope_note.write_text("Keep this too", encoding="utf-8")
        owned = vault / f"scopes/{scope_id}/records/{record_id}.md"
        owned.write_text("Hand-edited generated note", encoding="utf-8")

        publisher.publish(first_files)
        self.assertEqual(owned.read_text(encoding="utf-8"), first_files[f"scopes/{scope_id}/records/{record_id}.md"])
        owned.write_text("Hand-edited generated note", encoding="utf-8")

        result = publisher.publish({"index.md": "# Updated\n"})

        self.assertFalse(owned.exists())
        self.assertEqual(handwritten.read_text(encoding="utf-8"), "Keep this note")
        self.assertEqual(obsidian_settings.read_text(encoding="utf-8"), "{}")
        self.assertEqual(unknown_scope_note.read_text(encoding="utf-8"), "Keep this too")
        self.assertEqual(result.removed_file_count, len(first_files) - 1)

    def test_remove_managed_copies_leaves_handwritten_files_and_vault_directories(self) -> None:
        scope_id, record_id = uuid4(), uuid4()
        publisher = self._publisher()
        files = self._projection(scope_id, record_id)
        publisher.publish(files)
        vault = self.root / "vault"
        handwritten = vault / "handwritten.md"
        obsidian_settings = vault / ".obsidian" / "app.json"
        handwritten.write_text("Keep this note", encoding="utf-8")
        obsidian_settings.parent.mkdir(parents=True)
        obsidian_settings.write_text("{}", encoding="utf-8")
        owned_path = vault / f"scopes/{scope_id}/records/{record_id}.md"
        owned_path.write_text("Edited generated note", encoding="utf-8")

        result = publisher.remove_managed()

        self.assertEqual(result.removed_file_count, len(files))
        self.assertFalse((vault / "index.md").exists())
        self.assertFalse(owned_path.exists())
        self.assertTrue((vault / f"scopes/{scope_id}/records").is_dir())
        self.assertEqual(handwritten.read_text(encoding="utf-8"), "Keep this note")
        self.assertEqual(obsidian_settings.read_text(encoding="utf-8"), "{}")
        self.assertEqual(publisher.state().owned_files, ())
        self.assertFalse(publisher.state().pending)

    def test_unowned_collisions_and_unsafe_paths_are_rejected(self) -> None:
        scope_id, record_id = uuid4(), uuid4()
        publisher = self._publisher()
        vault = self.root / "vault"
        collision = vault / f"scopes/{scope_id}/records/{record_id}.md"
        collision.parent.mkdir(parents=True)
        collision.write_text("Handwritten claim", encoding="utf-8")

        with self.assertRaises(ContextVaultPublicationError) as collision_error:
            publisher.publish(self._projection(scope_id, record_id))
        self.assertEqual(collision_error.exception.code, "unowned_collision")
        self.assertEqual(collision.read_text(encoding="utf-8"), "Handwritten claim")

        with self.assertRaises(ContextVaultPublicationError) as traversal_error:
            publisher.publish({"index.md": "# APEX\n", "../secret.md": "private"})
        self.assertEqual(traversal_error.exception.code, "unsafe_path")
        self.assertFalse((self.root / "secret.md").exists())

    def test_symlinked_generated_directory_is_rejected(self) -> None:
        scope_id, record_id = uuid4(), uuid4()
        vault = self.root / "vault"
        (vault / "scopes").mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        link = vault / f"scopes/{scope_id}"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        with self.assertRaises(ContextVaultPublicationError) as error:
            self._publisher().publish(self._projection(scope_id, record_id))
        self.assertEqual(error.exception.code, "unsafe_path")
        self.assertEqual(list(outside.iterdir()), [])

    def test_interrupted_publication_keeps_pending_work_and_retry_completes(self) -> None:
        subject = self.store.create_entity("Retry Project")
        record, _ = self._record(entity_id=subject.id, text="Retryable claim")
        scope = ContextVaultScopeSettings(
            id=uuid4(), name="Retry", enabled=True, record_ids=(record.id,),
        )
        files = self.renderer.render(self._service(self.knowledge, scope).export_enabled_scopes())
        state_path = self.database_path
        failing_target = f"scopes/{scope.id}/records/{record.id}.md"

        class InterruptingPublisher(ContextVaultPublisher):
            failed = False

            def _atomic_replace(self, source: Path, target: Path) -> None:
                if target.as_posix().endswith(failing_target) and not self.failed:
                    self.failed = True
                    raise OSError("injected interruption")
                super()._atomic_replace(source, target)

        publisher = InterruptingPublisher(self.root / "vault", state_path)
        with self.assertRaises(ContextVaultPublicationError):
            publisher.publish(files)
        self.assertTrue(publisher.state().pending)
        self.assertFalse((self.root / "vault" / "index.md").exists())

        # Pending state contains only paths and hashes, not canonical or source text.
        conn = sqlite3.connect(state_path)
        try:
            pending_json = conn.execute(
                "SELECT pending_json FROM context_vault_publication_state"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertNotIn("Retryable claim", pending_json)
        self.assertNotIn("Private evidence text", pending_json)
        result = self._publisher().publish(files)

        self.assertEqual(result.owned_file_count, len(files))
        self.assertFalse(self._publisher().state().pending)
        self.assertTrue((self.root / "vault" / "index.md").exists())
        self.assertEqual(
            (self.root / "vault" / failing_target).read_text(encoding="utf-8"),
            files[failing_target],
        )

    def test_republication_retains_removed_ownership_after_multiple_interruptions(self) -> None:
        scope_id, previous_record_id, retry_record_id = uuid4(), uuid4(), uuid4()
        previous_record = f"scopes/{scope_id}/records/{previous_record_id}.md"
        retry_record = f"scopes/{scope_id}/records/{retry_record_id}.md"
        previous_files = {
            "index.md": "# APEX Context vault\n",
            f"scopes/{scope_id}/index.md": "# Previous scope\n",
            previous_record: "# Previous record\n",
        }

        class InterruptBeforeRootIndex(ContextVaultPublisher):
            def _atomic_replace(self, source: Path, target: Path) -> None:
                if target.relative_to(self._root).as_posix() == "index.md":
                    raise OSError("interrupt before root index")
                super()._atomic_replace(source, target)

        with self.assertRaises(ContextVaultPublicationError):
            InterruptBeforeRootIndex(self.root / "vault", self.database_path).publish(previous_files)

        previous_record_path = self.root / "vault" / previous_record
        self.assertTrue(previous_record_path.exists())
        retry_files = {
            "index.md": "# APEX Context vault after deselection\n",
            retry_record: "# Retry record\n",
        }

        class InterruptBeforeRetryRecord(ContextVaultPublisher):
            def _atomic_replace(self, source: Path, target: Path) -> None:
                if target.relative_to(self._root).as_posix() == retry_record:
                    raise OSError("interrupt before retry record")
                super()._atomic_replace(source, target)

        with self.assertRaises(ContextVaultPublicationError):
            InterruptBeforeRetryRecord(self.root / "vault", self.database_path).publish(retry_files)

        handwritten_retry_path = self.root / "vault" / retry_record
        handwritten_retry_path.parent.mkdir(parents=True, exist_ok=True)
        handwritten_retry_path.write_text("Handwritten note", encoding="utf-8")

        result = self._publisher().remove_managed()

        self.assertEqual(result.removed_file_count, 2)
        self.assertFalse(previous_record_path.exists())
        self.assertFalse((self.root / "vault" / f"scopes/{scope_id}/index.md").exists())
        self.assertEqual(handwritten_retry_path.read_text(encoding="utf-8"), "Handwritten note")
        self.assertEqual(self._publisher().state().owned_files, ())
        self.assertFalse(self._publisher().state().pending)

    def test_pending_intent_does_not_claim_or_delete_unwritten_paths(self) -> None:
        scope_id, record_id = uuid4(), uuid4()
        files = self._projection(scope_id, record_id)

        class FailingBeforeFirstWrite(ContextVaultPublisher):
            def _atomic_replace(self, source: Path, target: Path) -> None:
                raise OSError("interrupt before first target write")

        publisher = FailingBeforeFirstWrite(self.root / "vault", self.database_path)
        with self.assertRaises(ContextVaultPublicationError):
            publisher.publish(files)
        self.assertTrue(publisher.state().pending)

        record_path = self.root / "vault" / f"scopes/{scope_id}/records/{record_id}.md"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text("Handwritten note", encoding="utf-8")
        with self.assertRaises(ContextVaultPublicationError) as collision:
            publisher.publish(files)
        self.assertEqual(collision.exception.code, "unowned_collision")

        # If the record is deselected after the interrupted attempt, pending
        # intent still cannot authorize deleting that handwritten file.
        self._publisher().publish({"index.md": "# APEX Context vault\n"})

        self.assertEqual(record_path.read_text(encoding="utf-8"), "Handwritten note")
        self.assertFalse(self._publisher().state().pending)

    def test_indexes_are_written_after_notes(self) -> None:
        scope_id, record_id = uuid4(), uuid4()
        files = self._projection(scope_id, record_id)

        class TrackingPublisher(ContextVaultPublisher):
            replacements: list[str]

            def __init__(self, destination, state_database_path):
                super().__init__(destination, state_database_path)
                self.replacements = []

            def _atomic_replace(self, source: Path, target: Path) -> None:
                self.replacements.append(target.relative_to(self._root).as_posix())
                super()._atomic_replace(source, target)

        publisher = TrackingPublisher(self.root / "vault", self.database_path)
        publisher.publish(files)

        self.assertEqual(publisher.replacements[-2:], [f"scopes/{scope_id}/index.md", "index.md"])


if __name__ == "__main__":
    unittest.main()
