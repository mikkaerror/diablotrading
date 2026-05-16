from __future__ import annotations

"""Regression tests for the one-command capital launch check."""

import unittest

from inferno_capital_launch_check import launch_verdict, required_human_decisions


class CapitalLaunchCheckTests(unittest.TestCase):
    """Verify the launch cockpit collapses existing artifacts conservatively."""

    def test_launch_verdict_blocks_on_live_book_hard_blocker(self) -> None:
        result = launch_verdict(
            {"verdict": "manual-ready", "manualDeploymentAllowed": True},
            {"verdict": "clear", "summary": {"hardFails": 0}},
            {"counts": {"hardBlockers": 1}},
        )

        self.assertEqual(result["verdict"], "blocked")
        self.assertFalse(result["manualDeploymentAllowed"])

    def test_launch_verdict_allows_manual_ready_with_warnings(self) -> None:
        result = launch_verdict(
            {"verdict": "manual-ready-with-warnings", "manualDeploymentAllowed": True},
            {"verdict": "review", "summary": {"hardFails": 0}},
            {"counts": {"hardBlockers": 0}},
        )

        self.assertEqual(result["verdict"], "manual-ready-with-warnings")
        self.assertTrue(result["manualDeploymentAllowed"])

    def test_required_human_decisions_excludes_supported_positions(self) -> None:
        decisions = required_human_decisions(
            {
                "positions": [
                    {"symbol": "GDS", "unlockEffect": "hard-blocks-new-capital", "reviewHeat": 100},
                    {"symbol": "FLR", "unlockEffect": "does-not-block", "reviewHeat": 0},
                ]
            }
        )

        self.assertEqual([row["symbol"] for row in decisions], ["GDS"])


if __name__ == "__main__":
    unittest.main()
