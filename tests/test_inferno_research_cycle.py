from __future__ import annotations

import unittest
from unittest.mock import patch

import inferno_research_cycle as research_cycle


class InfernoResearchCycleTests(unittest.TestCase):
    """Verify the aggregate research runner keeps the evidence lanes in order."""

    def test_build_research_cycle_aggregates_research_artifacts(self) -> None:
        shadow = {"overall": {"trackedCount": 34, "closedCount": 10, "avgReturnOnRisk": 0.74}}
        performance = {
            "deskVerdict": {"level": "evidence-building", "message": "Need more samples."},
            "closedMetrics": {"scoredCount": 0},
        }
        strategy_lab = {
            "deskVerdict": {"level": "insufficient-data", "message": "Need more scored tickets."},
            "overall": {"scoredCount": 0},
            "promotionCandidates": [],
        }
        replay = {
            "deskVerdictReplay": {"level": "watch", "message": "Shadow lane still exploratory."},
            "lab": {"overall": {"scoredCount": 10}},
            "promotionCandidatesReplay": ["LONG_STRADDLE"],
        }
        hypothesis_lab = {
            "totalHypotheses": 7,
            "topHypotheses": [{"id": "h1"}, {"id": "h2"}],
            "allHypotheses": [{"id": "h1"}],
        }
        ledger_report = {"totalHypotheses": 1, "trajectoryCounts": {"new": 1}}
        scenario_backtest = {
            "stage": "scenario-backtest-research-only",
            "scenarioCount": 12,
            "closedEvidenceCount": 2,
            "counts": {"verdictCounts": {"insufficient-data": 12}},
            "topFocus": [{"ticker": "MOD"}, {"ticker": "THR"}],
            "promotable": False,
        }

        with (
            patch.object(research_cycle, "build_shadow_evidence", return_value=shadow),
            patch.object(research_cycle, "save_shadow_evidence"),
            patch.object(research_cycle, "build_performance_analytics", return_value=performance),
            patch.object(research_cycle, "save_performance_analytics"),
            patch.object(research_cycle, "build_strategy_lab", return_value=strategy_lab),
            patch.object(research_cycle, "save_strategy_lab"),
            patch.object(research_cycle, "build_replay", return_value=replay),
            patch.object(research_cycle, "save_replay"),
            patch.object(research_cycle, "build_hypothesis_lab", return_value=hypothesis_lab),
            patch.object(research_cycle, "save_hypothesis_lab"),
            patch.object(research_cycle, "update_ledger", return_value={"hypotheses": {"h1": {}}}),
            patch.object(research_cycle, "build_ledger_report", return_value=ledger_report),
            patch.object(research_cycle, "save_ledger_report"),
            patch.object(research_cycle, "build_scenario_backtest", return_value=scenario_backtest),
            patch.object(research_cycle, "save_scenario_backtest"),
        ):
            report = research_cycle.build_research_cycle()

        self.assertEqual(report["verdict"], "research-refreshed")
        self.assertEqual(report["shadow"]["trackedCount"], 34)
        self.assertEqual(report["strategyReplay"]["promotionCandidates"], ["LONG_STRADDLE"])
        self.assertEqual(report["hypothesisLab"]["totalHypotheses"], 7)
        self.assertEqual(report["scenarioBacktest"]["scenarioCount"], 12)
        self.assertEqual(report["scenarioBacktest"]["closedEvidenceCount"], 2)
        self.assertFalse(report["scenarioBacktest"]["promotable"])
        self.assertEqual(report["scenarioBacktest"]["topFocusTickers"], ["MOD", "THR"])


if __name__ == "__main__":
    unittest.main()
