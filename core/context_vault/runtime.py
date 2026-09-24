"""Lifespan-owned reconciliation for the local Context vault."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from core.context_vault.publisher import (
    ContextVaultPublicationError,
    ContextVaultPublisher,
    ContextVaultPublishResult,
)
from core.context_vault.render import ContextVaultMarkdownRenderer
from core.context_vault.selection import ContextVaultSelectionService
from core.knowledge.service import KnowledgeService
from core.settings.models import ContextVaultSettings

_LOGGER = logging.getLogger(__name__)
_RUNTIME: "ContextVaultRuntime | None" = None


def set_context_vault_runtime(runtime: "ContextVaultRuntime | None") -> None:
    global _RUNTIME
    _RUNTIME = runtime


def get_context_vault_runtime() -> "ContextVaultRuntime | None":
    return _RUNTIME


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _destination_key(destination: Path | None) -> str | None:
    if destination is None:
        return None
    return os.path.normcase(os.path.abspath(destination.expanduser()))


def _selection_hash(settings: ContextVaultSettings, *, production_allowed: bool) -> str:
    value = {
        "settings": settings.model_dump(mode="json"),
        "production_allowed": production_allowed,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class _StoredRuntimeState:
    generation: int
    dirty: bool
    exported_revision: int | None
    exported_selection_hash: str | None
    exported_destination_key: str | None
    last_attempt_at: str | None
    attempt_count: int
    last_success_at: str | None
    owned_file_count: int
    changed_file_count: int
    removed_file_count: int
    last_error_code: str | None
    last_destination_path: str | None
    retained_destinations: tuple[str, ...]


class ContextVaultRuntimeStateStore:
    """Keep reconciliation state beside APEX's local knowledge database."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path).expanduser()
        if not self._path.is_absolute():
            raise ContextVaultPublicationError("state_path_invalid")
        try:
            with self._connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS context_vault_runtime_state ("
                    "id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL DEFAULT 0, "
                    "dirty INTEGER NOT NULL DEFAULT 1, exported_revision INTEGER, "
                    "exported_selection_hash TEXT, exported_destination_key TEXT, "
                    "last_attempt_at TEXT, attempt_count INTEGER NOT NULL DEFAULT 0, "
                    "last_success_at TEXT, owned_file_count INTEGER NOT NULL DEFAULT 0, "
                    "changed_file_count INTEGER NOT NULL DEFAULT 0, removed_file_count INTEGER NOT NULL DEFAULT 0, "
                    "last_error_code TEXT, last_destination_path TEXT, "
                    "retained_destinations_json TEXT NOT NULL DEFAULT '[]')"
                )
                conn.execute("INSERT OR IGNORE INTO context_vault_runtime_state(id) VALUES (1)")
        except (OSError, sqlite3.Error):
            raise ContextVaultPublicationError("state_unavailable") from None

    def snapshot(self) -> _StoredRuntimeState:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT generation,dirty,exported_revision,exported_selection_hash,"
                    "exported_destination_key,last_attempt_at,attempt_count,last_success_at,"
                    "owned_file_count,changed_file_count,removed_file_count,last_error_code,"
                    "last_destination_path,retained_destinations_json "
                    "FROM context_vault_runtime_state WHERE id=1"
                ).fetchone()
            if row is None:
                raise ValueError("runtime state missing")
            retained = json.loads(str(row[13]))
            if not isinstance(retained, list) or any(not isinstance(item, str) for item in retained):
                raise ValueError("invalid retained destination state")
            return _StoredRuntimeState(
                generation=int(row[0]), dirty=bool(row[1]),
                exported_revision=int(row[2]) if row[2] is not None else None,
                exported_selection_hash=str(row[3]) if row[3] else None,
                exported_destination_key=str(row[4]) if row[4] else None,
                last_attempt_at=str(row[5]) if row[5] else None,
                attempt_count=int(row[6]), last_success_at=str(row[7]) if row[7] else None,
                owned_file_count=int(row[8]), changed_file_count=int(row[9]),
                removed_file_count=int(row[10]), last_error_code=str(row[11]) if row[11] else None,
                last_destination_path=str(row[12]) if row[12] else None,
                retained_destinations=tuple(retained),
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise ContextVaultPublicationError("state_unavailable") from None

    def mark_dirty(self) -> None:
        self._update(
            "UPDATE context_vault_runtime_state SET generation=generation+1,dirty=1 WHERE id=1"
        )

    def record_destination_change(self, destination: Path | None) -> None:
        """Remember the previous export root even while publication is disabled."""
        destination_text = str(destination.expanduser()) if destination is not None else None
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT last_destination_path,retained_destinations_json,owned_file_count "
                    "FROM context_vault_runtime_state WHERE id=1"
                ).fetchone()
                if row is None:
                    raise ValueError("runtime state missing")
                last_destination = str(row[0]) if row[0] else None
                retained = json.loads(str(row[1]))
                if not isinstance(retained, list) or any(not isinstance(item, str) for item in retained):
                    raise ValueError("invalid retained destination state")
                if last_destination and int(row[2]) > 0 and (
                    destination_text is None
                    or os.path.normcase(last_destination) != os.path.normcase(destination_text)
                ):
                    retained.append(last_destination)
                if destination_text:
                    retained = [
                        item for item in retained
                        if os.path.normcase(item) != os.path.normcase(destination_text)
                    ]
                retained = list(dict.fromkeys(retained))[-20:]
                conn.execute(
                    "UPDATE context_vault_runtime_state SET retained_destinations_json=? WHERE id=1",
                    (json.dumps(retained, separators=(",", ":")),),
                )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise ContextVaultPublicationError("state_unavailable") from None

    def begin_attempt(self, destination: Path | None) -> tuple[int, str]:
        timestamp = utc_now_iso()
        destination_text = str(destination.expanduser()) if destination is not None else None
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT generation,last_destination_path,retained_destinations_json "
                    "FROM context_vault_runtime_state WHERE id=1"
                ).fetchone()
                if row is None:
                    raise ValueError("runtime state missing")
                retained = json.loads(str(row[2]))
                if not isinstance(retained, list) or any(not isinstance(item, str) for item in retained):
                    raise ValueError("invalid retained destination state")
                last_destination = str(row[1]) if row[1] else None
                if last_destination and destination_text and os.path.normcase(last_destination) != os.path.normcase(destination_text):
                    retained.append(last_destination)
                if destination_text:
                    retained = [item for item in retained if os.path.normcase(item) != os.path.normcase(destination_text)]
                retained = list(dict.fromkeys(retained))[-20:]
                conn.execute(
                    "UPDATE context_vault_runtime_state SET dirty=1,last_attempt_at=?,attempt_count=attempt_count+1,"
                    "retained_destinations_json=? WHERE id=1",
                    (timestamp, json.dumps(retained, separators=(",", ":"))),
                )
                return int(row[0]), timestamp
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise ContextVaultPublicationError("state_unavailable") from None

    def mark_disabled(self, *, revision: int, selection_hash: str, destination: Path | None) -> None:
        self._update(
            "UPDATE context_vault_runtime_state SET dirty=0,exported_revision=?,"
            "exported_selection_hash=?,exported_destination_key=? WHERE id=1",
            (revision, selection_hash, _destination_key(destination)),
        )

    def mark_stale(self) -> None:
        self._update("UPDATE context_vault_runtime_state SET dirty=1 WHERE id=1")

    def mark_failure(self, code: str) -> None:
        safe_code = code if code.replace("_", "").isalnum() else "publication_failed"
        self._update(
            "UPDATE context_vault_runtime_state SET dirty=1,last_error_code=? WHERE id=1",
            (safe_code[:64],),
        )

    def mark_success(
        self,
        *,
        generation: int,
        revision: int,
        selection_hash: str,
        destination: Path,
        result: ContextVaultPublishResult,
        removal: bool = False,
    ) -> bool:
        timestamp = utc_now_iso()
        destination_key = _destination_key(destination)
        destination_text = str(destination.expanduser())
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT generation,retained_destinations_json FROM context_vault_runtime_state WHERE id=1"
                ).fetchone()
                current_revision_row = conn.execute(
                    "SELECT revision FROM knowledge_partition_revisions WHERE partition='production'"
                ).fetchone()
                current_revision = int(current_revision_row[0]) if current_revision_row is not None else 0
                if row is None:
                    raise ValueError("runtime state missing")
                retained = json.loads(str(row[1]))
                if not isinstance(retained, list):
                    raise ValueError("invalid retained destination state")
                retained = [item for item in retained if os.path.normcase(str(item)) != os.path.normcase(destination_text)]
                stale = int(row[0]) != generation or current_revision != revision
                conn.execute(
                    "UPDATE context_vault_runtime_state SET dirty=?,exported_revision=?,"
                    "exported_selection_hash=?,exported_destination_key=?,last_destination_path=?,"
                    "last_success_at=CASE WHEN ? THEN last_success_at ELSE ? END,"
                    "owned_file_count=?,changed_file_count=?,removed_file_count=?,"
                    "last_error_code=NULL,retained_destinations_json=? WHERE id=1",
                    (
                        int(stale), None if removal else revision,
                        None if removal else selection_hash,
                        None if removal else destination_key,
                        None if removal else destination_text,
                        int(removal), timestamp,
                        result.owned_file_count, result.changed_file_count,
                        result.removed_file_count, json.dumps(retained, separators=(",", ":")),
                    ),
                )
                return bool(stale)
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise ContextVaultPublicationError("state_unavailable") from None

    def _update(self, sql: str, params: tuple[object, ...] = ()) -> None:
        try:
            with self._connect() as conn:
                conn.execute(sql, params)
        except (OSError, sqlite3.Error):
            raise ContextVaultPublicationError("state_unavailable") from None

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()


