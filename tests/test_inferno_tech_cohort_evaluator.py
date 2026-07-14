import unittest

from inferno_tech_cohort_evaluator import build_cohort, option_pnl, trend_state


class TechCohortEvaluatorTests(unittest.TestCase):
    def test_common_risk_and_failed_arm_exclusion(self):
        plan = {"strategy": "CALL_DEBIT_SPREAD", "estimatedDebit": 2, "estimatedMaxLoss": 200, "expiration": "2026-08-01", "legs": [{"instruction": "BUY", "strike": 100}, {"instruction": "SELL", "strike": 105}]}
        pricing = {"generatedAt": "x", "items": [{"ticker": "AMD", "status": "priced", "price": 100, "daysUntilEarnings": 5, "recommendedStrategy": "CALL_DEBIT_SPREAD", "combinedPassed": True, "strikePlan": plan}]}
        result = build_cohort(pricing, basket_contract={"signalsTrusted": True}, risk_budget=500)
        arms = result["cohorts"][0]["arms"]
        self.assertEqual(arms[0]["units"], 5)
        self.assertEqual(arms[1]["contracts"], 2)
        self.assertEqual(arms[1]["projectedPnl"]["+10%"], 600)
        self.assertTrue(arms[1]["gateEligible"])
        self.assertIsNone(arms[0]["gateEligible"])
        self.assertFalse(result["promotable"])

    def test_option_expiration_payoff(self):
        call = {"strategy": "CALL_DEBIT_SPREAD", "estimatedDebit": 2, "legs": [{"instruction": "BUY", "strike": 100}, {"instruction": "SELL", "strike": 105}]}
        put = {"strategy": "PUT_DEBIT_SPREAD", "estimatedDebit": 2, "legs": [{"instruction": "BUY", "strike": 100}, {"instruction": "SELL", "strike": 95}]}
        self.assertEqual(option_pnl(call, 110), 300)
        self.assertEqual(option_pnl(put, 90), 300)

    def test_basket_only_name_gets_share_benchmark_and_trend(self):
        basket = [{"symbol": "NVDA", "cat": "Compute", "price": 200, "priceAvg50": 190, "priceAvg200": 180}]
        result = build_cohort({"items": []}, basket=basket, basket_contract={"signalsTrusted": True}, risk_budget=500)
        row = result["cohorts"][0]
        self.assertEqual(row["trendState"], "leader-trend")
        self.assertIsNone(row["eventId"])
        self.assertEqual(row["arms"][0]["units"], 2.5)
        self.assertEqual(trend_state({"price": 90, "priceAvg50": 100, "priceAvg200": 95}), "below-200-defensive")

    def test_untrusted_contract_suppresses_trend_label(self):
        basket = [{"symbol": "NVDA", "price": 200, "priceAvg50": 190, "priceAvg200": 180}]
        result = build_cohort({"items": []}, basket=basket, basket_contract={"signalsTrusted": False})
        self.assertEqual(result["cohorts"][0]["trendState"], "untrusted-source")


if __name__ == "__main__":
    unittest.main()
