from __future__ import annotations

"""Tests for the ex-ante earnings-richness selection signal.

The signal must: collapse to distinct events, refuse to conclude on unreliable or
too-thin data, and detect a genuinely predictive ex-ante ranking out of sample.
"""

import json
import tempfile
import unittest
from pathlib import Path

import inferno_earnings_richness_signal as sig


def _rec(ticker, implied, realized, t, **overrides):
    record = {
        "ticker": ticker,
        "impliedMovePct": implied,
        "realizedAbsMovePct": realized,
        "moveRatio": realized / implied,
        "reviewedAt": t,
        "family": "LONG_STRADDLE",
    }
    record.update(overrides)
    return record


def _build(records):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "ledger.json"
        p.write_text(json.dumps({"records": records}), encoding="utf-8")
        return sig.build_signal(str(p))


class EarningsRichnessSignalTests(unittest.TestCase):
    def test_thin_history_cannot_conclude(self):
        # one event per name -> no out-of-sample pairs possible.
        recs = [_rec(f"N{i}", 20.0, 10.0 + i, f"2026-01-0{i+1}") for i in range(5)]
        p = _build(recs)
        self.assertEqual(p["verdict"], "insufficient-history-for-oos-test")
        self.assertEqual(p["oosPairs"], 0)

    def test_predictive_when_richness_is_stable_per_name(self):
        # 5 names with stable, distinct richness across 6 events each ->
        # prior-mean predicts the held-out event -> positive OOS rank corr.
        recs = []
        targets = {"A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2, "E": 0.0}
        for nm, tgt in targets.items():
            for k in range(6):
                realized = (1 - tgt) * 20.0 + k * 0.01  # distinct values, tiny drift
                recs.append(_rec(nm, 20.0, realized, f"2026-0{k+1}-01"))
        p = _build(recs)
        self.assertGreaterEqual(p["oosPairs"], sig.MIN_OOS_PAIRS)
        self.assertEqual(p["verdict"], "signal-predictive-out-of-sample")
        self.assertGreater(p["oosRankCorr"], sig.PREDICTIVE_MIN_RANK_CORR)

    def test_research_only_flags(self):
        recs = [_rec("A", 20.0, 10.0, "2026-01-01"), _rec("A", 20.0, 12.0, "2026-04-01")]
        p = _build(recs)
        self.assertTrue(p["researchOnly"])
        self.assertFalse(p["promotable"])
        self.assertFalse(p["authorityChanged"])

    def test_chronic_over_mover_excluded_from_sell(self):
        recs = [_rec("BLOW", 10.0, 30.0, "2026-01-01"),
                _rec("BLOW", 10.0, 28.0, "2026-04-01")]  # realized 3x implied
        p = _build(recs)
        self.assertIn("BLOW", p["chronicOverMovers"])
        self.assertNotIn("BLOW", p["sellCandidates"])

    def test_same_realized_move_on_different_dates_stays_distinct(self):
        recs = [
            _rec("SAME", 20.0, 10.0, "2026-01-02T08:00:00-07:00", earningsDate="2026-01-02"),
            _rec("SAME", 20.0, 10.0, "2026-04-02T08:00:00-06:00", earningsDate="2026-04-02"),
        ]
        p = _build(recs)
        row = next(item for item in p["ranking"] if item["name"] == "SAME")
        self.assertEqual(row["events"], 2)
        self.assertTrue(row["richHistoryCandidate"])
        self.assertFalse(row["sellCandidate"])
        self.assertEqual(p["sellCandidates"], [])


if __name__ == "__main__":
    unittest.main()
