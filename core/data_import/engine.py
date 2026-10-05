"""Transactional, source-preserving copy import for APEX profiles."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager, ExitStack
from io import BytesIO, StringIO
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from core.host.profile_lock import ProfileAlreadyRunningError, ProfileLock
from core.persistence_validation import PersistenceValidationError, validate_persistence
from core.runtime_paths import RuntimePaths, resolve_runtime_paths

MAX_PREVIEW_BYTES = 64 * 1024
MAX_SOURCE_FILES = 100_000
JOURNAL_NAME = ".apex-import-journal.json"
MARKER_NAME = ".apex-setup.json"
_OPTIONAL_FILES = (
    "config.json", "config.local.json", ".env", "credentials.json", "token.json",
    "clients/.market_cache.json", "clients/.f1_cache.json", "clients/.football_cache.json",
)
_OPTIONAL_DIRS = ("weights/fastembed", "core/weights/kokoro")
_DATABASE = "apex_memory.db"
_DATABASE_NODES = (_DATABASE, _DATABASE + "-wal", _DATABASE + "-shm", _DATABASE + "-journal")


class ImportOperationError(RuntimeError):
    """An import operation failed with a safe, stable error code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha256(path: Path, progress: Callable[[int], None] | None = None) -> str:
    digest = hashlib.sha256()
    completed = 0
    with _guarded_read(path) as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            completed += len(block)
            if progress:
                progress(completed)
    return digest.hexdigest()


