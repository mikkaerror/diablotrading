from __future__ import annotations

"""Regression tests for the promotion-gap diagnostic.

Contract:
- the analyzer must not mutate the strategy_lab payload
- it must report ``researchOnly=True`` and ``promotable=False`` always
- the trades-to-floor projection must terminate even on hopeless inputs
- per-strategy gates must close monotonically as inputs cross thresholds
"""

import unittest

from inferno_promotion_gap import (
    PROMOTION_GAP_FILE,
    PROMOTION_GAP_STAGE,
    PROMOTION_GAP_TEXT_FILE,
    analyze_strategy,
    build_promotion_gap,
    trades_to_winrate_floor,
)


def strategy_summary(**overrides) -> dict:
    base = {
        "strategy": "TEST_EDGE",
        "winCount": 0,
        "lossCount": 0,
        "scoredCount": 0,
        "distinctEventCount": 0,
        "winRateLowerBound": None,
        "payoffRatio": None,
        "winRateLowerBoundTarget": None,
        "winRateLowerBoundTargetSource": None,
        "winRateBreakeven": None,
        "winRateBreakevenMargin": None,
        "expectancyPerRiskConfidence": {"lower": None},
        "profitFactor": None,
        "falsePositiveRate": 1.0,
        "maxDrawdownRiskUnits": None,
    }
    base.update(overrides)
    return base


class PromotionGapTests(unittest.TestCase):
    """Verify the analyzer is honest about distance to each gate."""

    def test_artifact_paths_are_distinct(self) -> None:
        self.assertTrue(str(PROMOTION_GAP_FILE).endswith("inferno_promotion_gap.json"))
        self.assertTrue(str(PROMOTION_GAP_TEXT_FILE).endswith("promotion_gap_latest.txt"))
        self.assertEqual(PROMOTION_GAP_STAGE, "promotion-gap-research-only")

    def test_empty_strategy_reports_full_gap(self) -> None:
        result = analyze_strategy(strategy_summary())
        self.assertEqual(result["scoredCountGap"], 30)
        self.assertEqual(result["distinctEventGap"], 30)
        self.assertEqual(result["gatesOpen"], 0)
        self.assertFalse(result["promotable"])

    def test_promotable_strategy_clears_all_gates(self) -> None:
        result = analyze_strategy(
            strategy_summary(
                winCount=25,
                lossCount=5,
                scoredCount=30,
                distinctEventCount=30,
                winRateLowerBound=0.55,
                payoffRatio=1.0,
                expectancyPerRiskConfidence={"lower": 0.1},
                profitFactor=1.6,
                falsePositiveRate=0.2,
                maxDrawdownRiskUnits=-2.0,
            )
        )
        self.assertTrue(result["promotable"])
        self.assertEqual(result["gatesOpen"], result["gatesTotal"])
        self.assertEqual(result["scoredCountGap"], 0)
        self.assertEqual(result["tradesToWinRateFloor"], 0)
        self.assertEqual(result["winRateLowerBoundTarget"], 0.53)

    def test_analyze_strategy_uses_payoff_aware_winrate_target(self) -> None:
        result = analyze_strategy(
            strategy_summary(
                winCount=27,
                lossCount=33,
                scoredCount=60,
                distinctEventCount=60,
                winRateLowerBound=0.331,
                payoffRatio=2.5,
                expectancyPerRiskConfidence={"lower": 0.1},
                profitFactor=2.0,
                falsePositiveRate=0.2,
                maxDrawdownRiskUnits=-2.0,
            )
        )

        self.assertTrue(result["promotable"])
        self.assertEqual(result["winRateBreakeven"], 0.2857)
        self.assertEqual(result["winRateLowerBoundTarget"], 0.3157)
        self.assertEqual(
            result["winRateLowerBoundTargetSource"],
            "payoff-implied-breakeven-plus-margin",
        )
        self.assertEqual(result["tradesToWinRateFloor"], 0)

    def test_trades_to_winrate_floor_returns_zero_when_already_clear(self) -> None:
        # 20 wins / 30 trades → wilson lower bound is well above 0.42.
        self.assertEqual(trades_to_winrate_floor(20, 30), 0)

    def test_trades_to_winrate_floor_returns_positive_when_below_floor(self) -> None:
        # 5 wins / 10 trades → wilson lower bound is around 0.24, below 0.42.
        # Hit rate is 50%, so additional samples should converge fast.
        result = trades_to_winrate_floor(5, 10, target=0.42)
        self.assertIsNotNone(result)
        self.assertGreater(result, 0)

    def test_trades_to_winrate_floor_caps_at_max_projection(self) -> None:
        # With a 30% hit rate, the projection cannot reach 0.42 floor.
        # The function must return None instead of looping forever.
        result = trades_to_winrate_floor(3, 10, target=0.42, max_trades=200)
        self.assertIsNone(result)

    def test_distinct_event_gap_blocks_otherwise_good_raw_trade_count(self) -> None:
        result = analyze_strategy(
            strategy_summary(
                winCount=25,
                lossCount=5,
                scoredCount=30,
                distinctEventCount=5,
                winRateLowerBound=0.55,
                payoffRatio=1.0,
                expectancyPerRiskConfidence={"lower": 0.1},
                profitFactor=1.6,
                falsePositiveRate=0.2,
                maxDrawdownRiskUnits=-2.0,
            )
        )

        self.assertFalse(result["promotable"])
        self.assertEqual(result["distinctEventGap"], 25)

    def test_build_promotion_gap_is_always_research_only(self) -> None:
        lab = {
            "generatedAt": "2026-05-10T08:00:00-06:00",
            "overall": strategy_summary(
                winCount=40, lossCount=0, scoredCount=40, distinctEventCount=40, winRateLowerBound=0.99,
                profitFactor=10.0, expectancyPerRiskConfidence={"lower": 5.0},
                falsePositiveRate=0.0, maxDrawdownRiskUnits=0.0,
            ),
            "strategies": [],
        }
        gap = build_promotion_gap(lab)
        self.assertTrue(gap["researchOnly"])
        self.assertFalse(gap["promotable"])
        self.assertIn("scoredTradesForPromotion", gap["thresholds"])
        self.assertIn("distinctEventsForPromotion", gap["thresholds"])

    def test_build_promotion_gap_handles_missing_inputs(self) -> None:
        gap = build_promotion_gap({})
        self.assertTrue(gap["researchOnly"])
        self.assertFalse(gap["promotable"])
        self.assertEqual(gap["strategies"], [])
        self.assertIsNone(gap["overall"])


if __name__ == "__main__":
    unittest.main()
