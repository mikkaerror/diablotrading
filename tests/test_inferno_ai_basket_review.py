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


if __name__ == "__main__":
    unittest.main()
