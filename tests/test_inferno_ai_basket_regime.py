import unittest
import inferno_ai_basket_regime as rg


def review(leaders, reduce, avoid, beating, basket_beats=False):
    ranking = ([{"tag": "LEADER", "above200": True, "above50": True} for _ in range(leaders)]
               + [{"tag": "REDUCE", "above200": True, "above50": False} for _ in range(reduce)]
               + [{"tag": "AVOID", "above200": False, "above50": False} for _ in range(avoid)])
    return {
        "composite": {"signalsTrusted": True, "ranking": ranking},
        "benchmark": {"namesBeatingSector": beating, "basketBeatsBenchmark": basket_beats},
    }


class RegimeTests(unittest.TestCase):
    def test_label_bands(self):
        self.assertEqual(rg.label_for(85), "RISK-ON")
        self.assertEqual(rg.label_for(60), "CONSTRUCTIVE")
        self.assertEqual(rg.label_for(45), "NEUTRAL")
        self.assertEqual(rg.label_for(30), "CAUTION")
        self.assertEqual(rg.label_for(10), "RISK-OFF")

    def test_strong_tape_scores_risk_on(self):
        # broad, well-led, beating the sector
        p = rg.score(review(leaders=20, reduce=8, avoid=2, beating=24, basket_beats=True))
        self.assertGreaterEqual(p["score"], 70)
        self.assertEqual(p["label"], "RISK-ON")

    def test_broken_tape_scores_risk_off(self):
        p = rg.score(review(leaders=0, reduce=3, avoid=27, beating=1))
        self.assertLess(p["score"], 25)
        self.assertEqual(p["label"], "RISK-OFF")

    def test_todays_tape_is_caution(self):
        # the real 2026-07-20 read: 2 leaders, 23 reduce, 5 avoid, 10 beating
        p = rg.score(review(leaders=2, reduce=23, avoid=5, beating=10))
        self.assertEqual(p["label"], "CAUTION")
        # breadth-200 high, breadth-50 and leadership thin
        self.assertGreater(p["components"]["breadth200"], 80)
        self.assertLess(p["components"]["leaderFraction"], 10)

    def test_components_sum_with_weights(self):
        p = rg.score(review(leaders=2, reduce=23, avoid=5, beating=10))
        recomputed = round(sum(rg.WEIGHTS[k] * v for k, v in p["components"].items()), 1)
        self.assertAlmostEqual(p["score"], recomputed, places=1)

    def test_fail_closed_on_empty(self):
        p = rg.score({"composite": {"ranking": []}})
        self.assertEqual(p["verdict"], "fail-closed")
        self.assertIsNone(p["score"])
        self.assertEqual(p["label"], "unknown")

    def test_fail_closed_when_untrusted(self):
        p = rg.score({"composite": {"signalsTrusted": False,
                                    "ranking": [{"tag": "LEADER", "above200": True}]}})
        self.assertEqual(p["verdict"], "fail-closed")

    def test_research_only_and_no_authority(self):
        p = rg.score(review(leaders=5, reduce=10, avoid=5, beating=12))
        self.assertTrue(p["researchOnly"])
        self.assertFalse(p["authorityChanged"])


if __name__ == "__main__":
    unittest.main()
