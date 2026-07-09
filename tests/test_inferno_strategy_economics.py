from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_strategy_economics as economics


class InfernoStrategyEconomicsTests(unittest.TestCase):
    def test_build_preserves_research_only_boundary_and_current_cost(self) -> None:
        payload = economics.build(sims=500)

        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertEqual(payload["assumptions"]["dataCostPerYear"], 1188.0)
        self.assertAlmostEqual(payload["assumptions"]["maxFeasibleEdgeR"], 0.1, places=3)
        self.assertIn("best feasible (+0.10R)", payload["scenarios"])

    def test_infeasible_edge_above_credit_cap_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            economics.win_magnitude_for_edge(0.20)

    def test_best_feasible_scenario_mean_tracks_requested_edge(self) -> None:
        result = economics.simulate(
            0.10,
            account=1100,
            risk_pct=0.05,
            events=50,
            sims=5000,
            seed=3,
        )

        self.assertAlmostEqual(result["meanAnnualPnl"], 275.0, delta=45.0)
        self.assertEqual(result["riskDollarsPerEvent"], 55.0)

    def test_save_strategy_economics_writes_json_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_file = Path(tmp) / "strategy.json"
            text_file = Path(tmp) / "strategy.txt"
            payload = economics.build(sims=100)

            with (
                patch("inferno_strategy_economics.DATA_FILE", data_file),
                patch("inferno_strategy_economics.TEXT_FILE", text_file),
            ):
                written = economics.save_strategy_economics(payload)

            self.assertEqual(written["data"], str(data_file))
            self.assertEqual(written["report"], str(text_file))
            self.assertIn("strategy-economics-research-only", data_file.read_text())
            self.assertIn("Pricing must be reverified before spend", text_file.read_text())


if __name__ == "__main__":
    unittest.main()
