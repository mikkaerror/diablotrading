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
        self.assertEqual(report["behemoths"][0]["ticker"], "NVDA")
        self.assertEqual(report["sleepers"][0]["ticker"], "MOD")
        self.assertTrue(any(item["ticker"] == "HOTRISK" for item in report["contradictions"]))
        self.assertTrue(any("high PE" in item["riskFlags"] for item in report["contradictions"]))
        self.assertTrue(report["strategyReferences"])
        self.assertTrue(report["regimeReferences"])

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
        self.assertIn("Research references", text)
        self.assertIn("Research-only", text)


if __name__ == "__main__":
    unittest.main()
