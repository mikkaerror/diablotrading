from __future__ import annotations

"""Regression tests for market-context audit and risk layering."""

import unittest
from unittest.mock import patch

import pandas as pd

from inferno_edge_research import classify_lane, confirmation_score, edge_score
from inferno_risk_policy import evaluate_strike_item
from inferno_strike_selector import clean_chain
from morning_inferno_pipeline import build_market_context_audit


class InfernoMarketContextLayeringTests(unittest.TestCase):
    """Verify confirmation data is consumed consistently across the stack."""

    def test_market_context_audit_reports_full_population(self) -> None:
        rows = [
            {
                "ticker": "NVDA",
                "marketContext": {
                    "rvol": 1.42,
                    "trend": {"label": "Bullish", "tone": "hot"},
                    "support": 101.0,
                    "resistance": 118.0,
                    "alignmentLabel": "Aligned",
                },
            },
            {
                "ticker": "AMD",
                "marketContext": {
                    "rvol": 0.96,
                    "trend": {"label": "Uptrend", "tone": "hot"},
                    "support": 91.5,
                    "resistance": 99.0,
                    "alignmentLabel": "Developing",
                },
            },
        ]
        audit = build_market_context_audit(rows)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["populatedRows"], 2)
        self.assertEqual(audit["totalRows"], 2)
        self.assertEqual(audit["bullishRows"], 2)

    def test_market_context_audit_treats_numeric_zero_as_populated(self) -> None:
        rows = [
            {
                "ticker": "GLDD",
                "marketContext": {
                    "rvol": 0.0,
                    "trend": {"label": "Neutral", "tone": "wild"},
                    "support": 16.92,
                    "resistance": 17.02,
                    "alignmentLabel": "Fragile",
                },
            },
        ]
        audit = build_market_context_audit(rows)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["populatedRows"], 1)
        self.assertEqual(audit["missingTickers"], [])

    def test_market_context_audit_ignores_vendor_gaps(self) -> None:
        rows = [
            {
                "ticker": "COMM",
                "marketContext": {
                    "sourceStatus": "unavailable",
                    "rvol": 1.0,
                    "trend": {"label": "N/A", "tone": "wild"},
                    "support": 0.0,
                    "resistance": 0.0,
                    "alignmentLabel": "Fragile",
                },
            },
            {
                "ticker": "NVDA",
                "marketContext": {
                    "sourceStatus": "history",
                    "rvol": 1.42,
                    "trend": {"label": "Bullish", "tone": "hot"},
                    "support": 101.0,
                    "resistance": 118.0,
                    "alignmentLabel": "Aligned",
                },
            },
        ]
        audit = build_market_context_audit(rows)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["populatedRows"], 2)
        self.assertEqual(audit["totalRows"], 2)
        self.assertEqual(audit["unavailableTickers"], ["COMM"])

    def test_edge_research_promotes_confirmed_catalyst(self) -> None:
        row = {
            "ticker": "NVDA",
            "readiness": 91,
            "priority": 6.2,
            "confidence": 3,
            "signalTrigger": True,
            "daysUntilEarnings": 12,
            "setupRec": "Vertical Call",
            "longTermScore": 7.4,
            "marketContext": {
                "rvol": 1.55,
                "trend": {"label": "Bullish", "tone": "hot"},
                "atrExpansion": 1.1,
                "distanceToResistancePct": 6.2,
                "distanceToSupportPct": 4.3,
            },
        }
        metadata = {
            "grossMargins": 0.74,
            "operatingMargins": 0.34,
            "profitMargins": 0.28,
            "revenueGrowth": 0.31,
            "freeCashflow": 1,
            "debtToEquity": 35,
            "forwardPE": 38,
            "priceToSalesTrailing12Months": 18,
            "beta": 1.6,
        }
        category = {"category": "AI/Compute Picks", "baseScore": 96}
        scores = edge_score(row, metadata, category)
        self.assertGreaterEqual(confirmation_score(row), 60)
        self.assertEqual(classify_lane(row, scores, category), "Catalyst Trade Candidate")

    def test_risk_policy_blocks_bullish_spread_into_resistance(self) -> None:
        item = {
            "ticker": "NVDA",
            "ok": True,
            "liveTradingAllowed": False,
            "marketContext": {
                "rvol": 1.1,
                "trend": {"label": "Bullish", "tone": "hot"},
                "atrExpansion": 0.4,
                "distanceToResistancePct": 1.2,
                "distanceToSupportPct": 7.8,
            },
            "strikePlan": {
                "strategy": "CALL_DEBIT_SPREAD",
                "estimatedMaxLoss": 220,
                "estimatedMaxProfit": 180,
                "estimatedDebit": 2.2,
                "legs": [
                    {"instruction": "BUY_TO_OPEN", "symbol": "TESTC1", "ask": 2.5, "bid": 2.3},
                    {"instruction": "SELL_TO_OPEN", "symbol": "TESTC2", "ask": 1.0, "bid": 0.8},
                ],
            },
        }
        with patch(
            "inferno_risk_policy.current_single_ticket_cap",
            return_value={
                "effectiveCap": 500.0,
                "source": "config-default",
                "recommendedCap": None,
                "ackedCap": None,
                "verdict": None,
                "shouldUseRecommendation": False,
            },
        ):
            verdict = evaluate_strike_item(item, strike_plan_generated_at=None, ledger_items=[])
        self.assertFalse(verdict.passed)
        self.assertIn("bullish call spread is too close to resistance", verdict.blocks)

    def test_risk_policy_blocks_bad_schwab_chain_when_attached(self) -> None:
        item = {
            "ticker": "NVDA",
            "ok": True,
            "liveTradingAllowed": False,
            "marketContext": {
                "rvol": 1.2,
                "trend": {"label": "Bullish", "tone": "hot"},
                "distanceToResistancePct": 7.0,
                "distanceToSupportPct": 5.0,
            },
            "schwabOptions": {
                "quoteQualityScore": 42,
                "quoteQualityLabel": "poor",
                "qualityFlags": ["wide-atm-spread", "incomplete-greeks"],
                "atmSpreadQuality": "untradeable",
                "atmLiquidityScore": 40,
                "atmExpectedMoveBucket": "inferno",
            },
            "strikePlan": {
                "strategy": "CALL_DEBIT_SPREAD",
                "estimatedMaxLoss": 220,
                "estimatedMaxProfit": 240,
                "estimatedDebit": 2.2,
                "legs": [
                    {"instruction": "BUY_TO_OPEN", "symbol": "TESTC1", "ask": 2.5, "bid": 2.3},
                    {"instruction": "SELL_TO_OPEN", "symbol": "TESTC2", "ask": 1.0, "bid": 0.8},
                ],
            },
        }

        verdict = evaluate_strike_item(item, strike_plan_generated_at=None, ledger_items=[])

        self.assertFalse(verdict.passed)
        self.assertIn("Schwab option chain quality block: wide-atm-spread", verdict.blocks)
        self.assertIn("Schwab quote quality 42/poor is below paper threshold", verdict.blocks)
        self.assertIn("Schwab option chain has incomplete Greeks", verdict.warnings)
        self.assertTrue(verdict.metrics["schwabOptions"]["attached"])

    def test_risk_policy_warns_but_does_not_require_missing_schwab_chain(self) -> None:
        item = {
            "ticker": "NVDA",
            "ok": True,
            "liveTradingAllowed": False,
            "marketContext": {
                "rvol": 1.2,
                "trend": {"label": "Bullish", "tone": "hot"},
                "distanceToResistancePct": 7.0,
                "distanceToSupportPct": 5.0,
            },
            "strikePlan": {
                "strategy": "CALL_DEBIT_SPREAD",
                "estimatedMaxLoss": 220,
                "estimatedMaxProfit": 240,
                "estimatedDebit": 2.2,
                "legs": [
                    {"instruction": "BUY_TO_OPEN", "symbol": "TESTC1", "ask": 2.5, "bid": 2.3},
                    {"instruction": "SELL_TO_OPEN", "symbol": "TESTC2", "ask": 1.0, "bid": 0.8},
                ],
            },
        }

        with patch(
            "inferno_risk_policy.current_single_ticket_cap",
            return_value={
                "effectiveCap": 500.0,
                "source": "config-default",
                "recommendedCap": None,
                "ackedCap": None,
                "verdict": None,
                "shouldUseRecommendation": False,
            },
        ):
            verdict = evaluate_strike_item(item, strike_plan_generated_at=None, ledger_items=[])

        self.assertTrue(verdict.passed)
        self.assertFalse(verdict.metrics["schwabOptions"]["attached"])

    def test_clean_chain_tolerates_missing_quote_columns(self) -> None:
        frame = pd.DataFrame(
            {
                "contractSymbol": ["TEST260515C00050000"],
                "strike": [50.0],
            }
        )
        cleaned = clean_chain(frame)
        self.assertIn("ask", cleaned.columns)
        self.assertIn("bid", cleaned.columns)
        self.assertIn("lastPrice", cleaned.columns)
        self.assertTrue(cleaned.empty)


if __name__ == "__main__":
    unittest.main()
