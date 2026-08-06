#!/usr/bin/env python3
"""Run quality and runtime benchmarks sequentially."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ROOT = Path(__file__).resolve().parent


def main() -> int:
    commands = [
        [sys.executable, str(ROOT / "benchmark_quality.py"), "--split", "dev", "--all-candidates"],
        [sys.executable, str(ROOT / "benchmark_quality.py"), "--split", "test", "--all-candidates"],
        [sys.executable, str(ROOT / "benchmark_runtime.py"), "--all-candidates"],
    ]
    for command in commands:
        print("Running:", " ".join(command))
        subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
