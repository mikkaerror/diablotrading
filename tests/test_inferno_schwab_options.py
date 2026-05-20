from __future__ import annotations

"""Regression tests for the read-only Schwab option-chain adapter."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_schwab_options as schwab


SAMPLE_CHAIN = {
    "symbol": "AAPL",
    "underlyingPrice": 200.0,
    "callExpDateMap": {
        "2026-06-19:30": {
            "200.0": [
                {
                    "symbol": "AAPL  260619C00200000",
                    "putCall": "CALL",
                    "bid": 8.9,
                    "ask": 9.1,
                    "mark": 9.0,
                    "delta": 0.51,
                    "gamma": 0.03,
                    "theta": -0.08,
                    "vega": 0.21,
                    "volatility": 35.0,
                    "openInterest": 1500,
                    "totalVolume": 550,
                    "strikePrice": 200.0,
                    "daysToExpiration": 30,
                    "inTheMoney": False,
                }
            ]
        }
    },
    "putExpDateMap": {
        "2026-06-19:30": {
            "200.0": [
                {
                    "symbol": "AAPL  260619P00200000",
                    "putCall": "PUT",
                    "bid": 7.8,
                    "ask": 8.2,
                    "mark": 8.0,
                    "delta": -0.49,
                    "gamma": 0.03,
                    "theta": -0.07,
                    "vega": 0.2,
                    "volatility": 36.0,
                    "openInterest": 1200,
                    "totalVolume": 325,
                    "strikePrice": 200.0,
                    "daysToExpiration": 30,
                    "inTheMoney": False,
                }
            ]
        }
    },
}


class SchwabOptionsTests(unittest.TestCase):
    """Pin the adapter's no-trade, quote-normalization behavior."""

    def test_build_chain_url_targets_marketdata_chain_endpoint(self) -> None:
        url = schwab.build_chain_url("aapl", {"strikeCount": 8})

        self.assertTrue(url.startswith("https://api.schwabapi.com/marketdata/v1/chains?"))
        self.assertIn("symbol=AAPL", url)
        self.assertIn("includeUnderlyingQuote=true", url)
        self.assertIn("strikeCount=8", url)

    def test_normalize_contract_computes_spread_and_liquidity(self) -> None:
        contract = schwab.normalize_contract(SAMPLE_CHAIN["callExpDateMap"]["2026-06-19:30"]["200.0"][0])

        self.assertEqual(contract["mid"], 9.0)
        self.assertEqual(contract["spread"], 0.2)
        self.assertEqual(contract["spreadPct"], 0.0222)
        self.assertEqual(contract["liquidityScore"], 100)

    def test_summarize_chain_extracts_atm_expected_move_proxy(self) -> None:
        summary = schwab.summarize_chain("AAPL", SAMPLE_CHAIN)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["contractCount"], 2)
        self.assertEqual(summary["atmStrike"], 200.0)
        self.assertEqual(summary["atmStraddleMid"], 17.0)
        self.assertEqual(summary["atmImpliedMovePct"], 0.085)
        self.assertEqual(summary["atmLiquidityScore"], 94)

    def test_disabled_report_fails_closed_without_network(self) -> None:
        with patch.object(schwab, "SCHWAB_OPTIONS_ENABLED", False):
            report = schwab.build_report(["AAPL"])

        self.assertEqual(report["status"], "disabled")
        self.assertFalse(report["configured"])
        self.assertEqual(report["rows"], [])
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["authorityChanged"])

    def test_fixture_report_exercises_full_normalizer_offline(self) -> None:
        report = schwab.build_report(["AAPL"], fixture_payloads={"AAPL": SAMPLE_CHAIN})

        self.assertEqual(report["status"], "fixture")
        self.assertEqual(report["rows"][0]["symbol"], "AAPL")
        self.assertEqual(report["rows"][0]["atmImpliedMovePct"], 0.085)

    def test_token_loader_reads_ignored_vault_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "schwab_token.json"
            token_file.write_text('{"access_token": "abc123"}', encoding="utf-8")

            self.assertEqual(schwab.load_schwab_access_token(token_file), "abc123")


if __name__ == "__main__":
    unittest.main()
