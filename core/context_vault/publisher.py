"""Safe, recoverable publication of APEX-owned Markdown files."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterator
from uuid import UUID, uuid4


_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TEMP_NAME = re.compile(r"^\.apex-context-vault-tmp-[0-9a-f]{32}\.tmp$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class ContextVaultPublicationError(RuntimeError):
    """A sanitized publication failure; the error code contains no path or note text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ContextVaultPublicationState:
    owned_files: tuple[tuple[str, str], ...]
    pending: bool
    last_error_code: str | None
    last_success_at: str | None


@dataclass(frozen=True, slots=True)
class ContextVaultPublishResult:
    owned_file_count: int
    changed_file_count: int
    removed_file_count: int


@dataclass(frozen=True, slots=True)
class _StoredState:
    owned: dict[str, str]
    pending: dict[str, object] | None
    last_error_code: str | None
    last_success_at: str | None


class ContextVaultPublicationStateStore:
    """Keep ownership and pending hashes in APEX's local SQLite state."""

    def __init__(self, database_path: str | Path) -> None:
        self._path = Path(database_path).expanduser()
        if not self._path.is_absolute():
            raise ContextVaultPublicationError("state_path_invalid")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS context_vault_publication_state ("
                    "destination_key TEXT PRIMARY KEY NOT NULL, "
                    "owned_files_json TEXT NOT NULL DEFAULT '{}', "
                    "pending_json TEXT, last_error_code TEXT, last_success_at TEXT)"
                )
        except (OSError, sqlite3.Error):
            raise ContextVaultPublicationError("state_unavailable") from None

    def load(self, destination_key: str) -> _StoredState:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT owned_files_json,pending_json,last_error_code,last_success_at "
                    "FROM context_vault_publication_state WHERE destination_key=?",
                    (destination_key,),
                ).fetchone()
            if row is None:
                return _StoredState({}, None, None, None)
            owned = json.loads(str(row[0]))
            pending = json.loads(str(row[1])) if row[1] is not None else None
            if not isinstance(owned, dict) or (pending is not None and not isinstance(pending, dict)):
                raise ValueError("invalid state shape")
            return _StoredState(
                owned={str(path): str(digest) for path, digest in owned.items()},
                pending=pending,
                last_error_code=str(row[2]) if row[2] else None,
                last_success_at=str(row[3]) if row[3] else None,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise ContextVaultPublicationError("state_unavailable") from None

    @staticmethod
    def read_last_successful_projection(
        database_path: str | Path, destination_key: str,
    ) -> dict[str, str] | None:
        """Read the last successful owned projection without creating or changing state."""
        path = Path(database_path).expanduser()
        if not path.is_absolute():
            raise ContextVaultPublicationError("state_path_invalid")
        try:
            if not path.is_file():
                return None
            uri = f"{path.resolve(strict=True).as_uri()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=10.0)
            try:
                conn.execute("PRAGMA query_only=ON")
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='context_vault_publication_state'"
                ).fetchone()
                if table is None:
                    return None
                row = conn.execute(
                    "SELECT owned_files_json,last_success_at "
                    "FROM context_vault_publication_state WHERE destination_key=?",
                    (destination_key,),
                ).fetchone()
                if row is None or not row[1]:
                    return None
                owned = json.loads(str(row[0]))
                return ContextVaultPublisher._hash_map(owned, allow_empty=True)
            finally:
                conn.close()
        except ContextVaultPublicationError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise ContextVaultPublicationError("state_unavailable") from None

    def save_pending(self, destination_key: str, pending: dict[str, object]) -> None:
        self._update(
            "INSERT INTO context_vault_publication_state(destination_key,owned_files_json,pending_json,last_error_code) "
            "VALUES (?,COALESCE((SELECT owned_files_json FROM context_vault_publication_state WHERE destination_key=?),'{}'),?,NULL) "
            "ON CONFLICT(destination_key) DO UPDATE SET pending_json=excluded.pending_json,last_error_code=NULL",
            (destination_key, destination_key, json.dumps(pending, sort_keys=True, separators=(",", ":"))),
        )

    def remove_pending_temp(self, destination_key: str, pending: dict[str, object]) -> None:
        self.save_pending(destination_key, pending)

    def mark_failure(self, destination_key: str, code: str) -> None:
        self._update(
            "INSERT INTO context_vault_publication_state(destination_key,owned_files_json,last_error_code) "
            "VALUES (?,'{}',?) ON CONFLICT(destination_key) DO UPDATE SET last_error_code=excluded.last_error_code",
            (destination_key, code),
        )

    def finish(self, destination_key: str, owned: dict[str, str]) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        self._update(
            "INSERT INTO context_vault_publication_state(destination_key,owned_files_json,pending_json,last_error_code,last_success_at) "
            "VALUES (?,?,NULL,NULL,?) ON CONFLICT(destination_key) DO UPDATE SET "
            "owned_files_json=excluded.owned_files_json,pending_json=NULL,last_error_code=NULL,last_success_at=excluded.last_success_at",
            (destination_key, json.dumps(owned, sort_keys=True, separators=(",", ":")), timestamp),
        )

    @staticmethod
    def public_state(state: _StoredState) -> ContextVaultPublicationState:
        return ContextVaultPublicationState(
            owned_files=tuple(sorted(state.owned.items())),
            pending=state.pending is not None,
            last_error_code=state.last_error_code,
            last_success_at=state.last_success_at,
        )

    def _update(self, sql: str, params: tuple[object, ...]) -> None:
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


