from __future__ import annotations

import unittest
from datetime import date

import inferno_deposit_card as dc
import inferno_live_book_officer as lb

OFFICER = {"book": {"nlv": 850.0, "nextDeposit": "2026-10-09"},
           "depositRouting": {"amount": 250, "core": 137.5, "conviction": 112.5, "coreVehicle": "SMH",
                              "convictionName": "CRDO", "convictionTranche": "1/3 now, rest on a pullback",
                              "reason": "cash 29% is above the 15% reserve target"}}
SIGNED = {"active": True}


class DepositCardTests(unittest.TestCase):
    def test_card_on_deposit_day_with_tranche_and_earmark(self):
        card = dc.build_card(OFFICER, SIGNED, date(2026, 10, 9), set())
        self.assertTrue(card["show"])
        self.assertEqual([(l["symbol"], l["dollars"]) for l in card["lines"]], [("SMH", 137.5), ("CRDO", 37.5)])
        self.assertEqual(card["earmark"], {"symbol": "CRDO", "dollars": 75.0})
        text = dc.card_text(card)
        self.assertIn("you key these; the desk never buys", text)
        self.assertIn("Nothing goes to IREN, HIVE, CLSK or TE", text)
        self.assertFalse(card["brokerSubmitAllowed"])

    def test_window_signature_and_done(self):
        self.assertFalse(dc.build_card(OFFICER, SIGNED, date(2026, 10, 5), set())["show"])
        self.assertTrue(dc.build_card(OFFICER, SIGNED, date(2026, 10, 8), set())["show"])
        self.assertFalse(dc.build_card(OFFICER, {"active": False}, date(2026, 10, 9), set())["show"])
        self.assertFalse(dc.build_card(OFFICER, SIGNED, date(2026, 10, 9), {"2026-10-09"})["show"])

    def test_full_tranche_has_no_earmark(self):
        officer = {**OFFICER, "depositRouting": {**OFFICER["depositRouting"], "convictionTranche": "full"}}
        card = dc.build_card(officer, SIGNED, date(2026, 10, 9), set())
        self.assertEqual(card["lines"][1]["dollars"], 112.5)
        self.assertIsNone(card["earmark"])

    def test_reserve_rule_when_no_routing(self):
        card = dc.build_card({**OFFICER, "depositRouting": None}, SIGNED, date(2026, 10, 9), set())
        self.assertIn("reserve", card["note"])

    def test_deposit_date_rolls_forward(self):
        dep = {"nextExpected": "2026-10-09", "everyDays": 14}
        self.assertEqual(lb.next_deposit_date(dep, date(2026, 10, 9)), "2026-10-09")
        self.assertEqual(lb.next_deposit_date(dep, date(2026, 10, 10)), "2026-10-23")


if __name__ == "__main__":
    unittest.main()
