"""Bounded retry helpers shared by inference providers."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

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
    check: Callable[[], None] | None = None,
    before_retry: Callable[[int], None] | None = None,
    remaining_seconds: Callable[[], float | None] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    execution_control: Any | None = None,
    wait_fn: Callable[[float], None] | None = None,
) -> tuple[T, int]:
    """Run ``operation`` with bounded retries.

    Returns ``(result, retry_count)`` where ``retry_count`` is the number of
    failed attempts before the successful call (0 on first-try success).
    The final failure re-raises the last exception.
    """
    if execution_control is not None:
        check = check or getattr(execution_control, "before_provider_attempt", None)
        before_retry = before_retry or getattr(execution_control, "before_retry", None)
        remaining_seconds = remaining_seconds or getattr(execution_control, "remaining_seconds", None)
        wait_fn = wait_fn or getattr(execution_control, "wait_retry", None)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    for attempt in range(max_attempts):
        if check is not None:
            check()
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
            if remaining_seconds is not None:
                remaining = remaining_seconds()
                if remaining is not None and remaining <= 0:
                    if check is not None:
                        check()
                    if wait_fn is not None:
                        wait_fn(0)
                    raise TimeoutError(f"{log_label} retry deadline exceeded")
                if remaining is not None and delay >= remaining:
                    if wait_fn is not None:
                        wait_fn(delay)
                    if check is not None:
                        check()
                    raise TimeoutError(f"{log_label} retry wait exceeds deadline")
            if check is not None:
                # Cancellation that happened while the failed request was
                # unwinding must not be charged as a retry that never starts.
                check()
            if before_retry is not None:
                # Charge this retry immediately before its interruptible wait.
                before_retry(attempt + 1)
            _LOGGER.warning(
                "%s request failed (%s); retrying in %.2fs (attempt %d/%d)",
                log_label,
                type(exc).__name__,
                delay,
                attempt + 1,
                max_attempts,
            )
            if sleep_fn is not None:
                sleep_fn(delay)
            elif wait_fn is not None:
                wait_fn(delay)
            elif execution_control is not None and hasattr(execution_control, "cancel_event"):
                # Event.wait provides a cooperative, interruptible backoff.
                execution_control.cancel_event.wait(delay)
            else:
                time.sleep(delay)
            if check is not None:
                check()

    raise RuntimeError(f"{log_label} retry loop exited without a result.")


def _default_wait_seconds(attempt: int) -> float:
    return (1.0 * (2**attempt)) + random.uniform(0, 0.5)


def exponential_backoff_seconds(attempt: int, *, base: float = 1.0) -> float:
    """Exponential backoff with jitter for rate-limit style failures."""
    return (base * (2**attempt)) + random.uniform(0, 0.5)


def fixed_backoff_seconds(_attempt: int, *, delay: float = 2.0) -> float:
    """Fixed delay used for transient server errors."""
    return delay
