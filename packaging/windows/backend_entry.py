"""Frozen executable entrypoint for the APEX backend host."""

from multiprocessing import freeze_support
from pathlib import Path
import sys


def main() -> int:
    freeze_support()
    is_setup = len(sys.argv) > 1 and sys.argv[1] == "setup"
    if getattr(sys, "frozen", False) and not is_setup:
        # The frozen trace stalls in NumPy's native import while the managed
        # control thread reads piped stdin; preload before that thread starts.
        # Similar upstream report: https://github.com/numpy/numpy/issues/24290
        import numpy  # noqa: F401

    if not getattr(sys, "frozen", False):
        root = Path(__file__).resolve().parents[2]
        sys.path[:0] = [str(root), str(root / "src")]
    from core.backend_host import main as backend_main

    return backend_main()


if __name__ == "__main__":
    raise SystemExit(main())
