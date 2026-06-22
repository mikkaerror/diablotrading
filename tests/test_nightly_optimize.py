from __future__ import annotations

"""Regression checks for the research-only nightly orchestration order."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "nightly_optimize.sh"


class NightlyOptimizeTests(unittest.TestCase):
    """Keep evidence summaries downstream of the evidence harvest."""

    def test_evidence_harvest_precedes_summary_recomputes(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        harvest = text.index('run_step "paper evidence harvest"')
        performance = text.index('run_step "performance analytics"')
        strategy = text.index('run_step "strategy lab"')
        velocity = text.index('run_step "paper velocity"')

        self.assertLess(harvest, performance)
        self.assertLess(performance, strategy)
        self.assertLess(strategy, velocity)

    def test_nightly_loop_does_not_approve_or_stage_tickets(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("approval_queue.py approve", text)
        self.assertNotIn("paper_execution.py stage", text)
        self.assertNotIn("submit_live_order", text)

    def test_live_account_sync_uses_supported_cli(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"$PYTHON" inferno_live_account_sync.py', text)
        self.assertNotIn("inferno_live_account_sync.py --quiet", text)

    def test_deployed_copy_can_use_repo_root(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('cd "${INFERNO_ROOT:-$(dirname "$0")}"', text)
        self.assertIn('RUN_LOG="${INFERNO_NIGHTLY_LOG:-data/nightly_optimize_run.log}"', text)


if __name__ == "__main__":
    unittest.main()
