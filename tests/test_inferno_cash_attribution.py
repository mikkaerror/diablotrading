from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import inferno_cash_attribution as cash_attribution


class InfernoCashAttributionTests(unittest.TestCase):
    """Verify cash reconciliation never fabricates realized trading profit."""

    def test_cash_decrease_stays_unattributed_without_transaction_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            data_dir.mkdir()
            reports_dir.mkdir()
            (data_dir / "inferno_live_account_sync.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-07-02T20:00:00-06:00",
                        "ok": True,
                        "verdict": "attention",
                        "accountDataSource": "schwab-account-api",
                        "matchedSuffix": "8499",
                        "totalCash": 0.0,
                        "netLiquidatingValue": 788.02,
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_schwab_account_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "inferno_deposit_plan.json").write_text(
                json.dumps(
                    {
                        "verdict": "configured",
                        "plan": {"amountDollars": 250.0, "intervalDays": 14, "firstDepositDate": "2026-07-03"},
                        "schedule": {"nextDepositDate": "2026-07-03", "daysUntilNextDeposit": 1},
                        "forecastWindows": {"30Days": {"grossDeposits": 750.0}},
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "nlv_history.csv").write_text(
                "\n".join(
                    [
                        "timestamp,date,nlv,cash",
                        "2026-06-26T00:35:41+00:00,2026-06-26,1481.79,599.93",
                        "2026-07-02T00:30:59+00:00,2026-07-01,850.14,0.00",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.object(cash_attribution, "CASH_ATTRIBUTION_FILE", data_dir / "inferno_cash_attribution.json"),
                patch.object(cash_attribution, "CASH_ATTRIBUTION_TEXT_FILE", reports_dir / "cash_attribution_latest.txt"),
                patch.object(cash_attribution, "LIVE_ACCOUNT_SYNC_FILE", data_dir / "inferno_live_account_sync.json"),
                patch.object(cash_attribution, "SCHWAB_ACCOUNT_SYNC_FILE", data_dir / "inferno_schwab_account_sync.json"),
                patch.object(cash_attribution, "DEPOSIT_PLAN_FILE", data_dir / "inferno_deposit_plan.json"),
                patch.object(cash_attribution, "NLV_HISTORY_FILE", data_dir / "nlv_history.csv"),
                patch.object(cash_attribution, "SCHWAB_TRANSACTION_LEDGER_FILE", data_dir / "schwab_transactions.csv"),
                patch.object(cash_attribution, "OPERATOR_CASH_EVENTS_FILE", data_dir / "operator_cash_events.csv"),
                patch.object(cash_attribution, "ensure_dirs", return_value=None),
            ):
                payload = cash_attribution.build_cash_attribution(
                    now=datetime.fromisoformat("2026-07-02T20:05:00-06:00")
                )

            self.assertEqual(payload["verdict"], "attribution-incomplete")
            self.assertEqual(payload["brokerCash"]["cash"], 0.0)
            self.assertEqual(payload["latestCashChange"]["deltaCash"], -599.93)
            self.assertEqual(
                payload["latestCashClassification"]["classification"],
                "cash-decrease-unattributed-without-transaction-ledger",
            )
            self.assertFalse(payload["realizedOptionsProfit"]["known"])
            self.assertTrue(payload["realizedOptionsProfit"]["neverInferFromCashChange"])
            self.assertFalse(payload["capitalTreatment"]["cashChangesCreateLiveAuthority"])
            rendered = (reports_dir / "cash_attribution_latest.txt").read_text(encoding="utf-8")
            self.assertIn("Never infer realized options profit", rendered)

    def test_cash_increase_near_schedule_is_likely_deposit_not_profit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            reports_dir = root / "reports"
            data_dir.mkdir()
            reports_dir.mkdir()
            (data_dir / "inferno_live_account_sync.json").write_text(
                json.dumps(
                    {
                        "generatedAt": "2026-07-03T08:00:00-06:00",
                        "ok": True,
                        "verdict": "healthy",
                        "accountDataSource": "schwab-account-api",
                        "matchedSuffix": "8499",
                        "totalCash": 250.0,
                        "netLiquidatingValue": 1038.02,
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "inferno_schwab_account_sync.json").write_text("{}", encoding="utf-8")
            (data_dir / "inferno_deposit_plan.json").write_text(
                json.dumps(
                    {
                        "verdict": "configured",
                        "plan": {"amountDollars": 250.0, "intervalDays": 14, "firstDepositDate": "2026-07-03"},
                        "schedule": {"nextDepositDate": "2026-07-03", "daysUntilNextDeposit": 0},
                        "forecastWindows": {"30Days": {"grossDeposits": 750.0}},
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "nlv_history.csv").write_text(
                "\n".join(
                    [
                        "timestamp,date,nlv,cash",
                        "2026-07-02T00:30:59+00:00,2026-07-02,788.02,0.00",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.object(cash_attribution, "CASH_ATTRIBUTION_FILE", data_dir / "inferno_cash_attribution.json"),
                patch.object(cash_attribution, "CASH_ATTRIBUTION_TEXT_FILE", reports_dir / "cash_attribution_latest.txt"),
                patch.object(cash_attribution, "LIVE_ACCOUNT_SYNC_FILE", data_dir / "inferno_live_account_sync.json"),
                patch.object(cash_attribution, "SCHWAB_ACCOUNT_SYNC_FILE", data_dir / "inferno_schwab_account_sync.json"),
                patch.object(cash_attribution, "DEPOSIT_PLAN_FILE", data_dir / "inferno_deposit_plan.json"),
                patch.object(cash_attribution, "NLV_HISTORY_FILE", data_dir / "nlv_history.csv"),
                patch.object(cash_attribution, "SCHWAB_TRANSACTION_LEDGER_FILE", data_dir / "schwab_transactions.csv"),
                patch.object(cash_attribution, "OPERATOR_CASH_EVENTS_FILE", data_dir / "operator_cash_events.csv"),
                patch.object(cash_attribution, "ensure_dirs", return_value=None),
            ):
                payload = cash_attribution.build_cash_attribution(
                    now=datetime.fromisoformat("2026-07-03T08:05:00-06:00")
                )

            self.assertEqual(payload["latestCashChange"]["deltaCash"], 250.0)
            self.assertEqual(
                payload["latestCashClassification"]["classification"],
                "likely-planned-deposit-confirmed-in-broker-cash",
            )
            self.assertFalse(payload["realizedOptionsProfit"]["known"])
            self.assertFalse(payload["plannedDeposit"]["plannedDepositsAreDeployable"])


if __name__ == "__main__":
    unittest.main()
