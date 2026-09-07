"""Entry-price, payoff, partial-quote and calendar regressions."""
from copy import deepcopy
from datetime import date, datetime, timezone
import unittest

import inferno_paper_mark_to_market as mtm
import inferno_trade_management as tm
from inferno_trade_evidence import entry_economics

NOW = datetime(2026, 9, 6, 18, tzinfo=timezone.utc)


def ticket(credit=False):
    return {
        "ticker": "TEST", "strategy": "PUT_CREDIT_SPREAD" if credit else "CALL_DEBIT_SPREAD",
        "expiration": "2026-10-02", "entryCostType": "credit" if credit else "debit",
        "entryLimit": 1.1 if credit else 2.75,
        "estimatedMaxLoss": 390 if credit else 275,
        "estimatedMaxProfit": 110 if credit else 225,
        "legs": [{"symbol": "LONG", "instruction": "BUY_TO_OPEN", "mid": 1},
                 {"symbol": "SHORT", "instruction": "SELL_TO_OPEN", "mid": 2.1}],
    }


def contracts():
    return [{"symbol": "LONG", "mid": 1, "bid": 0.9, "ask": 1.1},
            {"symbol": "SHORT", "mid": 1.6, "bid": 1.5, "ask": 1.7}]


class EntryExitContractTests(unittest.TestCase):
    def mark(self, t, quotes):
        return mtm.mark_to_market_one_ticket(t, contracts=quotes, underlying_price=100, now=NOW)

    def test_missing_first_or_second_quote_blocks_full_position_pnl(self):
        for quotes in (contracts()[:1], contracts()[1:]):
            with self.subTest(quotes=quotes):
                out = self.mark(ticket(), quotes)
                self.assertEqual(out["fetchStatus"], "partial")
                self.assertIsNone(out["unrealizedPnlDollars"])
                self.assertIsNone(out["quotedLiquidationPnlDollars"])

    def test_shared_basis_matches_reports_for_valid_and_invalid_entries(self):
        for credit in (False, True):
            for quantity in (1, 3, 0, 1.5, True, float("inf")):
                for price in (1.2, None, -1, float("nan")):
                    with self.subTest(credit=credit, quantity=quantity, price=price):
                        t = ticket(credit)
                        t["paperExecution"] = {"entryPrice": price, "contracts": quantity}
                        basis = entry_economics(t)
                        mark = self.mark(t, contracts())
                        economics = tm.exit_economics(t, mark)
                        self.assertEqual(mark["entryEconomics"], basis)
                        self.assertEqual(economics["entryEconomics"], basis)
                        if not basis["valuationBasisValid"]:
                            self.assertIsNone(mark["unrealizedPnlDollars"])
                            self.assertIsNone(economics["firstTargetProfitDollars"])
                            self.assertIsNone(economics["definedMaxLossDollars"])

    def test_filled_debit_with_no_planning_price_has_known_cost_unknown_reward(self):
        t = ticket(); t.pop("entryLimit")
        t["paperExecution"] = {"entryPrice": 1.8, "contracts": 2}
        out = self.mark(t, contracts())
        self.assertEqual(out["estimatedMaxLoss"], 360)
        self.assertIsNone(out["estimatedMaxProfit"])
        self.assertEqual(tm.exit_economics(t)["definedMaxLossDollars"], 360)

    def test_summary_uses_fill_and_mark_cannot_replace_entry_economics(self):
        t = ticket(); t["paperExecution"] = {"entryPrice": 1.8, "contracts": 2}
        result = tm.assess_ticket(t, mark={"fetchStatus": "ok"}, today=NOW.date())
        self.assertEqual(result["entryLimit"], 1.8)
        self.assertEqual(result["stagedEntryLimit"], 2.75)
        self.assertEqual(result["estimatedMaxLoss"], 360)
        self.assertEqual(result["estimatedMaxProfit"], 640)
        poisoned_mark = {"estimatedMaxLoss": 1, "estimatedMaxProfit": 99999}
        self.assertEqual(tm.exit_economics(t, poisoned_mark)["entryEconomics"], entry_economics(t))

    def test_rejected_mark_retains_status_timestamp_and_reason(self):
        t = ticket()
        mark = {"fetchStatus": "partial", "asOf": NOW.isoformat(), "playbookPctOfDebit": 2}
        out = tm.assess_ticket(t, mark=mark, today=NOW.date())
        self.assertEqual(out["verdict"], "awaiting-data")
        self.assertEqual(out["markFetchStatus"], "partial")
        self.assertEqual(out["markAsOf"], NOW.isoformat())
        self.assertIn("mark-fetch-partial", out["priceRulesBlockedReasons"])

    def test_old_fill_basis_cannot_fire_an_exit_after_fill_correction(self):
        t = ticket(); t["paperExecution"] = {"entryPrice": 1.8, "contracts": 2}
        mark = {"fetchStatus": "ok", "entryLimit": 2.75, "contracts": 1,
                "entryCostType": "debit", "playbookPctOfDebit": 2}
        out = tm.assess_ticket(t, mark=mark, today=NOW.date())
        self.assertEqual(out["verdict"], "awaiting-data")
        self.assertIn("mark-entry-basis-mismatch:entryLimit", out["priceRulesBlockedReasons"])
        self.assertIn("mark-entry-basis-mismatch:contracts", out["priceRulesBlockedReasons"])

    def test_old_profit_denominator_is_blocked_even_with_correct_fill_price(self):
        t = ticket(credit=True)
        t["paperExecution"] = {"entryPrice": 1.2, "contracts": 2}
        mark = self.mark(t, contracts())
        mark["estimatedMaxProfit"] = 220
        out = tm.assess_ticket(t, mark=mark, today=NOW.date())
        self.assertEqual(out["verdict"], "awaiting-data")
        self.assertIn("mark-entry-basis-mismatch:estimatedMaxProfit", out["priceRulesBlockedReasons"])

    def test_negative_adjusted_payoff_stays_unknown_not_negative_risk(self):
        t = ticket(credit=True)
        t["paperExecution"] = {"entryPrice": 9, "contracts": 1}
        out = entry_economics(t)
        self.assertIsNone(out["estimatedMaxLoss"])
        self.assertIn("invalid-max-loss-estimate", out["issues"])

    def test_empty_legs_unknown_sign_and_nonfinite_marks_cannot_fake_pnl(self):
        cases = []
        t = ticket(); t["legs"] = []; cases.append((t, contracts()))
        t = ticket(); t["legs"][0]["instruction"] = "UNKNOWN"; cases.append((t, contracts()))
        for invalid in (True, float("inf"), float("nan")):
            quotes = contracts(); quotes[0]["mid"] = invalid; cases.append((ticket(), quotes))
        for t, quotes in cases:
            self.assertIsNone(self.mark(t, quotes)["unrealizedPnlDollars"])

    def test_actual_credit_and_quantity_reconcile_all_return_denominators(self):
        t = ticket(credit=True)
        t["paperExecution"] = {"entryPrice": 1.2, "contracts": 2}
        before = deepcopy(t)
        out = self.mark(t, contracts())
        self.assertEqual(out["entryPriceSource"], "paper-fill")
        self.assertEqual(out["unrealizedPnlDollars"], 120)
        self.assertAlmostEqual(out["estimatedMaxLoss"], 760)
        self.assertEqual(out["estimatedMaxProfit"], 240)
        self.assertEqual(out["unrealizedPnlPctOfMaxProfit"], 0.5)
        self.assertEqual(out["quotedLiquidationPnlDollars"], 80)
        self.assertEqual(tm.exit_economics(t, out)["plannedStopLossDollars"], 240)
        self.assertEqual(tm.exit_economics(t)["definedMaxLossDollars"], 760)
        self.assertEqual(t, before)

    def test_invalid_fill_never_falls_back_to_planned_entry(self):
        t = ticket(); t["paperExecution"] = {"entryPrice": float("inf")}
        self.assertIsNone(self.mark(t, contracts())["unrealizedPnlDollars"])
        t["paperExecution"] = {"entryPrice": 1.2, "contracts": 1.5}
        self.assertIsNone(self.mark(t, contracts())["unrealizedPnlDollars"])

    def test_credit_stop_uses_executed_credit_not_stale_plan(self):
        t = ticket(credit=True)
        t["strikePlan"] = {"estimatedCredit": 1.1}
        t["paperExecution"] = {"entryPrice": 0.9, "contracts": 2}
        mark = {"fetchStatus": "ok", "unrealizedPnlDollars": -180, "unrealizedPnlPctOfMaxProfit": -1}
        self.assertEqual(tm.assess_ticket(t, mark=mark, today=NOW.date())["verdict"], "stop-loss")

    def test_debit_target_basis_and_full_loss_stress_are_distinct(self):
        out = tm.exit_economics(ticket())
        self.assertEqual(out["firstTargetProfitDollars"], 112.5)
        self.assertEqual(out["plannedStopLossDollars"], 137.5)
        self.assertAlmostEqual(out["firstTargetReturnOnMaxRisk"], 0.409091)
        self.assertEqual(out["twoOutcomeBreakevenAtPlannedStop"], 0.55)
        self.assertAlmostEqual(out["twoOutcomeBreakevenAtFullLoss"], 0.709677)
        self.assertFalse(out["wholeContractScaleOutPossible"])

    def test_runner_ladder_returns_100_percent_not_200_and_requires_four_units(self):
        t = ticket(); t["strategy"] = "LONG_CALL"
        one = tm.exit_economics(t)
        self.assertFalse(one["wholeContractScaleOutPossible"])
        self.assertEqual(one["runnerLadderIllustration"][0]["totalReturnIfRemainderExpiresWorthless"], -0.25)
        self.assertEqual(one["runnerLadderIllustration"][1]["totalReturnIfRemainderExpiresWorthless"], 0.25)
        self.assertEqual(one["runnerLadderIllustration"][-1]["realizedGainFractionOfOriginalDebit"], 1)
        t["contracts"] = 4
        self.assertTrue(tm.exit_economics(t)["wholeContractScaleOutPossible"])

    def test_credit_campaign_alias_and_stop_beyond_max_loss(self):
        t = ticket(credit=True); t.update(strategy="SHORT_PREMIUM_DEFINED", entryLimit=3.9, estimatedMaxProfit=390, estimatedMaxLoss=110)
        out = tm.exit_economics(t)
        self.assertEqual(out["lane"], "lane-b-credit")
        self.assertTrue(out["plannedStopExceedsDefinedMaxLoss"])

    def test_earnings_count_ages_and_calendar_exit_survives_missing_mark(self):
        t = ticket(); t.update(strategy="LONG_CALL", daysUntilEarnings=7, sourceStrikePlanGeneratedAt="2026-09-01")
        timing = tm.event_timing(t, date(2026, 9, 7))
        self.assertEqual(timing["daysUntilEarnings"], 1)
        self.assertEqual(tm.assess_ticket(t, mark=None, today=date(2026, 9, 7))["verdict"], "pre-event-exit")
        t["nextEarnings"] = "2026-09-20"
        self.assertEqual(tm.event_timing(t, date(2026, 9, 7))["daysUntilEarnings"], 13)

    def test_undated_count_is_unknown_and_bad_mark_does_not_fire_profit_trigger(self):
        t = ticket(); t.update(strategy="LONG_CALL", daysUntilEarnings=1)
        self.assertIsNone(tm.event_timing(t, NOW.date())["daysUntilEarnings"])
        result = tm.assess_ticket(t, mark={"fetchStatus": "partial", "playbookPctOfDebit": 2}, today=NOW.date())
        self.assertEqual(result["verdict"], "awaiting-data")
        self.assertEqual(tm.assess_ticket({**t, "strategy": "UNKNOWN"}, mark=None, today=NOW.date())["verdict"], "awaiting-data")


if __name__ == "__main__":
    unittest.main()
