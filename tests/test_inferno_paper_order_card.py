from __future__ import annotations

import unittest
from datetime import date

import inferno_paper_order_card as oc

TODAY = date(2026, 10, 6)


def ticket(**kw):
    base = {
        "ticketId": "abc123", "ticker": "DELL", "strategy": "CALL_DEBIT_SPREAD", "status": "paper-staged",
        "expiration": "2026-10-16", "entryLimit": 3.2, "entryCostType": "debit", "estimatedMaxLoss": 320.0,
        "exitRule": "exit-before-earnings",
        "legs": [{"instruction": "BUY_TO_OPEN", "putCall": "CALL", "symbol": "DELL  261016C00450000",
                  "strike": 450.0, "expiration": "2026-10-16", "bid": 23.0, "ask": 23.8}],
    }
    base.update(kw)
    return base


class OrderCardTests(unittest.TestCase):
    def test_enter_card_has_order_chase_and_record_command(self):
        card = oc.card_for(ticket(), {"ticketId": "abc123", "status": "planned"}, TODAY)
        self.assertEqual(card["kind"], "enter")
        self.assertEqual(card["orderType"], "NET DEBIT LIMIT, DAY")
        self.assertEqual(card["dontChasePast"], 3.35)
        self.assertIn("inferno_record_fill.py abc123 --entry", card["recordCommand"])
        self.assertTrue(card["seeded"])

    def test_credit_chase_goes_down(self):
        card = oc.card_for(ticket(entryCostType="credit", entryLimit=6.6), None, TODAY)
        self.assertEqual(card["orderType"], "NET CREDIT LIMIT, DAY")
        self.assertEqual(card["dontChasePast"], 6.25)
        self.assertFalse(card["seeded"])

    def test_exit_card_after_entry(self):
        card = oc.card_for(ticket(), {"ticketId": "abc123", "status": "open", "entryPrice": "3.1"}, TODAY)
        self.assertEqual(card["kind"], "exit")
        self.assertIn("before the earnings report", card["exitRule"])
        self.assertIn("--exit", card["recordCommand"])

    def test_closed_blocked_and_expired(self):
        self.assertIsNone(oc.card_for(ticket(paperExecution={"status": "closed"}), None, TODAY))
        self.assertIsNone(oc.card_for(ticket(status="paper-blocked"), None, TODAY))
        self.assertEqual(oc.card_for(ticket(expiration="2026-09-04"), None, TODAY)["kind"], "expired")

    def test_build_orders_exits_first_and_text(self):
        ledger = {"items": [ticket(ticketId="e1"), ticket(ticketId="x1"), ticket(ticketId="old", expiration="2026-09-01")]}
        fills = {"x1": {"ticketId": "x1", "status": "open", "entryPrice": "3.0"}}
        payload = oc.build_cards(ledger, fills, TODAY, "2026-10-06T07:00:00-06:00")
        self.assertEqual([c["kind"] for c in payload["cards"]], ["exit", "enter", "expired"])
        self.assertEqual(payload["counts"], {"exit": 1, "enter": 1, "expired": 1})
        self.assertFalse(payload["brokerSubmitAllowed"])
        text = oc.cards_text(payload)
        self.assertIn("ENTER  DELL", text)
        self.assertIn("CLOSE  DELL", text)


if __name__ == "__main__":
    unittest.main()
