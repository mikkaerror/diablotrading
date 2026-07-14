import unittest
import inferno_ai_basket_momentum as m

class MomentumTests(unittest.TestCase):
    def _rows(self, recs): return {r["symbol"]:r for r in m.rank(recs)}
    def test_blend_and_rank_order(self):
        recs=[{"symbol":"A","1M":1,"3M":30,"6M":40},{"symbol":"B","1M":1,"3M":5,"6M":5}]
        r=m.rank(recs)
        self.assertEqual(r[0]["symbol"],"A")          # higher blend ranks first
        self.assertAlmostEqual(r[0]["blended"],35.0)
    def test_accelerating_flag(self):
        # 3M pace (10/mo) > 6M pace (5/mo) -> accelerating
        r=self._rows([{"symbol":"A","1M":4,"3M":30,"6M":30}])
        self.assertTrue(r["A"]["accelerating"])
    def test_fading_flag(self):
        # up over 6M but down last month -> fading
        r=self._rows([{"symbol":"A","1M":-3,"3M":4,"6M":18}])
        self.assertTrue(r["A"]["fading"])
    def test_skips_incomplete(self):
        r=m.rank([{"symbol":"A","1M":1}])   # no 3M/6M
        self.assertEqual(r,[])
    def test_research_only_payload(self):
        p=m.build([{"symbol":"A","1M":1,"3M":5,"6M":5}])
        self.assertTrue(p["researchOnly"])
        self.assertIn("A",p["leaders"])

if __name__=="__main__": unittest.main()
