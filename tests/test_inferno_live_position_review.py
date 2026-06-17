from __future__ import annotations

"""Regression tests for live position review layering."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inferno_live_position_review import build_live_position_review


class InfernoLivePositionReviewTests(unittest.TestCase):
    """Verify live holdings are graded safely against research and tracker context."""

    @patch("inferno_live_position_review.save_live_position_review")
    @patch("inferno_live_position_review.load_json_file")
    def test_build_live_position_review_returns_healthy_when_book_is_supported(
        self,
        mock_load_json_file,
        _mock_save_live_position_review,
    ) -> None:
        live_sync = {
            "ok": True,
            "generatedAt": "2026-05-10T12:00:00-06:00",
            "matchedSuffix": "1234",
            "positions": [
                {
                    "symbol": "ORCL",
                    "qty": 10,
                    "markValue": 200.0,
                    "weightPct": 20.0,
                    "plOpen": 15.0,
                    "plPercent": 8.0,
                    "bucket": "long-term-core",
                    "riskFlags": [],
                    "trackerContext": {
                        "alignmentLabel": "Aligned",
                        "longTermScore": 4.0,
                        "readyScore": 2.8,
                        "priority": 6.5,
                    },
                }
            ],
        }
        edge_payload = {
            "ranked": [
                {
                    "ticker": "ORCL",
                    "lane": "Long-Term Shovel Accumulation",
                    "category": "Cloud/Data Rails",
                    "edgeScore": 89.0,
                    "thesis": "Cloud rails still compounding.",
                }
            ]
        }
        shadow_payload = {
            "items": [
                {
                    "ticker": "ORCL",
                    "strategy": "Straddle",
                    "tradeDate": "2026-04-22",
                    "createdAt": "2026-04-22T09:30:00-06:00",
                    "outcome": {
                        "status": "closed",
                        "estimatedReturnOnRisk": 0.92,
                        "estimatedPnl": 92.0,
                        "reviewedAt": "2026-04-29T10:00:00-06:00",
                    },
                    "blockReasons": [],
                }
            ]
        }
        mock_load_json_file.side_effect = [live_sync, edge_payload, shadow_payload]

        report = build_live_position_review(refresh_live_sync=False)

        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "healthy")
        self.assertEqual(report["counts"]["supported"], 1)
        self.assertEqual(report["positions"][0]["posture"], "supported")
        self.assertEqual(report["positions"][0]["actionLabel"], "hold-core")
        self.assertTrue(report["positions"][0]["convictionScore"] >= 70)

    @patch("inferno_live_position_review.save_live_position_review")
    @patch("inferno_live_position_review.load_json_file")
    def test_build_live_position_review_returns_review_when_holding_is_fragile(
        self,
        mock_load_json_file,
        _mock_save_live_position_review,
    ) -> None:
        live_sync = {
            "ok": True,
            "generatedAt": "2026-05-10T12:00:00-06:00",
            "matchedSuffix": "1234",
            "positions": [
                {
                    "symbol": "XYZ",
                    "qty": 5,
                    "markValue": 450.0,
                    "weightPct": 45.0,
                    "plOpen": -20.0,
                    "plPercent": -11.0,
                    "bucket": "off-book",
                    "riskFlags": ["untracked", "concentration", "drawdown"],
                    "trackerContext": None,
                }
            ],
        }
        mock_load_json_file.side_effect = [live_sync, {"ranked": []}, {"items": []}]

        report = build_live_position_review(refresh_live_sync=False)

        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "review")
        self.assertEqual(report["counts"]["fragile"], 1)
        self.assertEqual(report["positions"][0]["posture"], "fragile")
        self.assertEqual(report["positions"][0]["actionLabel"], "manual-review")
        self.assertIn("Manual risk review: XYZ.", report["nextActions"])

    @patch("inferno_live_position_review.save_live_position_review")
    @patch("inferno_live_position_review.load_json_file")
    def test_operator_declared_hold_does_not_count_as_fragile_blocker(
        self,
        mock_load_json_file,
        _mock_save_live_position_review,
    ) -> None:
        live_sync = {
            "ok": True,
            "generatedAt": "2026-06-17T12:00:00-06:00",
            "matchedSuffix": "8499",
            "positions": [
                {
                    "symbol": "IREN",
                    "qty": 10,
                    "markValue": 200.0,
                    "weightPct": 12.0,
                    "plOpen": 5.0,
                    "plPercent": 2.5,
                    "bucket": "long-term-core",
                    "riskFlags": ["fragile-alignment", "concentration"],
                    "trackerContext": {
                        "alignmentLabel": "Fragile",
                        "longTermScore": 2.0,
                        "readyScore": 1.0,
                        "priority": 2.0,
                    },
                }
            ],
        }
        mock_load_json_file.side_effect = [live_sync, {"ranked": []}, {"items": []}]

        with tempfile.TemporaryDirectory() as tmpdir:
            holds_file = Path(tmpdir) / "operator_long_term_holds.json"
            holds_file.write_text('{"symbols": ["IREN"]}', encoding="utf-8")
            with patch("inferno_live_position_review.OPERATOR_LONG_TERM_HOLDS_FILE", holds_file):
                report = build_live_position_review(refresh_live_sync=False)

        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "healthy")
        self.assertEqual(report["counts"]["fragile"], 0)
        self.assertEqual(report["counts"]["supported"], 1)
        self.assertEqual(report["counts"]["operatorLongTermHolds"], 1)
        self.assertEqual(report["positions"][0]["posture"], "supported")
        self.assertTrue(report["positions"][0]["operatorLongTermHold"])
        self.assertIn("operator-declared long-term hold", "; ".join(report["positions"][0]["reasons"]))


if __name__ == "__main__":
    unittest.main()
