import unittest
import inferno_ai_basket_composite as c

Q=[{"symbol":"AMD","price":557,"priceAvg50":477,"priceAvg200":285,"yearHigh":584},   # above both, near high
   {"symbol":"GOOG","price":355,"priceAvg50":369,"priceAvg200":317,"yearHigh":404},  # below 50, above 200, fading
   {"symbol":"ORCL","price":140,"priceAvg50":183,"priceAvg200":196,"yearHigh":345}]  # below 200
M={"ranking":[{"symbol":"AMD","blended":35,"accelerating":True,"fading":False},
              {"symbol":"GOOG","blended":11,"accelerating":False,"fading":True},
              {"symbol":"ORCL","blended":-32,"accelerating":False,"fading":False}]}
TRUSTED_CONTRACT={"signalsTrusted":True,"verdict":"trusted"}

class CompositeTests(unittest.TestCase):
    def setUp(self):
        self.expected = ["AMD", "GOOG", "ORCL"]
        self.p=c.build(Q,M,expected_universe=self.expected,data_contract=TRUSTED_CONTRACT)
        self.tag={r["symbol"]:r["tag"] for r in self.p["ranking"]}
    def test_below_200_is_avoid(self): self.assertEqual(self.tag["ORCL"],"AVOID")
    def test_below_50_or_fading_is_reduce(self): self.assertEqual(self.tag["GOOG"],"REDUCE")
    def test_strong_uptrend_leads(self):
        self.assertEqual(self.tag["AMD"],"LEADER"); self.assertEqual(self.p["ranking"][0]["symbol"],"AMD")
    def test_composite_0_100_and_sorted(self):
        cs=[r["composite"] for r in self.p["ranking"]]
        self.assertEqual(cs,sorted(cs,reverse=True))
        self.assertTrue(all(0<=x<=100 for x in cs))
    def test_research_only(self): self.assertTrue(self.p["researchOnly"])

    def test_partial_or_duplicate_inputs_fail_closed(self):
        p = c.build(Q[:2], M, expected_universe=self.expected,data_contract=TRUSTED_CONTRACT)
        self.assertFalse(p["signalsTrusted"])
        self.assertEqual(p["ranking"], [])
        self.assertEqual(p["missingQuoteSymbols"], ["ORCL"])

        duplicate = c.build(Q + [Q[0]], M, expected_universe=self.expected,data_contract=TRUSTED_CONTRACT)
        self.assertFalse(duplicate["signalsTrusted"])
        self.assertEqual(duplicate["duplicateSymbols"], ["AMD"])

    def test_outside_symbols_do_not_widen_the_composite(self):
        p = c.build(
            Q + [{"symbol":"RBC","price":100,"priceAvg50":90,"priceAvg200":80,"yearHigh":110}],
            M,
            expected_universe=self.expected,data_contract=TRUSTED_CONTRACT,
        )
        self.assertTrue(p["signalsTrusted"])
        self.assertEqual(p["extraSymbolsIgnored"], ["RBC"])
        self.assertNotIn("RBC", [row["symbol"] for row in p["ranking"]])

    def test_untrusted_canonical_contract_suppresses_labels(self):
        p = c.build(Q, M, expected_universe=self.expected, data_contract={"signalsTrusted":False})
        self.assertFalse(p["signalsTrusted"])
        self.assertFalse(p["dataContractTrusted"])
        self.assertEqual(p["ranking"], [])

if __name__=="__main__": unittest.main()
