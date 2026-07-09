from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import inferno_dual_momentum_backtest as dual_momentum


class InfernoDualMomentumBacktestTests(unittest.TestCase):
    """Protect the research-only dual-momentum engine from rule drift."""

    def test_backtest_switches_to_safe_asset_when_momentum_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "month_end.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "date,SPY,AGG",
                        "2026-01-31,100,100",
                        "2026-02-28,110,100.5",
                        "2026-03-31,120,101",
                        "2026-04-30,132,101.5",
                        "2026-05-31,118.8,102",
                        "2026-06-30,130.68,102.5",
                    ]
                ),
                encoding="utf-8",
            )

            dates, series = dual_momentum.load_prices(str(csv_path))
            payload = dual_momentum.backtest(
                dates,
                series,
                safe="AGG",
                lookback=2,
                cost_bps=1.0,
                account=1000.0,
            )

        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertEqual(payload["safeAsset"], "AGG")
        self.assertEqual(payload["riskAssets"], ["SPY"])
        self.assertEqual(payload["switches"], 1)
        self.assertEqual(payload["holdingsDistribution"], {"SPY": 2, "AGG": 1})
        self.assertEqual(payload["months"], 3)
        self.assertAlmostEqual(payload["accountEndValueStrategy"], 994.75, places=2)

    def test_text_renderer_labels_research_only(self) -> None:
        dates = [
            "2026-01-31",
            "2026-02-28",
            "2026-03-31",
            "2026-04-30",
            "2026-05-31",
        ]
        series = {
            "SPY": [100.0, 102.0, 104.0, 106.0, 108.0],
            "AGG": [100.0, 100.5, 101.0, 101.5, 102.0],
        }
        payload = dual_momentum.backtest(dates, series, safe="AGG", lookback=2)

        rendered = dual_momentum.text(payload)

        self.assertIn("Inferno Dual-Momentum ETF Backtest (research-only)", rendered)
        self.assertIn("DUAL-MOM", rendered)
        self.assertIn("Research-only", rendered)


if __name__ == "__main__":
    unittest.main()
