from __future__ import annotations

"""Tests for the multi-cash capital scenario matrix."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_capital_scenario_matrix as matrix


def launch_payload(cash: float) -> dict:
    """Build a minimal blocked launch payload for tests."""
    return {
        "generatedAt": "2026-06-04T12:00:00-06:00",
        "deployableCash": cash,
        "deploymentDate": "2026-07-06",
        "verdict": "blocked",
        "message": "blocked",
        "manualDeploymentAllowed": False,
        "autoLiveAllowed": False,
        "capitalReadiness": {
            "guardrails": {
                "maxOptionsRisk": cash * 0.25,
                "maxStarterTicket": min(500, cash * 0.125),
                "maxLongTermBuy": cash * 0.4,
                "reserveCash": cash * 0.35,
            },
            "blockers": ["Live account sync is not healthy: attention."],
            "warnings": ["Paper evidence loop still needs 30 closed paper trade(s)."],
        },
        "riskGateAudit": {
            "verdict": "blocked",
            "summary": {"passed": 3, "total": 12},
        },
        "liveBook": {
            "verdict": "blocked",
            "counts": {"hardBlockers": 2, "warnings": 2},
            "requiredHumanDecisions": [
                {"symbol": "TE"},
                {"symbol": "CLSK"},
            ],
        },
    }


class CapitalScenarioMatrixTests(unittest.TestCase):
    """Protect the planning matrix from drifting away from launch checks."""

    def test_scenario_row_preserves_guardrails_and_decisions(self) -> None:
        row = matrix.scenario_row(launch_payload(3000))

        self.assertEqual(row["deployableCash"], 3000)
        self.assertEqual(row["maxOptionsRisk"], 750)
        self.assertEqual(row["maxStarterTicket"], 375)
        self.assertEqual(row["maxLongTermBuy"], 1200)
        self.assertEqual(row["reserveCash"], 1050)
        self.assertEqual(row["requiredHumanDecisionSymbols"], ["TE", "CLSK"])

    def test_build_matrix_persists_text_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_path = root / "matrix.json"
            text_path = root / "matrix.txt"

            with (
                patch.object(matrix, "CAPITAL_SCENARIO_MATRIX_FILE", json_path),
                patch.object(matrix, "CAPITAL_SCENARIO_MATRIX_TEXT_FILE", text_path),
                patch.object(matrix, "build_capital_launch_check", side_effect=lambda **kwargs: launch_payload(kwargs["deployable_cash"])),
            ):
                payload = matrix.build_capital_scenario_matrix(
                    deployable_cash_values=[3000, 5000],
                    for_date="2026-07-06",
                )

            self.assertEqual(payload["verdict"], "all-blocked")
            self.assertEqual(payload["scenarioCount"], 2)
            rendered = text_path.read_text(encoding="utf-8")
            self.assertIn("$3,000.00: blocked", rendered)
            self.assertIn("$5,000.00: blocked", rendered)
            self.assertIn("decisions TE, CLSK", rendered)
            self.assertTrue(json_path.exists())


if __name__ == "__main__":
    unittest.main()
