"""Shared scoring utilities for semantic family ranking."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from core.agent.routing.encoder import TextEncoder
from core.agent.routing.families import CAPABILITY_FAMILIES, CapabilityFamilyDefinition
from core.agent.routing.models import RankedCapabilityFamily

PrototypeMode = str  # "combined" | "description" | "exemplars"


def family_prototype_texts(
    family: CapabilityFamilyDefinition,
    *,
    mode: PrototypeMode = "combined",
) -> tuple[str, ...]:
    if mode == "description":
        texts = (family.description,)
    elif mode == "exemplars":
        texts = family.semantic_examples
    else:
        texts = (family.description, *family.semantic_examples)
    return tuple(text for text in texts if text.strip())


def aggregate_family_score(similarities: Sequence[float]) -> float:
    if not similarities:
        return 0.0
    ordered = sorted(similarities, reverse=True)
    top = ordered[0]
    if len(ordered) == 1:
        return top
    return max(top, (ordered[0] + ordered[1]) / 2.0)


def cosine_similarity(query: np.ndarray, documents: np.ndarray) -> np.ndarray:
    query_norm = query / max(np.linalg.norm(query), 1e-12)
    doc_norms = np.linalg.norm(documents, axis=1, keepdims=True)
    doc_norms = np.clip(doc_norms, 1e-12, None)
    return (documents / doc_norms) @ query_norm


def rank_families_from_embeddings(
    query_vector: np.ndarray,
    family_vectors: dict[str, np.ndarray],
) -> list[RankedCapabilityFamily]:
    scores: list[RankedCapabilityFamily] = []
    for key, matrix in family_vectors.items():
        sims = cosine_similarity(query_vector, matrix)
        score = aggregate_family_score(sims.tolist())
        scores.append(RankedCapabilityFamily(key=key, score=float(score)))
    scores.sort(key=lambda item: (-item.score, item.key))
    return scores


def build_family_vectors(
    encoder: TextEncoder,
    families: Sequence[CapabilityFamilyDefinition] | None = None,
    *,
    mode: PrototypeMode = "combined",
) -> dict[str, np.ndarray]:
    selected = families or CAPABILITY_FAMILIES
    vectors: dict[str, np.ndarray] = {}
    for family in selected:
        texts = family_prototype_texts(family, mode=mode)
        vectors[family.key] = encoder.encode_documents(texts)
    return vectors
