from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from inferno_account_performance import (
    account_performance_text,
    build_account_performance,
    max_drawdown,
    twr_index,
)


class TwrTests(unittest.TestCase):
    def test_deposit_is_not_a_return(self):
        series = [(date(2026, 1, 1), 1000.0), (date(2026, 1, 2), 2000.0)]
        index = twr_index(series, {date(2026, 1, 2): 1000.0})
        self.assertAlmostEqual(index[-1][1], 1.0)

    def test_withdrawal_is_not_a_loss(self):
        series = [(date(2026, 1, 1), 1000.0), (date(2026, 1, 2), 450.0)]
        index = twr_index(series, {date(2026, 1, 2): -500.0})
        self.assertAlmostEqual(index[-1][1], 0.9)

    def test_drawdown_on_index(self):
        index = [(date(2026, 1, d), v) for d, v in [(1, 1.0), (2, 1.2), (3, 0.9), (4, 1.0)]]
        worst, peak, trough = max_drawdown(index)
        self.assertAlmostEqual(worst, -0.25)
        self.assertEqual((peak, trough), (date(2026, 1, 2), date(2026, 1, 3)))


class BuildTests(unittest.TestCase):
    def test_full_build_flags_outlier_peak_and_benchmarks(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "nlv_history.csv").write_text(
                "timestamp,date,nlv,cash\n"
                "x,2026-06-17,1000,0\nx,2026-06-18,,\nx,2026-06-19,1100,0\nx,2026-06-20,2050,1000\nx,2026-06-21,1640,0\n")
            (data / "inferno_schwab_transaction_ledger.json").write_text(json.dumps({"transactions": [
                {"transactionType": "CASH_RECEIPT", "occurredAt": "2026-06-20T10:00:00+0000", "netAmount": 1000},
                {"transactionType": "TRADE", "occurredAt": "2026-06-20T10:00:00+0000", "netAmount": -5},
            ]}))
            (data / "inferno_external_flows.csv").write_text("date,amount,provenance\n2026-06-21,-400,inferred\n")
            (data / "inferno_benchmark_prices.csv").write_text(
                "date,symbol,close,source\n2026-06-17,SPY,100,a\n2026-06-21,SPY,105,a\n")
            (data / "inferno_capital_scaling_state.json").write_text(json.dumps({"peakNlv": 5000}))
            p = build_account_performance(data)
        self.assertEqual(p["verdict"], "measured")
        self.assertEqual(p["netExternalFlows"], 600.0)
        self.assertEqual(p["moneyWeightedPnl"], 40.0)
        # 1.1 * (2050/2100) * (1640/1650)
        self.assertAlmostEqual(p["twrSinceStart"], round(1.1 * 2050 / 2100 * 1640 / 1650 - 1, 4))
        self.assertEqual(p["benchmark"]["return"], 0.05)
        self.assertFalse(p["peakIntegrity"]["supported"])
        self.assertFalse(p["authorityChanged"])
        self.assertIn("OUTLIER", account_performance_text(p))

    def test_insufficient_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = build_account_performance(Path(tmp))
        self.assertEqual(p["verdict"], "insufficient-history")


if __name__ == "__main__":
    unittest.main()
