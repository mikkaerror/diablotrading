from __future__ import annotations

"""Regression tests for the decision-brief generator.

Contract:
- the generator is diagnostic-only and cannot mutate any input
- briefs are produced only for pending tickers
- considerations include earnings, IV regime, sector concentration, and
  live-book overlap when applicable
- the artifact path is distinct from any operational artifact
"""

import unittest

from inferno_decision_brief import (
    DECISION_BRIEF_FILE,
    DECISION_BRIEF_STAGE,
    DECISION_BRIEF_TEXT_FILE,
    brief_considerations,
    build_brief_for_ticker,
    build_decision_briefs,
    exposure_impact,
)


SNAPSHOT = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "rows": [
        {
            "ticker": "CEG",
            "readiness": 99,
            "confidence": 3,
            "daysUntilEarnings": 1,
            "ivRank": 78,
            "ivRankChange": 4,
            "atrPercent": 3.2,
            "rec1": "STRADDLE (13)",
            "rec2": "STRADDLE (7.5)",
            "accumulationBias": "neutral",
            "distanceToSupportPct": -1.2,
            "distanceToResistancePct": 0.8,
            "rvol": 1.4,
            "marketContext": {"trend": {"label": "Bullish"}},
        },
        {
            "ticker": "VNET",
            "readiness": 92,
            "confidence": 2,
            "daysUntilEarnings": 17,
            "ivRank": 22,
            "atrPercent": 4.5,
            "rec1": "STRADDLE (12)",
            "marketContext": {"trend": {"label": "Bearish"}},
        },
    ],
}

EDGE = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "ranked": [
        {"ticker": "CEG", "category": "catalyst", "lane": "compute", "edgeScore": 0.81,
         "industry": "Utilities", "sector": "Utilities", "thesis": "power for AI build-outs"},
        {"ticker": "VNET", "category": "shovel", "lane": "data-rail", "edgeScore": 0.6,
         "industry": "IT Services", "sector": "Technology", "thesis": "China datacenter scale-out"},
    ],
}

EXPOSURE = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "sectorExposure": {
        "largestSector": "Technology",
        "largestSectorShare": 0.6,
        "rows": [
            {"ticker": "CEG", "sector": "Utilities", "industry": "Utilities", "riskUnits": 0.9, "intentStatus": "blocked"},
            {"ticker": "VNET", "sector": "Technology", "industry": "IT Services", "riskUnits": 0.9, "intentStatus": "blocked"},
        ],
    },
    "setupExposure": {"setupShares": {"Straddle": 0.8, "Vertical Call": 0.2}},
    "verdict": {"level": "review"},
    "marketRegime": {"regime": "bullish-normal"},
}

LIVE_REVIEW = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "positions": [
        {"symbol": "VNET", "posture": "fragile", "actionLabel": "manual-review",
         "bucket": "earnings", "weightPct": 14, "plPercent": -2.5, "qty": 100,
         "riskFlags": ["market-context fragile"], "reasons": ["weak alignment"]},
    ],
}

QUEUE = {
    "generatedAt": "2026-05-10T08:00:00-06:00",
    "items": [
        {"ticker": "CEG", "approvalStatus": "pending"},
        {"ticker": "VNET", "approvalStatus": "pending"},
        {"ticker": "OLD", "approvalStatus": "rejected"},
    ],
}


class DecisionBriefTests(unittest.TestCase):
    """Verify the briefs surface the right context without mutation."""

    def test_artifact_paths_distinct_and_stage_committed(self) -> None:
        self.assertTrue(str(DECISION_BRIEF_FILE).endswith("inferno_decision_briefs.json"))
        self.assertTrue(str(DECISION_BRIEF_TEXT_FILE).endswith("decision_briefs_latest.txt"))
        self.assertEqual(DECISION_BRIEF_STAGE, "decision-brief-diagnostic-only")

    def test_exposure_impact_flags_already_in_slate(self) -> None:
        impact = exposure_impact("CEG", EXPOSURE)
        self.assertTrue(impact["alreadyInSlate"])
        self.assertEqual(impact["sector"], "Utilities")

    def test_brief_for_imminent_earnings_flags_decide_today(self) -> None:
        brief = build_brief_for_ticker("CEG", snapshot=SNAPSHOT, edge=EDGE,
                                       exposure=EXPOSURE, live_review=LIVE_REVIEW)
        joined = " ".join(brief["considerations"]).lower()
        self.assertIn("earnings imminent", joined)
        self.assertIn("rich vol", joined)
        self.assertEqual(brief["edge"]["category"], "catalyst")

    def test_brief_flags_live_book_overlap(self) -> None:
        brief = build_brief_for_ticker("VNET", snapshot=SNAPSHOT, edge=EDGE,
                                       exposure=EXPOSURE, live_review=LIVE_REVIEW)
        self.assertTrue(brief["liveBook"]["held"])
        joined = " ".join(brief["considerations"]).lower()
        self.assertIn("already held", joined)
        self.assertIn("market-context fragile", joined)

    def test_build_decision_briefs_only_for_pending(self) -> None:
        report = build_decision_briefs(queue=QUEUE, snapshot=SNAPSHOT, edge=EDGE,
                                        exposure=EXPOSURE, live_review=LIVE_REVIEW)
        tickers = [brief["ticker"] for brief in report["briefs"]]
        self.assertEqual(set(tickers), {"CEG", "VNET"})
        self.assertEqual(report["pendingCount"], 2)
        self.assertTrue(report["diagnosticOnly"])

    def test_brief_considerations_flag_concentration_when_over_60(self) -> None:
        considerations = brief_considerations(
            row={"daysUntilEarnings": 10, "ivRank": 50, "marketContext": {}},
            edge_entry={"category": "catalyst", "lane": "compute"},
            exposure_view={
                "largestSector": "Technology",
                "largestSectorShare": 0.6,
                "setupShares": {"Straddle": 0.8},
            },
            live_pos={},
        )
        joined = " ".join(considerations).lower()
        self.assertIn("technology", joined)
        self.assertIn("setup concentration", joined)

    def test_build_decision_briefs_does_not_mutate_inputs(self) -> None:
        import json as _json
        before = _json.dumps([QUEUE, SNAPSHOT, EDGE, EXPOSURE, LIVE_REVIEW], sort_keys=True)
        build_decision_briefs(queue=QUEUE, snapshot=SNAPSHOT, edge=EDGE,
                               exposure=EXPOSURE, live_review=LIVE_REVIEW)
        after = _json.dumps([QUEUE, SNAPSHOT, EDGE, EXPOSURE, LIVE_REVIEW], sort_keys=True)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
