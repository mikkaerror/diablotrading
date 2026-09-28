from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inferno_pick_scorecard import (
    append_cohort,
    build_pick_scorecard,
    cohort_from_snapshot,
    load_cohorts,
    pick_scorecard_text,
    score,
)


def snap(day, prices, long_term, extra_rows=()):
    rows = [{"ticker": t, "price": p, "setupRec": "Avoid", "readiness": 50} for t, p in prices.items()]
    rows.extend(extra_rows)
    return {"generatedAt": f"{day}T07:00:00-06:00", "rows": rows, "longTermTickers": long_term}


class ScorecardTests(unittest.TestCase):
    def test_cohort_skips_missing_prices_and_selects_event_ready(self):
        s = snap("2026-01-01", {"A": 10, "B": 20}, ["A", "ZZZ"],
                 [{"ticker": "E", "price": 5, "setupRec": "Straddle", "readiness": 95, "priority": 3}])
        c = cohort_from_snapshot(s, spy_close=100)
        self.assertEqual(c["picks"]["longTerm"], ["A"])
        self.assertEqual(c["picks"]["eventReady"], ["E"])
        self.assertEqual(c["spy"], 100)

    def test_append_only_first_write_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.jsonl"
            first = cohort_from_snapshot(snap("2026-01-01", {"A": 10}, ["A"]))
            second = cohort_from_snapshot(snap("2026-01-01", {"A": 99}, ["A"]))
            self.assertTrue(append_cohort(first, path))
            self.assertFalse(append_cohort(second, path))
            self.assertEqual(load_cohorts(path)[0]["prices"]["A"], 10)

    def test_matured_horizon_excess_vs_universe(self):
        entry = cohort_from_snapshot(snap("2026-01-01", {"A": 10, "B": 10}, ["A"]))
        exit_ = cohort_from_snapshot(snap("2026-02-02", {"A": 12, "B": 10}, ["B"]))
        out = score([entry, exit_])
        h = out["longTerm"]["horizons"]["21s"]
        self.assertEqual(h["matured"], 1)
        self.assertAlmostEqual(h["meanPick"], 0.2)
        self.assertAlmostEqual(h["meanUniverse"], 0.1)
        self.assertAlmostEqual(h["meanExcessVsUniverse"], 0.1)
        self.assertEqual(out["longTermTurnover"]["meanReplacedShare"], 1.0)

    def test_exit_outside_tolerance_does_not_mature(self):
        entry = cohort_from_snapshot(snap("2026-01-01", {"A": 10}, ["A"]))
        late = cohort_from_snapshot(snap("2026-03-01", {"A": 12}, ["A"]))
        self.assertEqual(score([entry, late])["longTerm"]["horizons"]["21s"]["matured"], 0)

    def test_build_records_latest_and_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "latest_snapshot.json").write_text(json.dumps(snap("2026-01-05", {"A": 11, "B": 9}, ["A"])))
            append_cohort(cohort_from_snapshot(snap("2026-01-01", {"A": 10, "B": 10}, ["B"])),
                          data / "inferno_pick_scorecard_cohorts.jsonl")
            payload = build_pick_scorecard(data)
            self.assertEqual(payload["cohorts"], 2)
            self.assertFalse(payload["authorityChanged"])
            marks = payload["results"]["longTerm"]["openMarks"]
            self.assertEqual(marks[0]["picks"], ["B"])
            self.assertIn("not a result until its horizon matures", pick_scorecard_text(payload))


if __name__ == "__main__":
    unittest.main()
