"""Cross-platform exclusive lease for one APEX writable data profile."""

from __future__ import annotations

import os
import errno
from pathlib import Path
from typing import BinaryIO


class ProfileAlreadyRunningError(RuntimeError):
    """The data profile is already leased by another process."""


class ProfileLock:
    """Hold an OS-managed, non-inheritable lock on ``.apex-host.lock``.

    The marker file is deliberately retained after release. Its presence does
    not indicate ownership; only the operating-system byte lock does.
    """

    def __init__(self, data_root: Path | str) -> None:
        self.data_root = Path(data_root).expanduser().resolve(strict=False)
        self.path = self.data_root / ".apex-host.lock"
        self._file: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        return self._file is not None

    def acquire(self) -> "ProfileLock":
        if self._file is not None:
            return self
        self.data_root.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b", buffering=0)
        try:
            os.set_inheritable(handle.fileno(), False)
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    if exc.errno in (errno.EACCES, errno.EDEADLK, errno.EAGAIN, errno.EPERM):
                        raise ProfileAlreadyRunningError(
                            "The selected APEX profile is already in use."
                        ) from exc
                    raise
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno in (errno.EACCES, errno.EAGAIN):
                        raise ProfileAlreadyRunningError(
                            "The selected APEX profile is already in use."
                        ) from exc
                    raise
            self._file = handle
            return self
        except BaseException:
            handle.close()
            raise

    def release(self) -> None:
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "ProfileLock":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


__all__ = ["ProfileAlreadyRunningError", "ProfileLock"]
