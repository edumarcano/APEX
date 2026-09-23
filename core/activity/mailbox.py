"""Provider-neutral polling for completed reports in one operator-selected folder."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import stat
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import ValidationError

from core.activity.models import ActivityClientRegistration, ActivityReportContent
from core.activity.service import (
    ActivityClientDisabledError,
    ActivityPermissionError,
    ActivityService,
)
from core.activity.store import ActivityConflictError, ActivityStoreError, _MAX_REPORT_BYTES
from core.settings.models import ActivityMailboxSettings

_LOGGER = logging.getLogger(__name__)
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_mailbox: "ActivityMailbox | None" = None
MailboxState = Literal[
    "disabled",
    "demo_mode",
    "not_configured",
    "client_unavailable",
    "client_disabled",
    "client_not_permitted",
    "client_partition_mismatch",
    "folder_unavailable",
    "ready",
    "scan_error",
]


@dataclass(frozen=True, slots=True)
class MailboxStatus:
    enabled: bool
    state: MailboxState
    folder_available: bool | None
    client_registered: bool
    client_enabled: bool
    client_can_submit: bool
    client_partition_matches: bool
    last_scan_at: str | None
    last_imported_count: int
    last_error: str | None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _same_file_version(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare required size/mtime and inode identity when the OS provides it."""
    if left.st_size != right.st_size or left.st_mtime_ns != right.st_mtime_ns:
        return False
    return not (left.st_ino and right.st_ino) or (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _safe_key(value: str) -> bool:
    if not _SAFE_KEY.fullmatch(value):
        return False
    return value.split(".", 1)[0].casefold() not in _WINDOWS_RESERVED_NAMES


class ActivityMailbox:
    """Scans one configured directory and submits reports through ActivityService."""

    def __init__(
        self,
        activity_service: ActivityService,
        *,
        settings_getter: Callable[[], ActivityMailboxSettings],
        registration_loader: Callable[[], tuple[ActivityClientRegistration, ...]],
        partition_getter: Callable[[], str],
        demo_mode: bool = False,
    ) -> None:
        self._activity_service = activity_service
        self._settings_getter = settings_getter
        self._registration_loader = registration_loader
        self._partition_getter = partition_getter
        self._demo_mode = demo_mode
        self._scan_task: asyncio.Task[MailboxStatus] | None = None
        self._status_lock = threading.Lock()
        self._last_scan_at: str | None = None
        self._last_settings_key: tuple[bool, str, str, str, bool] | None = None
        self._last_imported_count = 0
        self._last_error: str | None = None
        self._last_state: MailboxState | None = None

    async def scan_now(self) -> MailboxStatus:
        """Run one scan, sharing an in-progress scan with concurrent callers."""
        task = self._scan_task
        if task is None or task.done():
            task = asyncio.create_task(self._run_scan(), name="activity-mailbox-scan")
            self._scan_task = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._scan_task is task:
                self._scan_task = None

    async def wait_for_idle(self, timeout_seconds: float) -> bool:
        """Drain an HTTP-triggered scan before its activity store is closed."""
        task = self._scan_task
        if task is None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, timeout_seconds))
        except asyncio.TimeoutError:
            return False
        except Exception:
            return True
        return True

    def status(self) -> MailboxStatus:
        """Return live folder/client readiness and the matching latest scan result."""
        settings = self._settings_getter()
        base = self._base_status(settings)
        key = self._settings_key(settings)
        with self._status_lock:
            same_settings = key == self._last_settings_key
            last_scan_at = self._last_scan_at if same_settings else None
            imported_count = self._last_imported_count if same_settings else 0
            last_error = self._last_error if same_settings else None
            last_state = self._last_state if same_settings else None
        state = base.state
        if base.state == "ready" and last_state in ("scan_error", "folder_unavailable"):
            state = last_state
        return MailboxStatus(
            enabled=base.enabled,
            state=state,
            folder_available=base.folder_available,
            client_registered=base.client_registered,
            client_enabled=base.client_enabled,
            client_can_submit=base.client_can_submit,
            client_partition_matches=base.client_partition_matches,
            last_scan_at=last_scan_at,
            last_imported_count=imported_count,
            last_error=last_error,
        )

    async def _run_scan(self) -> MailboxStatus:
        try:
            return await asyncio.to_thread(self._scan_sync)
        except Exception:
            _LOGGER.warning("Activity mailbox scan failed; it will retry later")
            return self._failure_status(
                self._settings_getter(), "The mailbox scan failed; APEX will retry."
            )

    def _scan_sync(self) -> MailboxStatus:
        settings = self._settings_getter()
        readiness = self._base_status(settings)
        if readiness.state != "ready":
            return self._recorded_result(settings, readiness.state, readiness, None, 0)

        imported = 0
        failures = 0
        try:
            with os.scandir(settings.folder_path) as folder_entries:
                entries = sorted(
                    (entry for entry in folder_entries if entry.name.endswith(".json")),
                    key=lambda entry: entry.name.casefold(),
                )
        except OSError:
            unavailable = MailboxStatus(
                enabled=readiness.enabled,
                state="folder_unavailable",
                folder_available=False,
                client_registered=readiness.client_registered,
                client_enabled=readiness.client_enabled,
                client_can_submit=readiness.client_can_submit,
                client_partition_matches=readiness.client_partition_matches,
                last_scan_at=None,
                last_imported_count=0,
                last_error=None,
            )
            return self._recorded_result(
                settings, "folder_unavailable", unavailable,
                "The mailbox folder is unavailable; APEX will retry.", 0,
            )

        partition = self._partition_getter()
        for entry in entries:
            if self._settings_getter() != settings:
                failures += 1
                break
            stem = entry.name[:-5]
            if not _safe_key(stem):
                failures += 1
                continue
            try:
                content = self._read_completed_report(entry, stem)
                if self._settings_getter() != settings:
                    failures += 1
                    break
                receipt = self._activity_service.submit(
                    client_id=settings.client_id,
                    principal="operator",
                    partition=partition,
                    content=content,
                )
            except (OSError, UnicodeError, json.JSONDecodeError, ValidationError,
                    ActivityConflictError, ActivityClientDisabledError,
                    ActivityPermissionError, ActivityStoreError, ValueError):
                failures += 1
                continue
            if not receipt.duplicate:
                imported += 1

        last_error = (
            "Some mailbox files were not imported; APEX will retry on the next scan."
            if failures
            else None
        )
        result = MailboxStatus(
            enabled=True,
            state="scan_error" if failures else "ready",
            folder_available=True,
            client_registered=readiness.client_registered,
            client_enabled=readiness.client_enabled,
            client_can_submit=readiness.client_can_submit,
            client_partition_matches=readiness.client_partition_matches,
            last_scan_at=_utc_now(),
            last_imported_count=imported,
            last_error=last_error,
        )
        return self._recorded_result(
            settings, result.state, result, result.last_error, result.last_imported_count
        )

    def _read_completed_report(self, entry: os.DirEntry[str], expected_key: str) -> ActivityReportContent:
        path = Path(entry.path)
        before_path = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(before_path.st_mode):
            raise ValueError("mailbox_entry_not_regular")
        if before_path.st_size > _MAX_REPORT_BYTES:
            raise ValueError("mailbox_report_too_large")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(path, flags)
        try:
            opened_before = os.fstat(file_descriptor)
            if not stat.S_ISREG(opened_before.st_mode) or not _same_file_version(opened_before, before_path):
                raise ValueError("mailbox_file_changed")
            with os.fdopen(file_descriptor, "rb", closefd=False) as report_file:
                raw = report_file.read(_MAX_REPORT_BYTES + 1)
            opened_after = os.fstat(file_descriptor)
        finally:
            os.close(file_descriptor)

        after_path = path.stat(follow_symlinks=False)
        if (
            len(raw) > _MAX_REPORT_BYTES
            or not stat.S_ISREG(opened_after.st_mode)
            or not stat.S_ISREG(after_path.st_mode)
            or not _same_file_version(opened_before, opened_after)
            or not _same_file_version(opened_after, after_path)
        ):
            raise ValueError("mailbox_file_changed")
        content = ActivityReportContent.model_validate_json(raw)
        if content.submission_key != expected_key:
            raise ValueError("mailbox_filename_key_mismatch")
        return content

    def _base_status(self, settings: ActivityMailboxSettings) -> MailboxStatus:
        partition = self._partition_getter()
        registrations = {entry.id: entry for entry in self._registration_loader()}
        registration = registrations.get(settings.client_id) if settings.client_id else None
        registered = registration is not None
        client_enabled = bool(registration and registration.enabled)
        client_can_submit = bool(
            registration
            and "activity:submit" in registration.permissions
            and "operator" in registration.allowed_principals
        )
        partition_matches = bool(registration and registration.partition == partition)
        folder_available: bool | None = None

        if not settings.enabled:
            state: MailboxState = "disabled"
        elif self._demo_mode:
            state = "demo_mode"
        elif not settings.folder_path:
            state = "not_configured"
        elif not registered:
            state = "client_unavailable"
        elif not client_enabled:
            state = "client_disabled"
        elif not client_can_submit:
            state = "client_not_permitted"
        elif not partition_matches:
            state = "client_partition_mismatch"
        else:
            try:
                folder_available = Path(settings.folder_path).is_dir()
            except OSError:
                folder_available = False
            state = "ready" if folder_available else "folder_unavailable"

        return MailboxStatus(
            enabled=settings.enabled,
            state=state,
            folder_available=folder_available,
            client_registered=registered,
            client_enabled=client_enabled,
            client_can_submit=client_can_submit,
            client_partition_matches=partition_matches,
            last_scan_at=None,
            last_imported_count=0,
            last_error=None,
        )

    def _failure_status(self, settings: ActivityMailboxSettings, error: str) -> MailboxStatus:
        base = self._base_status(settings)
        return self._recorded_result(settings, "scan_error", base, error, 0)

    def _recorded_result(
        self,
        settings: ActivityMailboxSettings,
        state: MailboxState,
        base: MailboxStatus,
        error: str | None,
        imported: int,
    ) -> MailboxStatus:
        result = MailboxStatus(
            enabled=base.enabled,
            state=state,
            folder_available=base.folder_available,
            client_registered=base.client_registered,
            client_enabled=base.client_enabled,
            client_can_submit=base.client_can_submit,
            client_partition_matches=base.client_partition_matches,
            last_scan_at=_utc_now(),
            last_imported_count=imported,
            last_error=error,
        )
        with self._status_lock:
            self._last_scan_at = result.last_scan_at
            self._last_settings_key = self._settings_key(settings)
            self._last_imported_count = imported
            self._last_error = error
            self._last_state = state
        return result

    def _settings_key(self, settings: ActivityMailboxSettings) -> tuple[bool, str, str, str, bool]:
        return (
            settings.enabled,
            settings.folder_path,
            settings.client_id,
            self._partition_getter(),
            self._demo_mode,
        )


def set_activity_mailbox(mailbox: ActivityMailbox | None) -> None:
    """Publish the lifespan-owned mailbox for local API routes."""
    global _mailbox
    _mailbox = mailbox


def get_activity_mailbox() -> ActivityMailbox:
    if _mailbox is None:
        raise RuntimeError("Activity mailbox is unavailable.")
    return _mailbox


async def run_activity_mailbox_poller(
    mailbox: ActivityMailbox,
    stop_event: asyncio.Event,
    *,
    interval_seconds: float = 60.0,
) -> None:
    """Scan on startup and repeat without blocking the API event loop."""
    while not stop_event.is_set():
        await mailbox.scan_now()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
