from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from inferno_capex_flow import (
    build_capex_flow,
    capex_flow_text,
    instrument_for,
    relative_strength,
    score_name,
    tap_regime,
)

TODAY = date(2026, 9, 28)


def spender(last, low, high, direction="raised", fcf=True, ocf=100.0):
    return {"lastYearCapex": last, "guidanceLow": low, "guidanceHigh": high,
            "guidanceDirection": direction, "fcfPositive": fcf, "lastYearOcf": ocf}


class TapTests(unittest.TestCase):
    def test_regimes(self):
        funded = {"spenders": {k: spender(100, 130, 130) for k in "ABCD"}}
        self.assertEqual(tap_regime(funded, TODAY)["regime"], "accelerating-funded")
        stretched = {"spenders": {k: spender(100, 130, 130, fcf=k == "A") for k in "ABCD"}}
        r = tap_regime(stretched, TODAY)
        self.assertEqual(r["regime"], "accelerating-stretched")
        self.assertEqual(r["growth"], 0.3)
        plateau = {"spenders": {k: spender(100, 105, 105) for k in "ABCD"}}
        self.assertEqual(tap_regime(plateau, TODAY)["regime"], "plateau")
        cut = {"spenders": {k: spender(100, 130, 130, direction="cut" if k in "AB" else "raised") for k in "ABCD"}}
        self.assertEqual(tap_regime(cut, TODAY)["throttle"], 0.0)
        self.assertEqual(tap_regime({}, TODAY)["regime"], "unknown")

    def test_stale_tape(self):
        tape = {"reviewAfter": "2026-09-01", "spenders": {"A": spender(1, 2, 2)}}
        self.assertTrue(tap_regime(tape, TODAY)["tapeStale"])


class NameTests(unittest.TestCase):
    regime = {"regime": "accelerating-stretched", "throttle": 0.8}
    supplier = {"name": "power", "funding": "paid-supplier", "order": 1}
    developer = {"name": "dev", "funding": "capital-dependent", "order": 2}

    def test_strength_is_bought_and_broken_trend_avoided(self):
        up = score_name({"ticker": "A", "trend": "Uptrend", "ivRank": 40}, self.supplier, self.regime, 0.10)
        self.assertEqual(up["action"], "BUY")
        self.assertIn("shares", up["instrument"])
        down = score_name({"ticker": "B", "trend": "Bearish"}, self.supplier, self.regime, 0.30)
        self.assertEqual(down["action"], "AVOID")

    def test_negative_rs_blocks_buy(self):
        n = score_name({"ticker": "A", "trend": "Uptrend"}, self.supplier, self.regime, -0.01)
        self.assertNotEqual(n["action"], "BUY")

    def test_capital_dependent_haircut_in_stretched_regime(self):
        s = score_name({"ticker": "A", "trend": "Uptrend"}, self.supplier, self.regime, 0.1)["score"]
        d = score_name({"ticker": "A", "trend": "Uptrend"}, self.developer, self.regime, 0.1)["score"]
        self.assertLess(d, s * 0.6)

    def test_cut_regime_no_new(self):
        n = score_name({"ticker": "A", "trend": "Uptrend"}, self.supplier, {"regime": "cut", "throttle": 0.0}, 0.2)
        self.assertEqual(n["action"], "NO-NEW")

    def test_instrument_by_conditions(self):
        rich = instrument_for({"ivRank": 70, "daysUntilEarnings": 30}, "BUY", "paid-supplier")
        self.assertIn("put spread", rich)
        cheap = instrument_for({"ivRank": 20, "daysUntilEarnings": 30}, "BUY", "paid-supplier")
        self.assertIn("call spread 60-120 DTE", cheap)
        near = instrument_for({"ivRank": 70, "daysUntilEarnings": 3}, "BUY", "paid-supplier")
        self.assertNotIn("put spread", near)
        self.assertIn("earnings in 3d", near)
        self.assertNotIn("straddle", rich + cheap + near)
        self.assertEqual(instrument_for({}, "AVOID", "paid-supplier"), "none")


class BuildTests(unittest.TestCase):
    def test_relative_strength_from_frozen_cohort(self):
        cohorts = [{"date": "2026-09-08", "prices": {"A": 10, "B": 10, "C": 10}}]
        rs, days = relative_strength(cohorts, {"A": 12, "B": 10, "C": 10}, TODAY)
        self.assertEqual(days, 20)
        self.assertAlmostEqual(rs["A"], 0.2)
        self.assertEqual(relative_strength(cohorts, {"A": 1}, date(2026, 9, 10)), ({}, None))

    def test_build_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, research = Path(tmp) / "data", Path(tmp) / "research"
            data.mkdir(); research.mkdir()
            (data / "latest_snapshot.json").write_text(json.dumps({"generatedAt": "2026-09-28T07:00:00-06:00", "rows": [
                {"ticker": "VRT", "price": 12, "trend": "Uptrend", "ivRank": 40},
                {"ticker": "IREN", "price": 10, "trend": "Bearish"},
                {"ticker": "MSFT", "price": 11, "trend": "Uptrend"},
            ]}))
            (data / "inferno_pick_scorecard_cohorts.jsonl").write_text(json.dumps(
                {"date": "2026-09-08", "prices": {"VRT": 10, "IREN": 10, "MSFT": 10}, "picks": {}}) + "\n")
            (research / "capex_tape.json").write_text(json.dumps({"spenders": {
                k: spender(100, 170, 180, fcf=False) for k in ("MSFT", "GOOG", "AMZN", "META")}}))
            (research / "capex_value_chain.json").write_text(json.dumps({"layers": {
                "power": {"funding": "paid-supplier", "order": 1, "tickers": ["VRT"]},
                "dev": {"funding": "capital-dependent", "order": 2, "tickers": ["IREN"]},
                "spenders": {"funding": "spender", "order": 0, "tickers": ["MSFT"]}}}))
            p = build_capex_flow(data, research)
        self.assertEqual(p["regime"]["regime"], "accelerating-stretched")
        self.assertEqual(p["topPicks"], ["VRT"])
        self.assertEqual([n["ticker"] for n in p["names"]], ["VRT", "IREN"])
        self.assertAlmostEqual(p["customerMomentum"], 0.0)
        self.assertFalse(p["authorityChanged"])
        self.assertIn("accelerating-stretched", capex_flow_text(p))


if __name__ == "__main__":
    unittest.main()
