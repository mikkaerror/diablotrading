from __future__ import annotations

"""Tests for the research-only strategy shadow comparison register."""

import unittest

import inferno_strategy_shadow_comparison as comparison


def priced_item(
    ticker: str,
    strategy: str,
    *,
    combined: bool,
    optimizer_blocks: list[str] | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "generatedAt": "2026-05-24T22:01:11-06:00",
        "status": "priced",
        "recommendedStrategy": strategy,
        "sourceRecommendedStrategy": "PUT_CREDIT_SPREAD",
        "candidateStrategyRank": 2 if strategy == "IRON_CONDOR" else 1,
        "fallbackVariant": strategy == "IRON_CONDOR",
        "sourceAlternativeScore": 46 if strategy == "IRON_CONDOR" else 72,
        "sourceAlternativeEdgeVsLongVol": -8 if strategy == "IRON_CONDOR" else 18,
        "longVolHurdle": "hard",
        "longVolAtrMultiple": 2.4,
        "longVolPressureScore": 55,
        "optimizerPassed": combined,
        "paperRiskPassed": True,
        "combinedPassed": combined,
        "riskVerdict": {"passed": True, "blocks": [], "warnings": []},
        "price": 50,
        "sourcePrice": 50,
        "marketContextSummary": {"support": 44, "resistance": 56, "trend": "Bullish", "rvol": 0.9},
        "intent": {"price": 50, "atr20Day": 5, "atrPercent": 10},
        "strikePlan": {
            "strategy": strategy,
            "expiration": "2026-06-18",
            "estimatedCredit": 1.2 if strategy == "IRON_CONDOR" else 0.7,
            "estimatedMaxLoss": 280 if strategy == "IRON_CONDOR" else 130,
            "estimatedMaxProfit": 120 if strategy == "IRON_CONDOR" else 70,
            "creditRisk": 0.43,
            "breakEven": 39.3 if strategy == "PUT_CREDIT_SPREAD" else None,
            "breakEvenLower": 38.8 if strategy == "IRON_CONDOR" else None,
            "breakEvenUpper": 56.2 if strategy == "IRON_CONDOR" else None,
            "shortPutStrike": 40,
            "longPutStrike": 38,
            "shortCallStrike": 55 if strategy == "IRON_CONDOR" else None,
            "longCallStrike": 58 if strategy == "IRON_CONDOR" else None,
            "greekSummary": {"netTheta": 0.01, "netVega": -0.02, "greeksComplete": True},
            "optimizerBlocks": optimizer_blocks or [],
            "optimizerPassed": combined,
        },
    }


