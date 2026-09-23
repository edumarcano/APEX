"""Focused coverage for the optional local activity-folder mailbox."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import core.activity.mailbox as mailbox_module
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

        self.assertEqual(result.state, "folder_unavailable")
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

        def scan_and_signal(settings=None, partition=None):
            result = original_scan(settings, partition)
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

        def blocked_scan(settings=None, partition=None):
            nonlocal calls
            calls += 1
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test scan was not released")
            try:
                return original_scan(settings, partition)
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

    async def test_manual_scan_follows_settings_change_during_an_active_scan(self) -> None:
        second_folder = self.root / "second-mailbox"
        second_folder.mkdir()
        self._configure(folder=self.folder)
        (self.folder / "first.json").write_text(report(key="first").model_dump_json(), encoding="utf-8")
        (second_folder / "second.json").write_text(report(key="second").model_dump_json(), encoding="utf-8")
        mailbox = self._mailbox()
        original_scan = mailbox._scan_sync
        first_scan_entered = threading.Event()
        release_first_scan = threading.Event()
        scan_paths: list[str] = []
        manual_request_read_new_settings = threading.Event()
        original_settings_getter = mailbox._settings_getter

        def observe_settings():
            settings = original_settings_getter()
            if settings.folder_path == str(second_folder):
                manual_request_read_new_settings.set()
            return settings

        def controlled_scan(settings=None, partition=None):
            path = settings.folder_path if settings is not None else ""
            scan_paths.append(path)
            if path == str(self.folder):
                first_scan_entered.set()
                if not release_first_scan.wait(3):
                    raise TimeoutError("first scan was not released")
            return original_scan(settings, partition)

        mailbox._settings_getter = observe_settings
        with mock.patch.object(mailbox, "_scan_sync", side_effect=controlled_scan):
            first = asyncio.create_task(mailbox.scan_now())
            self.assertTrue(await asyncio.wait_for(asyncio.to_thread(first_scan_entered.wait, 3), timeout=4))
            self._configure(folder=second_folder)
            manual = asyncio.create_task(mailbox.scan_now())
            self.assertTrue(await asyncio.wait_for(
                asyncio.to_thread(manual_request_read_new_settings.wait, 3), timeout=4,
            ))
            release_first_scan.set()
            first_result, manual_result = await asyncio.gather(first, manual)

        self.assertEqual(first_result.last_imported_count, 1)
        self.assertEqual(manual_result.last_imported_count, 1)
        self.assertEqual(scan_paths, [str(self.folder), str(second_folder)])
        self.assertEqual(
            {item.content.submission_key for item in self.service.list(partition="production")},
            {"second"},
        )

    async def test_partition_change_during_file_read_retries_in_new_partition(self) -> None:
        self._configure()
        (self.folder / "report-1.json").write_text(report().model_dump_json(), encoding="utf-8")
        partition = ["production"]
        mailbox = ActivityMailbox(
            self.service,
            settings_getter=lambda: self.settings_store.get_snapshot().activity_mailbox,
            registration_loader=lambda: self.registrations,
            partition_getter=lambda: partition[0],
        )
        original_read = mailbox._read_completed_report

        def switch_partition_after_read(entry):
            content = original_read(entry)
            partition[0] = "sandbox"
            self.registrations = (registration(partition="sandbox"),)
            return content

        with mock.patch.object(mailbox, "_read_completed_report", side_effect=switch_partition_after_read):
            retried = await mailbox.scan_now()

        self.assertEqual(retried.last_imported_count, 1)
        self.assertEqual(self.service.list(partition="production"), [])
        self.assertEqual(
            [item.content.submission_key for item in self.service.list(partition="sandbox")],
            ["report-1"],
        )

    async def test_unexpected_scan_failure_builds_readiness_status_off_event_loop(self) -> None:
        self._configure()
        mailbox = self._mailbox()
        event_loop_thread = threading.get_ident()
        readiness_threads: list[int] = []
        original_status = mailbox._base_status

        def record_readiness_thread(settings, partition=None):
            readiness_threads.append(threading.get_ident())
            return original_status(settings, partition)

        with mock.patch.object(mailbox, "_scan_sync", side_effect=RuntimeError("scan failed")), \
             mock.patch.object(mailbox, "_base_status", side_effect=record_readiness_thread):
            result = await mailbox.scan_now()

        self.assertEqual(result.state, "scan_error")
        self.assertEqual(len(readiness_threads), 1)
        self.assertNotEqual(readiness_threads[0], event_loop_thread)

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
        self.assertIn("key conflict", conflicted.last_error or "")
        self.assertEqual(len(self.service.list(partition="production")), 1)

        source.write_text(content.model_dump_json(), encoding="utf-8")
        recovered = await self._mailbox().scan_now()
        self.assertEqual(recovered.state, "ready")
        self.assertIsNone(recovered.last_error)
        self.assertEqual(recovered.last_imported_count, 0)

    async def test_descriptive_filenames_with_spaces_and_uppercase_extension_import(self) -> None:
        self._configure()
        (self.folder / "Agent run completed report.json").write_text(
            report(key="report-key").model_dump_json(), encoding="utf-8",
        )
        (self.folder / "Another descriptive report.JSON").write_text(
            report(key="second-key").model_dump_json(), encoding="utf-8",
        )

        result = await self._mailbox().scan_now()

        self.assertEqual(result.last_imported_count, 2)
        self.assertEqual(result.state, "ready")
        self.assertEqual(
            {item.content.submission_key for item in self.service.list(partition="production")},
            {"report-key", "second-key"},
        )

    async def test_identical_content_under_different_names_uses_service_idempotency(self) -> None:
        self._configure()
        serialized = report(key="shared-key").model_dump_json()
        (self.folder / "first completed report.json").write_text(serialized, encoding="utf-8")
        (self.folder / "copy from sync.JSON").write_text(serialized, encoding="utf-8")

        first = await self._mailbox().scan_now()
        second = await self._mailbox().scan_now()

        self.assertEqual(first.last_imported_count, 1)
        self.assertEqual(first.state, "ready")
        self.assertEqual(second.last_imported_count, 0)
        self.assertEqual(second.state, "ready")
        self.assertEqual(len(self.service.list(partition="production")), 1)

    async def test_failures_continue_past_good_files_and_recovery_clears_diagnostics(self) -> None:
        self._configure()
        partial = self.folder / "01-partial.json"
        partial.write_text('{"version":"1",', encoding="utf-8")
        invalid = self.folder / "02-invalid-fields.json"
        invalid.write_text('{"private report text":"do not expose"}', encoding="utf-8")
        oversized = self.folder / "03-large.json"
        oversized.write_bytes(b" " * (256 * 1024 + 1))
        directory = self.folder / "04-directory.json"
        directory.mkdir()
        (self.folder / "05-good report.JSON").write_text(
            report(key="already-good").model_dump_json(), encoding="utf-8",
        )

        failed = await self._mailbox().scan_now()
        self.assertEqual(failed.state, "scan_error")
        self.assertEqual(failed.last_imported_count, 1)
        self.assertIn("4 mailbox file(s) failed", failed.last_error or "")
        self.assertIn("invalid JSON", failed.last_error or "")
        self.assertIn("invalid report fields", failed.last_error or "")
        self.assertIn("oversized", failed.last_error or "")
        self.assertNotIn("private report text", failed.last_error or "")
        self.assertEqual(len(self.service.list(partition="production")), 1)

        partial.write_text(report(key="partial").model_dump_json(), encoding="utf-8")
        invalid.write_text(report(key="valid-after-retry").model_dump_json(), encoding="utf-8")
        oversized.write_text(report(key="size-recovered").model_dump_json(), encoding="utf-8")
        directory.rmdir()
        retried = await self._mailbox().scan_now()
        self.assertEqual(retried.state, "ready")
        self.assertIsNone(retried.last_error)
        self.assertEqual(retried.last_imported_count, 3)
        self.assertEqual(
            {item.content.submission_key for item in self.service.list(partition="production")},
            {"already-good", "partial", "valid-after-retry", "size-recovered"},
        )

    async def test_diagnostics_bound_examples_and_sanitize_long_filenames(self) -> None:
        self._configure()
        filenames = [f"{index}-" + "x" * 110 + ".json" for index in range(6)]
        for filename in filenames:
            (self.folder / filename).write_text("{", encoding="utf-8")

        result = await self._mailbox().scan_now()

        self.assertEqual(result.state, "scan_error")
        self.assertIn("6 mailbox file(s) failed", result.last_error or "")
        self.assertEqual((result.last_error or "").count("(invalid JSON)"), 3)
        self.assertIn("...", result.last_error or "")
        self.assertIn("and 3 more", result.last_error or "")
        self.assertLessEqual(len(result.last_error or ""), 500)
        self.assertTrue(all(filename not in (result.last_error or "") for filename in filenames))

    async def test_printable_unicode_filename_is_preserved_in_diagnostics(self) -> None:
        self._configure()
        filename = "résumé — 東京.json"
        (self.folder / filename).write_text("{", encoding="utf-8")

        result = await self._mailbox().scan_now()

        self.assertEqual(result.state, "scan_error")
        self.assertIn(filename, result.last_error or "")

    async def test_unexpected_submit_failure_uses_scan_level_error_and_stops_scanning(self) -> None:
        self._configure()
        first = self.folder / "first.json"
        first.write_text(report(key="first").model_dump_json(), encoding="utf-8")
        (self.folder / "second.json").write_text(report(key="second").model_dump_json(), encoding="utf-8")
        with mock.patch.object(self.service, "submit", side_effect=RuntimeError("private internal detail")) as submit:
            result = await self._mailbox().scan_now()

        self.assertEqual(result.state, "scan_error")
        self.assertEqual(result.last_error, "The mailbox scan failed; APEX will retry.")
        self.assertNotIn(first.name, result.last_error or "")
        self.assertNotIn("private internal detail", result.last_error or "")
        submit.assert_called_once()

    async def test_unreadable_changing_and_nonregular_files_have_safe_reasons(self) -> None:
        self._configure()
        (self.folder / "a-changing.json").write_text(report(key="changing").model_dump_json(), encoding="utf-8")
        (self.folder / "b-directory.json").mkdir()
        (self.folder / "c-unreadable.json").write_text(report(key="unreadable").model_dump_json(), encoding="utf-8")
        (self.folder / "d-good.JSON").write_text(report(key="good").model_dump_json(), encoding="utf-8")
        original_open = os.open
        original_same_version = mailbox_module._same_file_version
        changing_stat = (self.folder / "a-changing.json").stat()
        changing_identity = (
            changing_stat.st_dev, changing_stat.st_ino,
            changing_stat.st_size, changing_stat.st_mtime_ns,
        )
        simulated_change = False

        def simulate_change(left, right):
            nonlocal simulated_change
            for stat_result in (left, right):
                identity = (
                    stat_result.st_dev, stat_result.st_ino,
                    stat_result.st_size, stat_result.st_mtime_ns,
                )
                if not simulated_change and identity == changing_identity:
                    simulated_change = True
                    return False
            return original_same_version(left, right)

        def controlled_open(path, flags, *args, **kwargs):
            if Path(path).name == "c-unreadable.json":
                raise PermissionError("sensitive operating system detail")
            return original_open(path, flags, *args, **kwargs)

        with mock.patch("core.activity.mailbox._same_file_version", side_effect=simulate_change), \
             mock.patch("core.activity.mailbox.os.open", side_effect=controlled_open):
            result = await self._mailbox().scan_now()

        self.assertEqual(result.state, "scan_error")
        self.assertEqual(result.last_imported_count, 1, result)
        self.assertIn("changing file", result.last_error or "")
        self.assertIn("not a regular file", result.last_error or "")
        self.assertIn("unreadable", result.last_error or "")
        self.assertNotIn("sensitive operating system detail", result.last_error or "")

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
