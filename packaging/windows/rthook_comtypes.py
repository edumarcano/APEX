"""Keep generated SAPI wrappers in the user's temporary cache when frozen."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import types


if getattr(sys, "frozen", False):
    cache_name = f"python{sys.version_info.major}{sys.version_info.minor}-{os.getpid()}"
    wrapper_cache = Path(tempfile.gettempdir()) / "APEX" / "comtypes" / cache_name
    resolved_cache = wrapper_cache.resolve()
    for root in (getattr(sys, "_MEIPASS", None), Path(sys.executable).resolve().parent):
        if root is not None and resolved_cache.is_relative_to(Path(root).resolve()):
            raise RuntimeError("The SAPI wrapper cache cannot be inside the APEX installation.")
    wrapper_cache.mkdir(parents=True, exist_ok=True)
    cache_path = os.fspath(resolved_cache)

    def _cleanup_wrapper_cache() -> None:
        try:
            temp_root = Path(tempfile.gettempdir()).resolve()
            apex_root = temp_root / "APEX"
            comtypes_root = apex_root / "comtypes"
            if any(
                path.is_symlink() or path.is_junction()
                for path in (apex_root, comtypes_root, wrapper_cache)
            ):
                return
            expected_parent = comtypes_root.resolve()
            cleanup_path = wrapper_cache.resolve()
            if (
                wrapper_cache.name != cache_name
                or cleanup_path.name != cache_name
                or cleanup_path.parent != expected_parent
            ):
                return
            shutil.rmtree(cleanup_path)
        except OSError:
            # Wrapper cleanup is best effort and must never change shutdown behavior.
            pass

    import atexit

    atexit.register(_cleanup_wrapper_cache)

    import comtypes

    generated = types.ModuleType("comtypes.gen")
    generated.__package__ = "comtypes.gen"
    generated.__path__ = [cache_path]
    sys.modules["comtypes.gen"] = generated
    comtypes.gen = generated
