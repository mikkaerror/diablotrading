from __future__ import annotations

import csv
import io
import unittest

import inferno_tracker_role_policy_packet as packet


def registry() -> dict:
    return {
        "entries": [
            {
                "ticker": "HOLD",
                "existingEligibility": "existing-eligible",
                "taxonomy": {
                    "companyName": "Holding Co",
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
                    "companyName": "Quality Co",
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


class InfernoTrackerRolePolicyPacketTests(unittest.TestCase):
    """Protect the blank worksheet handoff from becoming a policy import layer."""

    def test_packet_retains_every_ticker_with_only_blank_operator_fields(self) -> None:
        report = packet.build_tracker_role_policy_packet(registry=registry())

        self.assertEqual(report["verdict"], "blank-operator-entry-packet-ready")
        self.assertEqual(report["coverage"]["trackedRows"], 2)
        self.assertEqual(report["coverage"]["blankOperatorEntryRows"], 2)
        self.assertEqual(report["coverage"]["operatorDecisionRows"], 0)
        skeleton = report["blankPolicySkeleton"]
        self.assertEqual([item["ticker"] for item in skeleton["decisions"]], ["HOLD", "QUAL"])
        self.assertEqual(skeleton["operator"], "")
        self.assertEqual(skeleton["updatedAt"], "")
        for item in skeleton["decisions"]:
            self.assertEqual(item["portfolioRole"], "")
            self.assertEqual(item["dcaResearchInclusion"], "")
            self.assertEqual(item["rationale"], "")
            self.assertNotIn("targetWeight", item)

    def test_packet_keeps_source_context_but_no_decision_or_authority_change(self) -> None:
        report = packet.build_tracker_role_policy_packet(registry=registry())
        hold = next(item for item in report["rows"] if item["ticker"] == "HOLD")

        self.assertEqual(hold["reference"]["sector"], "Technology")
        self.assertTrue(hold["existingContext"]["currentlyHeld"])
        self.assertTrue(hold["researchContext"]["longTermResearchQualified"])
        self.assertTrue(report["researchOnly"])
        self.assertFalse(report["authorityChanged"])
        self.assertFalse(report["authorityBoundary"]["operatorDecisionsProduced"])
        self.assertFalse(report["authorityBoundary"]["operatorDecisionsImported"])
        self.assertFalse(report["authorityBoundary"]["targetWeightsAccepted"])
        self.assertFalse(report["operatorHandoff"]["packetCanBeImported"])

    def test_csv_has_all_context_and_blank_entry_columns_without_weight_column(self) -> None:
        report = packet.build_tracker_role_policy_packet(registry=registry())
        rows = list(csv.DictReader(io.StringIO(packet.packet_csv(report))))

        self.assertEqual([row["ticker"] for row in rows], ["HOLD", "QUAL"])
        self.assertEqual(rows[0]["sector"], "Technology")
        self.assertEqual(rows[0]["portfolio_role"], "")
        self.assertEqual(rows[0]["dca_research_inclusion"], "")
        self.assertEqual(rows[0]["rationale"], "")
        self.assertNotIn("target_weight", rows[0])

    def test_rendered_packet_says_manual_only_and_weight_free(self) -> None:
        rendered = packet.tracker_role_policy_packet_text(
            packet.build_tracker_role_policy_packet(registry=registry())
        )

        self.assertIn("Automatic import: False", rendered)
        self.assertIn("not policy input", rendered)
        self.assertIn("Do not add target weights here", rendered)
        self.assertIn("creates, infers, imports, and changes no operator decision", rendered)


if __name__ == "__main__":
    unittest.main()
