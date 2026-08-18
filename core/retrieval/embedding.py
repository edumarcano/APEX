"""Optional local embedding adapters with a deliberately narrow contract."""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path
from typing import Iterable, Protocol

_LOGGER = logging.getLogger(__name__)


class EmbeddingAdapter(Protocol):
    model_id: str
    dimension: int
    version: str

    def prepare(self) -> str: ...

    def embed(self, texts: Iterable[str], *, allow_download: bool = False) -> list[list[float]]: ...


class EmbeddingError(RuntimeError):
    """An embedding operation failed; callers expose only its stable category."""


class FastEmbedAdapter:
    """Lazy FastEmbed integration; normal retrieval never downloads weights."""

    model_id = "BAAI/bge-small-en-v1.5"
    dimension = 384

    def __init__(self, cache_dir: Path | str) -> None:
        self.cache_dir = Path(cache_dir)
        try:
            self.version = importlib.metadata.version("fastembed")
        except importlib.metadata.PackageNotFoundError:
            self.version = "unavailable"
        self._model = None

    @property
    def fingerprint(self) -> str:
        return f"{self.model_id}:{self.dimension}:{self.version}"

    def _load(self, *, allow_download: bool) -> object:
        if self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding
        except Exception as exc:  # pragma: no cover - dependency is optional in unit tests
            raise EmbeddingError("embedding_initialization_failed") from exc
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._model = TextEmbedding(
                model_name=self.model_id,
                cache_dir=str(self.cache_dir),
                local_files_only=not allow_download,
            )
        except Exception as exc:
            category = "model_download_failed" if allow_download else "embedding_initialization_failed"
            raise EmbeddingError(category) from exc
        return self._model

    def prepare(self) -> str:
        self._load(allow_download=True)
        return self.fingerprint

    def embed(self, texts: Iterable[str], *, allow_download: bool = False) -> list[list[float]]:
        model = self._load(allow_download=allow_download)
        try:
            values = model.embed(list(texts))
            return [list(vector) for vector in values]
        except Exception as exc:
            _LOGGER.debug("FastEmbed inference failed: category=embedding_inference_failed")
            raise EmbeddingError("embedding_inference_failed") from exc
