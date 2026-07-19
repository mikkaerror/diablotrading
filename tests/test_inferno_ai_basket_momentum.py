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
