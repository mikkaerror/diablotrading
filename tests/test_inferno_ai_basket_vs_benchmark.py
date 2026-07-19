import unittest
import inferno_ai_basket_vs_benchmark as b

def q(s,p,a200,hi): return {"symbol":s,"price":p,"priceAvg200":a200,"yearHigh":hi,"priceAvg50":p}
TRUSTED_CONTRACT={"signalsTrusted":True,"verdict":"trusted"}

class BenchTests(unittest.TestCase):
    def test_beats_and_lags(self):
        # SMH +37% above 200d, -12% off high. LEAD stronger, LAG weaker.
        quotes=[q("SMH",137,100,155),                    # +37% above200, -12% offhigh
                q("LEAD",200,100,205),                    # +100% above200, -2% offhigh -> beats
                q("LAG",90,100,300)]                      # -10% above200, -70% offhigh -> lags
        p=b.build(quotes,"SMH", expected_universe=["LEAD", "LAG"],data_contract=TRUSTED_CONTRACT)
        tag={r["symbol"]:r["beatsSector"] for r in p["ranking"]}
        self.assertTrue(tag["LEAD"]); self.assertFalse(tag["LAG"])
        self.assertEqual(p["ranking"][0]["symbol"],"LEAD")
    def test_missing_benchmark_errors(self):
        p=b.build([q("AAA",100,90,110)],"SMH", expected_universe=["AAA"],data_contract=TRUSTED_CONTRACT)
        self.assertIn("error",p)
    def test_research_only(self):
        p=b.build([q("SMH",137,100,155),q("X",150,100,160)],"SMH", expected_universe=["X"],data_contract=TRUSTED_CONTRACT)
        self.assertTrue(p["researchOnly"])
        self.assertIn("basketBeatsBenchmark",p)

    def test_category_rollup_and_concentration(self):
        # NVDA/AMD are Compute (AI-capex complex); ORCL is Cloud Rails (software)
        quotes=[q("SMH",137,100,155),
                q("NVDA",200,100,205), q("AMD",180,100,200), q("ORCL",90,100,300)]
        p=b.build(quotes,"SMH", expected_universe=["NVDA", "AMD", "ORCL"],data_contract=TRUSTED_CONTRACT)
        cats={c["category"]:c for c in p["byCategory"]}
        self.assertEqual(cats["Compute"]["count"],2)
        self.assertEqual(cats["Compute"]["namesInUptrend"],2)
        conc=p["concentration"]
        self.assertEqual(conc["AI-capex hardware complex"]["count"],2)
        self.assertEqual(conc["Software / hyperscaler"]["count"],1)
        # rollup sorted strongest-first
        self.assertGreaterEqual(p["byCategory"][0]["avgRelStrength"],
                                p["byCategory"][-1]["avgRelStrength"])

    def test_partial_or_duplicate_declared_rows_fail_closed(self):
        partial = b.build(
            [q("SMH",137,100,155), q("NVDA",200,100,205)],
            "SMH", expected_universe=["NVDA", "AMD"],data_contract=TRUSTED_CONTRACT,
        )
        self.assertFalse(partial["signalsTrusted"])
        self.assertEqual(partial["ranking"], [])
        self.assertEqual(partial["missingSymbols"], ["AMD"])

        duplicate = b.build(
            [q("SMH",137,100,155), q("NVDA",200,100,205), q("NVDA",210,100,215)],
            "SMH", expected_universe=["NVDA"],data_contract=TRUSTED_CONTRACT,
        )
        self.assertFalse(duplicate["signalsTrusted"])
        self.assertEqual(duplicate["duplicateSymbols"], ["NVDA"])

    def test_untrusted_canonical_contract_suppresses_comparison(self):
        payload = b.build(
            [q("SMH",137,100,155), q("NVDA",200,100,205)],
            "SMH", expected_universe=["NVDA"], data_contract={"signalsTrusted":False},
        )
        self.assertFalse(payload["signalsTrusted"])
        self.assertFalse(payload["dataContractTrusted"])
        self.assertEqual(payload["ranking"], [])

if __name__=="__main__": unittest.main()
