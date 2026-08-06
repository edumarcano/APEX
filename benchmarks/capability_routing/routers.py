"""Benchmark router implementations."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from core.agent.routing.scoring import (
    build_family_vectors,
    rank_families_from_embeddings,
)
from core.agent.routing.families import CAPABILITY_FAMILIES
from core.agent.routing.context import build_routing_document
from core.agent.routing.model_manifest import CANDIDATE_MODEL_SPECS
from core.agent.routing.models import RankedCapabilityFamily
from core.agent.routing.onnx_encoder import get_onnx_encoder
from core.agent.types import AgentMessage


class BenchmarkRouter(Protocol):
    name: str

    def rank(
        self,
        prompt: str,
        history: Sequence[AgentMessage],
    ) -> list[RankedCapabilityFamily]: ...


class ExposeAllRouter:
    name = "expose-all"

    def rank(
        self,
        _prompt: str,
        _history: Sequence[AgentMessage],
    ) -> list[RankedCapabilityFamily]:
        return [
            RankedCapabilityFamily(key=family.key, score=1.0)
            for family in CAPABILITY_FAMILIES
            if family.key != "none"
        ]


_TOKEN = re.compile(r"[a-z0-9']+")


class LexicalBaselineRouter:
    name = "lexical-baseline"

    def __init__(self) -> None:
        self._family_tokens = {
            family.key: self._tokens(
                " ".join([family.description, *family.semantic_examples])
            )
            for family in CAPABILITY_FAMILIES
        }

    @staticmethod
    def _tokens(text: str) -> Counter[str]:
        return Counter(_TOKEN.findall(text.lower()))

    def rank(
        self,
        prompt: str,
        history: Sequence[AgentMessage],
    ) -> list[RankedCapabilityFamily]:
        document = build_routing_document(prompt, history)
        query = self._tokens(document)
        scores: list[RankedCapabilityFamily] = []
        for key, family_tokens in self._family_tokens.items():
            overlap = sum(min(query[token], family_tokens[token]) for token in query)
            norm = math.sqrt(sum(value * value for value in query.values())) or 1.0
            family_norm = math.sqrt(sum(value * value for value in family_tokens.values())) or 1.0
            score = overlap / (norm * family_norm)
            scores.append(RankedCapabilityFamily(key=key, score=float(score)))
        scores.sort(key=lambda item: (-item.score, item.key))
        return scores


@dataclass
class OnnxBenchmarkRouter:
    model_key: str
    name: str

    def __post_init__(self) -> None:
        spec = CANDIDATE_MODEL_SPECS[self.model_key]
        self._encoder = get_onnx_encoder(spec)
        self._family_vectors = build_family_vectors(self._encoder)

    def rank(
        self,
        prompt: str,
        history: Sequence[AgentMessage],
    ) -> list[RankedCapabilityFamily]:
        document = build_routing_document(prompt, history)
        query_vector = self._encoder.encode_queries([document])[0]
        return rank_families_from_embeddings(query_vector, self._family_vectors)


def build_candidate_routers(include_onnx: bool = True) -> list[BenchmarkRouter]:
    routers: list[BenchmarkRouter] = [ExposeAllRouter(), LexicalBaselineRouter()]
    if include_onnx:
        routers.extend(
            [
                OnnxBenchmarkRouter(
                    model_key="all-minilm-l6-v2",
                    name="minilm-onnx",
                ),
                OnnxBenchmarkRouter(
                    model_key="bge-small-en-v1.5",
                    name="bge-small-onnx",
                ),
            ]
        )
    return routers
