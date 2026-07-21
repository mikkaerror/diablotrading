from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import inferno_ai_basket_refresh as refresh
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

    def test_complete_save_refreshes_matching_data_contract(self) -> None:
        basket = {
            "expectedUniverse": ["AMD", "NVDA"],
            "records": [{"symbol": "AMD", "cat": "Compute"}, {"symbol": "NVDA", "cat": "Compute"}],
        }
        history = {
            "generatedAt": "2026-07-14T10:00:00+00:00",
            "status": "ok",
            "rows": [history_row("AMD"), history_row("NVDA")],
        }
        generated_at = datetime.now(timezone.utc).isoformat()
        payload, snapshot, momentum = build_refresh(
            basket,
            price_history=history,
            generated_at=generated_at,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(refresh, "OUTPUT_FILE", root / "refresh.json"),
                patch.object(refresh, "REPORT_FILE", root / "refresh.txt"),
                patch.object(refresh, "SNAPSHOT_FILE", root / "snapshot.json"),
                patch.object(refresh, "MOMENTUM_FILE", root / "momentum.json"),
                patch.object(refresh.basket_data_contract, "OUTPUT_FILE", root / "contract.json"),
                patch.object(refresh.basket_data_contract, "REPORT_FILE", root / "contract.txt"),
            ):
                saved = refresh.save(payload, snapshot, momentum)

            contract = json.loads((root / "contract.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["dataContract"]["verdict"], "trusted")
        self.assertTrue(saved["dataContract"]["signalsTrusted"])
        self.assertEqual(contract["verdict"], "trusted")
        self.assertEqual(contract["sources"]["snapshot"]["sourceTimestamp"], snapshot["generatedAt"])
        self.assertEqual(contract["sources"]["momentum"]["sourceTimestamp"], momentum["generatedAt"])

    def test_partial_save_does_not_replace_prior_data_contract(self) -> None:
        basket = {"expectedUniverse": ["AMD", "NVDA"], "records": [{"symbol": "AMD"}, {"symbol": "NVDA"}]}
        history = {"generatedAt": "x", "status": "partial-error", "rows": [history_row("AMD")]}
        payload, snapshot, momentum = build_refresh(
            basket,
            price_history=history,
            generated_at="2026-07-14T11:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(refresh, "OUTPUT_FILE", root / "refresh.json"),
                patch.object(refresh, "REPORT_FILE", root / "refresh.txt"),
                patch.object(refresh, "SNAPSHOT_FILE", root / "snapshot.json"),
                patch.object(refresh, "MOMENTUM_FILE", root / "momentum.json"),
                patch.object(refresh.basket_data_contract, "OUTPUT_FILE", root / "contract.json"),
                patch.object(refresh.basket_data_contract, "REPORT_FILE", root / "contract.txt"),
            ):
                refresh.save(payload, snapshot, momentum)
            self.assertFalse((root / "snapshot.json").exists())
            self.assertFalse((root / "momentum.json").exists())
            self.assertFalse((root / "contract.json").exists())


if __name__ == "__main__":
    unittest.main()
