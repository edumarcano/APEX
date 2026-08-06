"""Score calibration from development-split routing errors."""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.routing.models import RankedCapabilityFamily
from core.agent.routing.thresholds import RoutingThresholds


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    score_min: float
    score_max: float
    error_rate: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class ScoreCalibrator:
    bins: tuple[CalibrationBin, ...]
    default_error_rate: float = 0.5

    def error_rate_for_score(self, score: float | None) -> float:
        if score is None:
            return 1.0
        for item in self.bins:
            if item.score_min <= score < item.score_max:
                if item.sample_count < 10:
                    return self.default_error_rate
                return item.error_rate
        return self.default_error_rate

    def exceeds_error_budget(
        self,
        score: float | None,
        *,
        max_error_rate: float,
    ) -> bool:
        return self.error_rate_for_score(score) > max_error_rate


def _top_real_score(rankings: list[RankedCapabilityFamily]) -> float | None:
    for item in rankings:
        if item.key != "none":
            return item.score
    return None


def fit_calibrator(
    samples: list[tuple[float, bool]],
    *,
    bin_count: int = 8,
) -> ScoreCalibrator:
    """Fit bins from (top_score, is_correct) development samples."""
    if not samples:
        return ScoreCalibrator(bins=(), default_error_rate=0.5)

    scores = [score for score, _ in samples]
    lo = min(scores)
    hi = max(scores)
    if hi <= lo:
        errors = sum(1 for _, ok in samples if not ok)
        rate = errors / len(samples)
        return ScoreCalibrator(
            bins=(
                CalibrationBin(
                    score_min=lo,
                    score_max=hi + 1e-6,
                    error_rate=rate,
                    sample_count=len(samples),
                ),
            ),
            default_error_rate=rate,
        )

    width = (hi - lo) / bin_count
    bins: list[CalibrationBin] = []
    for index in range(bin_count):
        start = lo + index * width
        end = start + width if index < bin_count - 1 else hi + 1e-6
        bucket = [(score, ok) for score, ok in samples if start <= score < end]
        if not bucket:
            continue
        errors = sum(1 for _, ok in bucket if not ok)
        bins.append(
            CalibrationBin(
                score_min=start,
                score_max=end,
                error_rate=errors / len(bucket),
                sample_count=len(bucket),
            )
        )
    overall_errors = sum(1 for _, ok in samples if not ok)
    return ScoreCalibrator(
        bins=tuple(bins),
        default_error_rate=overall_errors / len(samples),
    )


def is_calibrated_low_confidence(
    rankings: list[RankedCapabilityFamily],
    *,
    calibrator: ScoreCalibrator,
    thresholds: RoutingThresholds,
) -> bool:
    top_score = _top_real_score(rankings)
    return calibrator.exceeds_error_budget(
        top_score,
        max_error_rate=thresholds.calibrated_max_error_rate,
    )


DEFAULT_CALIBRATOR = ScoreCalibrator(bins=(), default_error_rate=0.0)
