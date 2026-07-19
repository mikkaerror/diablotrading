from __future__ import annotations

"""Tests for the AI/data-center basket trend-crossing alerts."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import json

import inferno_ai_basket_alerts as al


def _q(sym, price, a50, a200, hi=100, lo=10):
    return {"symbol": sym, "price": price, "priceAvg50": a50,
            "priceAvg200": a200, "yearHigh": hi, "yearLow": lo}


class BasketAlertTests(unittest.TestCase):
    def test_exit_when_crossing_below_200(self):
        prev = al.compute_state([_q("DELL", 210, 200, 205)])   # above 200
        cur = al.compute_state([_q("DELL", 200, 200, 205)])     # below 200
        ev = al.diff_state(prev, cur)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["kind"], "EXIT")

    def test_reentry_when_crossing_above_200(self):
        prev = al.compute_state([_q("ORCL", 190, 195, 200)])    # below 200
        cur = al.compute_state([_q("ORCL", 205, 195, 200)])     # above 200
        ev = al.diff_state(prev, cur)
        self.assertEqual(ev[0]["kind"], "REENTRY")

    def test_warn_when_losing_50_but_above_200(self):
        prev = al.compute_state([_q("ANET", 160, 155, 140)])    # above both
        cur = al.compute_state([_q("ANET", 150, 155, 140)])     # below 50, above 200
        ev = al.diff_state(prev, cur)
        self.assertEqual(ev[0]["kind"], "WARN")

    def test_no_event_when_unchanged(self):
        prev = al.compute_state([_q("NVDA", 210, 200, 190)])
        cur = al.compute_state([_q("NVDA", 212, 201, 191)])     # still above both
        self.assertEqual(al.diff_state(prev, cur), [])

    def test_new_name_no_false_alert(self):
        prev = al.compute_state([_q("NVDA", 210, 200, 190)])
        cur = al.compute_state([_q("NVDA", 212, 201, 191), _q("AMD", 100, 90, 80)])
        self.assertEqual(al.diff_state(prev, cur), [])  # AMD has no prior -> ignored

    def test_events_sorted_exit_first(self):
        expected = ["NVDA", "AMD"]
        prev = al.compute_state(
            [_q("NVDA", 210, 200, 205), _q("AMD", 190, 195, 200)],
            expected_universe=expected,
        )
        cur = al.compute_state(
            [_q("NVDA", 200, 200, 205), _q("AMD", 205, 195, 200)],
            expected_universe=expected,
        )
        ev = al.diff_state(prev, cur)
        self.assertEqual(ev[0]["kind"], "EXIT")   # EXIT ranked before REENTRY

    def test_partial_or_extra_input_fails_closed_before_state_write(self):
        _, quality = al.quote_input_quality(
            [_q("NVDA", 210, 200, 190), _q("RBC", 100, 90, 80)],
            expected_universe=["NVDA", "AMD"],
        )
        self.assertFalse(quality["signalsTrusted"])
        self.assertEqual(quality["missingSymbols"], ["AMD"])
        self.assertEqual(quality["extraSymbolsIgnored"], ["RBC"])

    def test_untrusted_canonical_contract_does_not_update_alert_state(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            quotes = root / "quotes.json"
            quotes.write_text(json.dumps([_q(symbol, 210, 200, 190) for symbol in al.SYMBOLS]))
            state = root / "state.json"
            with mock.patch.object(al, "STATE_FILE", state):
                payload = al.run(str(quotes), data_contract={"signalsTrusted": False})
            self.assertEqual(payload["verdict"], "fail-closed")
            self.assertFalse(payload["dataContractTrusted"])
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
