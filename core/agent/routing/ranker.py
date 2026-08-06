"""Semantic family ranker for production tool routing."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

from core.agent.routing.scoring import (
    build_family_vectors,
    rank_families_from_embeddings,
)
from core.agent.routing.context import build_routing_document
from core.agent.routing.encoder import TextEncoder
from core.agent.routing.families import CAPABILITY_FAMILIES
from core.agent.routing.model_manifest import PRODUCTION_MODEL_SPEC
from core.agent.routing.models import RankedCapabilityFamily
from core.agent.routing.onnx_encoder import get_onnx_encoder
from core.agent.types import AgentMessage

_LOGGER = logging.getLogger(__name__)

_FAMILY_VECTORS: dict[str, np.ndarray] | None = None
_FAMILY_VECTORS_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class RankerResult:
    rankings: tuple[RankedCapabilityFamily, ...]
    model_key: str
    latency_ms: float


@dataclass(frozen=True, slots=True)
class RankerUnavailable:
    reason: str
    model_key: str | None = None


class SemanticFamilyRanker:
    def __init__(self, encoder: TextEncoder | None = None) -> None:
        self._encoder = encoder

    def _get_encoder(self) -> TextEncoder:
        if self._encoder is not None:
            return self._encoder
        return get_onnx_encoder(PRODUCTION_MODEL_SPEC)

    def _family_vectors(self, encoder: TextEncoder) -> dict[str, np.ndarray]:
        global _FAMILY_VECTORS
        with _FAMILY_VECTORS_LOCK:
            if _FAMILY_VECTORS is None:
                _FAMILY_VECTORS = build_family_vectors(encoder, CAPABILITY_FAMILIES)
            return _FAMILY_VECTORS

    def rank(
        self,
        prompt: str,
        history: tuple[AgentMessage, ...] | list[AgentMessage],
    ) -> RankerResult | RankerUnavailable:
        import time

        started = time.perf_counter()
        try:
            encoder = self._get_encoder()
            document = build_routing_document(prompt, history)
            query_vector = encoder.encode_queries([document])[0]
            rankings = rank_families_from_embeddings(
                query_vector,
                self._family_vectors(encoder),
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return RankerResult(
                rankings=tuple(rankings),
                model_key=encoder.model_key,
                latency_ms=latency_ms,
            )
        except FileNotFoundError:
            return RankerUnavailable(reason="model_unavailable")
        except Exception:
            _LOGGER.debug("Semantic ranker failed", exc_info=True)
            return RankerUnavailable(reason="model_error")


_DEFAULT_RANKER = SemanticFamilyRanker()


def rank_capability_families(
    prompt: str,
    history: tuple[AgentMessage, ...] | list[AgentMessage],
) -> RankerResult | RankerUnavailable:
    return _DEFAULT_RANKER.rank(prompt, history)
