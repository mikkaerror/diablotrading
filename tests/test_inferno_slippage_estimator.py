"""Contract tests for inferno_slippage_estimator.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Leg direction parses BUY_* as +1 and SELL_* as -1; unknown returns None.
  - Quoted spread math: spread = ask - bid, spreadPct = spread / mid.
  - Strategy family classifier handles snake_case (`long_straddle`,
    `call_debit_spread`) and display forms (`Long Straddle`, `Vertical Call`).
  - Entry slippage = entryLimit - Σ d_i · m_i, denominator |Σ d_i · m_i|.
  - Family verdict is 'thin' below MIN_TICKETS_PER_FAMILY, 'anchored' at/above.
  - Flags: wide-leg-spread when any leg spreadPct > WIDE_SPREAD_FLAG_PCT;
    high-entry-slippage when |entrySlipPct| > HIGH_ENTRY_SLIP_FLAG_PCT.
  - Empty-input case returns a clean 'no-usable-tickets' verdict.
  - Citations include ROLL-1984 and HASBROUCK-1991.
"""

from __future__ import annotations

import unittest

from inferno_slippage_estimator import (
    HIGH_ENTRY_SLIP_FLAG_PCT,
    MIN_TICKETS_PER_FAMILY,
    SLIPPAGE_STAGE,
    WIDE_SPREAD_FLAG_PCT,
    _family_anchor,
    _leg_direction,
    _leg_quoted_spread,
    _strategy_family,
    _ticket_entry_slippage,
    build_slippage_estimator,
    compute_slippage_table,
    slippage_estimator_text,
)


def _leg(instruction="BUY_TO_OPEN", bid=1.0, ask=1.1, mid=None, **kw):
    out = {"instruction": instruction, "bid": bid, "ask": ask}
    if mid is not None:
        out["mid"] = mid
    out.update(kw)
    return out


class LegDirectionTests(unittest.TestCase):
    def test_buy_to_open_is_plus_one(self):
        self.assertEqual(_leg_direction({"instruction": "BUY_TO_OPEN"}), 1)

    def test_buy_to_close_is_plus_one(self):
        self.assertEqual(_leg_direction({"instruction": "BUY_TO_CLOSE"}), 1)

    def test_sell_to_open_is_minus_one(self):
        self.assertEqual(_leg_direction({"instruction": "SELL_TO_OPEN"}), -1)

    def test_unknown_is_none(self):
        self.assertIsNone(_leg_direction({"instruction": "WAT"}))

    def test_missing_is_none(self):
        self.assertIsNone(_leg_direction({}))


class QuotedSpreadTests(unittest.TestCase):
    def test_basic_spread_math(self):
        out = _leg_quoted_spread(_leg(bid=1.00, ask=1.10))
        self.assertEqual(out["spread"], 0.10)
        self.assertEqual(out["mid"], 1.05)
        self.assertAlmostEqual(out["spreadPct"], 0.10 / 1.05, places=6)

    def test_missing_bid_returns_none(self):
        out = _leg_quoted_spread({"ask": 1.10})
        self.assertIsNone(out["spread"])
        self.assertIsNone(out["spreadPct"])

    def test_zero_mid_returns_none_spread_pct(self):
        out = _leg_quoted_spread({"bid": 0.0, "ask": 0.0, "mid": 0.0})
        self.assertIsNone(out["spreadPct"])


class StrategyFamilyTests(unittest.TestCase):
    def test_snake_case_long_straddle(self):
        self.assertEqual(_strategy_family({"strategy": "long_straddle"}), "Long Straddle")

    def test_snake_case_call_debit_spread(self):
        self.assertEqual(_strategy_family({"strategy": "call_debit_spread"}), "Vertical Debit")

    def test_display_vertical_call(self):
        self.assertEqual(_strategy_family({"setupRec": "Vertical Call"}), "Vertical Debit")

    def test_iron_condor(self):
        self.assertEqual(_strategy_family({"strategy": "iron_condor"}), "Iron Condor")

    def test_calendar(self):
        self.assertEqual(_strategy_family({"strategy": "calendar_call"}), "Calendar / Diagonal")

    def test_credit(self):
        self.assertEqual(_strategy_family({"strategy": "credit_spread"}), "Credit Spread")

    def test_falls_through_to_unknown(self):
        self.assertEqual(_strategy_family({"strategy": "weirdthing"}), "Unknown")

    def test_empty_is_unknown(self):
        self.assertEqual(_strategy_family({}), "Unknown")


