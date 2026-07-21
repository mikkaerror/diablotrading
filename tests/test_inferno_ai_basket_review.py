import unittest
import inferno_ai_basket_review as rv


class DisciplineWatchTests(unittest.TestCase):
    def test_avoid_names_flagged_do_not_average_down(self):
        cp = {"ranking": [
            {"symbol": "ORCL", "tag": "AVOID"},
            {"symbol": "MSFT", "tag": "REDUCE"},
            {"symbol": "STX", "tag": "LEADER"},
            {"symbol": "OTEX", "tag": "AVOID"},
        ]}
        al = {"events": []}
        dw = rv.discipline_watch(al, cp)
        self.assertEqual(dw["doNotAverageDown"], ["ORCL", "OTEX"])
        self.assertEqual(dw["reentryConfirmed"], [])

    def test_reentry_crossings_flagged(self):
        cp = {"ranking": [{"symbol": "NVDA", "tag": "LEADER"}]}
        al = {"events": [
            {"sym": "AAOI", "kind": "REENTRY"},
            {"sym": "SMCI", "kind": "EXIT"},
            {"sym": "GLW", "kind": "REENTRY"},
        ]}
        dw = rv.discipline_watch(al, cp)
        self.assertEqual(dw["reentryConfirmed"], ["AAOI", "GLW"])
        self.assertEqual(dw["doNotAverageDown"], [])

    def test_handles_empty_inputs(self):
        dw = rv.discipline_watch({}, {})
        self.assertEqual(dw, {"doNotAverageDown": [], "reentryConfirmed": []})


class DigestSizingBlockTests(unittest.TestCase):
    def _base(self, sizing):
        return {
            "alerts": {"events": [], "emailed": {}},
            "composite": {"ranking": [{"symbol": "NVDA", "tag": "LEADER"}]},
            "benchmark": {"error": "no benchmark"},
            "sizing": sizing,
        }

    def test_sizing_block_renders_weights_and_buckets(self):
        sizing = {
            "signalsTrusted": True, "investedWeight": 0.84, "cashWeight": 0.16,
            "bucketTotals": {"AI-capex hardware complex": 0.60,
                             "Industrials / bearings": 0.136},
            "unclassifiedSymbols": [],
            "targets": [
                {"symbol": "FTNT", "targetWeight": 0.08, "currentWeight": None,
                 "delta": None, "action": "—"},
                {"symbol": "ORCL", "targetWeight": 0.0, "currentWeight": None,
                 "delta": None, "action": "—"},
            ],
        }
        out = rv.digest(self._base(sizing))
        self.assertIn("TARGET SIZING:", out)
        self.assertIn("cash 16%", out)
        self.assertIn("FTNT 8.0%", out)
        self.assertIn("AI-capex hardware complex", out)

    def test_sizing_block_shows_actions_when_current_weights_given(self):
        sizing = {
            "signalsTrusted": True, "investedWeight": 0.5, "cashWeight": 0.5,
            "bucketTotals": {}, "unclassifiedSymbols": [],
            "targets": [
                {"symbol": "ORCL", "targetWeight": 0.0, "currentWeight": 0.10,
                 "delta": -0.10, "action": "EXIT"},
                {"symbol": "NVDA", "targetWeight": 0.05, "currentWeight": 0.01,
                 "delta": 0.04, "action": "ADD"},
            ],
        }
        out = rv.digest(self._base(sizing))
        self.assertIn("actions vs current book:", out)
        self.assertIn("[EXIT] ORCL", out)
        self.assertIn("[ADD ] NVDA", out)

    def test_sizing_block_reports_fail_closed(self):
        sizing = {"signalsTrusted": False, "reason": "composite inputs not trusted"}
        out = rv.digest(self._base(sizing))
        self.assertIn("fail-closed", out)
        self.assertNotIn("invested", out)

    def test_digest_without_sizing_key_still_works(self):
        r = self._base(None)
        r.pop("sizing")
        out = rv.digest(r)
        self.assertNotIn("TARGET SIZING:", out)
        self.assertIn("Decision-support only", out)

    def test_uncategorized_names_are_warned(self):
        sizing = {
            "signalsTrusted": True, "investedWeight": 0.5, "cashWeight": 0.5,
            "bucketTotals": {}, "unclassifiedSymbols": ["MYSTERY"],
            "targets": [{"symbol": "MYSTERY", "targetWeight": 0.05,
                         "currentWeight": None, "delta": None, "action": "—"}],
        }
        out = rv.digest(self._base(sizing))
        self.assertIn("uncategorized", out)
        self.assertIn("MYSTERY", out)


if __name__ == "__main__":
    unittest.main()
