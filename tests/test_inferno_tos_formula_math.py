from __future__ import annotations

"""Regression coverage for the TOS-style formula mirror."""

import unittest

import pandas as pd

from inferno_tos_formula_math import (
    FORMULA_VERSION,
    build_market_context_from_history,
    build_market_context_from_row,
    momentum_snapshot,
    relative_volume_from_series,
    strength_snapshot,
    support_resistance_from_history,
    tos_custom_quote_snapshot_from_history,
    tracker_score_snapshot_from_row,
    trend_descriptor_from_history,
)


def rising_history(rows: int = 80, *, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    close = [start + index * step for index in range(rows)]
    return pd.DataFrame(
        {
            "Close": close,
            "High": [value + 1.0 for value in close],
            "Low": [value - 1.0 for value in close],
            "Volume": [1_000_000 + index * 10_000 for index in range(rows)],
        }
    )


class InfernoTosFormulaMathTests(unittest.TestCase):
    def test_relative_volume_excludes_current_bar_from_baseline(self) -> None:
        volume = pd.Series([100, 100, 100, 100, 100, 300])

        self.assertAlmostEqual(relative_volume_from_series(volume, lookback=5) or 0.0, 3.0, places=4)

    def test_trend_descriptor_marks_rising_sma_stack_bullish(self) -> None:
        context = trend_descriptor_from_history(rising_history(), price=179.0)

        self.assertEqual(context["label"], "Bullish")
        self.assertEqual(context["tone"], "hot")
        self.assertGreater(context["sma20SlopePct"], 0)

    def test_support_resistance_uses_recent_twenty_bar_range(self) -> None:
        levels = support_resistance_from_history(rising_history(60))

        self.assertEqual(levels["support"], 139.0)
        self.assertEqual(levels["resistance"], 160.0)
        self.assertEqual(levels["rangeWidth"], 21.0)

    def test_momentum_snapshot_is_positive_and_bounded_for_rising_history(self) -> None:
        trend = trend_descriptor_from_history(rising_history())
        momentum = momentum_snapshot(rising_history(), trend=trend)

        self.assertGreater(momentum["trackerScore"], 1.25)
        self.assertLessEqual(momentum["trackerScore"], 2.5)
        self.assertGreater(momentum["score100"], 50.0)

    def test_strength_includes_relative_strength_when_benchmark_is_present(self) -> None:
        symbol = rising_history(step=1.0)
        benchmark = rising_history(step=0.2)
        trend = trend_descriptor_from_history(symbol)
        momentum = momentum_snapshot(symbol, trend=trend)

        strength = strength_snapshot(symbol, benchmark_history=benchmark, trend=trend, momentum=momentum)

        self.assertGreater(strength["relativeStrengthPct"], 0)
        self.assertIn(strength["label"], {"improving", "leader"})

    def test_history_market_context_preserves_existing_contract_and_adds_formula_metadata(self) -> None:
        context = build_market_context_from_history(
            rising_history(),
            price=179.0,
            atr_z_score=1.25,
            iv_rank_change=0.18,
        )

        self.assertEqual(context["formulaVersion"], FORMULA_VERSION)
        self.assertEqual(context["trend"]["label"], "Bullish")
        self.assertIn("momentum", context)
        self.assertIn("strength", context)
        self.assertIn("tosCustomFormulaMirror", context)
        self.assertAlmostEqual(context["atrExpansion"], 1.25, places=2)
        self.assertAlmostEqual(context["ivImpulse"], 0.18, places=3)

    def test_tos_custom_quote_snapshot_mirrors_user_screenshot_formulas(self) -> None:
        history = rising_history(rows=252)
        history["Volume"] = [1_000.0 for _ in range(251)] + [3_000.0]

        snapshot = tos_custom_quote_snapshot_from_history(history)

        self.assertEqual(snapshot["formulaStatus"], "mirrored-from-user-screenshot-and-tos-cache")
        self.assertAlmostEqual(snapshot["tos_rvol"]["value"], 2.81, places=2)
        self.assertAlmostEqual(snapshot["tos_pv52h"]["value"], 99.7, places=1)
        self.assertAlmostEqual(snapshot["tos_momentum"]["value"], 4.5, places=2)
        self.assertAlmostEqual(snapshot["tos_atr_percent"]["value"], 0.6, places=1)
        self.assertAlmostEqual(snapshot["tos_strength"]["value"], 50.0, places=1)
        self.assertEqual(snapshot["tos_support_resistance_state"]["label"], "\u2197 Near High")

    def test_row_market_context_prefers_sheet_values_when_present(self) -> None:
        context = build_market_context_from_row(
            {
                "price": 100.0,
                "atrPercent": 4.0,
                "atr20Day": 3.5,
                "atrZScore": 0.8,
                "ivRankChange": 0.12,
                "momentumScore": 0.7,
                "readyScore": 0.9,
                "signalTrigger": True,
                "urgency": "Watchlist",
                "trend": "Bullish",
                "rvol": 1.42,
                "support": 94.5,
                "resistance": 108.25,
                "distanceToSupportPct": 5.5,
                "distanceToResistancePct": 8.25,
                "tosCustomMetrics": {"tos_strength": {"value": 81.5}},
                "tosCustomSignalSummary": {"sourceStatus": "captured", "strength": 81.5},
            }
        )

        self.assertEqual(context["formulaVersion"], FORMULA_VERSION)
        self.assertEqual(context["trend"]["label"], "Bullish")
        self.assertAlmostEqual(context["rvol"], 1.42, places=2)
        self.assertAlmostEqual(context["support"], 94.5, places=2)
        self.assertAlmostEqual(context["resistance"], 108.25, places=2)
        self.assertEqual(context["momentum"]["source"], "tracker-row")
        self.assertEqual(context["momentum"]["semantics"], "positive-iv-rank-change")
        self.assertEqual(context["tosCustomMetricSourceStatus"], "captured")
        self.assertEqual(context["tosCustomMetrics"]["tos_strength"]["value"], 81.5)
        self.assertEqual(context["tosCustomSignalSummary"]["strength"], 81.5)

    def test_tracker_score_snapshot_mirrors_current_sheet_formula_semantics(self) -> None:
        scores = tracker_score_snapshot_from_row(
            {
                "confidence": 2,
                "ivRank": 50,
                "ivRankChange": -0.12,
                "atrZScore": -1.5,
                "signalTrigger": True,
                "setupRec": "Straddle",
            }
        )

        self.assertAlmostEqual(scores["valueScore"], 2.5, places=4)
        self.assertAlmostEqual(scores["momentumScore"], 0.0, places=4)
        self.assertAlmostEqual(scores["squeezeScore"], 1.5, places=4)
        self.assertAlmostEqual(scores["readyScore"], 2.5, places=4)
        self.assertAlmostEqual(scores["priority"], 6.5, places=4)


if __name__ == "__main__":
    unittest.main()
