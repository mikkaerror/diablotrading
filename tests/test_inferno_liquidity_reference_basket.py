from __future__ import annotations

"""Regression tests for the liquidity reference-basket acceptance harness."""

import json
import tempfile
import unittest
from pathlib import Path

from inferno_liquidity_reference_basket import build_reference_basket


def row(symbol: str, *, spread: float, oi: int) -> dict[str, object]:
    return {
        "symbol": symbol,
        "underlyingPrice": 100.0,
        "atmSpreadPct": spread,
        "atmWindowMedianSpreadPct": spread,
        "atmWindowOpenInterest": oi,
        "atmWindowContractCount": 2,
        "atmLiquidityScore": 100 if spread <= 0.20 and oi >= 250 else 40,
        "qualityFlags": [],
    }


class LiquidityReferenceBasketTests(unittest.TestCase):
    """Pin the acceptance basket required by the liquidity-gate handoff."""

    def test_reference_basket_passes_and_hive_azz_class_fails(self) -> None:
        snapshot = {
            "generatedAt": "2026-07-07T12:00:00-06:00",
            "rows": [
                row("GOOG", spread=0.18, oi=500),
                row("AAPL", spread=0.08, oi=1000),
                row("MSFT", spread=0.12, oi=700),
                row("SPY", spread=0.04, oi=5000),
                row("HIVE", spread=0.30, oi=10000),
                row("AZZ", spread=0.26, oi=10000),
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schwab_options.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")

            payload = build_reference_basket(str(path))

        self.assertTrue(payload["acceptancePassed"])
        self.assertEqual(payload["referenceBasketPresent"], ["GOOG", "AAPL", "MSFT", "SPY"])
        verdicts = {item["symbol"]: item for item in payload["verdicts"]}
        for symbol in ("GOOG", "AAPL", "MSFT", "SPY"):
            self.assertTrue(verdicts[symbol]["proposedPaperPass"])
        for symbol in ("HIVE", "AZZ"):
            self.assertFalse(verdicts[symbol]["proposedPaperPass"])
            self.assertIn("genuinely wide", verdicts[symbol]["note"])


if __name__ == "__main__":
    unittest.main()
