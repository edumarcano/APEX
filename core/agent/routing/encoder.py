"""Text encoder protocol for semantic tool routing."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import numpy as np


class TextEncoder(Protocol):
    @property
    def model_key(self) -> str: ...

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray: ...

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray: ...
