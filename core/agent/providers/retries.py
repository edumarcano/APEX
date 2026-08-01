"""Bounded retry helpers shared by inference providers."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

_LOGGER = logging.getLogger(__name__)
T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 3


def call_with_bounded_retries(
    operation: Callable[[], T],
    *,
    is_retryable: Callable[[BaseException], bool],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    wait_seconds: Callable[[int, BaseException], float] | None = None,
    log_label: str = "provider",
) -> tuple[T, int]:
    """Run ``operation`` with bounded retries.

    Returns ``(result, retry_count)`` where ``retry_count`` is the number of
    failed attempts before the successful call (0 on first-try success).
    The final failure re-raises the last exception.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    for attempt in range(max_attempts):
        try:
            return operation(), attempt
        except Exception as exc:
            if attempt >= max_attempts - 1 or not is_retryable(exc):
                raise
            delay = (
                wait_seconds(attempt, exc)
                if wait_seconds is not None
                else _default_wait_seconds(attempt)
            )
            _LOGGER.warning(
                "%s request failed (%s); retrying in %.2fs (attempt %d/%d)",
                log_label,
                type(exc).__name__,
                delay,
                attempt + 1,
                max_attempts,
            )
            time.sleep(delay)

    raise RuntimeError(f"{log_label} retry loop exited without a result.")


def _default_wait_seconds(attempt: int) -> float:
    return (1.0 * (2**attempt)) + random.uniform(0, 0.5)


def exponential_backoff_seconds(attempt: int, *, base: float = 1.0) -> float:
    """Exponential backoff with jitter for rate-limit style failures."""
    return (base * (2**attempt)) + random.uniform(0, 0.5)


def fixed_backoff_seconds(_attempt: int, *, delay: float = 2.0) -> float:
    """Fixed delay used for transient server errors."""
    return delay
