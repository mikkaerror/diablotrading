from __future__ import annotations

"""Regression tests for the read-only Schwab option-chain adapter."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_schwab_options as schwab


ROOT = Path(__file__).resolve().parents[1]
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

    def _spread_chain(
        self,
        symbol: str,
        *,
        underlying: float = 100.0,
        spread_pct: float = 0.10,
        open_interest: int = 500,
        volume: int = 0,
    ) -> dict:
        mid = 5.0
        bid = round(mid * (1 - spread_pct / 2), 4)
        ask = round(mid * (1 + spread_pct / 2), 4)
        return {
            "symbol": symbol,
            "underlyingPrice": underlying,
            "callExpDateMap": {
                "2026-07-17:10": {
                    str(underlying): [
                        {
                            "symbol": f"{symbol}C{int(underlying)}",
                            "putCall": "CALL",
                            "bid": bid,
                            "ask": ask,
                            "strikePrice": underlying,
                            "openInterest": open_interest,
                            "totalVolume": volume,
                            "delta": 0.50,
                            "gamma": 0.02,
                            "theta": -0.04,
                            "vega": 0.20,
                        }
                    ]
                }
            },
            "putExpDateMap": {
                "2026-07-17:10": {
                    str(underlying): [
                        {
                            "symbol": f"{symbol}P{int(underlying)}",
                            "putCall": "PUT",
                            "bid": bid,
                            "ask": ask,
                            "strikePrice": underlying,
                            "openInterest": open_interest,
                            "totalVolume": volume,
                            "delta": -0.50,
                            "gamma": 0.02,
                            "theta": -0.04,
                            "vega": 0.20,
                        }
                    ]
                }
            },
        }

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
        self.assertEqual(summary["atmLiquidityScore"], 100)
        self.assertEqual(summary["atmWindowMedianSpreadPct"], 0.0361)
        self.assertEqual(summary["atmWindowOpenInterest"], 2700)
        self.assertEqual(summary["atmWindowContractCount"], 2)
        self.assertEqual(summary["atmExpectedMoveDollar"], 17.0)
        self.assertEqual(summary["atmExpectedMoveBucket"], "hot")
        self.assertEqual(summary["atmSpreadQuality"], "tight")
        self.assertEqual(summary["atmLiquidityBucket"], "elite")
        self.assertEqual(summary["atmImpliedVolatility"], 0.355)
        self.assertEqual(summary["atmBreakEvenLower"], 183.0)
        self.assertEqual(summary["atmBreakEvenUpper"], 217.0)
        self.assertEqual(summary["quoteQualityScore"], 84)
        self.assertEqual(summary["quoteQualityLabel"], "usable")
        self.assertEqual(summary["qualityFlags"], [])
        self.assertEqual(summary["liquidContractRatio"], 1.0)
        self.assertEqual(summary["greeksCompletenessPct"], 1.0)
        self.assertEqual(len(summary["topLiquidContracts"]), 2)
        self.assertEqual(summary["sideStats"]["CALL"]["liquidCount"], 1)
        self.assertEqual(summary["sideStats"]["PUT"]["avgImpliedVolatility"], 0.36)

    def test_tight_atm_window_does_not_flag_thin_liquidity(self) -> None:
        chain = {
            "symbol": "GOOG",
            "underlyingPrice": 100.0,
            "callExpDateMap": {
                "2026-07-17:11": {
                    "100.0": [{
                        "symbol": "GOOGC100", "putCall": "CALL", "bid": 4.88, "ask": 5.12,
                        "strikePrice": 100, "openInterest": 60, "totalVolume": 5,
                        "delta": 0.50, "gamma": 0.02, "theta": -0.04, "vega": 0.2,
                    }],
                    "105.0": [{
                        "symbol": "GOOGC105", "putCall": "CALL", "bid": 2.9, "ask": 3.05,
                        "strikePrice": 105, "openInterest": 1200, "totalVolume": 300,
                        "delta": 0.35, "gamma": 0.02, "theta": -0.03, "vega": 0.18,
                    }],
                }
            },
            "putExpDateMap": {
                "2026-07-17:11": {
                    "100.0": [{
                        "symbol": "GOOGP100", "putCall": "PUT", "bid": 4.88, "ask": 5.12,
                        "strikePrice": 100, "openInterest": 55, "totalVolume": 5,
                        "delta": -0.50, "gamma": 0.02, "theta": -0.04, "vega": 0.2,
                    }],
                    "95.0": [{
                        "symbol": "GOOGP95", "putCall": "PUT", "bid": 2.9, "ask": 3.05,
                        "strikePrice": 95, "openInterest": 1200, "totalVolume": 300,
                        "delta": -0.35, "gamma": 0.02, "theta": -0.03, "vega": 0.18,
                    }],
                }
            },
        }

        summary = schwab.summarize_chain("GOOG", chain)

        self.assertLessEqual(summary["atmWindowMedianSpreadPct"], 0.05)
        self.assertGreaterEqual(summary["atmLiquidityScore"], 70)
        self.assertNotIn("thin-atm-liquidity", summary["qualityFlags"])

    def test_reference_basket_names_pass_paper_spread_oi_gate(self) -> None:
        for symbol in ("GOOG", "AAPL", "MSFT", "SPY"):
            with self.subTest(symbol=symbol):
                summary = schwab.summarize_chain(
                    symbol,
                    self._spread_chain(symbol, spread_pct=0.18, open_interest=150),
                )

                self.assertLessEqual(summary["atmWindowMedianSpreadPct"], schwab.PAPER_MAX_SPREAD_PCT)
                self.assertEqual(summary["atmWindowOpenInterest"], 300)
                self.assertTrue(summary["paperLiquidityPass"])
                self.assertNotIn("thin-atm-liquidity", summary["qualityFlags"])
                self.assertEqual(summary["paperFillFrictionPct"], summary["atmWindowMedianSpreadPct"])

    def test_thin_window_oi_fails_even_when_spread_is_inside_paper_gate(self) -> None:
        summary = schwab.summarize_chain(
            "THIN",
            self._spread_chain("THIN", spread_pct=0.12, open_interest=100, volume=10000),
        )

        self.assertLessEqual(summary["atmWindowMedianSpreadPct"], schwab.PAPER_MAX_SPREAD_PCT)
        self.assertEqual(summary["atmWindowOpenInterest"], 200)
        self.assertFalse(summary["paperLiquidityPass"])
        self.assertIn("thin-atm-liquidity", summary["qualityFlags"])
        self.assertIn("open-interest", summary["paperLiquidityBlockReason"])

    def test_raw_volume_cannot_lift_hard_wide_hive_azz_class_names(self) -> None:
        for symbol in ("HIVE", "AZZ"):
            with self.subTest(symbol=symbol):
                summary = schwab.summarize_chain(
                    symbol,
                    self._spread_chain(symbol, spread_pct=0.30, open_interest=5000, volume=100000),
                )

                self.assertGreater(summary["atmWindowMedianSpreadPct"], schwab.HARD_WIDE_SPREAD_PCT)
                self.assertFalse(summary["paperLiquidityPass"])
                self.assertIn("wide-atm-spread", summary["qualityFlags"])
                self.assertIn("thin-atm-liquidity", summary["qualityFlags"])
                self.assertLess(summary["atmLiquidityScore"], 70)

    def test_contract_volume_bonus_does_not_rescue_wide_spreads(self) -> None:
        self.assertLess(
            schwab.liquidity_score_for_contract(0.30, open_interest=5000, volume=100000),
            70,
        )

    def test_quality_flags_warn_on_unusable_chain(self) -> None:
        chain = {
            "symbol": "ZZZ",
            "underlyingPrice": 10.0,
            "callExpDateMap": {
                "2026-06-19:30": {
                    "10.0": [{"symbol": "ZZZC", "putCall": "CALL", "bid": 0.1, "ask": 0.6, "strikePrice": 10}]
                }
            },
            "putExpDateMap": {
                "2026-06-19:30": {
                    "10.0": [{"symbol": "ZZZP", "putCall": "PUT", "bid": 0.1, "ask": 0.7, "strikePrice": 10}]
                }
            },
        }

        summary = schwab.summarize_chain("ZZZ", chain)

        self.assertIn("wide-atm-spread", summary["qualityFlags"])
        self.assertIn("thin-atm-liquidity", summary["qualityFlags"])
        self.assertIn("incomplete-greeks", summary["qualityFlags"])
        self.assertEqual(summary["atmSpreadQuality"], "untradeable")
        self.assertEqual(summary["quoteQualityLabel"], "poor")

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

    def test_live_report_uses_bounded_strike_window(self) -> None:
        with patch.object(schwab, "SCHWAB_OPTIONS_ENABLED", True):
            with patch.object(schwab, "load_schwab_access_token", return_value="token"):
                with patch.object(schwab, "fetch_option_chain", return_value=SAMPLE_CHAIN) as fetch:
                    report = schwab.build_report(["AAPL"])

        self.assertEqual(report["status"], "ok")
        self.assertEqual(fetch.call_args.kwargs["params"], schwab.DEFAULT_CHAIN_PARAMS)
        self.assertEqual(fetch.call_args.kwargs["params"]["strikeCount"], schwab.SCHWAB_OPTIONS_STRIKE_COUNT)

    def test_load_fixture_supports_documented_sample_file(self) -> None:
        fixtures = schwab.load_fixture(ROOT / "tests" / "fixtures" / "schwab_chain_sample.json")
        report = schwab.build_report(["AAPL"], fixture_payloads=fixtures)

        self.assertEqual(report["rows"][0]["quoteQualityLabel"], "usable")
        self.assertEqual(report["rows"][0]["atmExpectedMoveBucket"], "hot")

    def test_token_loader_reads_ignored_vault_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "schwab_token.json"
            token_file.write_text('{"access_token": "abc123"}', encoding="utf-8")

            self.assertEqual(schwab.load_schwab_access_token(token_file), "abc123")


if __name__ == "__main__":
    unittest.main()


class AtmSeriesAndQuoteSessionTests(unittest.TestCase):
    """The ATM reference must never be a same-day series, and quote timing is labelled."""

    @staticmethod
    def _contract(symbol: str, put_call: str, exp: str, dte: int, strike: float, bid: float, ask: float, **extra):
        return {
            "symbol": symbol, "putCall": put_call, "expirationDate": exp, "daysToExpiration": dte,
            "strikePrice": strike, "bid": bid, "ask": ask, "openInterest": 5000, "totalVolume": 800,
            "delta": 0.5 if put_call == "CALL" else -0.5, "gamma": 0.01, "theta": -0.05, "vega": 0.1,
            "volatility": 60.0, **extra,
        }

    def _chain(self, dead_quote_ms: int | None = None, live_quote_ms: int | None = None) -> dict:
        dead = {}
        live = {}
        for strike in (155.0, 160.0, 165.0):
            # Expired-today series: pennies, 50%+ spreads (what a post-close 0-DTE tape looks like).
            dead[str(strike)] = [self._contract(f"D{strike}", "CALL", "2026-09-04", 0, strike, 0.01, 0.03, quoteTimeInLong=dead_quote_ms)]
            live[str(strike)] = [self._contract(f"L{strike}", "CALL", "2026-09-11", 7, strike, 9.0, 9.3, quoteTimeInLong=live_quote_ms)]
        dead_p = {k: [dict(v[0], putCall="PUT", symbol=v[0]["symbol"] + "P")] for k, v in dead.items()}
        live_p = {k: [dict(v[0], putCall="PUT", symbol=v[0]["symbol"] + "P")] for k, v in live.items()}
        return {
            "symbol": "ORCL", "underlyingPrice": 158.78,
            "callExpDateMap": {"2026-09-04:0": dead, "2026-09-11:7": live},
            "putExpDateMap": {"2026-09-04:0": dead_p, "2026-09-11:7": live_p},
        }

    def test_same_day_series_is_never_the_atm_reference(self) -> None:
        summary = schwab.summarize_chain("ORCL", self._chain())
        self.assertEqual(summary["atmExpiration"], "2026-09-11")
        self.assertEqual(summary["atmDaysToExpiration"], 7)
        self.assertFalse(summary["atmSeriesFallback"])
        self.assertEqual(summary["atmSkippedExpirations"], ["2026-09-04"])
        self.assertTrue(summary["paperLiquidityPass"], summary["paperLiquidityBlockReason"])
        self.assertGreater(summary["atmStraddleMid"], 15.0)
        self.assertNotIn("atm-series-fallback-sub-min-dte", summary["qualityFlags"])

    def test_legacy_nearest_series_is_flagged_when_nothing_clears_min_dte(self) -> None:
        chain = self._chain()
        chain["callExpDateMap"].pop("2026-09-11:7")
        chain["putExpDateMap"].pop("2026-09-11:7")
        summary = schwab.summarize_chain("ORCL", chain)
        self.assertEqual(summary["atmExpiration"], "2026-09-04")
        self.assertTrue(summary["atmSeriesFallback"])
        self.assertIn("atm-series-fallback-sub-min-dte", summary["qualityFlags"])
        self.assertFalse(summary["paperLiquidityPass"])

    def test_nearest_atm_pair_min_dte_is_explicit(self) -> None:
        contracts = [schwab.normalize_contract(c) for c in schwab.flatten_contracts(self._chain())]
        legacy = schwab.nearest_atm_pair(contracts, 158.78, min_dte=0)
        self.assertEqual(legacy["call"]["expirationDate"], "2026-09-04")
        self.assertFalse(legacy["seriesFallback"])
        guarded = schwab.nearest_atm_pair(contracts, 158.78)
        self.assertEqual(guarded["call"]["expirationDate"], "2026-09-11")

    def test_quote_session_classification(self) -> None:
        # 2026-09-04 (Friday) 13:00 ET == 17:00 UTC
        regular = 1788541200000
        self.assertEqual(schwab.classify_quote_session(regular), "regular")
        self.assertEqual(schwab.classify_quote_session(regular + 3 * 3600 * 1000 + 5 * 60 * 1000), "late-close")  # 16:05 ET
        self.assertEqual(schwab.classify_quote_session(regular + 6 * 3600 * 1000), "off-hours")  # 19:00 ET
        self.assertEqual(schwab.classify_quote_session(regular + 2 * 24 * 3600 * 1000), "off-hours")  # Sunday
        self.assertEqual(schwab.classify_quote_session(None), "unknown")

    def test_off_hours_snapshot_is_labelled_but_still_fails_closed(self) -> None:
        off_hours = 1788561600000  # 2026-09-04 18:40 ET
        summary = schwab.summarize_chain("ORCL", self._chain(dead_quote_ms=off_hours, live_quote_ms=off_hours))
        self.assertEqual(summary["quoteSession"], "off-hours")
        self.assertFalse(summary["quoteSessionIsRegular"])
        self.assertIn("off-hours-quote-snapshot", summary["qualityFlags"])
        self.assertEqual(summary["spreadEvidenceQuality"], "off-hours-quotes")
        # Fixtures without a timestamp stay unflagged so legacy tests and offline fixtures keep their meaning.
        plain = schwab.summarize_chain("ORCL", self._chain())
        self.assertEqual(plain["quoteSession"], "unknown")
        self.assertNotIn("unknown-quote-snapshot", plain["qualityFlags"])


class RegradeTests(unittest.TestCase):
    """Stored tapes can be re-graded offline after a rule change."""

    def test_regrade_moves_dead_series_row_to_live_series_without_touching_prices(self) -> None:
        chain = AtmSeriesAndQuoteSessionTests()._chain()
        fresh = schwab.summarize_chain("ORCL", chain)
        # Simulate the legacy grade: force the dead series as the stored ATM reference.
        legacy_pair = schwab.nearest_atm_pair(fresh["contracts"], fresh["underlyingPrice"], min_dte=0)
        legacy = {**fresh, **schwab.atm_metrics(legacy_pair, fresh["underlyingPrice"], fresh["contracts"])}
        self.assertEqual(legacy["atmExpiration"], "2026-09-04")
        self.assertFalse(legacy["paperLiquidityPass"])

        regraded = schwab.regrade_row(legacy)
        self.assertEqual(regraded["atmExpiration"], "2026-09-11")
        self.assertTrue(regraded["paperLiquidityPass"])
        self.assertEqual(regraded["underlyingPrice"], legacy["underlyingPrice"])
        self.assertEqual(regraded["contracts"], legacy["contracts"])
        self.assertEqual(regraded["regrade"]["before"]["atmExpiration"], "2026-09-04")

    def test_regrade_report_keeps_generated_at_and_stamps_provenance(self) -> None:
        report = {"generatedAt": "2026-09-04T16:27:47-06:00", "rows": [], "reminders": ["read-only"]}
        out = schwab.regrade_report(report)
        self.assertEqual(out["generatedAt"], report["generatedAt"])
        self.assertIn("regradedAt", out)
        self.assertIn("read-only", out["reminders"])
        self.assertTrue(any("regraded offline" in r for r in out["reminders"]))


class StrikeWindowTests(unittest.TestCase):
    def test_window_short_of_implied_move_is_flagged(self) -> None:
        chain = AtmSeriesAndQuoteSessionTests()._chain()  # strikes 155-165 on 158.78 => ~2.4% window, straddle ~11%
        summary = schwab.summarize_chain("ORCL", chain)
        self.assertIsNotNone(summary["chainStrikeWindowPct"])
        self.assertFalse(summary["strikeWindowCoversImpliedMove"])
        self.assertIn("strike-window-below-implied-move", summary["qualityFlags"])

    def test_wide_window_covers(self) -> None:
        contracts = [{"expirationDate": "2026-09-11", "strikePrice": k} for k in (100.0, 158.0, 220.0)]
        out = schwab.strike_window_metrics(contracts, 158.78, "2026-09-11", 0.117)
        self.assertTrue(out["strikeWindowCoversImpliedMove"])
        self.assertIsNone(schwab.strike_window_metrics([], 158.78, "2026-09-11", 0.1)["strikeWindowCoversImpliedMove"])
