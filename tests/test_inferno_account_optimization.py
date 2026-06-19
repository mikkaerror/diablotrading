from __future__ import annotations

"""Regression tests for the research-only account optimization brief."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_account_optimization as optimization


class AccountOptimizationTests(unittest.TestCase):
    """Keep growth math, risk affordability, and safety locks honest."""

    def test_compounding_math(self) -> None:
        self.assertAlmostEqual(optimization.monthly_to_annual(0.10), 2.1384283767)
        self.assertAlmostEqual(
            optimization.future_value(1600.87, 0.02, 500.0),
            8736.34,
            places=2,
        )

    def test_build_plan_freezes_live_options_without_evidence(self) -> None:
        payload = optimization.build_account_optimization(
            {
                "liveAccount": {
                    "accountDataSource": "schwab-account-api",
                    "matchedSuffix": "8499",
                    "netLiquidatingValue": 1600.87,
                    "totalCash": 599.93,
                    "positions": [
                        {
                            "symbol": "TE",
                            "markValue": 375.20,
                            "weightPct": 23.44,
                            "plPercent": 12.78,
                            "riskFlags": ["fragile-alignment"],
                        },
                        {
                            "symbol": "IREN",
                            "markValue": 239.84,
                            "weightPct": 14.98,
                            "plPercent": 13.60,
                            "riskFlags": ["fragile-alignment"],
                        },
                    ],
                },
                "allocator": {
                    "optionsLane": {"maxStarterTicketDollars": 149.98},
                },
                "strategyLab": {
                    "overall": {
                        "scoredCount": 1,
                        "riskUnitCap": 0.0,
                        "verdict": {"promotable": False},
                    }
                },
                "fastPaper": {
                    "counts": {"open": 4, "closedLifetime": 0},
                },
            }
        )

        self.assertEqual(payload["verdict"], "protect-and-prove")
        self.assertEqual(
            payload["optionsAffordability"]["edgeAdjustedLiveOptionsMaxLossDollars"],
            0.0,
        )
        self.assertEqual(payload["optionsAffordability"]["referenceTicketPctOfNlv"], 9.37)
        self.assertEqual(payload["concentration"]["topTwoPct"], 38.42)
        two_pct = next(
            row
            for row in payload["optionsAffordability"]["riskBands"]
            if row["riskPct"] == 2.0
        )
        self.assertEqual(two_pct["requiredNlvForReferenceTicket"], 7499.0)
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["authorityChanged"])

    def test_save_writes_operator_report(self) -> None:
        payload = optimization.build_account_optimization(
            {
                "liveAccount": {
                    "netLiquidatingValue": 1000.0,
                    "totalCash": 500.0,
                    "positions": [],
                },
                "allocator": {
                    "optionsLane": {"maxStarterTicketDollars": 100.0},
                },
                "strategyLab": {
                    "overall": {
                        "scoredCount": 0,
                        "riskUnitCap": 0.0,
                        "verdict": {"promotable": False},
                    }
                },
                "fastPaper": {"counts": {}},
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "optimization.json"
            text_path = Path(temp_dir) / "optimization.txt"
            with (
                patch.object(optimization, "ACCOUNT_OPTIMIZATION_FILE", json_path),
                patch.object(optimization, "ACCOUNT_OPTIMIZATION_TEXT_FILE", text_path),
            ):
                optimization.save_account_optimization(payload)

            self.assertTrue(json_path.exists())
            rendered = text_path.read_text(encoding="utf-8")
            self.assertIn("10% monthly stress test", rendered)
            self.assertIn("Evidence-adjusted live max loss now: $0.00", rendered)


if __name__ == "__main__":
    unittest.main()
