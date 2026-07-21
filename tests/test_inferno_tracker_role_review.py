from __future__ import annotations

import unittest

import inferno_tracker_role_review as role_review


def registry() -> dict:
    return {
        "entries": [
            {
                "ticker": "MISS",
                "existingEligibility": "existing-tracked-not-eligible",
                "taxonomy": {
                    "referenceStatus": "reference-missing",
                    "referenceFresh": False,
                    "sector": "Unknown",
                    "industry": "Unknown",
                    "economicExposure": "Unclassified",
                    "category": "Unclassified",
                },
                "holding": {"currentlyHeld": False},
                "research": {"rank": 3, "longTermResearchQualified": False, "longTermConvictionScore": 0, "evidenceGrade": "D"},
            },
            {
                "ticker": "HOLD",
                "existingEligibility": "existing-eligible",
                "taxonomy": {
                    "referenceStatus": "reference-covered",
                    "referenceFresh": True,
                    "sector": "Technology",
                    "industry": "Semiconductors",
                    "economicExposure": "semiconductors and equipment",
                    "taxonomySource": "fixture",
                    "category": "AI/Compute Picks",
                },
                "holding": {"currentlyHeld": True},
                "research": {"rank": 2, "longTermResearchQualified": True, "longTermConvictionScore": 82, "evidenceGrade": "B"},
            },
            {
                "ticker": "QUAL",
                "existingEligibility": "existing-tracked-not-eligible",
                "taxonomy": {
                    "referenceStatus": "reference-covered",
                    "referenceFresh": True,
                    "sector": "Utilities",
                    "industry": "Utilities - Regulated Electric",
                    "economicExposure": "electric power and utilities",
                    "taxonomySource": "fixture",
                    "category": "Unclassified",
                },
                "holding": {"currentlyHeld": False},
                "research": {"rank": 1, "longTermResearchQualified": True, "longTermConvictionScore": 76, "evidenceGrade": "C"},
            },
        ]
    }


class InfernoTrackerRoleReviewTests(unittest.TestCase):
    """Protect the operator-only role and DCA-policy boundary."""

    def test_role_review_retains_every_registry_name_and_prioritizes_gaps(self) -> None:
        report = role_review.build_tracker_role_review(
            registry=registry(), operator_long_term_holds={"HOLD"}
        )

        self.assertEqual(report["coverage"]["trackedRows"], 3)
        self.assertEqual(report["coverage"]["referenceCoveredRows"], 2)
        self.assertEqual(report["coverage"]["referenceMissingRows"], 1)
        self.assertEqual([item["ticker"] for item in report["reviewQueue"]], ["MISS", "HOLD", "QUAL"])
        self.assertEqual(report["reviewQueue"][0]["reviewPriority"], "data-quality-repair")
        self.assertEqual(report["reviewQueue"][1]["reviewPriority"], "existing-hold-review")

    def test_existing_hold_declaration_is_context_not_an_addition_or_role_decision(self) -> None:
        report = role_review.build_tracker_role_review(
            registry=registry(), operator_long_term_holds={"HOLD"}
        )
        hold = next(item for item in report["reviewQueue"] if item["ticker"] == "HOLD")

        self.assertTrue(hold["existingContext"]["operatorDeclaredLongTermHold"])
        self.assertEqual(hold["operatorDecision"]["portfolioRole"], "not-recorded")
        self.assertEqual(hold["operatorDecision"]["dcaResearchInclusion"], "not-recorded")
        self.assertEqual(report["coverage"]["portfolioRoleDefinedRows"], 0)
        self.assertEqual(report["coverage"]["dcaResearchInclusionDefinedRows"], 0)

    def test_role_review_pins_research_only_and_no_weight_boundary(self) -> None:
        report = role_review.build_tracker_role_review(registry=registry(), operator_long_term_holds={"HOLD"})

        self.assertEqual(report["verdict"], "operator-role-review-required")
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["promotable"])
        self.assertFalse(report["authorityChanged"])
        self.assertFalse(report["brokerSubmitAllowed"])
        self.assertFalse(report["liveTradingAllowed"])
        self.assertFalse(report["authorityBoundary"]["operatorPolicyChanged"])
        self.assertFalse(report["nextBuildGate"]["readyForDcaWeightResearch"])

    def test_rendered_queue_explains_it_is_not_a_buy_list(self) -> None:
        rendered = role_review.tracker_role_review_text(
            role_review.build_tracker_role_review(registry=registry(), operator_long_term_holds={"HOLD"})
        )

        self.assertIn("not a ranking or buy list", rendered)
        self.assertIn("does not assign portfolio roles, DCA inclusion, target weights", rendered)
        self.assertIn("Broker submission and live trading remain disabled", rendered)


if __name__ == "__main__":
    unittest.main()
