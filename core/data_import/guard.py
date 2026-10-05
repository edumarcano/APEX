"""Tiny startup guard that can run before configuration and store imports."""

from __future__ import annotations

from pathlib import Path


class ImportRecoveryRequired(RuntimeError):
    """The selected profile has an incomplete import transaction."""


def refuse_pending_import(data_root: Path) -> None:
    journal = data_root / ".apex-import-journal.json"
    try:
        journal.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ImportRecoveryRequired(
            "APEX data import recovery is required before this profile can start."
        ) from exc
    raise ImportRecoveryRequired(
        "APEX data import recovery is required before this profile can start."
    )


__all__ = ["ImportRecoveryRequired", "refuse_pending_import"]