class ContextVaultPublisher:
    """Atomically replace notes while touching only paths owned by this publisher."""

    def __init__(self, destination: str | Path, state_database_path: str | Path) -> None:
        destination_path = Path(destination).expanduser()
        if not destination_path.is_absolute():
            raise ContextVaultPublicationError("destination_invalid")
        self._root = Path(os.path.abspath(destination_path))
        self._destination_key = os.path.normcase(str(self._root))
        state_path = Path(state_database_path).expanduser()
        if not state_path.is_absolute():
            raise ContextVaultPublicationError("state_path_invalid")
        absolute_state = Path(os.path.abspath(state_path))
        try:
            roots = (str(self._root.resolve(strict=False)), str(absolute_state.resolve(strict=False)))
            if os.path.normcase(os.path.commonpath(roots)) == os.path.normcase(roots[0]):
                raise ContextVaultPublicationError("state_inside_vault")
        except ValueError:
            pass
        self._state = ContextVaultPublicationStateStore(absolute_state)

    def state(self) -> ContextVaultPublicationState:
        return self._state.public_state(self._load_validated())

    def remove_managed(self) -> ContextVaultPublishResult:
        """Remove only files recorded as APEX-owned, without pruning directories."""
        try:
            state = self._load_validated()
            pending = state.pending or {}
            desired = self._hash_map(pending.get("desired", {}), allow_empty=True)
            published = self._hash_map(pending.get("published", {}), allow_empty=True)
            pending_removed = self._path_list(pending.get("removed", []))
            known_owned = set(state.owned) | set(published) | pending_removed
            temporaries = self._temp_map(pending.get("temps", {}))

            self._validate_directory_chain(self._root)
            self._validate_paths(known_owned | set(desired))
            self._validate_temp_paths(temporaries)
            for relative, digest in desired.items():
                target = self._path(relative)
                if (
                    relative not in known_owned
                    and os.path.lexists(target)
                    and self._file_hash(target) == digest
                ):
                    known_owned.add(relative)

            # Validate every generated target before deleting the first one. A
            # failure leaves ownership state intact so a later retry can finish.
            targets = [self._path(relative) for relative in sorted(known_owned)]
            for target in targets:
                if os.path.lexists(target):
                    self._validate_regular_file(target)
            self._cleanup_pending_temps(temporaries)
            removed = 0
            for target in targets:
                if os.path.lexists(target):
                    target.unlink()
                    removed += 1
            self._state.finish(self._destination_key, {})
            return ContextVaultPublishResult(
                owned_file_count=0,
                changed_file_count=0,
                removed_file_count=removed,
            )
        except ContextVaultPublicationError as exc:
            self._record_failure(exc.code)
            raise
        except Exception:
            self._record_failure("publication_failed")
            raise ContextVaultPublicationError("publication_failed") from None

    def publish(self, files: Mapping[str, str]) -> ContextVaultPublishResult:
        try:
            desired = self._validate_projection(files)
            state = self._load_validated()
            previous_owned = set(state.owned)
            previous_pending = state.pending or {}
            pending_desired = self._hash_map(previous_pending.get("desired", {}), allow_empty=True)
            pending_published = self._hash_map(previous_pending.get("published", {}), allow_empty=True)
            # Keep ownership of paths awaiting removal across retries. Pending
            # desired intent alone cannot establish ownership of unwritten files.
            pending_removed = self._path_list(previous_pending.get("removed", []))
            known_owned = previous_owned | set(pending_published) | pending_removed
            pending_temps = self._temp_map(previous_pending.get("temps", {}))

            self._validate_directory_chain(self._root)
            self._validate_paths((*known_owned, *pending_desired, *desired))
            self._validate_temp_paths(pending_temps)
            self._cleanup_pending_temps(pending_temps)

            # A pending projection records intent before publication. Promote a
            # new path to owned only if its completion marker or exact expected
            # bytes prove that APEX already wrote it.
            for relative, digest in pending_desired.items():
                target = self._path(relative)
                if (
                    relative not in known_owned
                    and os.path.lexists(target)
                    and self._file_hash(target) == digest
                ):
                    known_owned.add(relative)

            for relative in desired:
                target = self._path(relative)
                if os.path.lexists(target) and relative not in known_owned:
                    raise ContextVaultPublicationError("unowned_collision")
            for relative in known_owned:
                target = self._path(relative)
                if os.path.lexists(target):
                    self._validate_regular_file(target)

            removed = sorted(known_owned - set(desired))
            pending: dict[str, object] = {
                "version": 1,
                "desired": desired,
                "removed": removed,
                "published": {},
                "temps": {},
            }
            self._state.save_pending(self._destination_key, pending)

            self._ensure_directory_chain(self._root)
            changed = 0
            ordered_paths = sorted(
                desired,
                key=lambda item: (self._is_index(item), item == "index.md", item),
            )
            index_paths = [path for path in ordered_paths if self._is_index(path)]
            content_paths = [path for path in ordered_paths if not self._is_index(path)]
            for relative in (*content_paths,):
                if self._write_if_changed(relative, files[relative], pending):
                    changed += 1

            removed_count = 0
            for relative in removed:
                target = self._path(relative)
                if os.path.lexists(target):
                    self._validate_regular_file(target)
                    target.unlink()
                    removed_count += 1

            for relative in sorted(index_paths, key=lambda item: (item == "index.md", item)):
                if self._write_if_changed(relative, files[relative], pending):
                    changed += 1

            self._state.finish(self._destination_key, desired)
            return ContextVaultPublishResult(
                owned_file_count=len(desired),
                changed_file_count=changed,
                removed_file_count=removed_count,
            )
        except ContextVaultPublicationError as exc:
            self._record_failure(exc.code)
            raise
        except Exception:
            self._record_failure("publication_failed")
            raise ContextVaultPublicationError("publication_failed") from None

    def _write_if_changed(self, relative: str, text: str, pending: dict[str, object]) -> bool:
        content = text.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        target = self._path(relative)
        self._ensure_parent_directories(target.parent)
        if os.path.lexists(target):
            self._validate_regular_file(target)
            if self._file_hash(target) == digest:
                self._mark_published(relative, digest, pending)
                return False

        temp_mapping = pending.get("temps")
        if not isinstance(temp_mapping, dict):
            raise ContextVaultPublicationError("state_unavailable")
        for _ in range(8):
            temp_relative = self._temporary_sibling(relative)
            temp_path = self._temporary_path(relative, temp_relative)
            try:
                descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            except OSError:
                raise ContextVaultPublicationError("destination_unavailable") from None
            registered = False
            try:
                temp_mapping[relative] = temp_relative
                self._state.save_pending(self._destination_key, pending)
                registered = True
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._atomic_replace(temp_path, target)
                self._mark_published(relative, digest, pending)
            except Exception:
                try:
                    if os.path.lexists(temp_path):
                        self._validate_regular_file(temp_path)
                        temp_path.unlink()
                except (OSError, ContextVaultPublicationError):
                    pass
                raise
            finally:
                if not registered:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                    temp_mapping.pop(relative, None)
                else:
                    temp_mapping.pop(relative, None)
                    self._state.remove_pending_temp(self._destination_key, pending)
            return True
        raise ContextVaultPublicationError("temporary_path_unavailable")

    @staticmethod
    def _atomic_replace(source: Path, target: Path) -> None:
        os.replace(source, target)

    @staticmethod
    def _file_hash(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            raise ContextVaultPublicationError("destination_unavailable") from None

    def _mark_published(self, relative: str, digest: str, pending: dict[str, object]) -> None:
        published = pending.get("published")
        if not isinstance(published, dict):
            raise ContextVaultPublicationError("state_unavailable")
        published[relative] = digest
        self._state.save_pending(self._destination_key, pending)

    def _load_validated(self) -> _StoredState:
        state = self._state.load(self._destination_key)
        self._hash_map(state.owned, allow_empty=True)
        pending = state.pending
        if pending is not None:
            if pending.get("version") != 1:
                raise ContextVaultPublicationError("state_unavailable")
            desired = self._hash_map(pending.get("desired"), allow_empty=True)
            self._path_list(pending.get("removed"))
            published = self._hash_map(pending.get("published", {}), allow_empty=True)
            if any(path not in desired or desired[path] != digest for path, digest in published.items()):
                raise ContextVaultPublicationError("state_unavailable")
            self._temp_map(pending.get("temps"))
        return state

    def _validate_projection(self, files: Mapping[str, str]) -> dict[str, str]:
        if "index.md" not in files or any(not isinstance(text, str) for text in files.values()):
            raise ContextVaultPublicationError("projection_invalid")
        normalized: dict[str, str] = {}
        for relative, text in files.items():
            safe = self._validate_relative_path(relative)
            if safe in normalized:
                raise ContextVaultPublicationError("projection_invalid")
            normalized[safe] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return dict(sorted(normalized.items()))

    @staticmethod
    def _validate_relative_path(relative: object) -> str:
        if not isinstance(relative, str) or not relative or "\\" in relative or relative.startswith("/"):
            raise ContextVaultPublicationError("unsafe_path")
        path = PurePosixPath(relative)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != relative:
            raise ContextVaultPublicationError("unsafe_path")
        if relative == "index.md":
            return relative
        parts = path.parts
        if len(parts) not in {3, 4} or parts[0] != "scopes":
            raise ContextVaultPublicationError("unsafe_path")
        if not ContextVaultPublisher._is_uuid(parts[1]):
            raise ContextVaultPublicationError("unsafe_path")
        if len(parts) == 3 and parts[2] == "index.md":
            return relative
        if len(parts) == 4 and parts[2] in {"entities", "records"} and parts[3].endswith(".md"):
            if ContextVaultPublisher._is_uuid(parts[3][:-3]):
                return relative
        raise ContextVaultPublicationError("unsafe_path")

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            return str(UUID(value)) == value
        except ValueError:
            return False

    @classmethod
    def _hash_map(cls, value: object, *, allow_empty: bool) -> dict[str, str]:
        if not isinstance(value, dict) or (not allow_empty and not value):
            raise ContextVaultPublicationError("state_unavailable")
        checked: dict[str, str] = {}
        for relative, digest in value.items():
            path = cls._validate_relative_path(relative)
            if not isinstance(digest, str) or not _HEX_DIGEST.fullmatch(digest):
                raise ContextVaultPublicationError("state_unavailable")
            checked[path] = digest
        return checked

    @classmethod
    def _path_list(cls, value: object) -> set[str]:
        if not isinstance(value, list):
            raise ContextVaultPublicationError("state_unavailable")
        return {cls._validate_relative_path(path) for path in value}

    @classmethod
    def _temp_map(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            raise ContextVaultPublicationError("state_unavailable")
        checked: dict[str, str] = {}
        for target, temporary in value.items():
            target_path = PurePosixPath(cls._validate_relative_path(target))
            if not isinstance(temporary, str) or "\\" in temporary:
                raise ContextVaultPublicationError("state_unavailable")
            temp_path = PurePosixPath(temporary)
            if (
                temp_path.parent != target_path.parent
                or not _TEMP_NAME.fullmatch(temp_path.name)
                or temp_path.as_posix() != temporary
            ):
                raise ContextVaultPublicationError("state_unavailable")
            checked[str(target)] = temporary
        return checked

    @classmethod
    def _temporary_sibling(cls, relative: str) -> str:
        target = PurePosixPath(cls._validate_relative_path(relative))
        return (target.parent / f".apex-context-vault-tmp-{uuid4().hex}.tmp").as_posix()

    @staticmethod
    def _is_index(relative: str) -> bool:
        return relative == "index.md" or relative.endswith("/index.md")

    def _path(self, relative: str) -> Path:
        safe = self._validate_relative_path(relative)
        return self._root.joinpath(*PurePosixPath(safe).parts)

    def _temporary_path(self, owner: str, relative: str) -> Path:
        safe_owner = self._validate_relative_path(owner)
        self._temp_map({safe_owner: relative})
        return self._root.joinpath(*PurePosixPath(relative).parts)

    def _validate_paths(self, relatives: tuple[str, ...] | list[str] | set[str]) -> None:
        for relative in relatives:
            target = self._path(relative)
            self._validate_directory_chain(target.parent)
            if os.path.lexists(target):
                self._validate_regular_file(target)

    def _validate_temp_paths(self, temporaries: dict[str, str]) -> None:
        for owner, relative in temporaries.items():
            target = self._temporary_path(owner, relative)
            self._validate_directory_chain(target.parent)
            if os.path.lexists(target):
                self._validate_regular_file(target)

    def _cleanup_pending_temps(self, temporaries: dict[str, str]) -> None:
        for owner, relative in temporaries.items():
            path = self._temporary_path(owner, relative)
            if os.path.lexists(path):
                self._validate_regular_file(path)
                path.unlink()

    def _validate_directory_chain(self, path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            if not os.path.lexists(current):
                break
            info = self._lstat(current)
            if self._is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise ContextVaultPublicationError("unsafe_path")

    def _ensure_directory_chain(self, path: Path) -> None:
        absolute = Path(os.path.abspath(path))
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current = current / part
            if os.path.lexists(current):
                info = self._lstat(current)
                if self._is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                    raise ContextVaultPublicationError("unsafe_path")
            else:
                try:
                    current.mkdir()
                except OSError:
                    if not os.path.lexists(current):
                        raise ContextVaultPublicationError("destination_unavailable") from None
                    info = self._lstat(current)
                    if self._is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                        raise ContextVaultPublicationError("unsafe_path")

    def _ensure_parent_directories(self, path: Path) -> None:
        self._ensure_directory_chain(path)

    @staticmethod
    def _lstat(path: Path) -> os.stat_result:
        try:
            return path.lstat()
        except OSError:
            raise ContextVaultPublicationError("destination_unavailable") from None

    @staticmethod
    def _is_reparse(info: os.stat_result) -> bool:
        attributes = getattr(info, "st_file_attributes", 0)
        return stat.S_ISLNK(info.st_mode) or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)

    def _validate_regular_file(self, path: Path) -> None:
        info = self._lstat(path)
        if self._is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise ContextVaultPublicationError("unsafe_path")

    def _record_failure(self, code: str) -> None:
        try:
            self._state.mark_failure(self._destination_key, code)
        except ContextVaultPublicationError:
            pass
