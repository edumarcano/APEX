"""Production routing thresholds tuned on the development split."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RoutingThresholds:
    minimum_top_score: float
    minimum_none_margin: float
    additional_family_minimum_score: float
    additional_family_margin: float
    max_selected_families: int
    max_schema_tokens_cloud: int
    max_schema_tokens_sorex: int
    max_schema_tokens_mus: int
    max_schema_tokens_apodemus: int


# Updated after benchmark tuning on dev split.
DEFAULT_THRESHOLDS = RoutingThresholds(
    minimum_top_score=0.28,
    minimum_none_margin=0.05,
    additional_family_minimum_score=0.38,
    additional_family_margin=0.06,
    max_selected_families=2,
    max_schema_tokens_cloud=4500,
    max_schema_tokens_sorex=900,
    max_schema_tokens_mus=1200,
    max_schema_tokens_apodemus=1500,
)
