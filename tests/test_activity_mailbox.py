"""Focused coverage for the optional local activity-folder mailbox."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core.activity import ActivityClientRegistration, ActivityReportContent, ActivityService, ActivityStore
from core.activity.mailbox import ActivityMailbox, run_activity_mailbox_poller
from core.settings.models import SettingsPatch
from core.settings.store import RuntimeSettingsStore


def registration(*, enabled: bool = True, partition: str = "production", permissions=("activity:submit",), principals=("operator",)):
    return ActivityClientRegistration(
        id="codex",
        display_name="Codex",
        enabled=enabled,
        allowed_principals=list(principals),
        permissions=frozenset(permissions),
        partition=partition,
    )


def report(*, key: str = "report-1", outcome: str = "Done") -> ActivityReportContent:
    return ActivityReportContent(
        submission_key=key,
        title="Completed work",
        task_status="completed",
        outcome=outcome,
        findings=[{"text": "The task completed."}],
    )


class ActivityMailboxTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="apex_activity_mailbox_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "mailbox"
        self.folder.mkdir()
        self.settings_store = RuntimeSettingsStore(
            config_path=self.root / "config.json",
            local_config_path=self.root / "config.local.json",
        )
        self.registrations = (registration(),)
        self.store_path = self.root / "activity.db"
        self.store = ActivityStore(self.store_path)
        self.store.initialize()
        self.service = self._new_activity_service()

    def tearDown(self) -> None:
        self.store.close()

    def _new_activity_service(self) -> ActivityService:
        return ActivityService(
            self.store,
            self.registrations,
            registration_loader=lambda: self.registrations,
        )

    def _mailbox(self, *, partition: str = "production") -> ActivityMailbox:
        return ActivityMailbox(
            self.service,
            settings_getter=lambda: self.settings_store.get_snapshot().activity_mailbox,
            registration_loader=lambda: self.registrations,
            partition_getter=lambda: partition,
        )

    def _configure(self, *, enabled: bool = True, folder: Path | None = None, client_id: str = "codex") -> None:
        self.settings_store.apply_patch(SettingsPatch.model_validate({
            "activity_mailbox": {
                "enabled": enabled,
                "folder_path": str(folder or self.folder),
                "client_id": client_id,
            },
        }))

    async def test_mailbox_is_disabled_by_default(self) -> None:
        mailbox = self._mailbox()
        self.assertFalse(self.settings_store.get_snapshot().activity_mailbox.enabled)
        result = await mailbox.scan_now()
        self.assertEqual(result.state, "disabled")
        self.assertEqual(self.service.list(partition="production"), [])

    async def test_live_settings_changes_choose_new_folder_without_restart(self) -> None:
        second_folder = self.root / "second-mailbox"
        second_folder.mkdir()
        self._configure(folder=self.folder)
        mailbox = self._mailbox()
        (self.folder / "first.json").write_text(report(key="first").model_dump_json(), encoding="utf-8")
        first_scan = await mailbox.scan_now()
        self.assertEqual(first_scan.last_imported_count, 1)

        self._configure(folder=second_folder)
        (second_folder / "second.json").write_text(report(key="second").model_dump_json(), encoding="utf-8")
        second_scan = await mailbox.scan_now()
        self.assertEqual(second_scan.last_imported_count, 1)
        self.assertEqual({item.content.submission_key for item in self.service.list(partition="production")}, {"first", "second"})

        self._configure(enabled=False, folder=second_folder)
        disabled = await mailbox.scan_now()
        self.assertEqual(disabled.state, "disabled")

    async def test_settings_changed_during_file_read_prevent_submission_and_stale_status(self) -> None:
        self._configure()
        mailbox = self._mailbox()
        (self.folder / "report-1.json").write_text(report().model_dump_json(), encoding="utf-8")
        missing = self.root / "not-synced-yet"

        def change_folder_before_return(*_args) -> ActivityReportContent:
            self._configure(folder=missing)
            return report()

        with mock.patch.object(mailbox, "_read_completed_report", side_effect=change_folder_before_return):
            result = await mailbox.scan_now()

        self.assertEqual(result.state, "scan_error")
        self.assertEqual(self.service.list(partition="production"), [])
        current = mailbox.status()
        self.assertEqual(current.state, "folder_unavailable")
        self.assertIsNone(current.last_error)

    async def test_missing_folder_remains_saved_and_poller_keeps_running(self) -> None:
        missing = self.root / "not-synced-yet"
        self._configure(folder=missing)
        mailbox = self._mailbox()
        completed = threading.Event()
        original_scan = mailbox._scan_sync

        def scan_and_signal():
            result = original_scan()
            completed.set()
            return result

        stop = asyncio.Event()
        with mock.patch.object(mailbox, "_scan_sync", side_effect=scan_and_signal):
            poller = asyncio.create_task(run_activity_mailbox_poller(mailbox, stop, interval_seconds=60))
            self.assertTrue(await asyncio.wait_for(asyncio.to_thread(completed.wait, 3), timeout=4))
            self.assertEqual(mailbox.status().state, "folder_unavailable")
            self.assertEqual(self.settings_store.get_snapshot().activity_mailbox.folder_path, str(missing))
            stop.set()
            await asyncio.wait_for(poller, timeout=2)

    async def test_periodic_and_manual_scan_share_one_in_progress_scan(self) -> None:
        self._configure()
        mailbox = self._mailbox()
        (self.folder / "report-1.json").write_text(report().model_dump_json(), encoding="utf-8")
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        calls = 0
        original_scan = mailbox._scan_sync

        def blocked_scan():
            nonlocal calls
            calls += 1
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test scan was not released")
            try:
                return original_scan()
            finally:
                finished.set()

        stop = asyncio.Event()
        with mock.patch.object(mailbox, "_scan_sync", side_effect=blocked_scan):
            poller = asyncio.create_task(run_activity_mailbox_poller(mailbox, stop, interval_seconds=60))
            self.assertTrue(await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), timeout=4))
            manual = asyncio.create_task(mailbox.scan_now())
            release.set()
            manual_result = await manual
            self.assertTrue(await asyncio.wait_for(asyncio.to_thread(finished.wait, 3), timeout=4))
            self.assertEqual(calls, 1)
            self.assertEqual(manual_result.last_imported_count, 1)
            stop.set()
            await asyncio.wait_for(poller, timeout=2)

    async def test_import_uses_configured_identity_and_durable_idempotency(self) -> None:
        self._configure()
        content = report()
        source = self.folder / f"{content.submission_key}.json"
        source.write_text(content.model_dump_json(), encoding="utf-8")
        before = source.stat()
        bytes_before = source.read_bytes()

        first = await self._mailbox().scan_now()
        self.assertEqual(first.last_imported_count, 1, first)
        imported = self.service.list(partition="production")
        self.assertEqual(len(imported), 1)
        self.assertEqual((imported[0].client_id, imported[0].principal, imported[0].partition), ("codex", "operator", "production"))
        self.assertEqual(source.read_bytes(), bytes_before)
        self.assertEqual((source.stat().st_size, source.stat().st_mtime_ns), (before.st_size, before.st_mtime_ns))

        self.store.close()
        self.store = ActivityStore(self.store_path)
        self.store.initialize()
        self.service = self._new_activity_service()
        restarted = await self._mailbox().scan_now()
        self.assertEqual(restarted.last_imported_count, 0)
        self.assertEqual(len(self.service.list(partition="production")), 1)

        source.write_text(report(outcome="Changed").model_dump_json(), encoding="utf-8")
        conflicted = await self._mailbox().scan_now()
        self.assertEqual(conflicted.state, "scan_error")
        self.assertEqual(len(self.service.list(partition="production")), 1)

    async def test_incomplete_malformed_oversized_and_mismatched_files_retry_without_import(self) -> None:
        self._configure()
        partial = self.folder / "partial.json"
        partial.write_text('{"version":"1",', encoding="utf-8")
        oversized = self.folder / "large.json"
        oversized.write_bytes(b" " * (256 * 1024 + 1))
        wrong_key = self.folder / "name.json"
        wrong_key.write_text(report(key="different").model_dump_json(), encoding="utf-8")
        (self.folder / "unsafe key.json").write_text(report(key="unsafe").model_dump_json(), encoding="utf-8")
        (self.folder / "directory.json").mkdir()

        failed = await self._mailbox().scan_now()
        self.assertEqual(failed.state, "scan_error")
        self.assertEqual(self.service.list(partition="production"), [])

        partial.write_text(report(key="partial").model_dump_json(), encoding="utf-8")
        retried = await self._mailbox().scan_now()
        self.assertEqual(retried.last_imported_count, 1)
        self.assertEqual([item.content.submission_key for item in self.service.list(partition="production")], ["partial"])

    async def test_invalid_disabled_permission_and_wrong_partition_clients_fail_closed(self) -> None:
        self._configure()
        (self.folder / "report-1.json").write_text(report().model_dump_json(), encoding="utf-8")
        mailbox = self._mailbox()
        for registrations, partition, expected in (
            ((), "production", "client_unavailable"),
            ((registration(enabled=False),), "production", "client_disabled"),
            ((registration(permissions=()),), "production", "client_not_permitted"),
            ((registration(principals=("other",)),), "production", "client_not_permitted"),
            ((registration(partition="sandbox"),), "production", "client_partition_mismatch"),
        ):
            self.registrations = registrations
            self.service = self._new_activity_service()
            mailbox = self._mailbox(partition=partition)
            result = await mailbox.scan_now()
            self.assertEqual(result.state, expected)
            self.assertEqual(self.service.list(partition="production"), [])

    async def test_status_checks_client_registration_against_latest_values(self) -> None:
        self._configure()
        mailbox = self._mailbox()
        self.assertEqual(mailbox.status().state, "ready")
        self.registrations = ()
        self.assertEqual(mailbox.status().state, "client_unavailable")
