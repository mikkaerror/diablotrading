from __future__ import annotations

"""Tests for the read-only Schwab price-history adapter."""

import json
import tempfile
import unittest
from pathlib import Path

import inferno_schwab_price_history as schwab_history


def sample_history_payload(symbol: str = "TEST", days: int = 30) -> dict[str, object]:
    base_ms = 1_700_000_000_000
    candles = []
    for day in range(1, days + 1):
        candles.append(
            {
                "datetime": base_ms + day * 86_400_000,
                "open": float(day),
                "high": float(day + 1),
                "low": float(day - 1),
                "close": float(day),
                "volume": 3000 if day == days else 1000,
            }
        )
    return {"symbol": symbol, "empty": False, "candles": candles}


class SchwabPriceHistoryTests(unittest.TestCase):
    def test_build_price_history_url_targets_marketdata_endpoint(self) -> None:
        url = schwab_history.build_price_history_url("aapl", {"period": 2})

        self.assertTrue(url.startswith("https://api.schwabapi.com/marketdata/v1/pricehistory?"))
        self.assertIn("symbol=AAPL", url)
        self.assertIn("periodType=year", url)
        self.assertIn("period=2", url)
        self.assertIn("frequencyType=daily", url)

    def test_normalize_candles_maps_lowercase_schwab_fields_to_ohlcv(self) -> None:
        payload = {
            "candles": [
                {"datetime": 2, "open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 200},
                {"datetime": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
            ]
        }

        frame = schwab_history.normalize_candles(payload)

        self.assertEqual(list(frame.columns), ["Datetime", "Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(frame.iloc[0]["Open"], 1.0)
        self.assertEqual(frame.iloc[-1]["Close"], 2.5)

    def test_fixture_report_computes_visible_tos_metrics_from_daily_history(self) -> None:
        report = schwab_history.build_report(
            ["TEST"],
            fixture_payloads={"TEST": sample_history_payload()},
        )

        row = report["rows"][0]
        mirror = row["tosCustomFormulaMirror"]

        self.assertEqual(report["status"], "fixture")
        self.assertEqual(row["candleCount"], 30)
        self.assertEqual(mirror["tos_rvol"]["value"], 2.81)
        self.assertEqual(mirror["tos_pv52h"]["value"], 96.8)
        self.assertEqual(mirror["tos_momentum"]["value"], 4.5)
        self.assertEqual(mirror["tos_atr_percent"]["value"], 6.7)
        self.assertEqual(mirror["tos_strength"]["value"], 50.0)
        self.assertEqual(mirror["tos_support_resistance_state"]["label"], "Neutral")
        self.assertTrue(row["formulaReady"])

    def test_symbols_from_snapshot_deduplicates_tracker_universe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "latest_snapshot.json"
            path.write_text(
                json.dumps(
                    {
                        "eligibleTickers": ["AAPL", "MSFT"],
                        "rows": [{"ticker": "AAPL"}, {"ticker": "NVDA"}],
                    }
                ),
                encoding="utf-8",
            )

            symbols = schwab_history.symbols_from_snapshot(path, limit=3)

        self.assertEqual(symbols, ["AAPL", "MSFT", "NVDA"])


if __name__ == "__main__":
    unittest.main()
