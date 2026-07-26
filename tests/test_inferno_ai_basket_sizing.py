import unittest
import inferno_ai_basket_sizing as sz


def row(sym, cat, tag, rs):
    return {"symbol": sym, "cat": cat, "tag": tag, "composite": rs}


def comp(rows, trusted=True):
    return {"signalsTrusted": trusted, "ranking": rows}


class SizingTests(unittest.TestCase):
    def test_avoid_names_get_zero_weight(self):
        p = sz.build(comp([
            row("NVDA", "Compute", "LEADER", 90),
            row("ORCL", "Cloud Rails", "AVOID", 5),
            row("VNET", "DC Operator", "AVOID", 2),
        ]))
        w = {t["symbol"]: t["targetWeight"] for t in p["targets"]}
        self.assertEqual(w["ORCL"], 0.0)
        self.assertEqual(w["VNET"], 0.0)
        self.assertGreater(w["NVDA"], 0.0)
        self.assertIn("ORCL", p["zeroWeighted"])

    def test_single_name_cap_enforced(self):
        # one dominant name should still be clipped at the cap
        p = sz.build(comp([
            row("NVDA", "Compute", "LEADER", 100),
            row("AMD", "Compute", "HOLD", 10),
            row("MSFT", "Hyperscaler", "HOLD", 10),
            row("RBC", "Bearings", "HOLD", 10),
        ]), max_name=0.08, max_bucket=0.60)
        for t in p["targets"]:
            self.assertLessEqual(t["targetWeight"], 0.08 + 1e-9,
                                 f"{t['symbol']} exceeded name cap")

    def test_factor_bucket_cap_enforced(self):
        # 6 strong Compute names (one bucket) vs 2 others -> bucket must be capped
        rows = [row(f"C{i}", "Compute", "LEADER", 90) for i in range(6)]
        rows += [row("MSFT", "Hyperscaler", "HOLD", 50),
                 row("RBC", "Bearings", "HOLD", 50)]
        p = sz.build(comp(rows), max_name=0.20, max_bucket=0.50)
        complex_total = p["bucketTotals"].get("AI-capex hardware complex", 0.0)
        self.assertLessEqual(complex_total, 0.50 + 1e-6)

    def test_weights_never_exceed_one_and_cash_is_residual(self):
        p = sz.build(comp([
            row("NVDA", "Compute", "LEADER", 90),
            row("AMD", "Compute", "LEADER", 80),
        ]), max_name=0.08, max_bucket=0.60)
        self.assertLessEqual(p["investedWeight"], 1.0 + 1e-9)
        self.assertAlmostEqual(p["investedWeight"] + p["cashWeight"], 1.0, places=6)
        # only 2 names at an 8% cap -> most of the book is cash
        self.assertGreater(p["cashWeight"], 0.8)

    def test_actions_vs_current_weights(self):
        p = sz.build(
            comp([
                row("NVDA", "Compute", "LEADER", 90),
                row("MSFT", "Hyperscaler", "HOLD", 60),
                row("ORCL", "Cloud Rails", "AVOID", 5),
            ]),
            current_weights={"ORCL": 0.10, "NVDA": 0.02, "MSFT": 0.99},
            max_name=0.08, max_bucket=0.60,
        )
        act = {t["symbol"]: t["action"] for t in p["targets"]}
        self.assertEqual(act["ORCL"], "EXIT")   # held but trend broken
        self.assertEqual(act["NVDA"], "ADD")    # under-weight vs target
        self.assertEqual(act["MSFT"], "TRIM")   # wildly over-weight

    def test_percentage_style_current_weights_are_normalized(self):
        p = sz.build(comp([row("NVDA", "Compute", "LEADER", 90)]),
                     current_weights={"NVDA": 50.0})  # 50 means 50%, not 5000%
        t = p["targets"][0]
        self.assertAlmostEqual(t["currentWeight"], 0.50, places=6)

    def test_weak_names_are_not_inflated_to_fill_the_book(self):
        """Regression: bucket-cap redistribution must not size REDUCE names like LEADERs.

        Six strong Compute names get capped as a bucket; the freed weight must NOT
        force the two weak non-complex names up to the full name cap. It should
        become cash instead.
        """
        rows = [row(f"C{i}", "Compute", "LEADER", 95) for i in range(6)]
        rows += [row("GOOG", "Hyperscaler", "REDUCE", 68),
                 row("RBC", "Bearings", "REDUCE", 66)]
        p = sz.build(comp(rows), max_name=0.08, max_bucket=0.60)
        w = {t["symbol"]: t["targetWeight"] for t in p["targets"]}
        reduce_ceiling = 0.08 * sz.TAG_MULTIPLIER["REDUCE"]  # 2.8%
        self.assertLessEqual(w["GOOG"], reduce_ceiling + 1e-9)
        self.assertLessEqual(w["RBC"], reduce_ceiling + 1e-9)
        # the unallocatable remainder must show up as cash, not as forced exposure
        self.assertGreater(p["cashWeight"], 0.0)

    def test_leader_ceiling_is_full_cap_hold_is_scaled(self):
        p = sz.build(comp([
            row("A", "Compute", "LEADER", 99),
            row("B", "Hyperscaler", "HOLD", 99),
            row("C", "Bearings", "REDUCE", 99),
        ]), max_name=0.10, max_bucket=0.90)
        w = {t["symbol"]: t["targetWeight"] for t in p["targets"]}
        self.assertLessEqual(w["A"], 0.10 + 1e-9)
        self.assertLessEqual(w["B"], 0.10 * 0.70 + 1e-9)
        self.assertLessEqual(w["C"], 0.10 * 0.35 + 1e-9)

    def test_unclassified_symbols_are_surfaced(self):
        p = sz.build(comp([
            row("NVDA", "Compute", "LEADER", 90),
            row("MYSTERY", "", "LEADER", 80),
        ]))
        self.assertIn("MYSTERY", p["unclassifiedSymbols"])
        self.assertNotIn("NVDA", p["unclassifiedSymbols"])

    # caps are deliberately non-binding here so the DUST rule is what's under test.
    # HOLD (not REDUCE) — REDUCE is unfundable by design, so it can't make dust.
    DUST_ROWS = ([row("BIG", "Compute", "LEADER", 100)]
                 + [row(f"T{i}", "Optical", "HOLD", 1) for i in range(40)])

    def test_dust_positions_are_dropped_not_held(self):
        """A long tail of weak names must not produce sub-minimum 'dust' positions."""
        p = sz.build(comp(self.DUST_ROWS), max_name=1.0, max_bucket=1.0,
                     min_weight=0.015)
        held = [t for t in p["targets"] if t["targetWeight"] > 0]
        self.assertTrue(held)
        for t in held:
            self.assertGreaterEqual(t["targetWeight"], 0.015 - 1e-9,
                                    f"{t['symbol']} is dust")

    def test_min_weight_can_be_disabled(self):
        p = sz.build(comp(self.DUST_ROWS), max_name=1.0, max_bucket=1.0,
                     min_weight=0.0)
        tiny = [t for t in p["targets"] if 0 < t["targetWeight"] < 0.015]
        self.assertTrue(tiny, "with min_weight=0 small positions should survive")

    def test_below_trend_and_dust_are_reported_separately(self):
        """A dusted-but-healthy name must never be labelled 'below 200-day'."""
        rows = [row("BIG", "Compute", "LEADER", 100),
                row("TINY", "Optical", "REDUCE", 1),      # healthy, just too small
                row("ORCL", "Cloud Rails", "AVOID", 5)]   # actually below trend
        p = sz.build(comp(rows), max_name=1.0, max_bucket=1.0, min_weight=0.015)
        self.assertIn("ORCL", p["belowTrend"])
        self.assertNotIn("ORCL", p["droppedAsDust"])
        self.assertIn("TINY", p["droppedAsDust"])
        self.assertNotIn("TINY", p["belowTrend"])

    def test_reduce_names_are_not_funded(self):
        """REDUCE is trim-toward-zero, not a small allocation."""
        p = sz.build(comp([
            row("FTNT", "Security", "LEADER", 100),
            row("NVDA", "Compute", "REDUCE", 95),
            row("AVGO", "Compute", "REDUCE", 90),
        ]))
        w = {t["symbol"]: t["targetWeight"] for t in p["targets"]}
        self.assertGreater(w["FTNT"], 0)
        self.assertEqual(w["NVDA"], 0.0)
        self.assertEqual(w["AVGO"], 0.0)

    def test_rolling_over_market_goes_mostly_to_cash(self):
        """If nearly everything is REDUCE, the book should be cash, not 79% invested."""
        rows = [row("FTNT", "Security", "LEADER", 100)]
        rows += [row(f"R{i}", "Compute", "REDUCE", 80 - i) for i in range(23)]
        rows += [row(f"A{i}", "Cloud Rails", "AVOID", 5) for i in range(5)]
        p = sz.build(comp(rows), nlv=706.41)
        self.assertGreater(p["cashWeight"], 0.5,
                           "a rolling-over tape must produce a mostly-cash book")