class EntrySlippageTests(unittest.TestCase):
    def test_clean_two_leg_debit_spread(self):
        # Buy leg mid 1.00, sell leg mid 0.40 → net 0.60 debit
        ticket = {
            "ticketId": "T1",
            "ticker": "AAA",
            "strategy": "call_debit_spread",
            "entryLimit": 0.70,  # we pay 0.70 vs 0.60 mid → 0.10 slip = 16.67%
            "legs": [
                _leg("BUY_TO_OPEN", bid=0.95, ask=1.05),
                _leg("SELL_TO_OPEN", bid=0.35, ask=0.45),
            ],
        }
        slip = _ticket_entry_slippage(ticket)
        self.assertTrue(slip["usable"])
        self.assertAlmostEqual(slip["sumLegMidNet"], 0.60, places=6)
        self.assertAlmostEqual(slip["entrySlippage"], 0.10, places=6)
        self.assertAlmostEqual(slip["entrySlipPct"], 0.10 / 0.60, places=4)
        self.assertIn("high-entry-slippage", slip["flags"])

    def test_unusable_when_leg_missing_bid(self):
        ticket = {
            "ticketId": "T2",
            "ticker": "BBB",
            "entryLimit": 1.0,
            "legs": [_leg("BUY_TO_OPEN", bid=None, ask=1.10)],
        }
        slip = _ticket_entry_slippage(ticket)
        self.assertFalse(slip["usable"])

    def test_unusable_without_entry_limit(self):
        ticket = {
            "ticketId": "T3",
            "ticker": "CCC",
            "legs": [_leg("BUY_TO_OPEN")],
        }
        slip = _ticket_entry_slippage(ticket)
        self.assertFalse(slip["usable"])

    def test_wide_spread_flag(self):
        # Leg with spread / mid > WIDE_SPREAD_FLAG_PCT
        ticket = {
            "ticketId": "T4",
            "ticker": "DDD",
            "strategy": "long_straddle",
            "entryLimit": 1.05,
            "legs": [
                # ask 1.5, bid 0.5, mid 1.0 → spread pct 100%
                _leg("BUY_TO_OPEN", bid=0.5, ask=1.5),
                _leg("BUY_TO_OPEN", bid=0.9, ask=1.0),
            ],
        }
        slip = _ticket_entry_slippage(ticket)
        self.assertTrue(slip["usable"])
        self.assertIn("wide-leg-spread", slip["flags"])

    def test_no_legs_is_unusable(self):
        slip = _ticket_entry_slippage({"ticketId": "T5", "entryLimit": 1.0})
        self.assertFalse(slip["usable"])


class FamilyAnchorTests(unittest.TestCase):
    def _row(self, spread_pct=0.05, slip_pct=0.03, flags=None):
        return {
            "usable": True,
            "avgLegSpreadPct": spread_pct,
            "entrySlipPct": slip_pct,
            "flags": flags or [],
        }

    def test_thin_when_below_min(self):
        anchor = _family_anchor([self._row() for _ in range(MIN_TICKETS_PER_FAMILY - 1)])
        self.assertEqual(anchor["verdict"], "thin")

    def test_anchored_at_min(self):
        anchor = _family_anchor([self._row() for _ in range(MIN_TICKETS_PER_FAMILY)])
        self.assertEqual(anchor["verdict"], "anchored")

    def test_medians_use_absolute_slip(self):
        rows = [
            self._row(spread_pct=0.05, slip_pct=0.10),
            self._row(spread_pct=0.10, slip_pct=-0.20),
            self._row(spread_pct=0.15, slip_pct=0.30),
        ]
        anchor = _family_anchor(rows)
        self.assertEqual(anchor["medianAvgLegSpreadPct"], 0.10)
        self.assertEqual(anchor["medianEntrySlipPct"], 0.20)
        self.assertEqual(anchor["maxEntrySlipPct"], 0.30)


class ComputeSlippageTableTests(unittest.TestCase):
    def test_empty_input(self):
        out = compute_slippage_table([])
        self.assertEqual(out["perTicket"], [])
        self.assertEqual(out["familyAnchors"], {})

    def test_unusable_tickets_excluded_from_family_anchors(self):
        tickets = [
            {"ticketId": "U1", "strategy": "long_straddle", "legs": []},
            {
                "ticketId": "U2",
                "strategy": "long_straddle",
                "entryLimit": 1.0,
                "legs": [_leg("BUY_TO_OPEN", bid=0.95, ask=1.05)],
            },
        ]
        out = compute_slippage_table(tickets)
        self.assertEqual(len(out["perTicket"]), 2)
        # Only the usable one made it into the family anchor
        self.assertEqual(out["familyAnchors"]["Long Straddle"]["ticketCount"], 1)


class BuildAndRenderTests(unittest.TestCase):
    def test_module_is_research_only(self):
        self.assertEqual(SLIPPAGE_STAGE, "slippage-estimator-research-only")

    def test_build_against_live_data_returns_valid_payload(self):
        payload = build_slippage_estimator()
        self.assertFalse(payload["promotable"])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["authorityChanged"])
        self.assertEqual(payload["stage"], SLIPPAGE_STAGE)
        self.assertIn(
            payload["verdict"],
            {"no-usable-tickets", "thin-anchors", "anchors-ready"},
        )
        self.assertIn("ROLL-1984", payload["citations"])
        self.assertIn("HASBROUCK-1991", payload["citations"])
        # thresholds exposed
        self.assertEqual(
            payload["thresholds"]["minTicketsPerFamily"], MIN_TICKETS_PER_FAMILY
        )

    def test_text_render_includes_key_sections(self):
        payload = build_slippage_estimator()
        text = slippage_estimator_text(payload)
        self.assertIn("Inferno Slippage Estimator", text)
        self.assertIn("Verdict:", text)
        self.assertIn("Reminders:", text)


if __name__ == "__main__":
    unittest.main()
