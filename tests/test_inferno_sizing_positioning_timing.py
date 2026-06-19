from __future__ import annotations

"""Tests for the total-account sizing, positioning, and timing overlay."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_sizing_positioning_timing as plan


def fixture() -> dict:
    """Return a compact current-account fixture."""
    return {
        "account": {
            "matchedSuffix": "8499",
            "netLiquidatingValue": 1599.17,
            "totalCash": 599.93,
            "positions": [
                {"symbol": "TE", "assetType": "EQUITY", "markValue": 374.0},
                {"symbol": "IREN", "assetType": "EQUITY", "markValue": 239.84},
                {"symbol": "HIVE", "assetType": "EQUITY", "markValue": 213.0},
                {"symbol": "CLSK", "assetType": "EQUITY", "markValue": 172.4},
            ],
        },
        "strategyLab": {
            "deskVerdict": {"promotable": False},
            "overall": {"scoredCount": 1, "verdict": {"promotable": False}},
        },
        "capitalScaling": {
            "recommendation": {
                "recommendedCap": 25.0,
                "recommendedDailyCap": 75.0,
            }
        },
        "edgeResearch": {
            "topLongTermShovels": [
                {
                    "ticker": "CHKP",
                    "price": 114.32,
                    "edgeScore": 82.7,
                    "longTermScore": 7.18,
                    "scores": {"qualityScore": 79.71},
                    "marketContext": {"support": 117.52},
                }
            ]
        },
        "priceHistory": {
            "rows": [
                {
                    "symbol": "CHKP",
                    "latestClose": 122.33,
                    "latestDate": "2026-06-18T05:00:00+00:00",
                }
            ]
        },
        "fastPaper": {
            "counts": {"open": 4},
            "openSlate": [{"exitEligibleDate": "2026-06-22"}],
        },
        "expectedMove": {
            "overall": {"beatRate": 0.3125, "meanMoveEdgePct": -11.4464}
        },
        "snapshot": {"rows": []},
    }


class SizingPositioningTimingTests(unittest.TestCase):
    """Protect total-NLV sleeve math and safety boundaries."""

    def test_unearned_options_sleeve_stays_in_cash(self) -> None:
        payload = plan.build_sizing_positioning_timing(fixture())

        self.assertEqual(payload["policySleeves"]["options"], 0.25)
        self.assertEqual(payload["evidenceAdjustedSleeves"]["options"], 0.0)
        self.assertEqual(payload["evidenceAdjustedSleeves"]["cash"], 0.50)
        self.assertEqual(payload["verdict"], "rebuild-cash-and-prove-edge")
        self.assertEqual(
            payload["positioningMath"]["newEquityCapacityAtStandardTargetDollars"],
            0.0,
        )
        self.assertAlmostEqual(
            payload["positioningMath"]["cashDepositToDiluteEquityToAdjustedTargetDollars"],
            399.31,
            places=2,
        )
        self.assertEqual(payload["optionsSizing"]["liveMaxLossDollars"], 0.0)
        self.assertFalse(payload["brokerSubmitAllowed"])

    def test_candidate_price_drift_requires_reconciliation(self) -> None:
        payload = plan.build_sizing_positioning_timing(fixture())
        candidate = payload["candidateReconciliation"][0]

        self.assertEqual(candidate["ticker"], "CHKP")
        self.assertEqual(candidate["priceDriftPct"], 7.01)
        self.assertTrue(candidate["materialPriceDrift"])
        self.assertEqual(candidate["decision"], "reconcile-live-quote-before-sizing")

    def test_save_writes_operator_report(self) -> None:
        payload = plan.build_sizing_positioning_timing(fixture())
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "plan.json"
            text_path = Path(temp_dir) / "plan.txt"
            with (
                patch.object(plan, "SIZING_POSITIONING_TIMING_FILE", json_path),
                patch.object(plan, "SIZING_POSITIONING_TIMING_TEXT_FILE", text_path),
            ):
                plan.save_sizing_positioning_timing(payload)

            rendered = text_path.read_text(encoding="utf-8")
            self.assertIn("Evidence-adjusted: shares 50.0% | options 0.0% | cash 50.0%", rendered)
            self.assertIn("2026-06-25 | post-data-reprice", rendered)


if __name__ == "__main__":
    unittest.main()
