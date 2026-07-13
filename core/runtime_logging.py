"""Shared logging bootstrap and per-briefing run ID context."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Callable, Iterator, ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")

_RUN_ID: ContextVar[str | None] = ContextVar("apex_run_id", default=None)
_BOOTSTRAPPED = False


class RunIdFilter(logging.Filter):
    """Inject the active briefing run ID into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _RUN_ID.get() or "-"  # type: ignore[attr-defined]
        return True


def get_run_id() -> str | None:
    """Return the active briefing run ID, if any."""
    return _RUN_ID.get()


def set_run_id(run_id: str | None) -> None:
    """Set the active briefing run ID for the current context."""
    _RUN_ID.set(run_id)


@contextmanager
def run_id_scope(run_id: str) -> Iterator[str]:
    """Bind ``run_id`` for the duration of a briefing pipeline run."""
    token = _RUN_ID.set(run_id)
    try:
        yield run_id
    finally:
        _RUN_ID.reset(token)


def bind_run_id_context(callback: Callable[_P, _R]) -> Callable[_P, _R]:
    """Bind the current run ID to ``callback`` for execution in another thread."""
    run_id = get_run_id()

    @wraps(callback)
    def bound(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        if run_id is None:
            return callback(*args, **kwargs)
        with run_id_scope(run_id):
            return callback(*args, **kwargs)

    return bound


def configure_logging(level: int = logging.INFO) -> None:
    """
    Configure a single stderr handler for APEX modules.

    Safe to call multiple times; subsequent calls are no-ops once configured.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    root = logging.getLogger()
    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(levelname)s [%(name)s] [run_id=%(run_id)s] %(message)s"
            )
        )
        handler.addFilter(RunIdFilter())
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.addFilter(RunIdFilter())

    root.setLevel(level)
    _BOOTSTRAPPED = True
