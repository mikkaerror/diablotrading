from __future__ import annotations

"""Tests for the research-only score calibration lab."""

import unittest
from copy import deepcopy

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
            },
            {
                "ticketId": "s2",
                "ticker": "DDD",
                "strategy": "IRON_CONDOR",
                "readiness": 77,
                "priorityScore": 64,
                "estimatedMaxLoss": 150,
                "outcome": {
                    "status": "open",
                },
            },
        ],
    }


class ScoreCalibrationTests(unittest.TestCase):
    """Calibration output should stay descriptive and authority-safe."""

    def test_frozen_entry_scores_outrank_refreshed_and_missing_is_not_backfilled(self) -> None:
        ledger = shadow_ledger()
        ledger["items"][0].update({
            "readiness": 99, "priorityScore": 9,
            "entryScoreSnapshotVersion": 1,
            "entryScoreSnapshot": {"readiness": 62, "priorityScore": None},
        })
        original = deepcopy(ledger)
        rows = calibration.option_score_rows(paper_ledger={}, shadow_ledger=ledger)
        self.assertEqual(rows[0]["readiness"], 62)
        self.assertNotIn("priorityScore", rows[0])
        self.assertEqual(rows[0]["scoreProvenance"], "entry-frozen")
        self.assertEqual(ledger, original)

    def test_priority_native_rank_quartiles_keep_ties_and_out_of_range_values(self) -> None:
        rows = [{"priorityScore": value, "resultClass": "neutral", "r": 0}
                for value in [-5, -5, 2, 2, 7, 7, 140, 140]]
        table = calibration.calibration_table(rows, "priorityScore", lane="shadow-options")
        self.assertEqual(table["bucketCount"], 4)
        self.assertEqual([b["sampleCount"] for b in table["buckets"]], [2, 2, 2, 2])
        self.assertEqual(table["buckets"][-1]["scoreMean"], 140)
        tied = calibration.calibration_table([rows[0]] * 40, "priorityScore", lane="shadow-options")
        self.assertEqual(tied["bucketCount"], 1)
        self.assertEqual(tied["verdict"], "single-bucket-watch")

    def test_rank_verdict_does_not_compare_score_to_win_probability(self) -> None:
        rows = [{"readiness": score, "resultClass": "unfavorable", "r": -0.1}
                for score in [85] * 20 + [95] * 20]
        table = calibration.calibration_table(rows, "readiness", lane="paper-options")
        self.assertEqual(table["verdict"], "calibration-building")
        self.assertIsNone(table["weightedAbsCalibrationGap"])
        self.assertTrue(all(b["favorableGapVsScoreMidpoint"] is None for b in table["buckets"]))

    def test_option_rank_inversion_uses_payoff_not_hit_rate(self) -> None:
        rows = ([{"readiness": 85, "resultClass": "favorable", "r": 2}] * 20
                + [{"readiness": 95, "resultClass": "favorable", "r": 0.1}] * 20)
        table = calibration.calibration_table(rows, "readiness", lane="paper-options")
        self.assertEqual(table["verdict"], "calibration-watch")
        self.assertEqual(table["monotonicViolations"][0]["metric"], "meanR")

    def test_nonfinite_and_boolean_values_cannot_become_scores_or_outcomes(self) -> None:
        for value in [float("nan"), float("inf"), "-inf", "nan", True, False]:
            self.assertIsNone(calibration.score_value(value, "readiness"))
            self.assertIsNone(calibration.score_value(value, "priorityScore"))
            self.assertIsNone(calibration.option_r({"outcome": {"estimatedReturnOnRisk": value}}))

    def test_sources_and_repeated_exposures_do_not_become_independent_evidence(self) -> None:
        item = {"ticker": "AAA", "expiration": "2026-06-19", "readiness": 88,
                "outcome": {"status": "closed", "estimatedReturnOnRisk": -1,
                            "reviewedAt": "2026-06-19T08:00:00+00:00"}}
        payload = calibration.build_score_calibration(
            scenario_evidence={}, paper_ledger={"items": [item]},
            shadow_ledger={"items": [item] * 40},
        )
        source_tables = {t["lane"]: t for t in payload["optionCalibrationBySource"] if t["field"] == "readiness"}
        self.assertEqual(source_tables["paper-options"]["sampleCount"], 1)
        self.assertEqual(source_tables["paper-options"]["verdict"], "insufficient-data")
        diagnostics = payload["evidenceDiagnostics"]
        self.assertEqual(diagnostics["exposureGroups"], 2)
        self.assertEqual(diagnostics["repeatedExposureRows"], 39)
        self.assertEqual(diagnostics["shadowTimingRows"]["closed-before-expiration-session"], 40)
        self.assertFalse(diagnostics["modelFitAllowed"])

    def test_shadow_timing_does_not_invent_verified_settlement(self) -> None:
        base = {"source": "shadow", "expiration": "2026-06-19"}
        for timestamp in ["2026-06-19T09:29:59-04:00", "2026-06-18T23:59:00-04:00"]:
            self.assertEqual(calibration.shadow_timing_status({**base, "reviewedAt": timestamp}), "closed-before-expiration-session")
        for timestamp in ["2026-06-19T09:30:00-04:00", "2026-06-20T17:00:00-04:00", "2026-06-19T01:00:00", "bad"]:
            self.assertEqual(calibration.shadow_timing_status({**base, "reviewedAt": timestamp}), "unverified-settlement-time")

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
        self.assertEqual(payload["counts"]["optionEntryRecords"], 2)
        self.assertEqual(payload["counts"]["optionEntryScoreRows"], 2)
        self.assertEqual(payload["counts"]["openOptionEntryScoreRows"], 1)
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
        self.assertIn("current option entries carrying scores", rendered)
        self.assertIn("research-only", rendered)
        self.assertIn("Scores are ranking surfaces", rendered)


if __name__ == "__main__":
    unittest.main()