@dataclass(frozen=True, slots=True)
class ContextVaultRuntimeStatus:
    dirty: bool
    refreshing: bool
    knowledge_revision: int
    exported_revision: int | None
    last_attempt_at: str | None
    attempt_count: int
    last_success_at: str | None
    owned_file_count: int
    changed_file_count: int
    removed_file_count: int
    last_error_code: str | None
    destination_path: str | None
    retained_destinations: tuple[str, ...]
    export_restricted: bool
    restriction_code: str | None


class ContextVaultRuntime:
    """Coalesce, serialize, and recover vault publications for one app lifespan."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeService,
        settings_getter: Callable[[], ContextVaultSettings],
        database_path: str | Path,
        destination: Path | None,
        production_allowed: Callable[[], bool],
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._knowledge = knowledge
        self._settings_getter = settings_getter
        self._destination = destination.expanduser() if destination is not None else None
        self._production_allowed = production_allowed
        self._renderer = ContextVaultMarkdownRenderer()
        self._state = ContextVaultRuntimeStateStore(database_path)
        self._state.record_destination_change(self._destination)
        self._poll_interval = max(0.1, poll_interval_seconds)
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()
        self._publish_lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._refreshing_lock = threading.Lock()
        self._refreshing = False

    def start(self) -> asyncio.Task[None]:
        self._loop = asyncio.get_running_loop()
        self._stopping.clear()
        task = asyncio.create_task(self.run(), name="context-vault-refresh")
        self._signal()
        return task

    def request_stop(self) -> None:
        self._stopping.set()
        self._signal()

    def notify_knowledge_change(self, _revision: int | None = None) -> None:
        self._state.mark_dirty()
        self._signal()

    async def notify_selection_change(self) -> None:
        await asyncio.to_thread(self._state.mark_dirty)
        self._signal()

    async def acquire_settings_transition(self) -> None:
        """Order enablement, selection, and sandbox changes against publication."""
        await self._publish_lock.acquire()

    def release_settings_transition(self) -> None:
        self._publish_lock.release()

    async def refresh_now(self) -> ContextVaultRuntimeStatus:
        if not self._production_allowed():
            raise ContextVaultRuntimeError(self._restriction_code() or "export_restricted")
        await asyncio.to_thread(self._state.mark_dirty)
        self._signal()
        async with self._publish_lock:
            while True:
                outcome = await self._run_operation(removal=False)
                if outcome == "stale":
                    continue
                if outcome != "success" or not await asyncio.to_thread(self._needs_refresh):
                    break
        return await asyncio.to_thread(self.status)

    async def remove_managed(self) -> ContextVaultRuntimeStatus:
        async with self._publish_lock:
            if not self._production_allowed():
                raise ContextVaultRuntimeError(self._restriction_code() or "export_restricted")
            if (await asyncio.to_thread(self._settings_getter)).enabled:
                raise ContextVaultRuntimeError("disable_export_before_removal")
            await self._run_operation(removal=True)
        return await asyncio.to_thread(self.status)

    def status(self) -> ContextVaultRuntimeStatus:
        settings = self._settings_getter()
        allowed = self._production_allowed()
        revision = self._knowledge.context_vault_revision(partition="production")
        selection_hash = _selection_hash(settings, production_allowed=allowed)
        stored = self._state.snapshot()
        destination_key = _destination_key(self._destination)
        enabled = settings.enabled
        dirty = stored.dirty
        if not enabled:
            dirty = False
        elif allowed:
            dirty = dirty or stored.exported_revision != revision
            dirty = dirty or stored.exported_selection_hash != selection_hash
            dirty = dirty or stored.exported_destination_key != destination_key
        with self._refreshing_lock:
            refreshing = self._refreshing
        return ContextVaultRuntimeStatus(
            dirty=dirty, refreshing=refreshing, knowledge_revision=revision,
            exported_revision=stored.exported_revision, last_attempt_at=stored.last_attempt_at,
            attempt_count=stored.attempt_count, last_success_at=stored.last_success_at,
            owned_file_count=stored.owned_file_count, changed_file_count=stored.changed_file_count,
            removed_file_count=stored.removed_file_count, last_error_code=stored.last_error_code,
            destination_path=str(self._destination) if self._destination else None,
            retained_destinations=tuple(
                item for item in stored.retained_destinations
                if not self._destination or os.path.normcase(item) != os.path.normcase(str(self._destination))
            ),
            export_restricted=not allowed,
            restriction_code=self._restriction_code() if not allowed else None,
        )

    async def run(self) -> None:
        settings = await asyncio.to_thread(self._settings_getter)
        if settings.enabled and self._production_allowed():
            await asyncio.to_thread(self._state.mark_dirty)
        self._signal()
        retry_delays = (0.25, 1.0, 3.0)
        while not self._stopping.is_set():
            await self._wait_for_wake()
            self._wake.clear()
            if self._stopping.is_set():
                break
            if not await asyncio.to_thread(self._needs_refresh):
                continue
            attempt_index = 0
            while not self._stopping.is_set():
                before_attempt_signature = await asyncio.to_thread(self._input_signature)
                async with self._publish_lock:
                    outcome = await self._run_operation(removal=False)
                if outcome == "stale":
                    continue
                if outcome == "success":
                    if await asyncio.to_thread(self._needs_refresh):
                        continue
                    break
                if attempt_index >= len(retry_delays):
                    failed_signature = await asyncio.to_thread(self._input_signature)
                    await self._wait_for_change(failed_signature)
                    break
                delay = retry_delays[attempt_index]
                attempt_index += 1
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=delay)
                except TimeoutError:
                    pass
                self._wake.clear()
                if self._stopping.is_set():
                    break
                # A new commit resets the bounded retry window.
                if await asyncio.to_thread(self._input_signature) != before_attempt_signature:
                    attempt_index = 0

    async def _wait_for_wake(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
                return
            except TimeoutError:
                if await asyncio.to_thread(self._needs_refresh):
                    return

    async def _wait_for_change(self, signature: tuple[int, str, str | None]) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)
            except TimeoutError:
                pass
            self._wake.clear()
            if await asyncio.to_thread(self._input_signature) != signature:
                return

    async def _run_operation(self, *, removal: bool) -> str:
        with self._refreshing_lock:
            self._refreshing = True
        try:
            try:
                return await asyncio.to_thread(self._perform_operation, removal=removal)
            except Exception:
                # Keep the lifespan worker alive if a transient database or
                # settings failure occurs before publication can record its
                # own sanitized error.
                _LOGGER.warning("Context vault refresh could not start an operation.")
                try:
                    await asyncio.to_thread(self._state.mark_failure, "publication_failed")
                except Exception:
                    pass
                return "failure"
        finally:
            with self._refreshing_lock:
                self._refreshing = False

    def _perform_operation(self, *, removal: bool) -> str:
        settings = self._settings_getter()
        allowed = self._production_allowed()
        revision = self._knowledge.context_vault_revision(partition="production")
        current_hash = _selection_hash(settings, production_allowed=allowed)
        if not removal and (not allowed or not settings.enabled):
            if allowed:
                self._state.mark_disabled(
                    revision=revision, selection_hash=current_hash, destination=self._destination,
                )
            return "skipped"

        generation, _ = self._state.begin_attempt(self._destination)
        if not allowed:
            self._state.mark_failure(self._restriction_code() or "export_restricted")
            return "failure"
        if self._destination is None:
            self._state.mark_failure("destination_not_configured")
            return "failure"

        publisher: ContextVaultPublisher | None = None
        try:
            publisher = ContextVaultPublisher(self._destination, self._state_path())
            if removal:
                result = publisher.remove_managed()
                final_revision = self._knowledge.context_vault_revision(partition="production")
                final_settings = self._settings_getter()
                final_hash = _selection_hash(
                    final_settings, production_allowed=self._production_allowed(),
                )
                self._state.mark_success(
                    generation=generation, revision=revision, selection_hash=final_hash,
                    destination=self._destination, result=result, removal=True,
                )
                if final_revision != revision or final_hash != current_hash:
                    self._state.mark_stale()
                    return "stale"
                return "success"

            selection = ContextVaultSelectionService(
                self._knowledge, settings, destination_configured=True,
            )
            scopes = selection.export_enabled_scopes()
            snapshot_revision = self._knowledge.context_vault_revision(partition="production")
            snapshot_settings = self._settings_getter()
            snapshot_hash = _selection_hash(
                snapshot_settings, production_allowed=self._production_allowed(),
            )
            if snapshot_revision != revision or snapshot_hash != current_hash:
                self._state.mark_stale()
                return "stale"

            files = self._renderer.render(scopes)
            before_publish_revision = self._knowledge.context_vault_revision(partition="production")
            before_publish_settings = self._settings_getter()
            before_publish_hash = _selection_hash(
                before_publish_settings, production_allowed=self._production_allowed(),
            )
            if before_publish_revision != revision or before_publish_hash != current_hash:
                self._state.mark_stale()
                return "stale"

            result = publisher.publish(files)
            final_settings = self._settings_getter()
            final_hash = _selection_hash(
                final_settings, production_allowed=self._production_allowed(),
            )
            stale = self._state.mark_success(
                generation=generation, revision=revision, selection_hash=current_hash,
                destination=self._destination, result=result,
            )
            if stale or final_hash != current_hash:
                self._state.mark_stale()
                return "stale"
            return "success"
        except ContextVaultPublicationError as exc:
            self._state.mark_failure(exc.code)
            return "failure"
        except Exception:
            _LOGGER.warning("Context vault refresh failed with an unexpected error.")
            self._state.mark_failure("publication_failed")
            return "failure"

    def _state_path(self) -> Path:
        return self._state._path

    def _needs_refresh(self) -> bool:
        settings = self._settings_getter()
        if not settings.enabled or not self._production_allowed():
            return False
        stored = self._state.snapshot()
        revision = self._knowledge.context_vault_revision(partition="production")
        selection_hash = _selection_hash(settings, production_allowed=True)
        return bool(
            stored.dirty
            or stored.exported_revision != revision
            or stored.exported_selection_hash != selection_hash
            or stored.exported_destination_key != _destination_key(self._destination)
        )

    def _input_signature(self) -> tuple[int, str, str | None]:
        settings = self._settings_getter()
        return (
            self._knowledge.context_vault_revision(partition="production"),
            _selection_hash(settings, production_allowed=self._production_allowed()),
            _destination_key(self._destination),
        )

    def _restriction_code(self) -> str | None:
        return None if self._production_allowed() else "production_export_restricted"

    def _signal(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._wake.set)
        except RuntimeError:
            pass


class ContextVaultRuntimeError(RuntimeError):
    """A safe, stable runtime restriction code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
