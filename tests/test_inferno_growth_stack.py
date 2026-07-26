from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import inferno_growth_stack as growth_stack
import inferno_doctor as doctor


class GrowthStackTests(unittest.TestCase):
    """Protect the deposit/account layering math and its authority boundary."""

    def setUp(self) -> None:
        self.now = datetime(2026, 7, 21, 9, 0, tzinfo=ZoneInfo("America/Denver"))
        self.inputs = {
            "liveAccount": {
                "generatedAt": "2026-07-21T08:00:00-06:00",
                "accountDataSource": "schwab-account-api",
                "netLiquidatingValue": 1_000.0,
            },
            "schwabAccount": {},
            "cashAttribution": {
                "generatedAt": "2026-07-21T08:02:00-06:00",
                "verdict": "attribution-incomplete",
                "brokerCash": {"cash": 0.0},
                "latestCashChange": {"deltaCash": -25.0},
                "latestCashClassification": {"classification": "cash-decrease-unattributed-without-transaction-ledger"},
                "realizedOptionsProfit": {"known": False},
            },
            "depositPlan": {
                "generatedAt": "2026-07-21T08:01:00-06:00",
                "verdict": "configured",
                "plan": {
                    "amountDollars": 250.0,
                    "intervalDays": 14,
                    "source": "operator-assumption",
                },
                "schedule": {"nextDepositDate": "2026-07-31"},
            },
        }

    def test_growth_stack_layers_scheduled_contributions_and_return_assumptions(self) -> None:
        payload = growth_stack.build_growth_stack(self.inputs, now=self.now)

        self.assertEqual(payload["verdict"], "forecast-ready")
        self.assertEqual(payload["depositPlan"]["forecastYearDepositCount"], 26)
        self.assertEqual(payload["depositPlan"]["forecastYearContributions"], 6_500.0)
        self.assertEqual(payload["projections"][0]["endingBalance"], 7_500.0)
        self.assertGreater(payload["projections"][-1]["endingBalance"], 7_500.0)
        self.assertEqual(payload["layeredMath"]["contributionToBaseEightPctReturnRatio"], 81.25)
        self.assertEqual(payload["cashAttribution"]["verdict"], "attribution-incomplete")
        self.assertEqual(payload["cashAttribution"]["latestDeltaCash"], -25.0)
        self.assertFalse(payload["cashAttribution"]["realizedOptionsProfitKnown"])
        self.assertFalse(payload["cashAttribution"]["plannedDepositsAreDeployable"])
        self.assertFalse(payload["layeredMath"]["plannedDepositsAreDeployable"])
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertFalse(payload["liveTradingAllowed"])

    def test_missing_plan_fails_closed_without_an_invented_deposit_schedule(self) -> None:
        payload = growth_stack.build_growth_stack(
            {"liveAccount": self.inputs["liveAccount"], "schwabAccount": {}, "depositPlan": {}, "cashAttribution": {}},
            now=self.now,
        )

        self.assertEqual(payload["verdict"], "missing-deposit-plan")
        self.assertEqual(payload["depositPlan"]["forecastYearContributions"], 0.0)
        self.assertIn("Deposit-plan artifact is missing", " ".join(payload["warnings"]))
        self.assertFalse(payload["layeredMath"]["plannedDepositsAreDeployable"])

    def test_observed_nlv_trend_never_becomes_a_return_claim_without_cash_attribution(self) -> None:
        payload = growth_stack.build_growth_stack(
            {
                **self.inputs,
                "nlvHistory": [
                    {
                        "source": "nlv-history",
                        "timestamp": "2026-06-21T08:00:00-06:00",
                        "date": "2026-06-21",
                        "netLiquidatingValue": 800.0,
                    }
                ],
            },
            now=self.now,
        )

        progress = payload["observedProgress"]
        self.assertEqual(progress["verdict"], "observed-nlv-change-unattributed")
        self.assertEqual(progress["observedNlvDeltaDollars"], 200.0)
        self.assertEqual(progress["observedNlvChangePct"], 25.0)
        self.assertEqual(progress["returnAttribution"], "withheld")
        self.assertFalse(progress["safeForPerformanceClaim"])

    def test_short_horizon_windows_are_explicitly_unattributed_and_non_executable(self) -> None:
        payload = growth_stack.build_growth_stack(
            {
                **self.inputs,
                "nlvHistory": [
                    {"date": "2026-06-21", "netLiquidatingValue": 800.0},
                    {"date": "2026-07-14", "netLiquidatingValue": 900.0},
                    {"date": "2026-07-20", "netLiquidatingValue": 975.0},
                ],
            },
            now=self.now,
        )

        windows = payload["observedProgress"]["shortHorizonWindows"]
        self.assertEqual([row["windowDays"] for row in windows], [1, 7, 30])
        self.assertEqual([row["actualSpanDays"] for row in windows], [1, 7, 30])
        self.assertEqual([row["observedNlvDeltaDollars"] for row in windows], [25.0, 100.0, 200.0])
        self.assertEqual([row["observedNlvChangePct"] for row in windows], [2.56, 11.11, 25.0])
        self.assertTrue(all(row["returnAttribution"] == "withheld" for row in windows))
        self.assertTrue(all(row["safeForPerformanceClaim"] is False for row in windows))
        self.assertTrue(all(row["availableToExecution"] is False for row in windows))
        with patch.object(doctor, "local_now", return_value=self.now):
            self.assertTrue(doctor.growth_stack_status(payload)[0])

            windows[0]["returnAttribution"] = "attributed"
            ok, detail = doctor.growth_stack_status(payload)
        self.assertFalse(ok)
        self.assertIn("research-only=False", detail)

    def test_save_writes_json_and_text(self) -> None:
        payload = growth_stack.build_growth_stack(self.inputs, now=self.now)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with (
                patch.object(growth_stack, "GROWTH_STACK_FILE", root / "growth.json"),
                patch.object(growth_stack, "GROWTH_STACK_TEXT_FILE", root / "growth.txt"),
                patch.object(growth_stack, "ensure_dirs", return_value=None),
            ):
                growth_stack.save_growth_stack(payload)

            report = (root / "growth.txt").read_text(encoding="utf-8")
            self.assertIn("Twelve-month layered projections", report)
            self.assertIn("Planned deposits remain forecast-only", report)
            self.assertIn("Cash attribution boundary", report)
            self.assertIn("Observed account progress", report)

    def test_doctor_rejects_a_growth_stack_that_treats_plans_as_cash(self) -> None:
        payload = growth_stack.build_growth_stack(self.inputs, now=self.now)
        with patch.object(doctor, "local_now", return_value=self.now):
            ok, _ = doctor.growth_stack_status(payload)
            self.assertTrue(ok)

            payload["layeredMath"]["plannedDepositsAreDeployable"] = True
            ok, detail = doctor.growth_stack_status(payload)
            self.assertFalse(ok)
            self.assertIn("research-only=False", detail)

            payload["layeredMath"]["plannedDepositsAreDeployable"] = False
            payload["observedProgress"]["safeForPerformanceClaim"] = True
            ok, detail = doctor.growth_stack_status(payload)
            self.assertFalse(ok)
            self.assertIn("research-only=False", detail)


if __name__ == "__main__":
    unittest.main()
