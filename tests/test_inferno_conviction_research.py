from __future__ import annotations

"""Regression tests for the research-only conviction map."""

import unittest

import inferno_conviction_research as conviction


def sample_rows() -> list[dict]:
    """Return a tiny slate with one giant, one sleeper, and one contradiction."""
    return [
        {
            "ticker": "NVDA",
            "readiness": 96,
            "priority": 8.4,
            "confidence": 3,
            "signalTrigger": True,
            "daysUntilEarnings": 10,
            "setupRec": "Vertical Call",
            "ivRank": 44,
            "ivRankChange": 0.25,
            "atrZScore": 1.4,
            "atrPercent": 4.8,
            "pe": 48,
            "longTermScore": 6.6,
            "marketContext": {
                "trend": {"label": "Bullish"},
                "rvol": 1.25,
                "atrExpansion": 1.4,
                "distanceToResistancePct": 7.0,
                "distanceToSupportPct": 5.0,
                "alignmentScore": 72,
                "support": 120.0,
                "resistance": 150.0,
                "sourceStatus": "confirmed",
            },
        },
        {
            "ticker": "MOD",
            "readiness": 91,
            "priority": 7.0,
            "confidence": 2,
            "signalTrigger": True,
            "daysUntilEarnings": 8,
            "setupRec": "Vertical Call",
            "ivRank": 42,
            "ivRankChange": 0.12,
            "atrZScore": 1.1,
            "atrPercent": 5.5,
            "pe": 26,
            "longTermScore": 8.1,
            "marketContext": {
                "trend": {"label": "Bullish"},
                "rvol": 0.95,
                "atrExpansion": 1.1,
                "distanceToResistancePct": 4.5,
                "distanceToSupportPct": 6.0,
                "alignmentScore": 68,
                "support": 225.0,
                "resistance": 294.0,
                "sourceStatus": "confirmed",
            },
        },
        {
            "ticker": "HOTRISK",
            "readiness": 98,
            "priority": 8.0,
            "confidence": 2,
            "signalTrigger": True,
            "daysUntilEarnings": 5,
            "setupRec": "Straddle",
            "ivRank": 93,
            "ivRankChange": 0.04,
            "atrZScore": -0.2,
            "atrPercent": 2.0,
            "pe": 160,
            "longTermScore": 2.0,
            "marketContext": {
                "trend": {"label": "Bullish"},
                "rvol": 0.4,
                "atrExpansion": -0.2,
                "distanceToResistancePct": 1.0,
                "distanceToSupportPct": 25.0,
                "alignmentScore": 25,
                "sourceStatus": "fallback",
            },
        },
    ]


def sample_edge_research() -> dict:
    """Return matching edge rows without needing yfinance."""
    return {
        "ranked": [
            {
                "ticker": "NVDA",
                "category": "AI/Compute Picks",
                "edgeScore": 88,
                "scores": {
                    "thesisScore": 96,
                    "qualityScore": 88,
                    "valuationRiskScore": 62,
                },
            },
            {
                "ticker": "MOD",
                "category": "AI/Data Center Power",
                "edgeScore": 78,
                "scores": {
                    "thesisScore": 84,
                    "qualityScore": 74,
                    "valuationRiskScore": 82,
                },
            },
        ]
    }


