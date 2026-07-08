from __future__ import annotations

"""Tests for the defined-risk short-premium study.

The study must: model short-vol R as (1 - moveRatio - friction) capped at the
protective-wing floor; cluster by name; render an honest verdict; and never
claim promotability or authority change.
"""

import json
import tempfile
import unittest
from pathlib import Path

import inferno_short_premium_study as study


def _ledger(records):
    # Mirror the real file shape: records nested under a dict key.
    return {"stage": "x", "records": records}


def _paper_ledger(records):
    return {"version": 1, "items": records}


def _rec(ticker, implied, realized):
    return {
        "ticker": ticker,
        "impliedMovePct": implied,
        "realizedAbsMovePct": realized,
        "moveRatio": realized / implied,
        "family": "LONG_STRADDLE",
    }


class ShortPremiumStudyTests(unittest.TestCase):
    def _build(self, records):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ledger.json"
            paper = Path(tmp) / "paper.json"
            p.write_text(json.dumps(_ledger(records)), encoding="utf-8")
            paper.write_text(json.dumps(_paper_ledger([])), encoding="utf-8")
            return study.build_study(str(p), paper_ledger_path=str(paper))

    def _build_with_paper(self, records, paper_records):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "ledger.json"
            paper = Path(tmp) / "paper.json"
            p.write_text(json.dumps(_ledger(records)), encoding="utf-8")
            paper.write_text(json.dumps(_paper_ledger(paper_records)), encoding="utf-8")
            return study.build_study(str(p), paper_ledger_path=str(paper))

    def test_seller_wins_when_realized_below_implied(self):
        # realized well below implied -> seller keeps ~full credit minus friction.
        recs = [_rec(f"T{i}", 20.0, 8.0) for i in range(20)]  # moveRatio 0.4
        p = self._build(recs)
        cap = p["caps"]["3.0"]
        # 1 - 0.4 - 0.10 friction = 0.50
        self.assertAlmostEqual(cap["meanR"], 0.50, places=2)
        self.assertEqual(cap["winRatePct"], 100.0)

    def test_tail_is_capped_by_wings(self):
        # A blowout (realized 5x implied) must not lose more than the cap.
        recs = [_rec("BLOWUP", 10.0, 50.0)]  # moveRatio 5 -> raw -4.10
        p = self._build(recs)
        self.assertGreaterEqual(p["caps"]["3.0"]["minR"], -3.0)
        self.assertGreaterEqual(p["caps"]["1.5"]["minR"], -1.5)

    def test_research_only_flags(self):
        p = self._build([_rec("A", 20.0, 10.0), _rec("B", 20.0, 30.0)])
        self.assertTrue(p["researchOnly"])
        self.assertFalse(p["promotable"])
        self.assertFalse(p["authorityChanged"])

    def test_verdict_negative_when_center_negative(self):
        # realized above implied for most -> seller loses -> not supported.
        recs = [_rec(f"T{i}", 20.0, 40.0) for i in range(20)]  # moveRatio 2
        p = self._build(recs)
        self.assertIn(p["verdict"], {"sell-side-negative-backward"})

    def test_forward_campaign_loads_closed_short_premium_defined_tickets(self):
        ticket = {
            "ticketId": "sp-1",
            "ticker": "WDC",
            "eventId": "WDC|2026-07-20",
            "arm": "SHORT_PREMIUM_DEFINED",
            "strategy": "SHORT_PREMIUM_DEFINED",
            "tradeDate": "2026-07-08",
            "entryLimit": 1.25,
            "estimatedMaxLoss": 375.0,
            "estimatedTotalSpreadFrictionDollars": 42.0,
            "frictionModel": "full-atm-spread-per-crossing",
            "impliedMovePct": 18.0,
            "outcome": {
                "status": "closed",
                "reviewedAt": "2026-07-21T16:00:00-06:00",
                "estimatedPnl": 90.0,
                "realizedAbsMovePct": 9.0,
            },
        }
        p = self._build_with_paper([_rec("A", 20.0, 10.0), _rec("B", 20.0, 10.0)], [ticket])
        self.assertEqual(p["forwardCampaign"]["verdict"], "forward-short-premium-collecting")
        self.assertEqual(p["forwardCampaign"]["distinctEvents"], 1)
        self.assertEqual(p["forwardCampaign"]["distinctNames"], 1)
        self.assertEqual(p["forwardRecords"][0]["arm"], "SHORT_PREMIUM_DEFINED")
        self.assertEqual(p["forwardRecords"][0]["creditCollectedDollars"], 125.0)
        self.assertEqual(p["forwardRecords"][0]["netR"], 0.24)
        self.assertEqual(p["forwardCampaign"]["maxNameRiskSharePct"], 100.0)
        self.assertFalse(p["forwardCampaign"]["promotionEligible"])
        self.assertTrue(p["forwardCampaign"]["researchOnly"])

    def test_forward_campaign_ignores_plain_credit_spreads(self):
        ticket = {
            "ticketId": "pcs-1",
            "ticker": "WDC",
            "eventId": "WDC|2026-07-20",
            "strategy": "PUT_CREDIT_SPREAD",
            "entryLimit": 1.25,
            "estimatedMaxLoss": 375.0,
            "outcome": {"status": "closed", "estimatedReturnOnRisk": 0.2},
        }
        p = self._build_with_paper([_rec("A", 20.0, 10.0), _rec("B", 20.0, 10.0)], [ticket])
        self.assertEqual(p["forwardCampaign"]["verdict"], "forward-awaiting-short-premium-records")
        self.assertEqual(p["forwardRecords"], [])

    def test_forward_campaign_timebox_kills_without_breadth(self):
        summary = study.forward_summary([], today=study.FORWARD_TIMEBOX_END.replace(day=6))
        self.assertEqual(summary["verdict"], "forward-short-premium-killed")
        self.assertIn("timebox-expired-without-breadth", summary["killReasons"])


if __name__ == "__main__":
    unittest.main()
