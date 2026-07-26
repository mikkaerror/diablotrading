import unittest
import inferno_ai_basket_momentum as m

class MomentumTests(unittest.TestCase):
    def _rows(self, recs): return {r["symbol"]:r for r in m.rank(recs)}
    def test_blend_and_rank_order(self):
        recs=[{"symbol":"NVDA","1M":1,"3M":30,"6M":40},{"symbol":"AMD","1M":1,"3M":5,"6M":5}]
        r=m.rank(recs)
        self.assertEqual(r[0]["symbol"],"NVDA")          # higher blend ranks first
        self.assertAlmostEqual(r[0]["blended"],35.0)
    def test_accelerating_flag(self):
        # 3M pace (10/mo) > 6M pace (5/mo) -> accelerating
        r=self._rows([{"symbol":"NVDA","1M":4,"3M":30,"6M":30}])
        self.assertTrue(r["NVDA"]["accelerating"])
    def test_fading_flag(self):
        # up over 6M but down last month -> fading
        r=self._rows([{"symbol":"NVDA","1M":-3,"3M":4,"6M":18}])
        self.assertTrue(r["NVDA"]["fading"])
    def test_skips_incomplete(self):
        r=m.rank([{"symbol":"NVDA","1M":1}])   # no 3M/6M
        self.assertEqual(r,[])
    def test_partial_payload_fails_closed(self):
        p=m.build([{"symbol":"NVDA","1M":1,"3M":5,"6M":5}])
        self.assertTrue(p["researchOnly"])
        self.assertFalse(p["signalsTrusted"])
        self.assertEqual(p["leaders"], [])
        self.assertFalse(p["brokerSubmitAllowed"])
        self.assertFalse(p["liveTradingAllowed"])

    def test_outside_symbol_is_ignored_without_expanding_universe(self):
        p=m.build(
            [{"symbol":"RBC","1M":1,"3M":5,"6M":5}],
            expected_universe=["NVDA"],
        )
        self.assertEqual(p["ranking"], [])
        self.assertEqual(p["extraSymbolsIgnored"], ["RBC"])
        self.assertEqual(p["missingSymbols"], ["NVDA"])

if __name__=="__main__": unittest.main()


class DirectionTests(unittest.TestCase):
    """accelerating and fading must be mutually exclusive in the reported direction."""

    def _rank(self, m1, m3, m6):
        # must use a symbol in the declared universe — rank() filters to it
        import inferno_ai_basket_momentum as mom
        return mom.rank([{"symbol": "NVDA", "1M": m1, "3M": m3, "6M": m6}])[0]

    def test_fading_wins_when_both_conditions_hold(self):
        # 3M pace beats 6M pace (accelerating) AND last month negative (fading)
        r = self._rank(-5.0, 60.0, 90.0)
        self.assertTrue(r["accelerating"])
        self.assertTrue(r["fading"])
        self.assertEqual(r["direction"], "fading")

    def test_accelerating_when_not_fading(self):
        r = self._rank(5.0, 60.0, 90.0)
        self.assertEqual(r["direction"], "accelerating")

    def test_steady_when_neither(self):
        r = self._rank(1.0, 10.0, 90.0)
        self.assertEqual(r["direction"], "steady")

    def test_payload_lists_are_disjoint(self):
        import inferno_ai_basket_momentum as mom
        recs = [{"symbol": "NVDA", "1M": -5.0, "3M": 60.0, "6M": 90.0},
                {"symbol": "AMD", "1M": 5.0, "3M": 60.0, "6M": 90.0},
                {"symbol": "ASML", "1M": 1.0, "3M": 10.0, "6M": 90.0}]
        p = mom.build(recs)
        acc, fad = set(p.get("accelerating") or []), set(p.get("fading") or [])
        self.assertFalse(acc & fad, "a name must not be both accelerating and fading")


class CoverageGuardTests(unittest.TestCase):
    """A partial run must never destroy a complete signal set (2026-07-20 incident)."""

    def setUp(self):
        import inferno_ai_basket_momentum as mom
        import tempfile, pathlib
        self.mom = mom
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_json, self._orig_txt = mom.OUT_JSON, mom.OUT_TXT
        mom.OUT_JSON = pathlib.Path(self._tmp.name) / "mom.json"
        mom.OUT_TXT = pathlib.Path(self._tmp.name) / "mom.txt"

    def tearDown(self):
        self.mom.OUT_JSON, self.mom.OUT_TXT = self._orig_json, self._orig_txt
        self._tmp.cleanup()

    def _payload(self, n):
        return {"generatedAt": "x", "count": n,
                "ranking": [{"symbol": f"S{i}", "blended": 1.0, "cat": "",
                             "m1": 0, "m3": 0, "m6": 0, "rank": i + 1,
                             "accelerating": False, "fading": False,
                             "direction": "steady"} for i in range(n)]}

    def test_first_publish_is_allowed(self):
        r = self.mom.save(self._payload(27))
        self.assertTrue(r["written"])
        self.assertEqual(self.mom.existing_coverage(), 27)

    def test_shrinking_coverage_is_refused(self):
        self.mom.save(self._payload(27))
        r = self.mom.save(self._payload(3))
        self.assertFalse(r["written"])
        self.assertIn("would shrink coverage 27 -> 3", r["reason"])
        # the good artifact must survive untouched
        self.assertEqual(self.mom.existing_coverage(), 27)

    def test_growing_coverage_is_allowed(self):
        self.mom.save(self._payload(27))
        r = self.mom.save(self._payload(30))
        self.assertTrue(r["written"])
        self.assertEqual(self.mom.existing_coverage(), 30)

    def test_equal_coverage_is_allowed(self):
        self.mom.save(self._payload(30))
        self.assertTrue(self.mom.save(self._payload(30))["written"])

    def test_shrink_can_be_forced_deliberately(self):
        self.mom.save(self._payload(30))
        r = self.mom.save(self._payload(5), allow_shrink=True)
        self.assertTrue(r["written"])
        self.assertEqual(self.mom.existing_coverage(), 5)