class StrategyShadowComparisonTests(unittest.TestCase):
    def test_register_tracks_passing_condor_without_authority(self) -> None:
        pricing = {
            "generatedAt": "2026-05-24T22:01:11-06:00",
            "verdict": "priced-risk-pass",
            "items": [
                priced_item("PL", "PUT_CREDIT_SPREAD", combined=False, optimizer_blocks=["short put above support"]),
                priced_item("PL", "IRON_CONDOR", combined=True),
                priced_item("MRVL", "IRON_CONDOR", combined=True),
                priced_item("VNET", "PUT_CREDIT_SPREAD", combined=False),
            ],
        }
        expected = {
            "currentPressureCandidates": [
                {
                    "ticker": "PL",
                    "strategy": "LONG_STRADDLE",
                    "premiumHurdleLabel": "hard",
                    "requiredMoveAtrMultiple": 2.5,
                    "rankPressureScore": 50,
                }
            ]
        }

        payload = comparison.build_strategy_shadow_comparison(pricing, expected)

        self.assertEqual(payload["verdict"], "shadow-comparison-ready")
        self.assertEqual(payload["counts"]["groups"], 2)
        self.assertEqual(payload["counts"]["trackedCondors"], 2)
        self.assertEqual(payload["counts"]["blockedPutCreditComparisons"], 1)
        for row in payload["register"]:
            self.assertTrue(row["shadowOnly"])
            self.assertTrue(row["researchOnly"])
            self.assertFalse(row["paperStageAllowed"])
            self.assertFalse(row["brokerSubmitAllowed"])
            self.assertFalse(row["liveTradingAllowed"])
            self.assertFalse(row["mutatesShadowLedger"])
        pl = next(row for row in payload["register"] if row["ticker"] == "PL")
        strategies = [row["strategy"] for row in pl["comparisons"] if row.get("type") == "priced-alternative"]
        self.assertEqual(strategies, ["PUT_CREDIT_SPREAD", "IRON_CONDOR"])
        self.assertIn("short put above support", pl["putCreditBlockSummary"])
        self.assertEqual(pl["marketReference"]["underlyingPrice"], 50.0)
        self.assertGreaterEqual(len(pl["expirationPayoffGrid"]), 5)
        current = next(row for row in pl["expirationPayoffGrid"] if row["label"] == "current")
        self.assertEqual(current["payoffs"]["IRON_CONDOR"]["pnl"], 120.0)
        self.assertEqual(current["payoffs"]["PUT_CREDIT_SPREAD"]["pnl"], 70.0)
        self.assertEqual(current["bestStrategyByPnl"], "IRON_CONDOR")

    def test_no_passing_variants_returns_empty_register(self) -> None:
        payload = comparison.build_strategy_shadow_comparison(
            {"items": [priced_item("PL", "PUT_CREDIT_SPREAD", combined=False)]},
            {},
        )

        self.assertEqual(payload["verdict"], "no-passing-alternatives")
        self.assertEqual(payload["counts"]["groups"], 0)
        self.assertEqual(payload["register"], [])

    def test_source_pricing_freshness_flags_stale_register(self) -> None:
        report = {"sourcePricing": {"generatedAt": "2026-07-06T10:00:00-06:00"}}
        pricing = {"generatedAt": "2026-07-06T10:05:00-06:00"}

        freshness = comparison.source_pricing_freshness(report, pricing)

        self.assertFalse(freshness["freshForPricing"])
        self.assertEqual(freshness["reason"], "stale-relative-to-pricing")

    def test_source_pricing_freshness_accepts_matching_source(self) -> None:
        report = {"sourcePricing": {"generatedAt": "2026-07-06T10:00:00-06:00"}}
        pricing = {"generatedAt": "2026-07-06T10:00:00-06:00"}

        self.assertTrue(comparison.source_pricing_freshness(report, pricing)["freshForPricing"])

    def test_text_report_names_register_and_condor(self) -> None:
        payload = comparison.build_strategy_shadow_comparison(
            {
                "items": [
                    priced_item("PL", "CALL_DEBIT_SPREAD", combined=True),
                    priced_item("PL", "PUT_CREDIT_SPREAD", combined=False, optimizer_blocks=["short put above support"]),
                    priced_item("PL", "IRON_CONDOR", combined=True),
                ]
            },
            {},
        )

        report = comparison.render_strategy_shadow_comparison(payload)

        self.assertIn("Strategy Shadow Comparison Register", report)
        self.assertIn("IRON_CONDOR", report)
        self.assertIn("CALL_DEBIT_SPREAD", report)
        self.assertIn("broker submit allowed: False", report)
        self.assertIn("payoff checkpoints", report)

    def test_credit_structure_payoff_math_handles_put_side_and_condor_call_side(self) -> None:
        condor = {
            "strategy": "IRON_CONDOR",
            "estimatedCredit": 1.2,
            "shortPutStrike": 40,
            "longPutStrike": 38,
            "shortCallStrike": 55,
            "longCallStrike": 58,
        }
        put_credit = {
            "strategy": "PUT_CREDIT_SPREAD",
            "estimatedCredit": 0.7,
            "shortPutStrike": 40,
            "longPutStrike": 38,
        }

        self.assertEqual(comparison.credit_structure_expiration_pnl(condor, 50), 120.0)
        self.assertEqual(comparison.credit_structure_expiration_pnl(condor, 60), -180.0)
        self.assertEqual(comparison.credit_structure_expiration_pnl(put_credit, 39), -30.0)

    def test_debit_spread_payoff_math_reads_strikes_from_legs(self) -> None:
        call_debit = {
            "strategy": "CALL_DEBIT_SPREAD",
            "estimatedDebit": 2.85,
            "legs": [
                {"instruction": "BUY_TO_OPEN", "putCall": "CALL", "strike": 365},
                {"instruction": "SELL_TO_OPEN", "putCall": "CALL", "strike": 370},
            ],
        }
        put_debit = {
            "strategy": "PUT_DEBIT_SPREAD",
            "estimatedDebit": 1.60,
            "legs": [
                {"instruction": "BUY_TO_OPEN", "putCall": "PUT", "strike": 75},
                {"instruction": "SELL_TO_OPEN", "putCall": "PUT", "strike": 72.5},
            ],
        }

        self.assertEqual(comparison.credit_structure_expiration_pnl(call_debit, 364), -285.0)
        self.assertEqual(comparison.credit_structure_expiration_pnl(call_debit, 368), 15.0)
        self.assertEqual(comparison.credit_structure_expiration_pnl(call_debit, 373), 215.0)
        self.assertEqual(comparison.credit_structure_expiration_pnl(put_debit, 76), -160.0)
        self.assertEqual(comparison.credit_structure_expiration_pnl(put_debit, 74), -60.0)
        self.assertEqual(comparison.credit_structure_expiration_pnl(put_debit, 70), 90.0)


if __name__ == "__main__":
    unittest.main()
