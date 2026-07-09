from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import inferno_market_mastery_plan as mastery


class InfernoMarketMasteryPlanTests(unittest.TestCase):
    def test_plan_prioritizes_fresh_data_and_negative_long_vol_evidence(self) -> None:
        now = datetime(2026, 6, 22, 8, 0, tzinfo=ZoneInfo("America/Denver"))
        payload = mastery.build_plan(
            {
                "schwabAccount": {
                    "generatedAt": "2026-06-20T19:20:00-06:00",
                    "sourceStatus": "ok",
                    "netLiquidatingValue": 1600,
                    "totalCash": 600,
                },
                "schwabOptions": {
                    "generatedAt": "2026-06-17T13:48:00-06:00",
                    "status": "ok",
                },
                "schwabPriceHistory": {
                    "generatedAt": "2026-06-19T13:59:00-06:00",
                    "status": "ok",
                },
                "paperExitAudit": {
                    "counts": {"closeNow": 2, "reviewToday": 1},
                },
                "expectedMove": {
                    "counts": {"closedLongVolRecords": 96},
                    "overall": {
                        "beatRate": 0.3125,
                        "meanMoveEdgePct": -11.4464,
                    },
                },
                "strategyLab": {"overall": {"scoredCount": 1}},
                "sizing": {
                    "currentSleeves": {"equityPct": 0.6248},
                    "optionsSizing": {"liveMaxLossDollars": 0},
                },
            },
            now=now,
        )

        by_id = {item["id"]: item for item in payload["tasks"]}
        self.assertEqual(by_id["M01"]["status"], "refresh-needed")
        self.assertIn("only restart OAuth", by_id["M01"]["action"])
        self.assertEqual(by_id["M02"]["status"], "action-now")
        self.assertEqual(by_id["M03"]["status"], "action-now")
        self.assertEqual(by_id["M05"]["status"], "action-now")
        self.assertFalse(payload["liveTradingAllowed"])
        self.assertFalse(payload["brokerSubmitAllowed"])
        self.assertEqual(len(payload["browserNextToDo"]), 8)
        self.assertIn("21-DTE exit is a cohort hypothesis", "\n".join(payload["claimCorrections"]))

    def test_fresh_account_clears_oauth_block(self) -> None:
        now = datetime(2026, 6, 22, 8, 0, tzinfo=ZoneInfo("America/Denver"))
        payload = mastery.build_plan(
            {
                "schwabAccount": {
                    "generatedAt": "2026-06-22T07:30:00-06:00",
                    "sourceStatus": "ok",
                },
                "schwabOptions": {
                    "generatedAt": "2026-06-22T07:30:00-06:00",
                    "status": "ok",
                },
                "schwabPriceHistory": {
                    "generatedAt": "2026-06-22T07:30:00-06:00",
                    "status": "ok",
                },
                "paperExitAudit": {"counts": {}},
                "expectedMove": {"counts": {}, "overall": {}},
                "strategyLab": {"overall": {}},
                "sizing": {"currentSleeves": {}, "optionsSizing": {}},
            },
            now=now,
        )
        by_id = {item["id"]: item for item in payload["tasks"]}
        self.assertEqual(by_id["M01"]["status"], "ready")
        self.assertEqual(by_id["M02"]["status"], "clear")

    def test_explicit_auth_failure_remains_oauth_block(self) -> None:
        now = datetime(2026, 6, 22, 8, 0, tzinfo=ZoneInfo("America/Denver"))
        payload = mastery.build_plan(
            {
                "schwabAccount": {
                    "generatedAt": "2026-06-22T07:30:00-06:00",
                    "sourceStatus": "reauthorization-required",
                    "message": "OAuth reauthorization required",
                },
                "schwabOptions": {
                    "generatedAt": "2026-06-22T07:30:00-06:00",
                    "status": "ok",
                },
                "schwabPriceHistory": {
                    "generatedAt": "2026-06-22T07:30:00-06:00",
                    "status": "ok",
                },
                "paperExitAudit": {"counts": {}},
                "expectedMove": {"counts": {}, "overall": {}},
                "strategyLab": {"overall": {}},
                "sizing": {"currentSleeves": {}, "optionsSizing": {}},
            },
            now=now,
        )
        by_id = {item["id"]: item for item in payload["tasks"]}
        self.assertEqual(by_id["M01"]["status"], "blocked-on-oauth")


if __name__ == "__main__":
    unittest.main()
