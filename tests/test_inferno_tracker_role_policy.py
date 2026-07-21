from __future__ import annotations

import unittest

import inferno_tracker_role_policy as policy_contract


def registry() -> dict:
    return {
        "entries": [
            {
                "ticker": "MISS",
                "taxonomy": {"referenceStatus": "reference-missing"},
            },
            {
                "ticker": "HOLD",
                "taxonomy": {"referenceStatus": "reference-covered"},
            },
            {
                "ticker": "QUAL",
                "taxonomy": {"referenceStatus": "reference-covered"},
            },
        ]
    }


def policy(decisions: list[dict]) -> dict:
    return {
        "version": 1,
        "operator": "human-reviewer",
        "updatedAt": "2026-07-21T00:00:00-06:00",
        "decisions": decisions,
    }


def decision(symbol: str, *, role: str = "core compounder", inclusion: str = "include-in-DCA-research") -> dict:
    return {
        "ticker": symbol,
        "portfolioRole": role,
        "dcaResearchInclusion": inclusion,
        "decisionAt": "2026-07-21T00:00:00-06:00",
        "decisionSource": "operator",
        "rationale": "Human-authored research policy rationale.",
    }


class InfernoTrackerRolePolicyTests(unittest.TestCase):
    """Protect the no-inference, no-weights policy contract boundary."""

    def test_missing_policy_preserves_every_tracker_name_as_pending(self) -> None:
        report = policy_contract.build_tracker_role_policy_contract(registry=registry())

        self.assertEqual(report["verdict"], "operator-policy-not-provided")
        self.assertEqual(report["coverage"]["trackedRows"], 3)
        self.assertEqual(report["coverage"]["validDecisionRows"], 0)
        self.assertEqual(report["coverage"]["pendingDecisionRows"], 3)
        self.assertEqual(report["coverage"]["pendingTickers"], ["HOLD", "MISS", "QUAL"])
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["authorityChanged"])
        self.assertFalse(report["authorityBoundary"]["operatorPolicyChanged"])
        self.assertFalse(report["authorityBoundary"]["targetWeightsAccepted"])

    def test_complete_human_policy_is_read_only_and_still_waits_for_reference_gap(self) -> None:
        report = policy_contract.build_tracker_role_policy_contract(
            registry=registry(),
            policy=policy(
                [
                    decision("MISS", role="exclude-from-DCA-research", inclusion="exclude-from-DCA-research"),
                    decision("HOLD", role="cyclical"),
                    decision("QUAL", role="thematic satellite"),
                ]
            ),
        )

        self.assertEqual(report["verdict"], "operator-policy-complete-reference-gap")
        self.assertEqual(report["coverage"]["validDecisionRows"], 3)
        self.assertEqual(report["coverage"]["pendingDecisionRows"], 0)
        self.assertEqual(report["coverage"]["referenceMissingRows"], 1)
        self.assertFalse(report["nextBuildGate"]["readyForRolePolicyIntegration"])
        self.assertTrue(report["operatorPolicyInput"]["readOnly"])
        self.assertFalse(report["authorityBoundary"]["eligibilityChanged"])
        self.assertFalse(report["authorityBoundary"]["purchasesProduced"])

    def test_target_weights_unknown_tickers_and_duplicates_are_rejected(self) -> None:
        invalid = policy(
            [
                {**decision("HOLD"), "targetWeight": 0.5},
                decision("HOLD"),
                decision("OUTSIDE"),
            ]
        )
        report = policy_contract.build_tracker_role_policy_contract(registry=registry(), policy=invalid)
        codes = {item["code"] for item in report["validationIssues"]}

        self.assertEqual(report["verdict"], "operator-policy-invalid")
        self.assertIn("target-weight-not-accepted", codes)
        self.assertIn("duplicate-ticker", codes)
        self.assertIn("ticker-not-in-tracker", codes)
        self.assertEqual(report["coverage"]["targetWeightDefinedRows"], 0)
        self.assertFalse(report["nextBuildGate"]["readyForDcaWeightResearch"])

    def test_rendered_report_is_not_an_allocation_or_buy_list(self) -> None:
        rendered = policy_contract.tracker_role_policy_text(
            policy_contract.build_tracker_role_policy_contract(registry=registry())
        )

        self.assertIn("all names remain retained", rendered)
        self.assertIn("does not assign weights, purchases, eligibility, or broker actions", rendered)
        self.assertIn("never creates or edits operator decisions", rendered)


if __name__ == "__main__":
    unittest.main()
