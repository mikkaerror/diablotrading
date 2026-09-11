from __future__ import annotations

"""Regression tests for research-only technical context in edge research."""

import unittest

import inferno_edge_research as edge


def sample_row(*, technical: dict | None = None) -> dict:
    row = {
        "ticker": "MRVL",
        "readiness": 91,
        "priority": 7.2,
        "confidence": 2,
        "signalTrigger": True,
        "daysUntilEarnings": 14,
        "setupRec": "Vertical Call",
        "longTermScore": 7.2,
        "marketContext": {
            "rvol": 1.2,
            "atrExpansion": 0.5,
            "distanceToResistancePct": 5.0,
            "distanceToSupportPct": 5.0,
            "trend": {"label": "Bullish"},
        },
    }
    if technical is not None:
        row["marketContext"]["watchlistPulse"] = {"technicalResearch": technical}
    return row


class InfernoEdgeResearchTests(unittest.TestCase):
    def test_negative_forward_pe_is_not_cheap_or_hidden_by_trailing(self):
        row = sample_row()
        missing = edge.valuation_risk_score(row, {})
        self.assertEqual(edge.valuation_risk_score(row, {"forwardPE": -10, "trailingPE": 15}), missing)
        self.assertGreater(edge.valuation_risk_score(row, {"forwardPE": 15}), missing)
        info = edge.valuation_pe_context(row, {"forwardPE": -10, "trailingPE": 15})
        self.assertEqual(info["status"], "not-meaningful")
        self.assertEqual(info["source"], "forwardPE")

    def test_pe_falls_back_only_when_absent(self):
        self.assertEqual(edge.valuation_pe_context({"pe": 12}, {"forwardPE": None, "trailingPE": 20})["value"], 20)
        self.assertEqual(edge.valuation_pe_context({"pe": 12}, {})["source"], "trackerPE")
        for raw in (0, "bad", float("nan"), float("inf"), True):
            info = edge.valuation_pe_context({"pe": 12}, {"forwardPE": raw, "trailingPE": 20})
            self.assertIsNone(info["value"])
            self.assertEqual(info["source"], "forwardPE")

    def test_only_valid_forward_earnings_offsets_enter_catalyst_lane(self):
        scores = {"edgeScore": 90, "confirmationScore": 90, "qualityScore": 90}
        category = {"category": "AI/Compute Picks"}
        for raw in (-1, None, "bad", float("nan"), float("inf"), -float("inf"), True, 22):
            row = sample_row(); row["daysUntilEarnings"] = raw
            self.assertNotEqual(edge.classify_lane(row, scores, category), "Catalyst Trade Candidate")
        for raw in (0, 21, "14"):
            row = sample_row(); row["daysUntilEarnings"] = raw
            self.assertEqual(edge.classify_lane(row, scores, category), "Catalyst Trade Candidate")

    def test_technical_discovery_context_does_not_change_edge_score_or_lane(self) -> None:
        metadata = {
            "grossMargins": 0.6,
            "operatingMargins": 0.3,
            "profitMargins": 0.2,
            "revenueGrowth": 0.2,
            "freeCashflow": 1,
            "debtToEquity": 40,
            "forwardPE": 30,
            "priceToSalesTrailing12Months": 8,
            "beta": 1.2,
        }
        category = {"category": "AI/Compute Picks", "baseScore": 96}
        technical = {
            "researchOnly": True,
            "gateInput": False,
            "calibrated": False,
            "status": "complete",
            "score": 84.0,
            "posture": "supports-discovery",
        }

        baseline = edge.edge_score(sample_row(), metadata, category)
        enriched = edge.edge_score(sample_row(technical=technical), metadata, category)

        self.assertEqual(enriched["technicalDiscoveryScore"], 84.0)
        self.assertEqual(enriched["technicalResearch"]["posture"], "supports-discovery")
        self.assertEqual(enriched["edgeScore"], baseline["edgeScore"])
        self.assertEqual(
            edge.classify_lane(sample_row(), baseline, category),
            edge.classify_lane(sample_row(technical=technical), enriched, category),
        )


if __name__ == "__main__":
    unittest.main()
