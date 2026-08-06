"""Regression coverage for explicit score-calibrator threading."""

from __future__ import annotations

import unittest

from core.agent.routing.calibration import (
    DISABLED_CALIBRATOR,
    CalibrationBin,
    ScoreCalibrator,
    is_calibrated_low_confidence,
)
from core.agent.routing.models import RankedCapabilityFamily
from core.agent.routing.service import _select_families
from core.agent.routing.thresholds import DEFAULT_THRESHOLDS
from benchmarks.capability_routing.tune_thresholds import select_families_from_rankings


class RoutingCalibrationTests(unittest.TestCase):
    def test_disabled_calibrator_never_triggers_low_confidence(self) -> None:
        rankings = [
            RankedCapabilityFamily(key="weather", score=0.5),
            RankedCapabilityFamily(key="none", score=0.1),
        ]
        strict = ScoreCalibrator(
            bins=(
                CalibrationBin(
                    score_min=0.0,
                    score_max=1.0,
                    error_rate=0.9,
                    sample_count=100,
                ),
            ),
            default_error_rate=0.9,
        )
        disabled_selected, _, _, disabled_low = _select_families(
            rankings,
            DEFAULT_THRESHOLDS,
            "cloud",
            calibrator=DISABLED_CALIBRATOR,
        )
        strict_selected, _, _, strict_low = _select_families(
            rankings,
            DEFAULT_THRESHOLDS,
            "cloud",
            calibrator=strict,
        )
        self.assertEqual(disabled_selected, ["weather"])
        self.assertFalse(disabled_low)
        self.assertEqual(strict_selected, [])
        self.assertTrue(strict_low)

    def test_benchmark_select_fn_uses_supplied_calibrator(self) -> None:
        rankings = [
            RankedCapabilityFamily(key="weather", score=0.5),
            RankedCapabilityFamily(key="none", score=0.1),
        ]
        strict = ScoreCalibrator(
            bins=(
                CalibrationBin(
                    score_min=0.0,
                    score_max=1.0,
                    error_rate=0.9,
                    sample_count=100,
                ),
            ),
            default_error_rate=0.9,
        )
        disabled = select_families_from_rankings(
            rankings,
            DEFAULT_THRESHOLDS,
            calibrator=DISABLED_CALIBRATOR,
        )
        calibrated = select_families_from_rankings(
            rankings,
            DEFAULT_THRESHOLDS,
            calibrator=strict,
        )
        self.assertEqual(disabled, {"weather"})
        self.assertEqual(calibrated, set())

    def test_is_calibrated_low_confidence_uses_explicit_calibrator(self) -> None:
        rankings = [
            RankedCapabilityFamily(key="weather", score=0.4),
            RankedCapabilityFamily(key="none", score=0.1),
        ]
        permissive = ScoreCalibrator(bins=(), default_error_rate=0.1)
        strict = ScoreCalibrator(bins=(), default_error_rate=0.9)
        self.assertFalse(
            is_calibrated_low_confidence(
                rankings,
                calibrator=permissive,
                thresholds=DEFAULT_THRESHOLDS,
            )
        )
        self.assertTrue(
            is_calibrated_low_confidence(
                rankings,
                calibrator=strict,
                thresholds=DEFAULT_THRESHOLDS,
            )
        )


if __name__ == "__main__":
    unittest.main()
