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
        self.assertIn("./run_inferno_dawn_cycle.sh --skip-email --refresh-prices", text)
        self.assertIn('skip_schwab_step "Schwab option-chain tape"', text)
        self.assertIn('run_advisory "snapshot price overlay"', text)
        self.assertIn('run_advisory "research cycle"', text)
        self.assertIn('run_advisory "ticket cap policy" python3 inferno_ticket_cap_policy.py', text)
        self.assertIn("./run_inferno_strategy_alternative_pricing.sh --limit 6 --variants-per-ticker 3", text)
        self.assertIn('run_advisory "short premium study" python3 inferno_short_premium_study.py run', text)
        self.assertIn('run_advisory "cash attribution" python3 inferno_cash_attribution.py', text)
        self.assertNotIn("python3 inferno_schwab_oauth.py ensure\n\nif", text)


if __name__ == "__main__":
    unittest.main()
