"""Keep eSpeak's Windows data lookup compatible with Unicode install paths."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
from typing import Callable


def _get_short_path_name(path: str) -> str | None:
    """Return Windows' existing short path alias, when one is available."""
    if sys.platform != "win32":
        return None

    get_short_path_name = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
    get_short_path_name.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_short_path_name.restype = ctypes.c_uint32
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_short_path_name(path, buffer, len(buffer))
    if length == 0 or length >= len(buffer):
        return None
    return buffer.value


def _resolve_data_path(
    data_path: str | os.PathLike[str],
    *,
    short_path_resolver: Callable[[str], str | None] = _get_short_path_name,
) -> str:
    """Return a verified ASCII path for the narrow-path eSpeak native API."""
    original = os.fspath(data_path)
    original_path = Path(original)
    phontab = original_path / "phontab"
    if not original_path.is_dir() or not phontab.is_file():
        raise RuntimeError("The bundled eSpeak NG data directory is missing phontab.")

    if original.isascii():
        return original

    alias = short_path_resolver(original)
    if not alias or not alias.isascii():
        raise _ascii_alias_error()

    alias_path = Path(alias)
    if not alias_path.is_dir() or not (alias_path / "phontab").is_file():
        raise _ascii_alias_error()
    try:
        same_directory = os.path.samefile(original_path, alias_path)
    except OSError:
        same_directory = False
    if not same_directory:
        raise _ascii_alias_error()
    return alias


def _ascii_alias_error() -> RuntimeError:
    return RuntimeError(
        "Kokoro's eSpeak data path has non-ASCII characters and Windows has no "
        "verified ASCII short-path alias. Install APEX under an ASCII-only path "
        "such as C:\\Apps\\APEX, then retry."
    )


def _patch_loader(loader: object, *, short_path_resolver: Callable[[str], str | None] = _get_short_path_name) -> None:
    original_get_data_path = loader.get_data_path

    def get_frozen_data_path() -> str:
        # Resolve lazily when Kokoro asks for eSpeak data; do not probe or load
        # model assets during the frozen backend's startup.
        return _resolve_data_path(original_get_data_path(), short_path_resolver=short_path_resolver)

    loader.get_data_path = get_frozen_data_path


if sys.platform == "win32" and getattr(sys, "frozen", False):
    import espeakng_loader

    _patch_loader(espeakng_loader)
