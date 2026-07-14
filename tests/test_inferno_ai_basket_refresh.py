from __future__ import annotations

import unittest

from inferno_ai_basket_refresh import build_refresh, declared_universe


def history_row(symbol: str, count: int = 210) -> dict:
    candles = []
    for index in range(count):
        close = 100.0 + index
        candles.append({"close": close, "high": close + 1, "low": close - 1})
    return {"symbol": symbol, "candles": candles}


class AiBasketRefreshTests(unittest.TestCase):
    def test_complete_history_publishes_full_universe(self) -> None:
        basket = {
            "expectedUniverse": ["AMD", "NVDA"],
            "records": [{"symbol": "AMD", "cat": "Compute"}, {"symbol": "NVDA", "cat": "Compute"}],
        }
        history = {"generatedAt": "2026-07-14T10:00:00+00:00", "status": "ok", "rows": [history_row("AMD"), history_row("NVDA")]}
        payload, snapshot, momentum = build_refresh(basket, price_history=history, generated_at="2026-07-14T11:00:00+00:00")
        self.assertEqual(payload["verdict"], "complete")
        self.assertTrue(payload["published"])
        self.assertEqual(snapshot["expectedUniverse"], ["AMD", "NVDA"])
        self.assertEqual(len(snapshot["records"]), 2)
        self.assertEqual(momentum["count"], 2)
        self.assertEqual(snapshot["records"][0]["priceAvg200"], 209.5)
        self.assertFalse(payload["liveTradingAllowed"])

    def test_partial_history_fails_closed_without_shrinking_universe(self) -> None:
        basket = {"expectedUniverse": ["AMD", "NVDA"], "records": [{"symbol": "AMD"}, {"symbol": "NVDA"}]}
        history = {"generatedAt": "x", "status": "partial-error", "rows": [history_row("AMD")]}
        payload, snapshot, momentum = build_refresh(basket, price_history=history, generated_at="2026-07-14T11:00:00+00:00")
        self.assertEqual(payload["verdict"], "fail-closed")
        self.assertFalse(payload["published"])
        self.assertEqual(payload["counts"]["blockedSymbols"]["NVDA"], ["missing-price-history", "trailing-return-history-incomplete"])
        self.assertEqual(snapshot["expectedUniverse"], ["AMD", "NVDA"])
        self.assertEqual(momentum["expectedUniverse"], ["AMD", "NVDA"])

    def test_legacy_list_remains_the_declared_universe(self) -> None:
        self.assertEqual(declared_universe([{"symbol": "NVDA"}, {"symbol": "AMD"}, {"symbol": "NVDA"}]), ["NVDA", "AMD"])


if __name__ == "__main__":
    unittest.main()