class InfernoConvictionResearchTests(unittest.TestCase):
    """Verify the conviction layer stays useful and research-only."""

    def test_conviction_research_classifies_giants_sleepers_and_contradictions(self) -> None:
        report = conviction.build_conviction_research(
            rows=sample_rows(),
            edge_research=sample_edge_research(),
            limit=5,
        )

        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])
        self.assertEqual(report["trackedRows"], 3)
        self.assertEqual(report["mathVersion"], "conviction-v2-balance-uncertainty")
        self.assertEqual(report["behemoths"][0]["ticker"], "NVDA")
        self.assertEqual(report["sleepers"][0]["ticker"], "MOD")
        self.assertTrue(report["bestBalanced"])
        self.assertTrue(any(item["ticker"] == "HOTRISK" for item in report["contradictions"]))
        self.assertTrue(any("high PE" in item["riskFlags"] for item in report["contradictions"]))
        self.assertTrue(report["strategyReferences"])
        self.assertTrue(report["regimeReferences"])

    def test_adjusted_score_haircuts_lopsided_fragile_rows(self) -> None:
        report = conviction.build_conviction_research(
            rows=sample_rows(),
            edge_research=sample_edge_research(),
            limit=5,
        )
        ranked_by_ticker = {item["ticker"]: item for item in report["ranked"]}

        risky = ranked_by_ticker["HOTRISK"]
        giant = ranked_by_ticker["NVDA"]

        self.assertLess(risky["convictionAdjustedScore"], risky["gutCheckScore"])
        self.assertGreater(risky["uncertaintyPenalty"], giant["uncertaintyPenalty"])
        self.assertEqual(risky["evidenceGrade"], "D")
        self.assertIn("risk-flagged", risky["reasonCodes"])
        self.assertIn(giant["evidenceGrade"], {"A", "B", "C"})

    def test_technical_discovery_context_is_visible_without_changing_conviction_gates(self) -> None:
        baseline_rows = sample_rows()
        enriched_rows = sample_rows()
        enriched_rows[0]["marketContext"]["watchlistPulse"] = {
            "technicalResearch": {
                "researchOnly": True,
                "gateInput": False,
                "calibrated": False,
                "status": "complete",
                "score": 82.5,
                "posture": "supports-discovery",
                "inputs": {"rvolPrior30": 1.7, "momentumAtrMultiple": 1.2},
            }
        }

        baseline = conviction.build_conviction_research(
            rows=baseline_rows,
            edge_research=sample_edge_research(),
            limit=5,
        )
        enriched = conviction.build_conviction_research(
            rows=enriched_rows,
            edge_research=sample_edge_research(),
            limit=5,
        )
        baseline_nvda = next(item for item in baseline["ranked"] if item["ticker"] == "NVDA")
        enriched_nvda = next(item for item in enriched["ranked"] if item["ticker"] == "NVDA")

        self.assertEqual(enriched_nvda["technicalResearchScore"], 82.5)
        self.assertEqual(enriched_nvda["technicalResearch"]["posture"], "supports-discovery")
        self.assertEqual(enriched_nvda["convictionAdjustedScore"], baseline_nvda["convictionAdjustedScore"])
        self.assertEqual(enriched["technicalDiscoveryLeaders"][0]["ticker"], "NVDA")

    def test_full_tracker_ranking_is_retained_beyond_report_digest_limit(self) -> None:
        rows = []
        for index in range(40):
            row = dict(sample_rows()[1])
            row["ticker"] = f"FULL{index:02d}"
            rows.append(row)

        report = conviction.build_conviction_research(
            rows=rows,
            edge_research={"ranked": []},
            limit=5,
        )

        self.assertEqual(report["trackedRows"], 40)
        self.assertEqual(len(report["ranked"]), 40)
        self.assertEqual(report["coverage"]["retainedRankedRows"], 40)
        self.assertTrue(report["coverage"]["fullTrackerRetained"])
        self.assertEqual(
            sum(report["coverage"]["researchActionCounts"].values()),
            40,
        )

    def test_pillar_balance_penalizes_one_pillar_wonders(self) -> None:
        balanced = {
            "theme": 75,
            "timing": 75,
            "options": 75,
            "structure": 75,
            "quality": 75,
            "valuation": 75,
            "evidence": 75,
        }
        lopsided = {
            "theme": 100,
            "timing": 100,
            "options": 100,
            "structure": 20,
            "quality": 20,
            "valuation": 20,
            "evidence": 20,
        }

        self.assertGreater(conviction.pillar_balance_score(balanced), 99)
        self.assertLess(conviction.pillar_balance_score(lopsided), 85)

    def test_rendered_text_contains_sources_and_safety(self) -> None:
        report = conviction.build_conviction_research(
            rows=sample_rows(),
            edge_research=sample_edge_research(),
            limit=5,
        )
        text = conviction.conviction_research_text(report)

        self.assertIn("Inferno Conviction Research", text)
        self.assertIn("Behemoths / giants", text)
        self.assertIn("Sleepers to investigate", text)
        self.assertIn("Best balanced conviction", text)
        self.assertIn("Full tracker coverage", text)
        self.assertIn("Research references", text)
        self.assertIn("Research-only", text)


if __name__ == "__main__":
    unittest.main()
