from __future__ import annotations

"""Tests for score/threshold audit safety and conclusions."""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import inferno_score_threshold_audit as audit


def artifact_fixture() -> dict:
    return {
        "scoreCalibration": {
            "counts": {
                "closedScenarioObservations": 401,
                "closedOptionRecords": 146,
                "optionScoreRows": 0,
            },
            "scenarioCalibration": [
                {
                    "field": "scenarioScore",
                    "sampleCount": 401,
                    "monotonicViolations": [{"gap": 0.21}],
                },
                {
                    "field": "readiness",
                    "sampleCount": 401,
                    "monotonicViolations": [{"gap": 0.05}],
                },
            ],
        },
        "expectedMoveLedger": {
            "counts": {
                "closedLongVolRecords": 96,
                "currentMissingPriceOrPremium": 8,
            },
            "overall": {
                "beatRate": 0.3125,
                "meanMoveEdgePct": -11.45,
            },
        },
        "capitalScaling": {
            "inputs": {"netLiquidatingValue": 1477.29},
            "recommendation": {"recommendedCap": 25.0},
            "currentEnforced": {"singleTicketCap": 500.0},
        },
        "strategyAlternativePricing": {
            "counts": {"scannerCandidates": 4, "riskPassed": 3},
        },
        "paperVariantScanner": {
            "counts": {"pricingCandidates": 8},
        },
        "dtePolicyAnalysis": {
            "observational21DteComparison": {
                "closedAtOrAbove21Dte": {"scoredCount": 0},
                "closedBelow21Dte": {"scoredCount": 146},
            }
        },
    }


def sensitivity_fixture() -> dict:
    return {
        "promotedAnyUnder": [],
        "sourceLabGeneratedAt": "now",
    }


class ScoreThresholdAuditTests(unittest.TestCase):
    """The audit must be research-only and should not advise gate loosening."""

    def setUp(self) -> None:
        fixed_now = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)
        self.time_patch = patch("inferno_score_threshold_audit.local_now", return_value=fixed_now)
        self.time_patch.start()

    def tearDown(self) -> None:
        self.time_patch.stop()

    def test_build_audit_is_research_only_and_flags_core_findings(self) -> None:
        payload = audit.build_score_threshold_audit(
            artifacts=artifact_fixture(),
            production_sensitivity=sensitivity_fixture(),
            shadow_sensitivity=sensitivity_fixture(),
        )

        self.assertEqual(payload["verdict"], "calibrate-scores-do-not-loosen-gates")
        self.assertTrue(payload["researchOnly"])
        self.assertTrue(payload["diagnosticOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])

        titles = {item["title"] for item in payload["findings"]}
        self.assertIn("Score surfaces are not monotonic enough to treat as probabilities", titles)
        self.assertIn("Loosening promotion thresholds would not solve the current problem", titles)
        self.assertIn("Configured ticket cap is far above the account-size formula", titles)
        self.assertGreaterEqual(payload["counts"]["thresholdsCataloged"], 10)

    def test_render_makes_no_loosen_gate_recommendation_visible(self) -> None:
        payload = audit.build_score_threshold_audit(
            artifacts=artifact_fixture(),
            production_sensitivity=sensitivity_fixture(),
            shadow_sensitivity=sensitivity_fixture(),
        )

        rendered = audit.render_score_threshold_audit(payload)

        self.assertIn("Do not loosen promotion or risk gates", rendered)
        self.assertIn("optionScoreRows=0", rendered)
        self.assertIn("Authority: research-only; broker submit OFF; live trading OFF", rendered)
        self.assertIn("Threshold catalog", rendered)


if __name__ == "__main__":
    unittest.main()
