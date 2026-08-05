from __future__ import annotations

"""Regression checks for the manual daily model refresh wrapper."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run_inferno_daily_model_refresh.sh"


class DailyModelRefreshTests(unittest.TestCase):
    def test_schwab_oauth_failure_skips_only_schwab_steps(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("SCHWAB_READY=0", text)
        self.assertIn("LOCK_DIR=", text)
        self.assertIn("Advisory warning: Schwab OAuth preflight failed", text)
        self.assertIn(
            'run_advisory "tracker and morning model refresh" "$BACKTEST_PYTHON" inferno_dawn_pipeline.py --skip-email --refresh-prices',
            text,
        )
        self.assertIn('skip_schwab_step "Schwab option-chain tape"', text)
        self.assertIn('run_advisory "snapshot price overlay"', text)
        self.assertIn('run_advisory "research cycle"', text)
        self.assertIn('run_advisory "ticket cap policy" python3 inferno_ticket_cap_policy.py', text)
        self.assertIn('run_advisory "strategy alternative pricing" run_strategy_alternative_pricing --limit 6 --variants-per-ticker 3', text)
        self.assertIn('run_advisory "short premium study" python3 inferno_short_premium_study.py run', text)
        self.assertIn('run_advisory "paper test director" python3 inferno_paper_test_director.py build', text)
        self.assertIn('run_advisory "paper blocker swarm" python3 inferno_paper_blocker_swarm.py run', text)
        self.assertIn('run_advisory "paper bottleneck reducer" python3 inferno_paper_bottleneck_reducer.py build', text)
        self.assertIn('run_advisory "cash attribution" python3 inferno_cash_attribution.py', text)
        self.assertNotIn("python3 inferno_schwab_oauth.py ensure\n\nif", text)

    def test_deployed_refresh_avoids_workspace_shell_entrypoints(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("./run_inferno_", text)
        self.assertNotIn("./inferno ", text)
        self.assertIn("run_strategy_alternative_pricing()", text)
        self.assertIn("inferno_paper_variant_scanner.py run", text)

    def test_paper_selection_sync_follows_fresh_strategy_pricing(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        pricing = text.index('run_advisory "strategy alternative pricing"')
        shadow = text.index('run_advisory "strategy shadow comparison"')
        director = text.index('run_advisory "paper test director"')
        blocker = text.index('run_advisory "paper blocker swarm"')
        reducer = text.index('run_advisory "paper bottleneck reducer"')
        evidence_audit = text.index('run_advisory "paper evidence audit"')
        command_center = text.index('run_advisory "model command center"')
        doctor = text.index('run_advisory "doctor"')
        central_handoff = text.index('run_advisory "central handoff"')
        usage_handoff = text.index('run_advisory "usage handoff"')

        self.assertLess(pricing, shadow)
        self.assertLess(shadow, director)
        self.assertLess(director, blocker)
        self.assertLess(blocker, reducer)
        self.assertLess(reducer, evidence_audit)
        self.assertLess(evidence_audit, command_center)
        self.assertLess(command_center, doctor)
        self.assertLess(doctor, central_handoff)
        self.assertLess(central_handoff, usage_handoff)
        self.assertLess(reducer, command_center)

    def test_individual_schwab_read_failures_remain_advisory(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'run_advisory "Schwab account truth" python3 inferno_schwab_account_sync.py build --skip-refresh --quiet',
            text,
        )
        self.assertIn(
            'run_advisory "Schwab transaction ledger" python3 inferno_schwab_transaction_ledger.py build --skip-refresh --quiet',
            text,
        )
        self.assertIn(
            'run_advisory "Schwab option-chain tape" python3 inferno_schwab_daily_ops.py --skip-refresh --quiet',
            text,
        )
        self.assertIn(
            'run_advisory "Schwab price history" python3 inferno_schwab_price_history.py --from-snapshot --limit "$LIMIT" --skip-refresh --quiet',
            text,
        )

    def test_growth_stack_follows_fresh_cash_attribution(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")

        deposit_plan = text.index('run_advisory "deposit plan"')
        cash_attribution = text.index('run_advisory "cash attribution"')
        growth_stack = text.index('run_advisory "growth stack"')

        self.assertLess(deposit_plan, cash_attribution)
        self.assertLess(cash_attribution, growth_stack)
        self.assertIn(
            'run_advisory "Schwab-derived TOS metrics" python3 inferno_schwab_tos_metrics_sync.py --from-snapshot --limit "$LIMIT" --skip-refresh --quiet',
            text,
        )


if __name__ == "__main__":
    unittest.main()
