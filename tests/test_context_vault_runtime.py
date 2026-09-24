from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from uuid import uuid4
from unittest import mock

from core.context_vault.publisher import ContextVaultPublisher
from core.context_vault.runtime import ContextVaultRuntime, ContextVaultRuntimeError
from core.knowledge.service import KnowledgeService
from core.knowledge.store import KnowledgeStore
from core.retrieval.store import RetrievalStore
from core.settings.models import ContextVaultScopeSettings, ContextVaultSettings


class ContextVaultRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="apex_vault_runtime_")
        self.root = Path(self.temp_dir.name)
        self.database_path = self.root / "apex.db"
        self.retrieval = RetrievalStore(self.database_path)
        self.retrieval.initialize()
        self.store = KnowledgeStore(self.database_path)
        self.store.initialize()
        self.knowledge = KnowledgeService(self.store)
        self.entity = self.store.create_entity("Runtime Project")
        self.record = self._create_record("Current claim")
        self.settings = ContextVaultSettings(
            enabled=True,
            scopes=(ContextVaultScopeSettings(
                id=uuid4(), name="Runtime", enabled=True,
                selected_entity_ids=(self.entity.id,),
            ),),
        )
        self.allowed = True
        self.destination = self.root / "vault"
        self.runtime = self._runtime(self.destination)

    def tearDown(self) -> None:
        self.store.close()
        self.retrieval.close()
        self.temp_dir.cleanup()

    def _create_record(self, text: str):
        source = self.store.create_source(
            kind="manual", partition="production", locator=f"manual/{uuid4()}",
            original_text=f"Private source for {text}",
        )
        return self.store.create_record(
            partition="production", kind="note", text=text, source_ids=(source.id,),
            subject_entity_id=self.entity.id if hasattr(self, "entity") else None,
            predicate="has_state" if hasattr(self, "entity") else None,
            object_value="current" if hasattr(self, "entity") else None,
        )

    def _runtime(self, destination: Path | None) -> ContextVaultRuntime:
        return ContextVaultRuntime(
            knowledge=self.knowledge,
            settings_getter=lambda: self.settings,
            database_path=self.database_path,
            destination=destination,
            production_allowed=lambda: self.allowed,
            poll_interval_seconds=0.1,
        )

    async def test_manual_refresh_persists_revision_and_disable_retains_before_removal(self) -> None:
        first = await self.runtime.refresh_now()
        self.assertFalse(first.dirty)
        self.assertEqual(first.exported_revision, first.knowledge_revision)
        self.assertTrue((self.destination / "index.md").exists())
        generated = self.destination / f"scopes/{self.settings.scopes[0].id}/records/{self.record.id}.md"
        self.assertTrue(generated.exists())
        handwritten = self.destination / "handwritten.md"
        handwritten.write_text("Keep", encoding="utf-8")

        with self.assertRaises(ContextVaultRuntimeError) as raised:
            await self.runtime.remove_managed()
        self.assertEqual(raised.exception.code, "disable_export_before_removal")
        self.assertTrue(generated.exists())

        self.settings = ContextVaultSettings(enabled=False, scopes=self.settings.scopes)
        await self.runtime.notify_selection_change()
        disabled = await self.runtime.refresh_now()
        self.assertFalse(disabled.dirty)
        self.assertTrue(generated.exists())
        self.assertTrue((self.destination / "index.md").exists())

        removed = await self.runtime.remove_managed()
        self.assertEqual(removed.owned_file_count, 0)
        self.assertFalse(generated.exists())
        self.assertFalse((self.destination / "index.md").exists())
        self.assertEqual(handwritten.read_text(encoding="utf-8"), "Keep")

    async def test_change_during_publication_keeps_dirty_and_republishes_latest_revision(self) -> None:
        original = ContextVaultPublisher.publish
        created: list[str] = []
        store = self.store

        class MutatingPublisher(ContextVaultPublisher):
            def publish(inner_self, files):
                if not created:
                    new_record = self._create_record("Added during publication")
                    created.append(str(new_record.id))
                return original(inner_self, files)

        with mock.patch("core.context_vault.runtime.ContextVaultPublisher", MutatingPublisher):
            final = await self.runtime.refresh_now()

        self.assertEqual(len(created), 1)
        self.assertFalse(final.dirty)
        self.assertEqual(final.exported_revision, self.store.context_vault_revision())
        new_path = self.destination / f"scopes/{self.settings.scopes[0].id}/records/{created[0]}.md"
        self.assertTrue(new_path.exists())

    async def test_concurrent_manual_refreshes_are_serialized(self) -> None:
        started = threading.Event()
        release = threading.Event()
        guard = threading.Lock()
        active = 0
        maximum_active = 0
        original = ContextVaultPublisher.publish

        class BlockingPublisher(ContextVaultPublisher):
            def publish(inner_self, files):
                nonlocal active, maximum_active
                with guard:
                    active += 1
                    maximum_active = max(maximum_active, active)
                    first = maximum_active == 1 and not started.is_set()
                if first:
                    started.set()
                    if not release.wait(timeout=10):
                        raise TimeoutError("test did not release publication")
                try:
                    return original(inner_self, files)
                finally:
                    with guard:
                        active -= 1

        with mock.patch("core.context_vault.runtime.ContextVaultPublisher", BlockingPublisher):
            first = asyncio.create_task(self.runtime.refresh_now())
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            second = asyncio.create_task(self.runtime.refresh_now())
            release.set()
            first_status, second_status = await asyncio.gather(first, second)

        self.assertLessEqual(maximum_active, 1)
        self.assertFalse(first_status.dirty)
        self.assertFalse(second_status.dirty)

    async def test_runtime_change_reconciles_new_destination_without_deleting_old_copies(self) -> None:
        await self.runtime.refresh_now()
        next_destination = self.root / "next-vault"
        moved = self._runtime(next_destination)

        status = await moved.refresh_now()

        self.assertTrue((self.destination / "index.md").exists())
        self.assertTrue((next_destination / "index.md").exists())
        self.assertIn(str(self.destination), status.retained_destinations)

    async def test_runtime_change_reports_old_destination_while_exports_are_disabled(self) -> None:
        await self.runtime.refresh_now()
        self.settings = ContextVaultSettings(enabled=False, scopes=self.settings.scopes)
        await self.runtime.notify_selection_change()
        next_destination = self.root / "next-vault"

        moved = self._runtime(next_destination)

        self.assertTrue((self.destination / "index.md").exists())
        self.assertFalse(next_destination.exists())
        self.assertIn(str(self.destination), moved.status().retained_destinations)

    async def test_sandbox_restriction_blocks_refresh_and_managed_removal(self) -> None:
        self.allowed = False
        with self.assertRaises(ContextVaultRuntimeError):
            await self.runtime.refresh_now()
        with self.assertRaises(ContextVaultRuntimeError):
            await self.runtime.remove_managed()
        self.assertTrue(self.runtime.status().export_restricted)
        self.assertFalse(self.destination.exists())

    async def test_unavailable_destination_keeps_durable_dirty_error_state(self) -> None:
        blocker = self.root / "file"
        blocker.write_text("not a directory", encoding="utf-8")
        runtime = self._runtime(blocker / "vault")

        status = await runtime.refresh_now()

        self.assertTrue(status.dirty)
        self.assertEqual(status.last_error_code, "unsafe_path")
        self.assertEqual(status.attempt_count, 1)

    async def test_startup_recovers_pending_publication_after_failed_attempt(self) -> None:
        original_write = ContextVaultPublisher._write_if_changed
        writes = 0

        def fail_after_first_write(publisher, relative, text, pending):
            nonlocal writes
            if writes == 1:
                raise OSError("simulated interruption")
            writes += 1
            return original_write(publisher, relative, text, pending)

        with mock.patch.object(
            ContextVaultPublisher, "_write_if_changed", fail_after_first_write,
        ):
            failed = await self.runtime.refresh_now()

        self.assertTrue(failed.dirty)
        self.assertEqual(failed.last_error_code, "publication_failed")
        self.assertTrue(any(self.destination.rglob("*.md")))

        recovered = self._runtime(self.destination)
        published = threading.Event()
        base_publisher = ContextVaultPublisher

        class ObservedPublisher(base_publisher):
            def publish(inner_self, files):
                result = super().publish(files)
                published.set()
                return result

        with mock.patch("core.context_vault.runtime.ContextVaultPublisher", ObservedPublisher):
            task = recovered.start()
            self.assertTrue(await asyncio.to_thread(published.wait, 5))
            recovered.request_stop()
            await asyncio.wait_for(task, timeout=5)

        status = recovered.status()
        self.assertFalse(status.dirty)
        self.assertEqual(status.exported_revision, status.knowledge_revision)
        self.assertEqual(status.last_error_code, None)

    async def test_shutdown_waits_for_in_flight_filesystem_publication(self) -> None:
        started = threading.Event()
        release = threading.Event()
        original = ContextVaultPublisher.publish

        class BlockingPublisher(ContextVaultPublisher):
            def publish(inner_self, files):
                started.set()
                if not release.wait(timeout=10):
                    raise TimeoutError("test did not release publication")
                return original(inner_self, files)

        with mock.patch("core.context_vault.runtime.ContextVaultPublisher", BlockingPublisher):
            task = self.runtime.start()
            self.assertTrue(await asyncio.to_thread(started.wait, 5))
            self.runtime.request_stop()
            self.assertFalse(task.done())
            release.set()
            await asyncio.wait_for(task, timeout=5)

        self.assertEqual(self.runtime.status().exported_revision, self.store.context_vault_revision())


if __name__ == "__main__":
    unittest.main()
