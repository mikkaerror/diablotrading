"""Behavioral checks for the diagnostic premium/universe contract."""
from copy import deepcopy
import unittest

import inferno_score_threshold_audit as audit
from inferno_expected_move_ledger import premium_comparability, premium_hurdle
from inferno_trade_evidence import long_vol_hurdle


class UniversePremiumAuditTests(unittest.TestCase):
    def fixture(self):
        return {
            "trackerSnapshot": {"generatedAt": "2026-09-04", "rows": [
                {"ticker": "SEMI", "price": 200, "ivRank": 60, "readiness": 90,
                 "signalTrigger": True, "daysUntilEarnings": 30, "atrPercent": 4,
                 "nextEarnings": "2026-10-04"},
                {"ticker": "BUILD", "price": 300, "ivRank": 20, "readiness": 90,
                 "signalTrigger": True, "daysUntilEarnings": 30, "atrPercent": 3},
            ]},
            "trackerTaxonomy": {"entries": [
                {"ticker": "SEMI", "economicExposure": "semiconductors"},
                {"ticker": "BUILD", "economicExposure": "construction"},
            ]},
            "ticketCapPolicy": {
                "constructionBand": {"hardCapDollars": 500},
                "effectiveBand": {"hardCapDollars": 2000},
                "liveCapitalBand": {"hardCapDollars": 0},
            },
            "strategyAlternativePricing": {"generatedAt": "2026-09-04", "items": [{
                "ticker": "SEMI", "price": 200, "status": "priced", "combinedPassed": False,
                "expiration": "2026-10-02", "strikePlan": {
                    "strategy": "CALL_DEBIT_SPREAD", "estimatedMaxLoss": 600,
                    "estimatedMaxProfit": 400, "legs": [
                        {"putCall": "CALL", "instruction": "BUY_TO_OPEN", "strike": 200},
                        {"putCall": "CALL", "instruction": "SELL_TO_OPEN", "strike": 210},
                    ],
                },
            }]},
        }

    def test_nominal_price_counterfactual_does_not_override_other_gates_or_mutate(self):
        artifacts = self.fixture()
        before = deepcopy(artifacts)
        result = audit.universe_premium_context(artifacts)
        self.assertEqual(result["aboveNominalPriceCap"], 2)
        self.assertEqual(result["nominalPriceOnlyExclusionCount"], 1)
        self.assertEqual(result["nominalPriceOnlyExclusions"][0]["ticker"], "SEMI")
        self.assertTrue(result["nominalPriceOnlyExclusions"][0]["broadShortPremiumRouteEligible"])
        self.assertFalse(result["candidateSelectionChanged"])
        self.assertEqual(artifacts, before)

    def test_budget_fit_is_not_tradeability_and_spread_captures_only_limited_upside(self):
        result = audit.universe_premium_context(self.fixture())
        row = result["pricedStructures"][0]
        self.assertFalse(row["fitsConstructionCap"])
        self.assertTrue(row["fitsPaperBudget"])
        self.assertFalse(row["combinedPassed"])
        self.assertEqual(row["upsideCapMovePct"], 5)
        self.assertEqual(row["spreadWidthPctOfSpot"], 5)
        self.assertEqual(row["maxProfitR"], 0.6667)
        self.assertEqual(row["eventCoverage"], "expires-before-earnings")
        self.assertEqual(row["calendarDaysToExpirationAtPricing"], 28)
        self.assertEqual(result["caps"]["liveCapitalDollars"], 0)

    def test_missing_nonfinite_and_duplicate_inputs_do_not_create_evidence(self):
        artifacts = self.fixture()
        artifacts["trackerSnapshot"]["rows"].append(deepcopy(artifacts["trackerSnapshot"]["rows"][0]))
        artifacts["ticketCapPolicy"] = {}
        plan = artifacts["strategyAlternativePricing"]["items"][0]["strikePlan"]
        plan["estimatedMaxLoss"] = float("nan")
        plan["estimatedMaxProfit"] = True
        result = audit.universe_premium_context(artifacts)
        self.assertEqual(result["tickerCount"], 2)
        self.assertEqual(result["duplicateTrackerRows"], 1)
        row = result["pricedStructures"][0]
        self.assertIsNone(row["fitsConstructionCap"])
        self.assertIsNone(row["fitsPaperBudget"])
        self.assertIsNone(row["maxProfitR"])
        self.assertEqual(audit.universe_premium_context({})["verdict"], "missing-universe")

    def test_same_date_earnings_does_not_imply_event_is_covered(self):
        artifacts = self.fixture()
        artifacts["strategyAlternativePricing"]["items"][0]["expiration"] = "2026-10-04"
        self.assertEqual(audit.universe_premium_context(artifacts)["pricedStructures"][0]["eventCoverage"], "same-date-timing-unknown")

    def test_tail_selected_benchmarks_are_not_typical_event_calibration(self):
        artifacts = self.fixture()
        artifacts["eventMoveCalibration"] = {"symbols": [{
            "eventSource": "inferred-large-move-volume-surge", "events": [{}, {}],
        }]}
        context = audit.universe_premium_context(artifacts)
        self.assertEqual(context["historicalBenchmarkAudit"]["outcomeSelectedEvents"], 2)
        self.assertFalse(context["historicalBenchmarkAudit"]["typicalEventCalibrationAllowed"])
        self.assertTrue(any("Selected large-move" in row["title"] for row in audit.universe_premium_findings(context)))

    def test_own_stock_atr_scales_hurdle_but_does_not_prove_value(self):
        slow = premium_hurdle(entry={"atrPercent": 1, "scenarioScore": 90}, implied_pct=5, baseline=100)
        fast = premium_hurdle(entry={"atrPercent": 5, "scenarioScore": 90}, implied_pct=5, baseline=1000)
        self.assertEqual(slow["requiredMoveAtrMultiple"], 5)
        self.assertEqual(fast["requiredMoveAtrMultiple"], 1)
        self.assertGreater(slow["rankPenalty"], fast["rankPenalty"])
        scaled = premium_hurdle(entry={"atrPercent": 5, "scenarioScore": 90}, implied_pct=5, baseline=100)
        self.assertEqual(scaled["rankPenalty"], fast["rankPenalty"])

    def test_tenor_uses_option_expiry_and_source_time_not_days_to_earnings(self):
        context = premium_comparability({"expiration": "2026-09-11", "daysUntilEarnings": 2,
                                         "sourceStrikePlanGeneratedAt": "2026-09-04"}, source_as_of="2026-09-06")
        self.assertEqual(context["calendarDaysToExpiration"], 7)
        self.assertFalse(context["sameHorizonComparison"])
        self.assertFalse(context["fairValueConclusionAllowed"])
        missing = premium_comparability({"daysUntilEarnings": 2}, source_as_of="2026-09-06")
        self.assertEqual(missing["status"], "missing-option-expiration")
        self.assertIsNone(missing["calendarDaysToExpiration"])
        expired = premium_comparability({"expiration": "2026-09-04"}, source_as_of="2026-09-06")
        self.assertEqual(expired["status"], "nonpositive-option-tenor")

    def test_fixed_evidence_band_rejects_low_and_high_move_even_with_positive_forecast(self):
        for move, expected in [(5, "shadow-only-event-premium-mismatch"), (25, "shadow-only-high-implied-move")]:
            with self.subTest(implied_move=move):
                result = long_vol_hurdle({"strategy": "LONG_STRADDLE", "price": 100,
                    "daysUntilEarnings": 3, "forecastRealizedMovePct": 40,
                    "schwabOptions": {"atmImpliedMovePct": move, "atmSpreadPct": 5}})
                self.assertGreater(result["forecastEdgePct"], 0)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["paperComparisonAllowed"])


if __name__ == "__main__":
    unittest.main()
