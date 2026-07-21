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


def taxonomy() -> dict:
    return {
        "generatedAt": "2026-07-20T10:15:00-06:00",
        "entries": [
            {
                "ticker": "NVDA",
                "sector": "Technology",
                "industry": "Semiconductors",
                "economicExposure": "semiconductors and equipment",
                "referenceStatus": "reference-covered",
                "referenceSource": "taxonomy-cache/fixture",
                "referenceFresh": True,
                "referenceAsOf": "2026-07-20T10:15:00-06:00",
                "portfolioRole": "not-defined-by-reference-data",
                "portfolioRoleStatus": "requires-operator-policy",
            },
            {
                "ticker": "MYST",
                "sector": "Industrials",
                "industry": "Engineering & Construction",
                "economicExposure": "infrastructure construction and services",
                "referenceStatus": "reference-covered",
                "referenceSource": "taxonomy-cache/fixture",
                "referenceFresh": True,
                "referenceAsOf": "2026-07-20T10:15:00-06:00",
                "portfolioRole": "not-defined-by-reference-data",
                "portfolioRoleStatus": "requires-operator-policy",
            },
        ],
    }


class InfernoTrackerRegistryTests(unittest.TestCase):
    """Protect full-tracker coverage and the no-allocation boundary."""

    def test_registry_retains_all_tracker_rows_and_joins_holdings(self) -> None:
        report = registry.build_tracker_registry(
            snapshot=snapshot(), conviction=conviction(), account=account(), taxonomy=taxonomy()
        )

        self.assertEqual(report["coverage"]["trackedRows"], 2)
        self.assertEqual(report["coverage"]["convictionCoverage"], 2)
        self.assertEqual([item["ticker"] for item in report["entries"]], ["NVDA", "MYST"])
        nvda = report["entries"][0]
        self.assertTrue(nvda["holding"]["currentlyHeld"])
        self.assertEqual(nvda["existingEligibility"], "existing-eligible")
        self.assertEqual(nvda["taxonomy"]["economicExposure"], "semiconductors and equipment")
        self.assertEqual(nvda["taxonomy"]["sector"], "Technology")
        self.assertEqual(report["coverage"]["holdingsCoverage"]["heldNotInTracker"], ["OFFTRACK"])

    def test_registry_keeps_reference_data_separate_from_portfolio_roles(self) -> None:
        report = registry.build_tracker_registry(
            snapshot=snapshot(), conviction=conviction(), account=account(), taxonomy=taxonomy()
        )

        mystery = next(item for item in report["entries"] if item["ticker"] == "MYST")
        self.assertEqual(report["verdict"], "reference-covered-role-policy-pending")
        self.assertEqual(mystery["taxonomy"]["category"], "Unclassified")
        self.assertEqual(mystery["taxonomy"]["taxonomyStatus"], "reference-backed")
        self.assertEqual(mystery["taxonomy"]["portfolioRoleStatus"], "requires-operator-policy")
        self.assertFalse(report["nextBuildGate"]["readyForDiversifiedDcaConstruction"])
        self.assertIn("operator-approved portfolio-role policy", " ".join(report["blockers"]))

    def test_registry_pins_research_and_authority_boundary(self) -> None:
        report = registry.build_tracker_registry(
            snapshot=snapshot(), conviction=conviction(), account=account(), taxonomy=taxonomy()
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
            registry.build_tracker_registry(snapshot=snapshot(), conviction=conviction(), account=account(), taxonomy=taxonomy())
        )
        self.assertIn("DCA construction gate", text)
        self.assertIn("not a target-weight model", text)
        self.assertIn("Broker submission and live trading remain disabled", text)

    def test_registry_preserves_missing_reference_data_as_an_explicit_blocker(self) -> None:
        report = registry.build_tracker_registry(
            snapshot=snapshot(), conviction=conviction(), account=account(), taxonomy={"entries": []}
        )

        self.assertEqual(report["verdict"], "reference-coverage-incomplete")
        self.assertEqual(report["coverage"]["referenceCoverage"]["referenceMissingRows"], 2)
        self.assertIn("lack reference sector/industry coverage", " ".join(report["blockers"]))


if __name__ == "__main__":
    unittest.main()
