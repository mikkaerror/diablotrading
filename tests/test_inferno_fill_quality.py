import json
import tempfile
import unittest
from pathlib import Path

import inferno_fill_quality as fq


def leg(instruction, bid, ask):
    return {"instruction": instruction, "bid": bid, "ask": ask, "mid": round((bid + ask) / 2, 4)}


DEBIT = {
    "ticketId": "d1", "ticker": "DELL", "strategy": "CALL_DEBIT_SPREAD", "status": "paper-staged",
    "entryCostType": "debit", "entryLimit": 3.2, "estimatedSpreadFrictionPerCrossingDollars": 12.86,
    "legs": [leg("BUY_TO_OPEN", 23.0, 23.8), leg("SELL_TO_OPEN", 20.6, 21.4)],
}
CREDIT = {
    "ticketId": "c1", "ticker": "ACN", "strategy": "SHORT_PREMIUM_DEFINED", "status": "paper-staged",
    "entryCostType": "credit", "entryLimit": 4.0, "estimatedSpreadFrictionPerCrossingDollars": 20.0,
    "legs": [leg("SELL_TO_OPEN", 6.0, 6.4), leg("BUY_TO_OPEN", 1.8, 2.0)],
}


class StagedMarketTests(unittest.TestCase):
    def test_debit_mid_natural_far(self):
        m = fq.staged_market(DEBIT)
        self.assertAlmostEqual(m["mid"], 2.4)
        self.assertAlmostEqual(m["natural"], 3.2)
        self.assertAlmostEqual(m["far"], 1.6)

    def test_credit_magnitudes(self):
        m = fq.staged_market(CREDIT)
        self.assertAlmostEqual(m["mid"], 4.3)      # 6.2 - 1.9
        self.assertAlmostEqual(m["natural"], 4.0)  # receive bid 6.0, pay ask 2.0
        self.assertAlmostEqual(m["far"], 4.6)

    def test_missing_quotes(self):
        self.assertIsNone(fq.staged_market({"legs": [{"instruction": "BUY_TO_OPEN", "bid": None, "ask": 1}]}))
        self.assertIsNone(fq.staged_market({"legs": []}))


class AssessTests(unittest.TestCase):
    def test_debit_at_natural_is_one_half_spread(self):
        r = fq.assess(DEBIT, {"entryPrice": "3.2", "contracts": "1"}, {})
        self.assertAlmostEqual(r["slipVsStagedMid"], 0.8)
        self.assertEqual(r["halfSpreadsVsStagedMid"], 1.0)
        self.assertEqual(r["slipVsStagedMidDollars"], 80.0)
        self.assertEqual(r["flags"], [])
        self.assertFalse(r["clean"])

    def test_past_limit_and_better_than_mid_flags(self):
        past = fq.assess(DEBIT, {"entryPrice": "3.3"}, {})
        self.assertIn("filled past the staged limit", past["flags"])
        better = fq.assess(DEBIT, {"entryPrice": "2.0"}, {})
        self.assertTrue(any("better than staged mid" in f for f in better["flags"]))
        outside = fq.assess(DEBIT, {"entryPrice": "1.5"}, {})
        self.assertTrue(any("outside the staged market" in f for f in outside["flags"]))

    def test_credit_sign_positive_means_cost(self):
        r = fq.assess(CREDIT, {"entryPrice": "4.0"}, {})
        self.assertAlmostEqual(r["slipVsStagedMid"], 0.3)
        self.assertEqual(r["flags"], [])
        low = fq.assess(CREDIT, {"entryPrice": "3.9"}, {})
        self.assertIn("filled past the staged limit", low["flags"])

    def test_fill_time_mid_makes_it_clean_and_exit_cost(self):
        r = fq.assess(DEBIT, {"entryPrice": "2.5", "exitPrice": "3.0"}, {"entryMid": 2.3, "exitMid": 3.1})
        self.assertTrue(r["clean"])
        self.assertAlmostEqual(r["slipVsFillMidDollars"], 20.0)
        self.assertAlmostEqual(r["exitSlipDollars"], 10.0)   # sold 0.10 below mid

    def test_no_entry_is_skipped(self):
        self.assertIsNone(fq.assess(DEBIT, {"entryPrice": ""}, {}))


class SummaryTests(unittest.TestCase):
    def rows(self, n, slip_dollars, modeled):
        return [{"clean": True, "flags": [], "halfSpreadsVsStagedMid": 0.5,
                 "slipVsFillMidDollars": slip_dollars, "modeledFrictionPerCrossingDollars": modeled}] * n

    def test_collecting_until_five_clean(self):
        s = fq.summarize(self.rows(4, 50, 10))
        self.assertTrue(s["verdict"].startswith("collecting"))

    def test_verdicts(self):
        self.assertIn("too optimistic", fq.summarize(self.rows(5, 50, 10))["verdict"])
        self.assertIn("conservative", fq.summarize(self.rows(5, 5, 10))["verdict"])
        self.assertIn("about right", fq.summarize(self.rows(5, 10, 10))["verdict"])

    def test_model_check_flags_under_charged_spreads(self):
        checks = fq.model_check({"items": [DEBIT, CREDIT]})
        by = {c["strategy"]: c for c in checks}
        self.assertEqual(by["CALL_DEBIT_SPREAD"]["read"], "model under-charges")   # 80 / 12.86
        self.assertEqual(by["SHORT_PREMIUM_DEFINED"]["read"], "model under-charges")  # 30 / 20 = 1.5
        self.assertEqual(fq.model_check({"items": [{**DEBIT, "estimatedSpreadFrictionPerCrossingDollars": 160}]})[0]["read"],
                         "model over-charges")

class CliTests(unittest.TestCase):
    def test_note_mid_and_run_write_only_own_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ledger = tmp / "ledger.json"
            ledger.write_text(json.dumps({"items": [DEBIT]}))
            fills = tmp / "fills.csv"
            fills.write_text("ticketId,ticker,entryPrice,exitPrice,contracts\nd1,DELL,2.6,,1\n")
            marks = tmp / "marks.jsonl"
            fq.note_mid("DELL", 2.45, None, ledger_path=ledger, marks_path=marks)
            before = ledger.read_text(), fills.read_text()
            payload = fq.run(ledger, fills, marks, tmp / "out.json", tmp / "out.txt")
            self.assertEqual((ledger.read_text(), fills.read_text()), before)
            row = payload["fills"][0]
            self.assertTrue(row["clean"])
            self.assertAlmostEqual(row["slipVsFillMidDollars"], 15.0)
            self.assertFalse(payload["liveTradingAllowed"])
            self.assertIn("DELL", (tmp / "out.txt").read_text())

    def test_note_mid_refuses_unknown_and_bad_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.json"
            ledger.write_text(json.dumps({"items": [DEBIT]}))
            with self.assertRaises(SystemExit):
                fq.note_mid("ZZZ", 1.0, None, ledger_path=ledger, marks_path=Path(tmp) / "m.jsonl")
            with self.assertRaises(SystemExit):
                fq.note_mid("d1", -1.0, None, ledger_path=ledger, marks_path=Path(tmp) / "m.jsonl")


if __name__ == "__main__":
    unittest.main()
