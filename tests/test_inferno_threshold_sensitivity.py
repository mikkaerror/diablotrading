from __future__ import annotations

"""Regression tests for the threshold sensitivity sweep.

Contract:
- the sweep is research-only and ``promotable: false`` no matter the inputs
- the production profile must use the committed thresholds verbatim
- looser profiles never cause stricter profiles to also pass (monotonicity)
- the sweep does not mutate input strategy summaries
- the artifact paths are distinct from the real strategy lab
"""

import unittest

from inferno_strategy_lab import (
    MAX_DRAWDOWN_RISK_UNITS,
    MAX_FALSE_POSITIVE_RATE,
    MIN_EXPECTANCY_LOWER_BOUND,
    MIN_PROFIT_FACTOR,
    MIN_SCORED_TRADES_FOR_PROMOTION,
    MIN_WIN_RATE_LOWER_BOUND,
)
from inferno_threshold_sensitivity import (
    SENSITIVITY_FILE,
    SENSITIVITY_STAGE,
    SENSITIVITY_TEXT_FILE,
    build_sensitivity,
    default_threshold_profiles,
    format_distance_summary,
    gate_distances,
    sweep_strategy,
    verdict_under_thresholds,
)


def strategy_summary(
    name: str = "TEST_EDGE",
    *,
    scored: int = 0,
    win_lower: float | None = None,
    expectancy_lower: float | None = None,
    profit_factor: float | None = None,
    false_positive: float | None = 1.0,
    drawdown: float | None = None,
) -> dict:
    return {
        "strategy": name,
        "scoredCount": scored,
        "winRateLowerBound": win_lower,
        "expectancyPerRiskConfidence": {"lower": expectancy_lower},
        "profitFactor": profit_factor,
        "falsePositiveRate": false_positive,
        "maxDrawdownRiskUnits": drawdown,
    }


