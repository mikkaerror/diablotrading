from __future__ import annotations

"""Tests for the research-only score calibration lab."""

import unittest

import inferno_score_calibration as calibration


def scenario_evidence() -> dict:
    return {
        "observations": [
            {
                "observationId": "o1",
                "ticker": "AAA",
                "strategy": "CALL_DEBIT_SPREAD",
                "readiness": 92,
                "scenarioScore": 86,
                "outcome": {
                    "status": "closed",
                    "resultClass": "favorable",
                    "observationScore": 2.5,
                    "underlyingReturnPct": 2.5,
                },
            },
            {
                "observationId": "o2",
                "ticker": "BBB",
                "strategy": "LONG_STRADDLE",
                "readiness": 83,
                "scenarioScore": 74,
                "outcome": {
                    "status": "closed",
                    "resultClass": "neutral",
                    "observationScore": 0.0,
                    "underlyingReturnPct": 0.2,
                },
            },
            {
                "observationId": "o3",
                "ticker": "CCC",
                "strategy": "CALL_DEBIT_SPREAD",
                "readiness": 63,
                "scenarioScore": 58,
                "outcome": {
                    "status": "closed",
                    "resultClass": "unfavorable",
                    "observationScore": -1.8,
                    "underlyingReturnPct": -1.8,
                },
            },
            {
                "observationId": "open",
                "ticker": "DDD",
                "strategy": "CALL_DEBIT_SPREAD",
                "readiness": 99,
                "scenarioScore": 90,
                "outcome": {"status": "open"},
            },
        ],
    }


def shadow_ledger() -> dict:
    return {
        "items": [
            {
                "ticketId": "s1",
                "ticker": "AAA",
                "strategy": "CALL_DEBIT_SPREAD",
                "readiness": 88,
                "scenarioScore": 81,
                "estimatedMaxLoss": 100,
                "outcome": {
                    "status": "closed",
                    "estimatedPnl": 35,
                },
            }
        ],
    }


class ScoreCalibrationTests(unittest.TestCase):
    """Calibration output should stay descriptive and authority-safe."""

    def test_build_score_calibration_buckets_closed_observations(self) -> None:
        payload = calibration.build_score_calibration(
            scenario_evidence=scenario_evidence(),
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
        )

        self.assertTrue(payload["researchOnly"])
        self.assertTrue(payload["diagnosticOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertEqual(payload["counts"]["closedScenarioObservations"], 3)
        scenario_score = next(
            table
            for table in payload["scenarioCalibration"]
            if table["field"] == "scenarioScore"
        )
        self.assertEqual(scenario_score["sampleCount"], 3)
        self.assertEqual([bucket["bucket"] for bucket in scenario_score["buckets"]], ["50-59", "70-79", "80-89"])
        top_bucket = scenario_score["buckets"][-1]
        self.assertEqual(top_bucket["favorableCount"], 1)
        self.assertEqual(top_bucket["favorableRate"], 1.0)

    def test_option_score_rows_preserve_r_unit_outcomes(self) -> None:
        payload = calibration.build_score_calibration(
            scenario_evidence=scenario_evidence(),
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
        )

        option_score = next(
            table
            for table in payload["optionCalibration"]
            if table["field"] == "scenarioScore"
        )
        self.assertEqual(option_score["sampleCount"], 1)
        self.assertEqual(option_score["buckets"][0]["meanR"], 0.35)

    def test_text_report_renders_core_sections(self) -> None:
        payload = calibration.build_score_calibration(
            scenario_evidence=scenario_evidence(),
            paper_ledger={"items": []},
            shadow_ledger=shadow_ledger(),
        )
        rendered = calibration.score_calibration_text(payload)

        self.assertIn("Inferno Score Calibration Lab", rendered)
        self.assertIn("Scenario observation calibration", rendered)
        self.assertIn("research-only", rendered)
        self.assertIn("Scores are ranking surfaces", rendered)


if __name__ == "__main__":
    unittest.main()
