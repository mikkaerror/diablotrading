import unittest
import inferno_basket_holdings_join as hj


def pos(sym, wt=10.0, lth=False, mv=100.0, pl=-5.0):
    return {"symbol": sym, "qty": 10, "markValue": mv, "weightPct": wt,
            "plPercent": pl, "bucket": "long-term-core",
            "operatorLongTermHold": lth}


def q(sym, price, a50, a200, hi=100.0):
    return {"symbol": sym, "price": price, "priceAvg50": a50,
            "priceAvg200": a200, "yearHigh": hi}


class LongTermHoldTests(unittest.TestCase):
    def test_long_term_hold_never_gets_exit_even_when_below_200d(self):
        p = hj.build([pos("IREN", lth=True)],
                     [q("IREN", 40.0, 52.0, 49.0, 76.0)])
        h = p["holdings"][0]
        self.assertEqual(h["action"], "HOLD-CORE")
        self.assertIn("excluded from exit logic", h["actionReason"])
        self.assertNotIn(h["action"], ("EXIT", "TRIM"))

    def test_trend_state_is_still_reported_for_long_term_holds(self):
        """Respecting the hold must not hide the data."""
        p = hj.build([pos("IREN", lth=True)],
                     [q("IREN", 40.0, 52.0, 49.0, 76.0)])
        h = p["holdings"][0]
        self.assertEqual(h["trendState"], "below-200d")
        self.assertFalse(h["above200"])
        self.assertIn("IREN", p["longTermHoldsBelowTrend"])

    def test_non_flagged_name_below_200d_gets_exit(self):
        p = hj.build([pos("XYZ", lth=False)],
                     [q("XYZ", 40.0, 52.0, 49.0, 76.0)])
        h = p["holdings"][0]
        self.assertEqual(h["action"], "EXIT")

    def test_non_flagged_name_below_50d_gets_trim(self):
        p = hj.build([pos("CLSK", lth=False)],
                     [q("CLSK", 14.42, 15.23, 13.28, 23.61)])
        self.assertEqual(p["holdings"][0]["action"], "TRIM")

    def test_healthy_non_flagged_name_holds(self):
        p = hj.build([pos("NVDA", lth=False)],
                     [q("NVDA", 211.8, 209.0, 191.8, 236.5)])
        self.assertEqual(p["holdings"][0]["action"], "HOLD")

    def test_exit_eligible_count_excludes_long_term_holds(self):
        p = hj.build([pos("A", lth=True), pos("B", lth=True), pos("C", lth=False)],
                     [q("A", 1, 2, 3), q("B", 1, 2, 3), q("C", 1, 2, 3)])
        self.assertEqual(p["longTermHoldCount"], 2)
        self.assertEqual(p["exitEligibleCount"], 1)


class GapAndScaleTests(unittest.TestCase):
    def test_gap_reports_both_directions(self):
        composite = {"signalsTrusted": True, "ranking": [
            {"symbol": "FTNT", "tag": "LEADER"}, {"symbol": "DELL", "tag": "LEADER"}]}
        p = hj.build([pos("IREN", lth=True)], [q("IREN", 40, 52, 49)],
                     composite=composite, watchlist={"FTNT": "Security", "DELL": "Server OEM"})
        g = p["gaps"]
        self.assertEqual(g["heldNotOnWatchlist"], ["IREN"])
        self.assertEqual(g["watchlistLeadersNotHeld"], ["FTNT", "DELL"])
        self.assertEqual(g["overlapCount"], 0)

    def test_account_scale_converts_weights_to_dollars(self):
        p = hj.build([pos("IREN")], [q("IREN", 40, 52, 49)], nlv=706.41)
        s = p["accountScale"]
        self.assertAlmostEqual(s["onePctDollars"], 7.06, places=2)
        self.assertAlmostEqual(s["maxPositionDollars"], 56.51, places=2)

    def test_missing_quote_non_lth_is_no_data(self):
        p = hj.build([pos("GHOST", lth=False)], [])
        h = p["holdings"][0]
        self.assertEqual(h["trendState"], "no-data")
        self.assertEqual(h["action"], "NO-DATA")

    def test_missing_quote_lth_still_holds_core(self):
        p = hj.build([pos("GHOST", lth=True)], [])
        self.assertEqual(p["holdings"][0]["action"], "HOLD-CORE")

    def test_research_only_boundary_flags(self):
        p = hj.build([pos("IREN")], [q("IREN", 40, 52, 49)])
        self.assertTrue(p["researchOnly"])
        self.assertFalse(p["promotable"])
        self.assertFalse(p["authorityChanged"])
        self.assertFalse(p["brokerSubmitAllowed"])
        self.assertFalse(p["liveTradingAllowed"])


if __name__ == "__main__":
    unittest.main()
