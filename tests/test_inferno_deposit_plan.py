from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import inferno_deposit_plan as deposit_plan
from inferno_io import atomic_write_json


class InfernoDepositPlanTests(unittest.TestCase):
    """Keep deposit forecasts separate from deployable broker cash."""

    def test_build_deposit_plan_uses_saved_biweekly_plan_without_making_cash_deployable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            data_dir.mkdir()
            reports_dir.mkdir()
            files = {
                "DEPOSIT_PLAN_CONFIG_FILE": data_dir / "operator_deposit_plan.json",
                "DEPOSIT_PLAN_FILE": data_dir / "inferno_deposit_plan.json",
                "DEPOSIT_PLAN_TEXT_FILE": reports_dir / "deposit_plan_latest.txt",
                "LIVE_ACCOUNT_SYNC_FILE": data_dir / "inferno_live_account_sync.json",
                "SCHWAB_ACCOUNT_SYNC_FILE": data_dir / "inferno_schwab_account_sync.json",
            }
            atomic_write_json(
                files["DEPOSIT_PLAN_CONFIG_FILE"],
                {
                    "amountDollars": 250,
                    "intervalDays": 14,
                    "firstDepositDate": "2026-07-03",
                    "source": "operator-assumption",
                },
            )
            atomic_write_json(
                files["LIVE_ACCOUNT_SYNC_FILE"],
                {
                    "generatedAt": "2026-07-02T09:00:00-06:00",
                    "accountDataSource": "schwab-account-api",
                    "totalCash": 42.5,
                    "netLiquidatingValue": 900,
                },
            )
            now = datetime(2026, 7, 3, 9, 0, tzinfo=ZoneInfo("America/Denver"))
            with ExitStack() as stack:
                for name, path in files.items():
                    stack.enter_context(patch.object(deposit_plan, name, path))
                stack.enter_context(patch.object(deposit_plan, "ensure_dirs", return_value=None))
                payload = deposit_plan.build_deposit_plan(now=now)

            self.assertEqual(payload["verdict"], "configured")
            self.assertEqual(payload["plan"]["annualPlannedDollars"], 6500)
            self.assertEqual(payload["schedule"]["nextDepositDate"], "2026-07-03")
            self.assertEqual(payload["forecastWindows"]["30Days"]["grossDeposits"], 750)
            self.assertEqual(payload["forecastWindows"]["planYear"]["depositCount"], 26)
            self.assertEqual(payload["brokerCashSnapshot"]["cash"], 42.5)
            self.assertFalse(payload["capitalTreatment"]["plannedDepositsAreDeployable"])
            self.assertTrue(files["DEPOSIT_PLAN_TEXT_FILE"].exists())

    def test_save_plan_config_persists_operator_assumption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "operator_deposit_plan.json"
            with patch.object(deposit_plan, "DEPOSIT_PLAN_CONFIG_FILE", path), \
                 patch.object(deposit_plan, "ensure_dirs", return_value=None):
                payload = deposit_plan.save_plan_config(
                    amount_dollars=250,
                    interval_days=14,
                    first_deposit_date="2026-07-03",
                )

            self.assertEqual(payload["amountDollars"], 250)
            self.assertEqual(payload["intervalDays"], 14)
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
