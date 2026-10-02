"""Command construction and allowlisted dispatch for frozen worker processes."""

from __future__ import annotations

import importlib
import sys

from core.host.processes import python_child_invocation


def worker_invocation(output_path: str) -> tuple[list[str], dict[str, str]]:
    """Build the worker command and environment with a directly owned Python child."""
    if getattr(sys, "frozen", False):
        arguments = ["worker", "speech-export", output_path]
    else:
        arguments = [
            "-m",
            "core.backend_host",
            "worker",
            "speech-export",
            output_path,
        ]
    return python_child_invocation(arguments)


def dispatch_worker(arguments: list[str]) -> int | None:
    """Dispatch a supported worker request, returning None for host commands.

    Worker dispatch deliberately has a closed worker-name allowlist. It also
    imports the worker implementation only after an explicit dispatch request,
    so the ordinary host startup does not load speaker or settings state.
    """
    if not arguments or arguments[0] != "worker":
        return None
    if len(arguments) < 2 or arguments[1] != "speech-export":
        return 2
    if len(arguments) != 3:
        return 2
    export_module = importlib.import_module("core.speaker_export")
    return export_module.main(arguments[2:])