class AccountShapeTests(unittest.TestCase):
    def test_small_account_gets_fewer_larger_positions(self):
        shaped = sz.account_shape(706.41, 0.08, 0.015)
        max_name, min_w, max_pos = shaped
        self.assertEqual(max_pos, 7)                 # 706 // 100
        self.assertGreater(max_name, 0.08)           # cap relaxed for concentration
        self.assertGreater(min_w, 0.015)             # dust threshold raised

    def test_large_account_keeps_the_original_caps(self):
        max_name, min_w, max_pos = sz.account_shape(500_000.0, 0.08, 0.015)
        self.assertEqual(max_pos, sz.MAX_POSITIONS)
        self.assertAlmostEqual(max_name, 0.08, places=6)  # 1.25/20 = 0.0625 < 0.08
        self.assertAlmostEqual(min_w, 0.025, places=6)    # 0.5/20

    def test_no_nlv_leaves_caps_untouched(self):
        max_name, min_w, max_pos = sz.account_shape(None, 0.08, 0.015)
        self.assertEqual((max_name, min_w, max_pos), (0.08, 0.015, None))

    def test_position_count_is_enforced(self):
        rows = [row(f"L{i}", "Compute", "LEADER", 100 - i) for i in range(20)]
        p = sz.build(comp(rows), nlv=706.41, max_bucket=1.0)
        funded = [t for t in p["targets"] if t["targetWeight"] > 0]
        self.assertLessEqual(len(funded), 7)

    def test_tiny_account_floors_at_min_positions(self):
        _, _, max_pos = sz.account_shape(50.0, 0.08, 0.015)
        self.assertEqual(max_pos, sz.MIN_POSITIONS)

    def test_regime_throttle_caps_a_narrow_rally(self):
        """Many leaders but a weak regime -> deployment capped, rest to cash."""
        rows = [row(f"L{i}", "Compute", "LEADER", 100 - i) for i in range(6)]
        # max_name 0.20 so 6 leaders can fully deploy without the name cap binding
        full = sz.build(comp(rows), nlv=500_000, max_name=0.20, max_bucket=1.0)
        # RISK-OFF regime (score 15) must cap deployment at 30%
        throttled = sz.build(comp(rows), nlv=500_000, max_name=0.20, max_bucket=1.0,
                             regime_score=15)
        self.assertGreater(full["investedWeight"], 0.9)
        self.assertAlmostEqual(throttled["investedWeight"], 0.30, places=2)
        self.assertTrue(throttled["params"]["regimeThrottled"])
        self.assertGreater(throttled["cashWeight"], 0.65)

    def test_strong_regime_does_not_throttle(self):
        rows = [row(f"L{i}", "Compute", "LEADER", 100 - i) for i in range(6)]
        p = sz.build(comp(rows), nlv=500_000, max_bucket=1.0, regime_score=85)
        self.assertFalse(p["params"]["regimeThrottled"])

    def test_throttle_only_reduces_never_forces_investment(self):
        # a cash-heavy book (all REDUCE -> 0) must not be pushed UP by a strong regime
        rows = [row("FTNT", "Security", "LEADER", 100)]
        rows += [row(f"R{i}", "Compute", "REDUCE", 50) for i in range(10)]
        p = sz.build(comp(rows), nlv=706.41, regime_score=95)
        self.assertLess(p["investedWeight"], 0.5)   # still mostly cash

    def test_no_regime_score_means_no_throttle(self):
        rows = [row(f"L{i}", "Compute", "LEADER", 100 - i) for i in range(6)]
        p = sz.build(comp(rows), nlv=500_000, max_bucket=1.0)
        self.assertFalse(p["params"]["regimeThrottled"])

    def test_fail_closed_when_composite_untrusted(self):
        p = sz.build(comp([row("NVDA", "Compute", "LEADER", 90)], trusted=False))
        self.assertEqual(p["verdict"], "fail-closed")
        self.assertEqual(p["targets"], [])
        self.assertEqual(p["cashWeight"], 1.0)

    def test_research_only_boundary_flags(self):
        p = sz.build(comp([row("NVDA", "Compute", "LEADER", 90)]))
        self.assertTrue(p["researchOnly"])
        self.assertFalse(p["promotable"])
        self.assertFalse(p["authorityChanged"])
        self.assertFalse(p["brokerSubmitAllowed"])
        self.assertFalse(p["liveTradingAllowed"])


if __name__ == "__main__":
    unittest.main()
