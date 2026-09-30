from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import inferno_lifecycle_board as lb

RULES = json.loads(Path(lb.RULES_FILE).read_text())


def _w(folder: Path, name: str, payload: dict) -> None:
    (folder / name).write_text(json.dumps(payload), encoding="utf-8")


class LifecycleTests(unittest.TestCase):
    def test_runner_graduation_and_kill(self):
        lane = RULES["lanes"]["runner-B"]
        good = {"runner": {"scoreboard": {"B": {"closed": 31, "mean": 0.2, "meanExTwoBest": 0.1, "clusterCI95": [0.02, 0.3]}}}}
        bad = {"runner": {"scoreboard": {"B": {"closed": 31, "mean": -0.1, "meanExTwoBest": -0.2, "clusterCI95": [-0.4, 0.05]}}}}
        thin = {"runner": {"scoreboard": {"B": {"closed": 5, "mean": 0.5, "meanExTwoBest": 0.4, "clusterCI95": [0.1, 0.9]}}}}
        self.assertIn("graduation", lb.evaluate(lane, good, date(2026, 12, 1))["flag"])
        self.assertIn("decommission", lb.evaluate(lane, bad, date(2026, 12, 1))["flag"])
        self.assertIsNone(lb.evaluate(lane, thin, date(2026, 12, 1))["flag"])
        self.assertIn("time-box", lb.evaluate(lane, thin, date(2027, 3, 1))["flag"])

    def test_capex_cut_back_and_tap_cut(self):
        lane = RULES["lanes"]["capex-flow"]
        lag = {"scorecard": {"results": {"capexFlow": {"horizons": {
            "63s": {"matured": 2, "meanExcessVsUniverse": -0.07}, "126s": {"matured": 0}}}}}}
        self.assertIn("cut-back", lb.evaluate(lane, lag, date(2027, 1, 1))["flag"])
        cut = {**lag, "capex": {"regime": {"regime": "cut"}}}
        self.assertIn("capex tap turned to cut", lb.evaluate(lane, cut, date(2027, 1, 1))["flag"])

    def test_board_end_to_end_is_report_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, research = Path(tmp) / "data", Path(tmp) / "research"
            data.mkdir(); research.mkdir()
            _w(research, "strategy_lifecycle.json", RULES)
            _w(data, "inferno_promotion_evidence_lineage.json", {"promotion": {"qualifiedPaperOutcomes": 1}})
            p = lb.build(data, research, date(2026, 10, 1))
        self.assertEqual(p["rulesStatus"], "draft-unsigned")
        self.assertFalse(p["brokerSubmitAllowed"])
        self.assertEqual(p["lanes"][0]["stage"], "embargo")
        self.assertEqual(p["lanes"][-1]["stage"], "decommission")
        self.assertIn("1/30 qualified fills", lb.board_text(p))
        self.assertIn("DRAFT", lb.board_text(p))


if __name__ == "__main__":
    unittest.main()
