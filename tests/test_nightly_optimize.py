from __future__ import annotations

"""Regression checks for the research-only nightly orchestration order."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "nightly_optimize.sh"


class NightlyOptimizeTests(unittest.TestCase):
    """Keep evidence summaries downstream of the bounded evidence loop."""

    def test_evidence_goal_loop_precedes_summary_recomputes(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        goal_loop = text.index('run_step "evidence goal loop"')
        performance = text.index('run_step "performance analytics"')
        strategy = text.index('run_step "strategy lab"')
        velocity = text.index('run_step "paper velocity"')

        self.assertLess(goal_loop, performance)
        self.assertLess(performance, strategy)
        self.assertLess(strategy, velocity)
        self.assertNotIn(
            'run_step "paper evidence harvest" ./run_inferno_paper_evidence_harvest.sh',
            text,
        )

    def test_nightly_loop_does_not_approve_or_stage_tickets(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("approval_queue.py approve", text)
        self.assertNotIn("paper_execution.py stage", text)
        self.assertNotIn("submit_live_order", text)

    def test_live_account_sync_uses_supported_cli(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"$PYTHON" inferno_live_account_sync.py', text)
        self.assertNotIn("inferno_live_account_sync.py --quiet", text)

    def test_nightly_refresh_preserves_schwab_snapshot_price_overlay(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        options = text.index('run_step "schwab options chain"')
        overlay = text.index('run_step "snapshot price overlay"')
        history = text.index('run_step "schwab price history"')

        self.assertLess(options, overlay)
        self.assertLess(overlay, history)

    def test_nightly_refresh_runs_short_premium_monitor(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        funnel = text.index('run_step "funnel diagnostic"')
        short_premium = text.index('run_step "short premium study"')
        mastery = text.index('run_step "market mastery plan"')

        self.assertLess(funnel, short_premium)
        self.assertLess(short_premium, mastery)

    def test_deployed_copy_can_use_repo_root(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('cd "${INFERNO_ROOT:-$(dirname "$0")}"', text)
        self.assertIn('RUN_LOG="${INFERNO_NIGHTLY_LOG:-data/nightly_optimize_run.log}"', text)


if __name__ == "__main__":
    unittest.main()
