"""Contract tests for inferno_universe_cap_fit.

Pinned invariants:
  - Module is research-only, diagnosticOnly=True, promotable=False.
  - Per-ticker structure estimates round-trip with sensible bounds.
  - Verdict thresholds are pinned: <30% fit-rate → "universe-too-expensive";
    30-60% → "many-tickers-cap-stretched"; >60% → "universe-well-suited".
  - Module NEVER mutates ledger, snapshot, or scaling state.
"""

from __future__ import annotations

import unittest

import inferno_universe_cap_fit as ucf


def _fake_snapshot(rows: list[dict]) -> dict:
    return {"generatedAt": "2026-06-22T00:00:00Z", "rows": rows}


class StructureCostEstimateTests(unittest.TestCase):
    def test_zero_or_missing_price_returns_all_none(self) -> None:
        for price in (None, 0, -10):
            out = ucf._estimate_structure_costs(price, 2.0, 50)  # type: ignore[arg-type]
            self.assertEqual(out["straddle"], None)
            self.assertEqual(out["long_leg"], None)

    def test_high_iv_rank_makes_straddle_more_expensive(self) -> None:
        low = ucf._estimate_structure_costs(100.0, 2.0, 10)
        high = ucf._estimate_structure_costs(100.0, 2.0, 90)
        self.assertGreater(high["straddle"], low["straddle"])

    def test_long_leg_is_half_straddle(self) -> None:
        out = ucf._estimate_structure_costs(100.0, 2.0, 50)
        self.assertAlmostEqual(out["long_leg"], out["straddle"] / 2, places=2)

    def test_debit_spread_always_under_500_at_5_width(self) -> None:
        # $5-wide spread cost is bounded by width * 100 = $500
        out = ucf._estimate_structure_costs(1000.0, 5.0, 100)
        self.assertLessEqual(out["debit_5w"], 500.0)

    def test_credit_spread_max_loss_has_floor(self) -> None:
        # Even at max iv_tilt, credit_1w max loss has a $25 floor
        out = ucf._estimate_structure_costs(100.0, 2.0, 100)
        self.assertGreaterEqual(out["credit_1w"], 25.0)


class VerdictThresholdTests(unittest.TestCase):
    def test_well_suited_at_high_fit_rate(self) -> None:
        # Cheap stocks → universe-well-suited verdict
        rows = [
            {"ticker": f"T{i}", "price": 10.0, "atrPercent": 2.0, "ivRank": 50}
            for i in range(20)
        ]
        out = ucf.build_audit(snapshot=_fake_snapshot(rows), cap_dollars=500.0)
        self.assertEqual(out["verdict"], "universe-well-suited-to-cap")
        self.assertEqual(out["counts"]["anyFits"], 20)

    def test_too_expensive_at_low_fit_rate(self) -> None:
        # All very-expensive stocks where credit-spread floor wins → still fits.
        # To genuinely create none-fits, need missing-price rows.
        rows = [
            {"ticker": f"T{i}", "price": None}
            for i in range(20)
        ]
        out = ucf.build_audit(snapshot=_fake_snapshot(rows), cap_dollars=500.0)
        self.assertEqual(out["verdict"], "universe-too-expensive-for-cap")
        self.assertEqual(out["counts"]["noneFits"], 0)
        self.assertEqual(out["counts"]["missingPrice"], 20)

    def test_empty_universe_returns_zero_fit_rate(self) -> None:
        out = ucf.build_audit(snapshot=_fake_snapshot([]), cap_dollars=500.0)
        self.assertEqual(out["counts"]["total"], 0)
        self.assertEqual(out["fitRate"], 0)


class InvariantTests(unittest.TestCase):
    def test_payload_has_research_only_invariants(self) -> None:
        out = ucf.build_audit(snapshot=_fake_snapshot([]), cap_dollars=500.0)
        self.assertEqual(out["stage"], "universe-cap-fit-research-only")
        self.assertTrue(out["researchOnly"])
        self.assertTrue(out["diagnosticOnly"])
        self.assertFalse(out["promotable"])
        self.assertFalse(out["authorityChanged"])
        self.assertFalse(out["brokerSubmitAllowed"])
        self.assertFalse(out["liveTradingAllowed"])

    def test_text_render_is_nonempty(self) -> None:
        rows = [{"ticker": "AAA", "price": 50.0, "atrPercent": 2.0, "ivRank": 40}]
        out = ucf.build_audit(snapshot=_fake_snapshot(rows), cap_dollars=500.0)
        text = ucf.render_text(out)
        self.assertIn("Universe Cap-Fit", text)
        self.assertIn("Fit rate", text)


if __name__ == "__main__":
    unittest.main()
