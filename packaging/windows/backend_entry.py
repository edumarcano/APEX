"""Frozen executable entrypoint for the APEX backend host."""

from multiprocessing import freeze_support
from pathlib import Path
import sys


def main() -> int:
    freeze_support()
    if not getattr(sys, "frozen", False):
        root = Path(__file__).resolve().parents[2]
        sys.path[:0] = [str(root), str(root / "src")]
    from core.backend_host import main as backend_main

    return backend_main()


if __name__ == "__main__":
    raise SystemExit(main())
