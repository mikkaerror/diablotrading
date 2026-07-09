from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import inferno_capital_launch_check as launch_check


class InfernoCapitalLaunchCheckTests(unittest.TestCase):
    """Verify launch checks surface deposits without treating forecasts as cash."""

    def test_build_capital_launch_check_includes_deposit_plan_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_file = root / "capital_launch_check.json"
            text_file = root / "capital_launch_check.txt"
            readiness = {
                "verdict": "not-ready",
                "message": "blocked",
                "deploymentDate": "2026-07-06",
                "deployableCashSource": "operator-argument",
                "guardrails": {
                    "deployableCash": 0.0,
                    "maxOptionsRisk": 0.0,
                    "maxStarterTicket": 0.0,
                    "maxLongTermBuy": 0.0,
                    "reserveCash": 0.0,
                },
                "blockers": ["Capital allocator has no deployable cash."],
                "warnings": [],
                "manualDeploymentAllowed": False,
                "autoLiveAllowed": False,
            }
            deposit = {
                "verdict": "configured",
                "message": "$250.00 every 14 days; planned deposits are forecast-only until broker cash confirms.",
                "plan": {"amountDollars": 250.0, "intervalDays": 14, "annualPlannedDollars": 6500.0},
                "schedule": {"nextDepositDate": "2026-07-03", "daysUntilNextDeposit": 0},
                "forecastWindows": {"30Days": {"depositCount": 3, "grossDeposits": 750.0}},
                "capitalTreatment": {"plannedDepositsAreDeployable": False},
                "brokerCashSnapshot": {"cash": 42.5},
            }
            cash_attribution = {
                "verdict": "attribution-incomplete",
                "message": "cash source attribution requires transaction history",
                "brokerCash": {"cash": 42.5},
                "latestCashChange": {"deltaCash": -250.0},
                "latestCashClassification": {
                    "classification": "cash-decrease-unattributed-without-transaction-ledger"
                },
                "realizedOptionsProfit": {"known": False},
                "capitalTreatment": {"cashChangesCreateLiveAuthority": False},
            }
            with (
                patch.object(launch_check, "CAPITAL_LAUNCH_CHECK_FILE", data_file),
                patch.object(launch_check, "CAPITAL_LAUNCH_CHECK_TEXT_FILE", text_file),
                patch.object(launch_check, "ensure_dirs", return_value=None),
                patch.object(launch_check, "build_live_account_sync", return_value={"verdict": "healthy", "matchedSuffix": "1234"}),
                patch.object(launch_check, "build_live_position_review", return_value={"verdict": "healthy", "counts": {}}),
                patch.object(launch_check, "build_capital_deployment_readiness", return_value=readiness),
                patch.object(launch_check, "build_review_packet", return_value={"verdict": "clear", "counts": {}}),
                patch.object(launch_check, "build_risk_gate_audit", return_value={"verdict": "clear", "summary": {"hardFails": 0, "passed": 12, "total": 12}, "gates": []}),
                patch.object(launch_check, "build_command_center", return_value={"generatedAt": "2026-07-02T09:00:00-06:00"}),
                patch.object(launch_check, "build_deposit_plan", return_value=deposit),
                patch.object(launch_check, "build_cash_attribution", return_value=cash_attribution),
                patch.object(launch_check, "approved_account_scope", return_value="account ending 1234"),
            ):
                payload = launch_check.build_capital_launch_check(deployable_cash=0.0, for_date="2026-07-06")

            self.assertEqual(payload["depositPlan"]["plan"]["amountDollars"], 250.0)
            self.assertFalse(payload["depositPlan"]["capitalTreatment"]["plannedDepositsAreDeployable"])
            rendered = text_file.read_text(encoding="utf-8")
            self.assertIn("Deposit plan", rendered)
            self.assertIn("Broker-confirmed cash: $42.50", rendered)
            self.assertIn("planned deposits are not deployable", rendered)
            self.assertIn("Cash attribution", rendered)
            self.assertIn("Realized options profit known: False", rendered)
            self.assertIn("cash changes are not option profit", rendered)


if __name__ == "__main__":
    unittest.main()
