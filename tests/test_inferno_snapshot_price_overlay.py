from __future__ import annotations

import unittest

from inferno_snapshot_price_overlay import apply_schwab_price_overlay


class InfernoSnapshotPriceOverlayTests(unittest.TestCase):
    def test_overlay_preserves_sheet_price_and_reprices_snapshot_from_schwab(self) -> None:
        snapshot = {
            "generatedAt": "2026-07-01T06:00:00-06:00",
            "rows": [
                {
                    "ticker": "FCX",
                    "price": 67.44,
                    "marketContext": {
                        "support": 60.51,
                        "resistance": 72.28,
                        "distanceToSupportPct": 10.28,
                        "distanceToResistancePct": 7.18,
                    },
                },
                {"ticker": "NOPE", "price": 12.34, "marketContext": {}},
            ],
        }
        options = {
            "generatedAt": "2026-07-01T16:04:40-06:00",
            "rows": [
                {"symbol": "FCX", "underlyingPrice": 60.53, "quoteQualityScore": 38},
            ],
        }

        updated_snapshot, summary = apply_schwab_price_overlay(
            snapshot,
            options,
            generated_at="2026-07-01T16:05:00-06:00",
        )

        fcx = updated_snapshot["rows"][0]
        self.assertEqual(fcx["price"], 60.53)
        self.assertEqual(fcx["sheetPrice"], 67.44)
        self.assertEqual(fcx["priceSource"], "schwab-options-underlying")
        self.assertEqual(fcx["priceAsOf"], "2026-07-01T16:04:40-06:00")
        self.assertAlmostEqual(fcx["priceOverlay"]["driftPct"], -10.2461, places=4)
        self.assertAlmostEqual(fcx["marketContext"]["distanceToSupportPct"], 0.033, places=3)
        self.assertAlmostEqual(fcx["marketContext"]["distanceToResistancePct"], 19.412, places=3)
        self.assertEqual(updated_snapshot["rows"][1]["priceSource"], "google-sheet-price")
        self.assertEqual(summary["counts"]["updated"], 1)
        self.assertEqual(summary["counts"]["missingOptionRows"], 1)


if __name__ == "__main__":
    unittest.main()
