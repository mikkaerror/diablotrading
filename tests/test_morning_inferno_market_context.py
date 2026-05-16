from __future__ import annotations

"""Regression tests for real market-context enrichment."""

import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from morning_inferno_pipeline import build_market_context, compute_market_context_from_history, sync_market_context_columns


class MorningInfernoMarketContextTests(unittest.TestCase):
    """Verify bias-confirmation metrics stay stable and deterministic."""

    def test_compute_market_context_from_history_builds_real_levels(self) -> None:
        history = pd.DataFrame(
            {
                "Close": [100 + index for index in range(60)],
                "High": [101 + index for index in range(60)],
                "Low": [99 + index for index in range(60)],
                "Volume": [1_000_000 + (index * 10_000) for index in range(60)],
            }
        )

        context = compute_market_context_from_history(
            history,
            price=159.0,
            atr_z_score=1.25,
            iv_rank_change=0.18,
        )

        self.assertEqual(context["trend"]["label"], "Bullish")
        self.assertGreater(context["resistance"], context["support"])
        self.assertGreaterEqual(context["distanceToResistancePct"], 0)
        self.assertAlmostEqual(context["atrExpansion"], 1.25, places=2)
        self.assertAlmostEqual(context["ivImpulse"], 0.18, places=3)

    def test_build_market_context_prefers_sheet_values_when_present(self) -> None:
        context = build_market_context(
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
            }
        )

        self.assertEqual(context["trend"]["label"], "Bullish")
        self.assertEqual(context["trend"]["tone"], "hot")
        self.assertAlmostEqual(context["rvol"], 1.42, places=2)
        self.assertAlmostEqual(context["support"], 94.5, places=2)
        self.assertAlmostEqual(context["resistance"], 108.25, places=2)
        self.assertAlmostEqual(context["distanceToSupportPct"], 5.5, places=2)
        self.assertAlmostEqual(context["distanceToResistancePct"], 8.25, places=2)

    def test_sync_market_context_columns_writes_data_rows_without_header_overflow(self) -> None:
        class FakeSheet:
            def get_all_values(self):
                return [
                    ["Ticker", "Price", "ATR% Z-Score", "IV Rank Change (5-day delta)"],
                    ["NVDA", "100", "1.25", "0.18"],
                    ["AMD", "90", "0.80", "0.05"],
                ]

        updates: list[tuple[str, list[list[object]]]] = []

        def capture_update(_sheet, range_name, values):
            updates.append((range_name, values))

        with (
            patch("morning_inferno_pipeline.get_sheet", return_value=FakeSheet()),
            patch("morning_inferno_pipeline.ensure_sheet_has_columns"),
            patch("morning_inferno_pipeline.google_sheets_call", side_effect=lambda _label, fn: fn()),
            patch(
                "morning_inferno_pipeline.compute_market_context_snapshot",
                side_effect=[
                    {
                        "rvol": 1.5,
                        "trend": {"label": "Bullish"},
                        "support": 95.0,
                        "resistance": 108.0,
                        "distanceToSupportPct": 5.0,
                        "distanceToResistancePct": 8.0,
                    },
                    {
                        "rvol": 1.1,
                        "trend": {"label": "Developing"},
                        "support": 86.0,
                        "resistance": 96.0,
                        "distanceToSupportPct": 4.0,
                        "distanceToResistancePct": 6.0,
                    },
                ],
            ),
            patch("morning_inferno_pipeline.update_sheet_range", side_effect=capture_update),
        ):
            result = sync_market_context_columns(Path("/tmp/backtest"), "Earnings Tracker")

        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["updated"], 2)
        self.assertEqual(updates[0][0], "Z1:AE1")
        self.assertEqual(updates[1][0], "Z2:AE3")
        self.assertEqual(len(updates[1][1]), 2)


if __name__ == "__main__":
    unittest.main()
