from __future__ import annotations

import unittest

import inferno_tracker_registry as registry


def snapshot() -> dict:
    return {
        "generatedAt": "2026-07-20T10:00:00-06:00",
        "eligibleTickers": ["NVDA"],
        "rows": [
            {"ticker": "NVDA", "status": "Ready", "priceAsOf": "2026-07-20T10:00:00-06:00", "priceSource": "sheet"},
            {"ticker": "MYST", "status": "Watch", "priceAsOf": "2026-07-20T10:00:00-06:00", "priceSource": "sheet"},
        ],
    }


def conviction() -> dict:
    return {
        "generatedAt": "2026-07-20T10:05:00-06:00",
        "ranked": [
            {
                "ticker": "NVDA",
                "category": "AI/Compute Picks",
                "convictionAdjustedScore": 89.0,
                "longTermConvictionScore": 84.0,
                "researchAction": "inventory watchlist",
                "evidenceGrade": "B",
                "longTermResearchQualified": True,
            },
            {
                "ticker": "MYST",
                "category": "Unclassified",
                "convictionAdjustedScore": 50.0,
                "longTermConvictionScore": 45.0,
                "researchAction": "shadow only",
                "evidenceGrade": "D",
                "longTermResearchQualified": False,
            },
        ],
    }


def account() -> dict:
    return {
        "generatedAt": "2026-07-20T10:10:00-06:00",
        "positions": [
            {"symbol": "NVDA", "qty": 2, "markValue": 350.0, "weightPct": 35.0, "operatorLongTermHold": True},
            {"symbol": "OFFTRACK", "qty": 1, "markValue": 20.0, "weightPct": 2.0},
        ],
    }


class InfernoTrackerRegistryTests(unittest.TestCase):
    """Protect full-tracker coverage and the no-allocation boundary."""

    def test_registry_retains_all_tracker_rows_and_joins_holdings(self) -> None:
        report = registry.build_tracker_registry(
            snapshot=snapshot(), conviction=conviction(), account=account()
        )

        self.assertEqual(report["coverage"]["trackedRows"], 2)
        self.assertEqual(report["coverage"]["convictionCoverage"], 2)
        self.assertEqual([item["ticker"] for item in report["entries"]], ["NVDA", "MYST"])
        nvda = report["entries"][0]
        self.assertTrue(nvda["holding"]["currentlyHeld"])
        self.assertEqual(nvda["existingEligibility"], "existing-eligible")
        self.assertEqual(nvda["taxonomy"]["economicExposure"], "AI compute and semiconductors")
        self.assertEqual(report["coverage"]["holdingsCoverage"]["heldNotInTracker"], ["OFFTRACK"])

    def test_registry_surfaces_unclassified_taxonomy_without_inventing_a_sector(self) -> None:
        report = registry.build_tracker_registry(
            snapshot=snapshot(), conviction=conviction(), account=account()
        )

        mystery = next(item for item in report["entries"] if item["ticker"] == "MYST")
        self.assertEqual(report["verdict"], "taxonomy-incomplete")
        self.assertEqual(mystery["taxonomy"]["category"], "Unclassified")
        self.assertEqual(mystery["taxonomy"]["taxonomyStatus"], "needs-operator-taxonomy")
        self.assertFalse(report["nextBuildGate"]["readyForDiversifiedDcaConstruction"])
        self.assertIn("need canonical taxonomy", " ".join(report["blockers"]))

    def test_registry_pins_research_and_authority_boundary(self) -> None:
        report = registry.build_tracker_registry(
            snapshot=snapshot(), conviction=conviction(), account=account()
        )

        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])
        self.assertFalse(report["authorityChanged"])
        self.assertFalse(report["brokerSubmitAllowed"])
        self.assertFalse(report["liveTradingAllowed"])
        self.assertFalse(report["authorityBoundary"]["targetWeightsProduced"])
        self.assertFalse(report["authorityBoundary"]["brokerActionProduced"])

    def test_rendered_registry_explains_its_dca_boundary(self) -> None:
        text = registry.tracker_registry_text(
            registry.build_tracker_registry(snapshot=snapshot(), conviction=conviction(), account=account())
        )
        self.assertIn("DCA construction gate", text)
        self.assertIn("not a target-weight model", text)
        self.assertIn("Broker submission and live trading remain disabled", text)


if __name__ == "__main__":
    unittest.main()