class ThresholdSensitivityTests(unittest.TestCase):
    """Verify the sweep is honest about which thresholds clear which strategies."""

    def test_artifact_paths_distinct_and_stage_committed(self) -> None:
        self.assertTrue(str(SENSITIVITY_FILE).endswith("inferno_threshold_sensitivity.json"))
        self.assertTrue(str(SENSITIVITY_TEXT_FILE).endswith("threshold_sensitivity_latest.txt"))
        self.assertEqual(SENSITIVITY_STAGE, "threshold-sensitivity-research-only")

    def test_production_profile_mirrors_committed_constants(self) -> None:
        profiles = default_threshold_profiles()
        production = next(p for p in profiles if p["name"] == "production")
        self.assertEqual(production["minScored"], MIN_SCORED_TRADES_FOR_PROMOTION)
        self.assertEqual(production["minWinRateLowerBound"], MIN_WIN_RATE_LOWER_BOUND)
        self.assertEqual(production["minExpectancyLowerBound"], MIN_EXPECTANCY_LOWER_BOUND)
        self.assertEqual(production["minProfitFactor"], MIN_PROFIT_FACTOR)
        self.assertEqual(production["maxFalsePositiveRate"], MAX_FALSE_POSITIVE_RATE)
        self.assertEqual(production["maxDrawdownRiskUnits"], MAX_DRAWDOWN_RISK_UNITS)

    def test_empty_strategy_fails_every_profile(self) -> None:
        profiles = default_threshold_profiles()
        for profile in profiles:
            verdict = verdict_under_thresholds(strategy_summary(), profile)
            self.assertFalse(verdict["promotable"])

    def test_strong_evidence_passes_production_profile(self) -> None:
        strong = strategy_summary(
            scored=40, win_lower=0.55, expectancy_lower=0.1,
            profit_factor=1.6, false_positive=0.2, drawdown=-2.0,
        )
        profiles = default_threshold_profiles()
        production = next(p for p in profiles if p["name"] == "production")
        verdict = verdict_under_thresholds(strong, production)
        self.assertTrue(verdict["promotable"])
        self.assertEqual(verdict["blockers"], [])
        self.assertEqual(verdict["distanceSummary"]["blockingGateCount"], 0)

    def test_monotonicity_strict_passes_implies_loose_passes(self) -> None:
        """If a strategy passes the production gate, it must pass every looser
        profile too. Without this, the sweep is misleading.
        """
        strong = strategy_summary(
            scored=40, win_lower=0.55, expectancy_lower=0.1,
            profit_factor=1.6, false_positive=0.2, drawdown=-2.0,
        )
        result = sweep_strategy(strong, default_threshold_profiles())
        self.assertEqual(set(result["promotedUnder"]),
                         {"production", "moderate", "exploratory", "permissive"})

    def test_sweep_never_mutates_strategy_inputs(self) -> None:
        import json as _json
        strat = strategy_summary(scored=10, win_lower=0.4, profit_factor=1.2)
        before = _json.dumps(strat, sort_keys=True)
        sweep_strategy(strat, default_threshold_profiles())
        self.assertEqual(_json.dumps(strat, sort_keys=True), before)

    def test_build_sensitivity_is_always_research_only(self) -> None:
        # Even a fabricated "perfect" lab payload must not flip the
        # research-only flag.
        lab = {
            "generatedAt": "2026-05-10T08:00:00-06:00",
            "strategies": [
                strategy_summary(
                    "PERFECT", scored=100, win_lower=0.99,
                    expectancy_lower=10, profit_factor=99, false_positive=0,
                    drawdown=0,
                )
            ],
            "overall": strategy_summary("ALL", scored=100, win_lower=0.99,
                                        expectancy_lower=10, profit_factor=99,
                                        false_positive=0, drawdown=0),
        }
        report = build_sensitivity(lab=lab)
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])

    def test_gate_distances_quantify_primary_gap(self) -> None:
        strat = strategy_summary(
            scored=12, win_lower=0.37, expectancy_lower=-0.02,
            profit_factor=1.05, false_positive=0.7, drawdown=-8.0,
        )
        profile = next(p for p in default_threshold_profiles() if p["name"] == "production")
        verdict = verdict_under_thresholds(strat, profile)

        self.assertFalse(verdict["promotable"])
        self.assertEqual(verdict["distanceSummary"]["primaryGapGate"], "sample-size")
        self.assertEqual(verdict["distanceSummary"]["primaryGap"], 18)
        self.assertEqual(verdict["distanceSummary"]["primaryGapUnit"], "trades")
        self.assertTrue(any(row["gate"] == "profit-factor" and row["gap"] == 0.2 for row in verdict["gateDistances"]))
        self.assertTrue(any(row["gate"] == "false-positive-rate" and row["kind"] == "warning" for row in verdict["gateDistances"]))

    def test_gate_distances_treat_missing_metrics_as_blocking(self) -> None:
        rows = gate_distances(strategy_summary(scored=20), default_threshold_profiles()[1])

        self.assertTrue(any(row["gate"] == "expectancy-lower-bound" and row["gap"] is None for row in rows))
        self.assertTrue(any(row["gate"] == "win-rate-lower-bound" and row["gap"] is None for row in rows))

    def test_distance_summary_formats_missing_metrics_cleanly(self) -> None:
        text = format_distance_summary({
            "primaryGapGate": "expectancy-lower-bound",
            "primaryGap": None,
            "primaryGapUnit": "R",
        })

        self.assertEqual(text, "expectancy-lower-bound missing")

    def test_tightest_promoting_profile_is_strict_first(self) -> None:
        lab = {
            "strategies": [
                strategy_summary(
                    "MID", scored=15, win_lower=0.38,
                    expectancy_lower=0.05, profit_factor=1.15,
                    false_positive=0.4, drawdown=-1.0,
                )
            ],
            "overall": None,
        }
        report = build_sensitivity(lab=lab)
        # ``exploratory`` should pass for this strategy; ``production`` won't.
        # The tightest promoting profile is the first in profile-order that
        # any strategy clears, which by sort order is ``exploratory``.
        self.assertIn("exploratory", report["promotedAnyUnder"])
        self.assertNotIn("production", report["promotedAnyUnder"])


if __name__ == "__main__":
    unittest.main()
