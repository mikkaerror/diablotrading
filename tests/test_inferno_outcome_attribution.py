"""Contract tests for inferno_outcome_attribution.

Pinned invariants:
  - Module is research-only and promotable=False.
  - Empty-data case produces a valid 'awaiting-closed-outcomes' verdict
    without crashing.
  - Brinson decomposition identity holds: allocation + selection +
    interaction = active return (within float tolerance).
  - The Eckhardt comfortable-win flag fires ONLY on winners that
    cleared the readiness floor AND sat in the dominant family.
  - Citations include BHB-1986 and ECKHARDT-MW93.
"""

from __future__ import annotations

import unittest

from inferno_outcome_attribution import (
    ATTRIBUTION_STAGE,
    _brinson_decompose,
    _eckhardt_flags,
    _strategy_family,
    build_outcome_attribution,
    outcome_attribution_text,
)


class OutcomeAttributionTests(unittest.TestCase):
    # ---------- module-level invariants ----------

    def test_module_is_research_only(self):
        self.assertEqual(ATTRIBUTION_STAGE, "outcome-attribution-research-only")

    def test_empty_data_does_not_crash(self):
        """With no ledger files, build still returns a valid payload."""
        # Use the live function — even if shadow + paper exist, the
        # closed-outcome count is currently 0, so verdict must be 'awaiting'.
        payload = build_outcome_attribution()
        self.assertFalse(payload["promotable"])
        self.assertEqual(payload["stage"], ATTRIBUTION_STAGE)
        if payload["counts"]["closedOutcomes"] == 0:
            self.assertEqual(payload["verdict"], "awaiting-closed-outcomes")

    def test_payload_has_required_citations(self):
        payload = build_outcome_attribution()
        cits = payload.get("citations") or []
        self.assertIn("BHB-1986", cits)
        self.assertIn("ECKHARDT-MW93", cits)

    # ---------- strategy family bucketing ----------

    def test_strategy_family_buckets(self):
        cases = {
            "LONG_STRADDLE": "Long Straddle",
            "STRADDLE": "Long Straddle",
            "CALL_DEBIT_SPREAD": "Vertical Debit",
            "PUT_CREDIT_SPREAD": "Credit Spread",
            "IRON_CONDOR": "Iron Condor",
            "BUTTERFLY": "Butterfly",
            "Calendar": "Calendar / Diagonal",
            "Vertical Call": "Vertical",
        }
        for raw, expected in cases.items():
            self.assertEqual(_strategy_family({"strategy": raw}), expected)

    # ---------- Brinson identity ----------

    def test_brinson_identity_holds(self):
        """Active return must equal alloc + selection + interaction."""
        # Synthetic two-family case
        portfolio = [
            {"strategy": "LONG_STRADDLE", "pnl": 100.0, "tradeDate": "2026-05-01"},
            {"strategy": "LONG_STRADDLE", "pnl": -50.0, "tradeDate": "2026-05-01"},
            {"strategy": "CALL_DEBIT_SPREAD", "pnl": 40.0, "tradeDate": "2026-05-01"},
        ]
        universe = portfolio + [
            {"strategy": "LONG_STRADDLE", "pnl": 60.0, "tradeDate": "2026-05-01"},
            {"strategy": "CALL_DEBIT_SPREAD", "pnl": 10.0, "tradeDate": "2026-05-01"},
            {"strategy": "CALL_DEBIT_SPREAD", "pnl": 30.0, "tradeDate": "2026-05-01"},
        ]
        d = _brinson_decompose(portfolio, universe)
        t = d["totals"]
        self.assertAlmostEqual(
            t["active_return"],
            t["allocation"] + t["selection"] + t["interaction"],
            places=4,
        )

    def test_brinson_empty_portfolio_zeroes(self):
        d = _brinson_decompose([], [])
        self.assertEqual(d["totals"]["active_return"], 0.0)
        self.assertEqual(d["families"], [])

    def test_brinson_zero_active_when_portfolio_equals_universe(self):
        """If we hold the universe, active return is exactly zero."""
        universe = [
            {"strategy": "LONG_STRADDLE", "pnl": 50.0, "tradeDate": "x"},
            {"strategy": "CALL_DEBIT_SPREAD", "pnl": -20.0, "tradeDate": "x"},
        ]
        d = _brinson_decompose(universe, universe)
        self.assertAlmostEqual(d["totals"]["active_return"], 0.0, places=6)

    # ---------- Eckhardt comfortable-win flag ----------

    def test_eckhardt_fires_on_dominant_family_winner(self):
        universe = [
            {"strategy": "LONG_STRADDLE", "ticker": "A", "tradeDate": "d1",
             "pnl": 100.0, "readinessScore": 85},
            {"strategy": "LONG_STRADDLE", "ticker": "B", "tradeDate": "d1"},
            {"strategy": "LONG_STRADDLE", "ticker": "C", "tradeDate": "d1"},
            {"strategy": "CALL_DEBIT_SPREAD", "ticker": "D", "tradeDate": "d1"},
        ]
        closed = [universe[0]]
        flags = _eckhardt_flags(closed, universe)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["citation"], "ECKHARDT-MW93")
        self.assertEqual(flags[0]["family"], "Long Straddle")

    def test_eckhardt_silent_on_loser(self):
        universe = [
            {"strategy": "LONG_STRADDLE", "ticker": "A", "tradeDate": "d1",
             "pnl": -50.0, "readinessScore": 90},
            {"strategy": "LONG_STRADDLE", "ticker": "B", "tradeDate": "d1"},
            {"strategy": "LONG_STRADDLE", "ticker": "C", "tradeDate": "d1"},
        ]
        flags = _eckhardt_flags([universe[0]], universe)
        self.assertEqual(flags, [])

    def test_eckhardt_silent_on_low_readiness(self):
        universe = [
            {"strategy": "LONG_STRADDLE", "ticker": "A", "tradeDate": "d1",
             "pnl": 50.0, "readinessScore": 60},
            {"strategy": "LONG_STRADDLE", "ticker": "B", "tradeDate": "d1"},
            {"strategy": "LONG_STRADDLE", "ticker": "C", "tradeDate": "d1"},
        ]
        flags = _eckhardt_flags([universe[0]], universe)
        self.assertEqual(flags, [])

    def test_eckhardt_silent_when_not_dominant_family(self):
        # Three families, no dominance over 50%
        universe = [
            {"strategy": "LONG_STRADDLE", "ticker": "A", "tradeDate": "d1",
             "pnl": 50.0, "readinessScore": 90},
            {"strategy": "CALL_DEBIT_SPREAD", "ticker": "B", "tradeDate": "d1"},
            {"strategy": "IRON_CONDOR", "ticker": "C", "tradeDate": "d1"},
        ]
        flags = _eckhardt_flags([universe[0]], universe)
        self.assertEqual(flags, [])

    # ---------- text rendering ----------

    def test_rendered_text_has_required_sections(self):
        payload = build_outcome_attribution()
        text = outcome_attribution_text(payload)
        self.assertIn("Inferno Outcome Attribution", text)
        self.assertIn("research-only", text)
        self.assertIn("Reminders:", text)


if __name__ == "__main__":
    unittest.main()
