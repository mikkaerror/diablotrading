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


class ThesisFitTests(unittest.TestCase):
    """Verticals must span the event move to count as a thesis fit."""

    def test_thesis_costs_scale_with_price_and_move(self) -> None:
        small = ucf._thesis_structure_costs(20.0, 10.0)   # $2 move -> $84 full width
        big = ucf._thesis_structure_costs(850.0, 13.0)    # $110.5 move -> $4641
        self.assertAlmostEqual(small["debit_expected_move"], 84.0, places=1)
        self.assertGreater(big["debit_expected_move"], 4000)
        self.assertIsNone(ucf._thesis_structure_costs(850.0, None)["debit_expected_move"])

    def test_event_move_source_precedence(self) -> None:
        implied = {"AAA": 12.0}
        curated = {"AAA": 9.0, "BBB": 15.0}
        self.assertEqual(ucf._event_move_pct("AAA", 3.0, implied, curated), (12.0, "schwab-atm-implied"))
        self.assertEqual(ucf._event_move_pct("BBB", 3.0, implied, curated), (15.0, "curated-earnings-history-median"))
        move, source = ucf._event_move_pct("CCC", 4.0, implied, curated)
        self.assertEqual(source, "atr-x-universe-median-proxy")
        self.assertAlmostEqual(move, 4.0 * ucf.EVENT_MOVE_ATR_MULTIPLE_PROXY, places=3)
        self.assertEqual(ucf._event_move_pct("DDD", None, implied, curated), (None, "unavailable"))

    def test_audit_reports_thesis_fit_separately_from_fixed_width_fit(self) -> None:
        snapshot = {"rows": [
            {"ticker": "CHEAP", "price": 20.0, "atrPercent": 4.0, "ivRank": 50},
            {"ticker": "PRICEY", "price": 850.0, "atrPercent": 6.0, "ivRank": 50},
        ]}
        payload = ucf.build_audit(snapshot=snapshot, cap_dollars=500.0)
        by = {r["ticker"]: r for r in payload["perTicker"]}
        self.assertTrue(by["CHEAP"]["fits"]["debit_5w"] and by["PRICEY"]["fits"]["debit_5w"])  # fixed width always fits
        self.assertEqual(by["CHEAP"]["thesisVerdict"], "expected-move-fits")
        self.assertEqual(by["PRICEY"]["thesisVerdict"], "thesis-does-not-fit")
        self.assertEqual(payload["thesisFitRate"], 0.5)
        self.assertIn("Thesis fit", ucf.render_text(payload))
        self.assertTrue(payload["researchOnly"])
