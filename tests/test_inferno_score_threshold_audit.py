from __future__ import annotations

"""Tests for score/threshold audit safety and conclusions."""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
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


class GateSelectivityTests(unittest.TestCase):
    """The selectivity check must flag a fixed gate that drifts from the
    intended top-percentile band, and stay quiet when it is aligned."""

    def test_loose_gate_is_flagged(self) -> None:
        # Universe 60..80; a gate of 72 sits near the 60th percentile (admits
        # ~40%) while intent is the top 20%.
        values = [60 + i * 0.2 for i in range(100)]
        findings = audit.gate_selectivity_findings(
            readiness_values=values, gate=72, intended_percentile=80
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "P2")
        self.assertIn("looser", findings[0]["title"])

    def test_aligned_gate_not_flagged(self) -> None:
        # Universe 0..89; a gate of 72 admits ~the top 20%, matching intent.
        values = [i * 0.9 for i in range(100)]
        findings = audit.gate_selectivity_findings(
            readiness_values=values, gate=72, intended_percentile=80
        )
        self.assertEqual(findings, [])

    def test_too_strict_gate_is_flagged(self) -> None:
        # Gate so high it admits almost nothing vs an intended top 20%.
        values = [i * 0.9 for i in range(100)]
        findings = audit.gate_selectivity_findings(
            readiness_values=values, gate=88, intended_percentile=80
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("stricter", findings[0]["title"])

    def test_thin_sample_is_skipped(self) -> None:
        findings = audit.gate_selectivity_findings(
            readiness_values=[80, 85, 90], gate=72, intended_percentile=80
        )
        self.assertEqual(findings, [])


class SpreadLiquidityConsistencyTests(unittest.TestCase):
    """The spread/liquidity mismatch check must fire only when a name clears
    the spread gate yet the liquidity model rejects it — using the system's
    own emitted flags, with no false alarms."""

    def test_mismatch_is_flagged(self) -> None:
        rows = [{"symbol": "MEI", "atmSpreadPct": 0.177,
                 "qualityFlags": ["thin-atm-liquidity", "no-liquid-contracts"]}]
        findings = audit.spread_liquidity_consistency_findings(rows=rows)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "P2")
        self.assertIn("MEI", findings[0]["evidence"])

    def test_wide_spread_name_not_flagged(self) -> None:
        # Already blocked by the spread gate -> no disagreement to report.
        rows = [{"symbol": "IREN", "atmSpreadPct": 0.98,
                 "qualityFlags": ["wide-atm-spread", "thin-atm-liquidity"]}]
        self.assertEqual(audit.spread_liquidity_consistency_findings(rows=rows), [])

    def test_clean_name_not_flagged(self) -> None:
        rows = [{"symbol": "OK", "atmSpreadPct": 0.08, "qualityFlags": []}]
        self.assertEqual(audit.spread_liquidity_consistency_findings(rows=rows), [])

    def test_empty_rows_not_flagged(self) -> None:
        self.assertEqual(audit.spread_liquidity_consistency_findings(rows=[]), [])


class ConstantDriftScanTests(unittest.TestCase):
    """The drift scanner should flag literal duplicates but treat aliases as
    single-sourced definitions."""

    def test_alias_definition_is_not_counted_as_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inferno_math_config.py").write_text(
                "TEST_LIMIT = 0.42\n", encoding="utf-8"
            )
            (root / "inferno_strategy_lab.py").write_text(
                "TEST_LIMIT = SHARED_TEST_LIMIT\n", encoding="utf-8"
            )

            findings = audit.constant_drift_findings(root=root, names=("TEST_LIMIT",))

        self.assertEqual(findings, [])

    def test_literal_duplicate_is_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "inferno_a.py").write_text("TEST_LIMIT = 0.42\n", encoding="utf-8")
            (root / "inferno_b.py").write_text("TEST_LIMIT = 0.42\n", encoding="utf-8")

            findings = audit.constant_drift_findings(root=root, names=("TEST_LIMIT",))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "P2")


if __name__ == "__main__":
    unittest.main()
