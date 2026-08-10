"""APEX test suite bootstrap."""

from __future__ import annotations

import os
import warnings

from starlette.exceptions import StarletteDeprecationWarning

# Keep third-party import diagnostics out of successful test output.  This is
# intentionally narrow: application warnings remain visible unless their
# owning negative-path test captures them.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
warnings.filterwarnings(
    "ignore",
    message=r"Using `httpx` with `starlette\.testclient` is deprecated.*",
    category=StarletteDeprecationWarning,
)