class _GuardedFile:
    """Open a source file while denying concurrent writes on Windows."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        _assert_no_reparse_ancestry(self.path)
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                               ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                               ctypes.c_void_p]
            create.restype = ctypes.c_void_p
            handle = create(str(self.path), 0x80000000, 0x00000001, None, 3, 0x08200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ImportOperationError("source_busy_or_unreadable")
            import msvcrt
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | getattr(os, "O_BINARY", 0))
            if getattr(os.fstat(fd), "st_file_attributes", 0) & 0x400:
                os.close(fd)
                raise ImportOperationError("path_reparse_point")
            self.handle = os.fdopen(fd, "rb")
        else:
            descriptor = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            if stat.S_ISLNK(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise ImportOperationError("path_reparse_point")
            self.handle = os.fdopen(descriptor, "rb")
        return self.handle

    def __exit__(self, *_args):
        if self.handle is not None:
            self.handle.close()


def _guarded_read(path: Path) -> _GuardedFile:
    return _GuardedFile(path)


def _read_guarded(path: Path) -> bytes:
    with _guarded_read(path) as source:
        return source.read()


def _safe_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _node_exists(path: Path) -> bool:
    """Detect files, directories, and dangling links without following them."""
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ImportOperationError("path_reparse_point") from exc


def _allowed_import_path(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if not parts or relative.is_absolute() or any(
        part in {"", ".", ".."} or ":" in part or "\\" in part for part in parts
    ):
        return False
    value = relative.as_posix()
    return (
        value in set(_OPTIONAL_FILES)
        or value == _DATABASE
        or value == MARKER_NAME
        or (len(parts) >= 3 and parts[:2] in (("weights", "fastembed"), ("core", "weights"))
            and (parts[:2] == ("weights", "fastembed") or parts[2] == "kokoro")
        )
    )


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ImportOperationError("source_inventory_unavailable") from exc
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _assert_no_reparse_ancestry(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if _node_exists(current) and _is_reparse(current):
            raise ImportOperationError("path_reparse_point")
    return absolute


@contextmanager
def _source_lease(root: Path):
    """Hold the existing host lease while inspecting and copying the source."""
    held = None
    if _node_exists(root / JOURNAL_NAME):
        raise ImportOperationError("source_recovery_required")
    lock_path = root / ".apex-host.lock"
    try:
        lock_path.lstat()
        lock_present = True
    except FileNotFoundError:
        lock_present = False
    except OSError as exc:
        raise ImportOperationError("source_activity_uncertain") from exc
    if lock_present:
        try:
            if _is_reparse(lock_path):
                raise ImportOperationError("source_activity_uncertain")
            handle = lock_path.open("r+b", buffering=0)
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError as exc:
                        raise ImportOperationError("source_active") from exc
                    held = (handle, "windows")
                else:
                    import fcntl
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError as exc:
                        raise ImportOperationError("source_active") from exc
                    held = (handle, "posix")
                if held is not None:
                    handle = None
            finally:
                if handle is not None:
                    handle.close()
        except ImportOperationError:
            raise
        except OSError as exc:
            raise ImportOperationError("source_activity_uncertain") from exc
    try:
        import psutil
    except ImportError as exc:
        if held:
            held[0].close()
        raise ImportOperationError("source_activity_uncertain") from exc
    expected = os.path.normcase(os.path.normpath(str(root.resolve(strict=True))))
    try:
        for process in psutil.process_iter(("name", "cmdline", "cwd")):
            try:
                if process.pid == os.getpid():
                    continue
                info = process.info
                name = str(info.get("name") or "").casefold()
                if not (name.startswith("python") or name.startswith("apex")):
                    continue
                cmdline = info.get("cmdline")
                if cmdline is None:
                    raise ImportOperationError("source_activity_uncertain")
                haystack = os.path.normcase(" ".join(str(part) for part in cmdline))
                cwd = os.path.normcase(str(info.get("cwd") or ""))
                relevant = any(token in haystack.casefold() for token in
                               ("launcher.py", "core.backend_host", "backend_entry", "uvicorn", "core.api.app"))
                process_data_root = None
                if relevant or name.startswith("apex"):
                    try:
                        process_data_root = process.environ().get("APEX_DATA_DIR")
                    except psutil.AccessDenied as exc:
                        raise ImportOperationError("source_activity_uncertain") from exc
                configured = (
                    os.path.normcase(os.path.normpath(str(Path(process_data_root).expanduser().resolve())))
                    if process_data_root else None
                )
                if configured == expected or (cwd == expected and relevant) or (expected in haystack and relevant):
                    if relevant or name.startswith("apex"):
                        raise ImportOperationError("source_active")
            except (psutil.AccessDenied, psutil.ZombieProcess) as exc:
                if str(process.name()).casefold().startswith(("python", "apex")):
                    raise ImportOperationError("source_activity_uncertain") from exc
            except psutil.NoSuchProcess:
                continue
    except ImportOperationError:
        if held:
            held[0].close()
        raise
    except Exception as exc:
        if held:
            held[0].close()
        raise ImportOperationError("source_activity_uncertain") from exc
    try:
        yield
    finally:
        if held:
            handle, kind = held
            try:
                handle.seek(0)
                if kind == "windows":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()


def _collect_paths(root: Path) -> list[Path]:
    candidates: list[Path] = [root / name for name in _OPTIONAL_FILES]
    candidates.extend(root / name for name in (_DATABASE, _DATABASE + "-wal", _DATABASE + "-shm", _DATABASE + "-journal"))
    for relative in _OPTIONAL_DIRS:
        directory = root / relative
        if _node_exists(directory):
            if _is_reparse(directory):
                raise ImportOperationError("source_reparse_point")
            for parent, dirs, files in os.walk(directory, followlinks=False):
                base = Path(parent)
                for name in dirs:
                    if _is_reparse(base / name):
                        raise ImportOperationError("source_reparse_point")
                for name in files:
                    file_path = base / name
                    if _is_reparse(file_path):
                        raise ImportOperationError("source_reparse_point")
                    candidates.append(file_path)
    unique: dict[str, Path] = {}
    for path in candidates:
        _assert_no_reparse_ancestry(path)
        if _node_exists(path):
            if _is_reparse(path) or not path.is_file():
                raise ImportOperationError("source_reparse_point")
            unique[_safe_rel(path, root)] = path
    if len(unique) > MAX_SOURCE_FILES:
        raise ImportOperationError("source_inventory_too_large")
    return sorted(unique.values(), key=lambda item: _safe_rel(item, root))


def _inventory(
    root: Path,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, object]], str, list[Path], dict[str, str]]:
    files = _collect_paths(root)
    digest = hashlib.sha256()
    items_by_category: dict[str, dict[str, object]] = {}
    file_hashes: dict[str, str] = {}
    total_bytes = sum(path.stat().st_size for path in files)
    completed_bytes = 0
    for path in files:
        relative = _safe_rel(path, root)
        try:
            info = path.stat()
            last_report_bytes = 0
            last_report_time = time.monotonic()

            def report_file_progress(value: int) -> None:
                nonlocal last_report_bytes, last_report_time
                now = time.monotonic()
                if progress and (value - last_report_bytes >= 16 * 1024 * 1024 or now - last_report_time >= 0.5):
                    progress(completed_bytes + value, total_bytes)
                    last_report_bytes = value
                    last_report_time = now

            content_digest = _sha256(path, progress=report_file_progress)
            file_hashes[relative] = content_digest
            after = path.stat()
            if (info.st_size, info.st_mtime_ns, info.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino
            ):
                raise ImportOperationError("source_changed")
        except ImportOperationError:
            raise
        except OSError as exc:
            raise ImportOperationError("source_busy_or_unreadable") from exc
        category = (
            "database" if relative.startswith(_DATABASE) else
            "configuration" if relative in {"config.json", "config.local.json"} else
            "credentials" if relative in {".env", "credentials.json", "token.json"} else
            "cache" if relative.startswith("clients/") else
            "managed_weights"
        )
        if relative.startswith(_DATABASE):
            display_path = "apex_memory.db + SQLite sidecars"
        elif relative.startswith("weights/fastembed/"):
            display_path = "weights/fastembed"
        elif relative.startswith("core/weights/kokoro/"):
            display_path = "core/weights/kokoro"
        else:
            display_path = relative
        row_key = display_path
        row = items_by_category.setdefault(row_key, {
            "path": display_path, "category": category, "disposition": "copy",
            "file_count": 0, "total_bytes": 0,
        })
        row["file_count"] = int(row["file_count"]) + 1
        row["total_bytes"] = int(row["total_bytes"]) + info.st_size
        digest.update(
            relative.encode("utf-8") + b"\0" + str(info.st_size).encode() + b"\0"
            + str(info.st_mtime_ns).encode() + b"\0" + str(info.st_ino).encode() + b"\n"
        )
        digest.update(content_digest.encode("ascii") + b"\n")
        completed_bytes += info.st_size
        if progress:
            progress(completed_bytes, total_bytes)
    return list(items_by_category.values()), digest.hexdigest(), files, file_hashes


def _db_compatibility(
    source: Path,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[bool, bool]:
    db = source / _DATABASE
    if not db.is_file():
        return False, False
    scratch = Path(tempfile.mkdtemp(prefix="apex-import-check-"))
    try:
        source_bytes = sum(
            (source / name).stat().st_size
            for name in (_DATABASE, _DATABASE + "-wal", _DATABASE + "-shm", _DATABASE + "-journal")
            if _node_exists(source / name)
        )
        _copy_database_to_scratch(
            source, scratch / _DATABASE,
            progress=progress,
        )
        conn = sqlite3.connect(f"{(scratch / _DATABASE).as_uri()}?mode=ro", uri=True)
        try:
            retrieval_ok = validate_persistence(conn, check_integrity=True)
        except PersistenceValidationError:
            return False, False
        finally:
            conn.close()
        return True, retrieval_ok
    except (OSError, sqlite3.Error, ImportOperationError):
        return False, False
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _copy_database_to_scratch(
    source_root: Path,
    target: Path,
    *,
    progress: Callable[[str, int, int], None] | None = None,
) -> None:
    """Transport stable SQLite bytes to scratch, then back up transactionally."""
    names = (_DATABASE, _DATABASE + "-wal", _DATABASE + "-shm", _DATABASE + "-journal")
    transport = target.parent / "transport"
    transport.mkdir(parents=True, exist_ok=True)
    transported = 0
    with ExitStack() as stack:
        locked: list[tuple[Path, object, os.stat_result]] = []
        for name in names:
            source = source_root / name
            if _node_exists(source):
                before = source.stat()
                stream = stack.enter_context(_guarded_read(source))
                locked.append((source, stream, before))
        transport_total = sum(before.st_size for _path, _stream, before in locked)
        for source, stream, before in locked:
            output_path = transport / source.name
            with output_path.open("xb") as output:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    transported += len(block)
                    if progress:
                        progress("database_transport", transported, transport_total)
                output.flush()
                os.fsync(output.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ImportOperationError("source_changed")
    raw = transport / _DATABASE
    if not _node_exists(raw):
        raise ImportOperationError("source_database_missing")
    # This transport copy is private scratch. SQLite may recover a hot journal
    # here without opening the selected source in a modifying mode.
    source_conn = sqlite3.connect(raw, timeout=3.0)
    try:
        destination_conn = sqlite3.connect(target)
        try:
            page_size = int(source_conn.execute("PRAGMA page_size").fetchone()[0])
            total_pages = int(source_conn.execute("PRAGMA page_count").fetchone()[0])

            def backup_progress(_status: int, remaining: int, total_pages: int) -> None:
                if progress:
                    progress(
                        "database_backup",
                        (total_pages - remaining) * page_size,
                        total_pages * page_size,
                    )

            source_conn.backup(destination_conn, pages=512, progress=backup_progress, sleep=0.01)
            destination_conn.commit()
        finally:
            destination_conn.close()
    except sqlite3.Error as exc:
        raise ImportOperationError("source_database_unavailable") from exc
    finally:
        source_conn.close()
    shutil.rmtree(transport, ignore_errors=True)


_REFERENCE_LABELS = {
    "GOOGLE_APPLICATION_CREDENTIALS": "Google application credentials",
    "MICROSOFT_TODO_TOKEN_CACHE_PATH": "Microsoft authentication cache",
    "APEX_CONTEXT_VAULT_PATH": "Context Vault",
    "CUSTOM_BROWSER_PATH": "Custom browser",
}


def _reference_plan(
    paths: Iterable[Path], source: Path, destination: Path,
    *, expected_env_hash: str | None = None,
) -> tuple[list[str], list[dict[str, object]], bytes | None]:
    """Resolve only documented path keys; never traverse an external target."""
    source = source.resolve(strict=True)
    destination = destination.resolve(strict=False)
    files = list(paths)
    copied = {_safe_rel(path, source) for path in files}
    env_path = source / ".env"
    warnings: list[str] = []
    references: list[dict[str, object]] = []
    replacements: dict[str, str] = {}
    encoded: bytes | None = None
    if env_path in files:
        try:
            original_bytes = _read_guarded(env_path)
            if expected_env_hash is not None and hashlib.sha256(original_bytes).hexdigest() != expected_env_hash:
                raise ImportOperationError("source_changed")
            original = original_bytes.decode("utf-8")
            from dotenv import dotenv_values

            values = dotenv_values(stream=StringIO(original), interpolate=False)
        except ImportOperationError:
            raise
        except (OSError, UnicodeError, ImportError):
            return ["configuration_needs_review"], [], None
        for key, label in _REFERENCE_LABELS.items():
            raw = values.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            if re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*", raw):
                warnings.append(
                    "microsoft_cache_path_needs_review"
                    if key == "MICROSOFT_TODO_TOKEN_CACHE_PATH"
                    else "relative_credential_path_needs_review"
                    if key == "GOOGLE_APPLICATION_CREDENTIALS"
                    else "external_path_needs_review"
                )
                references.append({
                    "path": label,
                    "category": "credentials" if "credentials" in key.casefold() or "token" in key.casefold() else "configuration",
                    "disposition": "retain_external",
                    "file_count": 0,
                    "total_bytes": 0,
                })
                continue
            candidate = Path(raw.strip()).expanduser()
            if candidate.is_absolute():
                resolved = candidate.resolve(strict=False)
                inside_source = True
                try:
                    resolved.relative_to(source)
                except ValueError:
                    inside_source = False
            else:
                resolved = (source / candidate).resolve(strict=False)
                inside_source = True
            included = False
            if inside_source:
                try:
                    relative = _safe_rel(resolved, source)
                    included = relative in copied
                except ValueError:
                    included = False

            if key == "GOOGLE_APPLICATION_CREDENTIALS" and included:
                replacements[key] = str(destination / relative)
                continue
            if not candidate.is_absolute():
                replacements[key] = str(resolved)
            if key == "MICROSOFT_TODO_TOKEN_CACHE_PATH":
                warnings.append("microsoft_cache_path_needs_review")
            elif key == "GOOGLE_APPLICATION_CREDENTIALS":
                warnings.append("relative_credential_path_needs_review" if not candidate.is_absolute() else "external_path_needs_review")
            elif not inside_source or not included:
                warnings.append("external_path_needs_review")
            references.append({
                "path": label,
                "category": "credentials" if "credentials" in key.casefold() or "token" in key.casefold() else "configuration",
                "disposition": "retain_external",
                "file_count": 0,
                "total_bytes": 0,
            })

        rewritten: list[str] = []
        for line in original.splitlines(keepends=True):
            body = line.rstrip("\r\n")
            ending = line[len(body):]
            match = re.match(r"^(\s*(?:export\s+)?([A-Z0-9_]+)\s*=)(.*)$", body)
            if not match or match.group(2) not in replacements:
                rewritten.append(line)
                continue
            raw_value = match.group(3)
            suffix_match = re.search(r"\s+#.*$", raw_value)
            suffix = suffix_match.group(0) if suffix_match else ""
            rewritten_value = json.dumps(replacements[match.group(2)], ensure_ascii=False)
            rewritten.append(match.group(1) + rewritten_value + suffix + ending)
        encoded = "".join(rewritten).encode("utf-8")

    json_references = {
        ("llama_cpp", "executable_path"): "Local model executable",
        ("llama_cpp", "preset_path"): "Local model preset",
        ("activity_report_folder", "folder_path"): "Activity report folder",
    }
    for config_name in ("config.json", "config.local.json"):
        config_path = source / config_name
        if config_path not in files:
            continue
        try:
            config_value = json.loads(_read_guarded(config_path).decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            warnings.append("configuration_needs_review")
            continue
        for (parent_key, key), label in json_references.items():
            parent = config_value.get(parent_key) if isinstance(config_value, dict) else None
            raw = parent.get(key) if isinstance(parent, dict) else None
            if isinstance(raw, str) and raw.strip():
                references.append({
                    "path": label,
                    "category": "configuration",
                    "disposition": "retain_external",
                    "file_count": 0,
                    "total_bytes": 0,
                })
                warnings.append("external_path_needs_review")
    return list(dict.fromkeys(warnings)), references, encoded


class ImportEngine:
    """Operate on the selected destination profile without loading its .env."""

    def __init__(self, paths: RuntimePaths | None = None, *, progress: Callable[[str, int, int], None] | None = None):
        self.paths = paths or resolve_runtime_paths()
        self.requested_root = _assert_no_reparse_ancestry(self.paths.data_root)
        self.root = self.paths.data_root.resolve(strict=False)
        self.progress = progress or (lambda *_args: None)
        self.journal = self.root / JOURNAL_NAME

    def status(self) -> dict[str, object]:
        if _node_exists(self.journal):
            return {"phase": "recovery_required", "error_code": "import_recovery_required"}
        if any(_node_exists(self.root / name) for name in _DATABASE_NODES[1:]) and not _node_exists(self.root / _DATABASE):
            return {"phase": "choice_required", "error_code": "destination_database_exists"}
        marker = self.root / MARKER_NAME
        if _node_exists(marker):
            try:
                if _is_reparse(marker) or not marker.is_file():
                    raise ImportOperationError("setup_marker_invalid")
                value = json.loads(_read_guarded(marker).decode("utf-8"))
                if (
                    isinstance(value, dict)
                    and type(value.get("version")) is int
                    and value.get("version") == 1
                    and value.get("choice") == "fresh_start"
                    and set(value) == {"version", "choice"}
                ):
                    return {"phase": "ready", "error_code": None}
                if (
                    isinstance(value, dict)
                    and type(value.get("version")) is int
                    and value.get("version") == 1
                    and value.get("choice") == "import"
                    and set(value) == {"version", "choice", "id"}
                    and isinstance(value.get("id"), str)
                    and str(uuid.UUID(value["id"])) == value["id"]
                    and _node_exists(self.root / _DATABASE)
                    and (self.root / _DATABASE).is_file()
                ):
                    return {"phase": "ready", "error_code": None}
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, ValueError, TypeError, ImportOperationError):
                pass
            return {"phase": "recovery_required", "error_code": "setup_marker_invalid"}
        database = self.root / _DATABASE
        if _node_exists(database):
            if _is_reparse(database) or not database.is_file():
                return {"phase": "recovery_required", "error_code": "setup_marker_invalid"}
            return {"phase": "ready", "error_code": None}
        return {"phase": "choice_required", "error_code": None}

    def preview(self, source_dir: str) -> dict[str, object]:
        source = self._validate_source(source_dir)
        try:
            with _source_lease(source):
                return self._preview(source)
        except ImportOperationError as exc:
            if exc.code not in {
                "source_active", "source_activity_uncertain", "source_busy_or_unreadable",
                "source_recovery_required",
            }:
                raise
            return {
                "preview_id": "",
                "can_import": False,
                "items": [],
                "warnings": [],
                "blockers": [exc.code],
            }

    def _preview(self, source: Path) -> dict[str, object]:
        return self._preview_data(source)[0]

    def _preview_data(
        self, source: Path, *, check_database: bool = True,
    ) -> tuple[dict[str, object], str, list[Path], dict[str, str]]:
        self._assert_destination_safe()
        items, fingerprint, files, file_hashes = _inventory(
            source,
            progress=lambda completed, total: self.progress("inventory", completed, total),
        )
        blockers: list[str] = []
        warnings, references, _prepared_env = _reference_plan(files, source, self.root)
        if not any(_safe_rel(path, source) == _DATABASE for path in files):
            blockers.append("source_database_missing")
        elif check_database:
            core_ok, retrieval_ok = _db_compatibility(
                source,
                progress=lambda stage, completed, total: self.progress(
                    "database_preview_" + stage.removeprefix("database_"), completed, total
                ),
            )
            if not core_ok:
                blockers.append("source_database_incompatible")
            elif not retrieval_ok:
                warnings.append("retrieval_schema_unsupported")
        if any(_node_exists(self.root / name) for name in _DATABASE_NODES):
            blockers.append("destination_database_exists")
        if _node_exists(self.root / MARKER_NAME):
            blockers.append("destination_setup_marker_exists")
        for path in files:
            relative = _safe_rel(path, source)
            if relative == _DATABASE or relative.startswith(_DATABASE + "-"):
                continue
            destination = self.root.joinpath(*PurePosixPath(relative).parts)
            if _node_exists(destination):
                blockers.append("destination_path_exists")
                break
        for name in _OPTIONAL_FILES:
            if not _node_exists(source / name):
                category = (
                    "configuration" if name in {"config.json", "config.local.json"} else
                    "cache" if name.startswith("clients/") else "credentials"
                )
                items.append({"path": name, "category": category, "disposition": "missing", "file_count": 0, "total_bytes": 0})
        if not any(item["category"] == "database" for item in items):
            items.append({"path": _DATABASE, "category": "database", "disposition": "missing", "file_count": 0, "total_bytes": 0})
        for managed_dir in _OPTIONAL_DIRS:
            if not any(item["path"] == managed_dir for item in items):
                items.append({"path": managed_dir, "category": "managed_weights", "disposition": "missing", "file_count": 0, "total_bytes": 0})
        items.append({"path": "Microsoft authentication", "category": "credentials", "disposition": "reuse", "file_count": 0, "total_bytes": 0})
        items.extend(references)
        return ({
            "preview_id": self._preview_id(source, fingerprint),
            "can_import": not blockers,
            "items": items,
            "warnings": list(dict.fromkeys(warnings)),
            "blockers": list(dict.fromkeys(blockers)),
        }, fingerprint, files, file_hashes)

    def fresh_start(self) -> dict[str, object]:
        existing = self.status()
        if existing["phase"] == "ready":
            return existing
        if existing.get("error_code") == "setup_marker_invalid":
            raise ImportOperationError("setup_marker_invalid")
        if existing.get("error_code") == "destination_database_exists":
            raise ImportOperationError("destination_database_exists")
        self._assert_no_journal()
        with self._lease():
            self._assert_no_journal()
            if any(_node_exists(self.root / name) for name in _DATABASE_NODES):
                raise ImportOperationError("destination_database_exists")
            self.root.mkdir(parents=True, exist_ok=True)
            self._write_json_exclusive(self.root / MARKER_NAME, {"version": 1, "choice": "fresh_start"})
        return {"phase": "ready", "error_code": None}

    def import_data(self, source_dir: str, preview_id: str) -> dict[str, object]:
        source = self._validate_source(source_dir)
        with _source_lease(source), self._lease():
            self._assert_no_journal()
            current, approved_fingerprint, files, file_hashes = self._preview_data(
                source, check_database=False
            )
            if not current["can_import"]:
                for blocker in current["blockers"]:
                    if blocker in {"destination_database_exists", "destination_path_exists", "destination_setup_marker_exists"}:
                        raise ImportOperationError(str(blocker))
                raise ImportOperationError("import_blocked")
            if not isinstance(preview_id, str) or not hmac.compare_digest(preview_id, str(current["preview_id"])):
                raise ImportOperationError("preview_stale")
            if any(_node_exists(self.root / name) for name in _DATABASE_NODES):
                raise ImportOperationError("destination_database_exists")
            fingerprint = approved_fingerprint
            _reference_warnings, _references, prepared_env = _reference_plan(
                files, source, self.root, expected_env_hash=file_hashes.get(".env")
            )
            operation_id = str(uuid.uuid4())
            stage = self.root / f".apex-import-stage-{operation_id}"
            self.root.mkdir(parents=True, exist_ok=True)
            journal = {"version": 1, "id": operation_id, "phase": "staging", "source_fingerprint": fingerprint,
                       "stage": stage.name, "outputs": []}
            self._write_json_exclusive(self.journal, journal)
            stage.mkdir()
            (stage / ".owner").write_text(operation_id, encoding="ascii")
            expected_total = sum(path.stat().st_size for path in files if not _safe_rel(path, source).startswith(_DATABASE))
            if prepared_env is not None:
                source_env_size = next((path.stat().st_size for path in files if _safe_rel(path, source) == ".env"), 0)
                expected_total += len(prepared_env) - source_env_size
            completed = 0
            outputs: list[dict[str, str]] = []
            try:
                for source_file in files:
                    relative = _safe_rel(source_file, source)
                    if relative.startswith(_DATABASE):
                        continue
                    before = source_file.stat()
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    copied_hash = hashlib.sha256()
                    stream_context = (
                        BytesIO(prepared_env)
                        if relative == ".env" and prepared_env is not None
                        else _guarded_read(source_file)
                    )
                    with stream_context as stream, target.open("xb") as out:
                        last_emit = time.monotonic()
                        while True:
                            block = stream.read(1024 * 1024)
                            if not block:
                                break
                            out.write(block)
                            copied_hash.update(block)
                            completed += len(block)
                            now = time.monotonic()
                            if now - last_emit >= 0.25 or len(block) < 1024 * 1024:
                                self.progress("copying", completed, expected_total)
                                last_emit = now
                        out.flush()
                        os.fsync(out.fileno())
                    after = source_file.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ImportOperationError("source_changed")
                    expected_copy_hash = (
                        hashlib.sha256(prepared_env).hexdigest()
                        if relative == ".env" and prepared_env is not None
                        else file_hashes[relative]
                    )
                    if copied_hash.hexdigest() != expected_copy_hash:
                        raise ImportOperationError("source_changed")
                    outputs.append({"path": relative, "sha256": copied_hash.hexdigest()})
                    self.progress("copying", completed, expected_total)
                db_target = stage / _DATABASE
                def database_progress(stage_name: str, bytes_copied: int, total_bytes: int) -> None:
                    self.progress(stage_name, bytes_copied, total_bytes)

                _copy_database_to_scratch(source, db_target, progress=database_progress)
                conn = sqlite3.connect(f"{db_target.resolve().as_uri()}?mode=ro", uri=True)
                try:
                    retrieval_ok = validate_persistence(conn, check_integrity=True)
                except PersistenceValidationError as exc:
                    raise ImportOperationError(exc.code) from exc
                finally:
                    conn.close()
                outputs.append({"path": _DATABASE, "sha256": _sha256(db_target)})
                setup_marker = stage / MARKER_NAME
                self._write_json_exclusive(
                    setup_marker,
                    {"version": 1, "choice": "import", "id": operation_id},
                )
                outputs.append({"path": MARKER_NAME, "sha256": _sha256(setup_marker)})
                outputs.sort(key=lambda row: 2 if row["path"] == MARKER_NAME else 1 if row["path"] == _DATABASE else 0)
                # Verify the source again after all copies and SQLite backup.
                _items, final_fingerprint, _files, _hashes = _inventory(
                    source,
                    progress=lambda done, total: self.progress("inventory", done, total),
                )
                if final_fingerprint != approved_fingerprint:
                    raise ImportOperationError("source_changed")
                if any(_node_exists(self.root / name) for name in _DATABASE_NODES):
                    raise ImportOperationError("destination_database_exists")
                journal["phase"] = "committing"
                journal["outputs"] = outputs
                self._write_json_replace(self.journal, journal)
                for output in outputs:
                    source_staged = stage / output["path"]
                    destination = self.root / PurePosixPath(output["path"])
                    _assert_no_reparse_ancestry(destination.parent)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if _node_exists(destination):
                        raise ImportOperationError("destination_path_exists")
                    try:
                        os.link(source_staged, destination)
                    except FileExistsError as exc:
                        raise ImportOperationError("destination_path_exists") from exc
                    except (OSError, ImportOperationError):
                        # Exclusive creation never replaces a path; a crash leaves a
                        # partial file which recovery refuses to remove without proof.
                        with destination.open("xb") as out, source_staged.open("rb") as inp:
                            shutil.copyfileobj(inp, out, 1024 * 1024)
                            out.flush()
                            os.fsync(out.fileno())
                journal["phase"] = "committed"
                self._write_json_replace(self.journal, journal)
                self.journal.unlink()
                shutil.rmtree(stage, ignore_errors=True)
                if not retrieval_ok:
                    return {"phase": "ready", "error_code": "retrieval_schema_unsupported"}
                return {"phase": "ready", "error_code": None}
            except BaseException:
                # Leave the journal and stage intact for proof-based recovery.
                raise

    def recover(self) -> dict[str, object]:
        with self._lease():
            if not _node_exists(self.journal):
                return self.status()
            journal = self._read_journal()
            if journal.get("phase") == "committed":
                stage = self._owned_stage(journal)
                for row in journal["outputs"]:
                    relative = PurePosixPath(row["path"])
                    destination = self.root.joinpath(*relative.parts)
                    try:
                        _assert_no_reparse_ancestry(destination.parent)
                        if (
                            _is_reparse(destination)
                            or _sha256(destination) != row["sha256"]
                        ):
                            return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
                    except OSError:
                        return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
                marker = self.root / MARKER_NAME
                try:
                    marker_data = json.loads(_read_guarded(marker).decode("utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
                if (
                    not isinstance(marker_data, dict)
                    or set(marker_data) != {"version", "choice", "id"}
                    or type(marker_data.get("version")) is not int
                    or marker_data.get("version") != 1
                    or marker_data.get("choice") != "import"
                    or marker_data.get("id") != journal["id"]
                ):
                    return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
                self.journal.unlink()
                if stage is not None:
                    shutil.rmtree(stage, ignore_errors=True)
                return {"phase": "ready", "error_code": None}
            stage = self._owned_stage(journal)
            if stage is None:
                if journal.get("phase") == "staging" and journal.get("outputs") == [] and not _node_exists(self.root / str(journal.get("stage", ""))):
                    self.journal.unlink()
                    return {"phase": "choice_required", "error_code": None}
                return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
            outputs = journal.get("outputs", [])
            verified: list[Path] = []
            for row in outputs:
                relative = PurePosixPath(row["path"])
                staged = stage.joinpath(*relative.parts)
                destination = self.root.joinpath(*relative.parts)
                try:
                    _assert_no_reparse_ancestry(staged.parent)
                    _assert_no_reparse_ancestry(destination.parent)
                    if not _node_exists(destination):
                        continue
                    if (
                        _is_reparse(destination)
                        or _is_reparse(staged)
                        or not os.path.samefile(staged, destination)
                        or _sha256(destination) != row["sha256"]
                    ):
                        return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
                    verified.append(destination)
                except (OSError, ImportOperationError):
                    return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
            total = sum(
                (self.root / str(row.get("path", ""))).stat().st_size
                for row in outputs if isinstance(row, dict)
                and _node_exists(self.root / str(row.get("path", "")))
                and (self.root / str(row.get("path", ""))).is_file()
            )
            completed = 0
            for row in outputs:
                if not isinstance(row, dict) or not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
                    return {"phase": "recovery_required", "error_code": "import_journal_invalid"}
                relative = PurePosixPath(row["path"])
                if not _allowed_import_path(relative):
                    return {"phase": "recovery_required", "error_code": "import_journal_invalid"}
                staged = stage.joinpath(*relative.parts)
                destination = self.root.joinpath(*relative.parts)
                if _node_exists(destination):
                    try:
                        _assert_no_reparse_ancestry(staged.parent)
                        _assert_no_reparse_ancestry(destination.parent)
                        if _is_reparse(destination) or _is_reparse(staged):
                            return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
                        same_file = os.path.samefile(staged, destination)
                        unchanged = _sha256(
                            destination,
                            progress=lambda value: self.progress(
                                "recovery_verify", min(total, completed + value), total
                            ),
                        ) == row["sha256"]
                        completed += destination.stat().st_size
                    except (OSError, ImportOperationError):
                        same_file = unchanged = False
                    if not (same_file and unchanged):
                        return {"phase": "recovery_required", "error_code": "import_recovery_unproven"}
            for destination in verified:
                destination.unlink()
            self.journal.unlink()
            shutil.rmtree(stage, ignore_errors=True)
            return {"phase": "choice_required", "error_code": None}

    def _validate_source(self, raw: str) -> Path:
        if not isinstance(raw, str) or not raw or "\0" in raw:
            raise ImportOperationError("source_invalid")
        try:
            requested = _assert_no_reparse_ancestry(Path(raw))
            source = requested.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ImportOperationError("source_invalid") from exc
        if not source.is_dir() or source == self.root:
            raise ImportOperationError("source_invalid")
        try:
            self.root.relative_to(source)
        except ValueError:
            pass
        else:
            raise ImportOperationError("source_invalid")
        try:
            source.relative_to(self.root)
        except ValueError:
            pass
        else:
            raise ImportOperationError("source_invalid")
        installation = self.paths.installation_root
        if installation is not None:
            try:
                source.relative_to(installation.resolve())
            except ValueError:
                pass
            else:
                raise ImportOperationError("source_invalid")
        return source

    def _assert_destination_safe(self) -> None:
        _assert_no_reparse_ancestry(self.requested_root)

    def _preview_id(self, source: Path, fingerprint: str) -> str:
        value = f"{source}\0{self.root}\0{fingerprint}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()

    def _lease(self):
        self._assert_destination_safe()
        try:
            return ProfileLock(self.root).acquire()
        except ProfileAlreadyRunningError as exc:
            raise ImportOperationError("destination_active") from exc

    def _assert_no_journal(self) -> None:
        if _node_exists(self.journal):
            raise ImportOperationError("import_recovery_required")

    def _write_json_exclusive(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        owned = False
        try:
            with temp.open("xb") as output:
                owned = True
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            # Hard-link publication is atomic and fails if the destination
            # already exists, unlike replace/rename which could overwrite it.
            os.link(temp, path)
        finally:
            if owned:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass

    def _write_json_replace(self, path: Path, value: object) -> None:
        self._assert_destination_safe()
        if _node_exists(path) and _is_reparse(path):
            raise ImportOperationError("path_reparse_point")
        temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        owned = False
        try:
            with temp.open("xb") as output:
                owned = True
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, path)
        finally:
            if owned:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass

    def _read_journal(self) -> dict[str, object]:
        try:
            if _is_reparse(self.journal) or self.journal.stat().st_size > 16 * 1024 * 1024:
                raise ImportOperationError("import_journal_invalid")
            value = json.loads(_read_guarded(self.journal).decode("utf-8"))
        except ImportOperationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ImportOperationError("import_journal_invalid") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "id", "phase", "source_fingerprint", "stage", "outputs"}
            or type(value.get("version")) is not int
            or value.get("version") != 1
            or not isinstance(value.get("id"), str)
        ):
            raise ImportOperationError("import_journal_invalid")
        try:
            if str(uuid.UUID(value["id"])) != value["id"]:
                raise ValueError("noncanonical operation id")
        except (ValueError, TypeError, AttributeError) as exc:
            raise ImportOperationError("import_journal_invalid") from exc
        if value.get("stage") != f".apex-import-stage-{value['id']}":
            raise ImportOperationError("import_journal_invalid")
        if value.get("phase") not in {"staging", "committing", "committed"}:
            raise ImportOperationError("import_journal_invalid")
        fingerprint = value.get("source_fingerprint")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ImportOperationError("import_journal_invalid")
        outputs = value.get("outputs")
        if not isinstance(outputs, list):
            raise ImportOperationError("import_journal_invalid")
        paths: set[str] = set()
        for row in outputs:
            if (
                not isinstance(row, dict)
                or set(row) != {"path", "sha256"}
                or not isinstance(row.get("path"), str)
                or not isinstance(row.get("sha256"), str)
            ):
                raise ImportOperationError("import_journal_invalid")
            relative = PurePosixPath(row["path"])
            if not _allowed_import_path(relative) or row["path"] in paths:
                raise ImportOperationError("import_journal_invalid")
            if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                raise ImportOperationError("import_journal_invalid")
            paths.add(row["path"])
        if value["phase"] == "staging" and outputs:
            raise ImportOperationError("import_journal_invalid")
        if value["phase"] in {"committing", "committed"}:
            if (
                len(outputs) < 2
                or outputs[-2]["path"] != _DATABASE
                or outputs[-1]["path"] != MARKER_NAME
            ):
                raise ImportOperationError("import_journal_invalid")
        return value

    def _owned_stage(self, journal: dict[str, object]) -> Path | None:
        stage_name = journal.get("stage")
        operation_id = journal.get("id")
        if not isinstance(stage_name, str) or not isinstance(operation_id, str) or stage_name != f".apex-import-stage-{operation_id}":
            return None
        stage = self.root / stage_name
        try:
            _assert_no_reparse_ancestry(stage.parent)
            if _is_reparse(stage) or _is_reparse(stage / ".owner") or _read_guarded(stage / ".owner").decode("ascii") != operation_id:
                return None
        except OSError:
            return None
        return stage


__all__ = ["ImportEngine", "ImportOperationError"]
