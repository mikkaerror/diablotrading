from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from inferno_dte_policy_analysis import build_dte_policy_analysis
from inferno_expectancy_ledger import build_expectancy_ledger
from inferno_portfolio_heat import build_portfolio_heat
from inferno_process_compliance import build_process_compliance
from inferno_trade_evidence import decision_card, is_long_vol, normalized_outcome
from inferno_trading_behavior_audit import build_trading_behavior_audit
from inferno_wheel_shadow import build_wheel_shadow


def closed_ticket(
    ticket_id: str,
    *,
    ticker: str = "XYZ",
    strategy: str = "CALL_DEBIT_SPREAD",
    pnl: float = 50.0,
    trade_date: str = "2026-05-01",
    reviewed_at: str = "2026-05-10T12:00:00-06:00",
    expiration: str = "2026-06-20",
) -> dict:
    return {
        "ticketId": ticket_id,
        "ticker": ticker,
        "strategy": strategy,
        "tradeDate": trade_date,
        "expiration": expiration,
        "entryLimit": 1.0,
        "estimatedMaxLoss": 100.0,
        "legs": [
            {"instruction": "BUY_TO_OPEN", "bid": 0.85, "ask": 0.95, "mid": 0.90},
            {"instruction": "SELL_TO_OPEN", "bid": 0.05, "ask": 0.15, "mid": 0.10},
        ],
        "outcome": {
            "status": "closed",
            "estimatedPnl": pnl,
            "reviewedAt": reviewed_at,
        },
    }


class TradeEvidenceTests(unittest.TestCase):
    def test_long_vol_card_requires_positive_forecast_edge(self) -> None:
        item = {
            "ticker": "XYZ",
            "price": 100.0,
            "ivRank": 25.0,
            "forecastRealizedMovePct": 8.0,
            "strikePlan": {
                "strategy": "LONG_STRADDLE",
                "estimatedDebit": 5.0,
                "estimatedMaxLoss": 500.0,
                "lowerBreakEven": 95.0,
                "upperBreakEven": 105.0,
                "liquidityNotes": [],
                "greekSummary": {
                    "netDelta": 0.0,
                    "netGamma": 0.1,
                    "netTheta": -0.2,
                    "netVega": 0.3,
                    "greeksComplete": True,
                },
            },
        }
        card = decision_card(item, account_nlv=5000)
        self.assertTrue(card["complete"])
        self.assertTrue(card["paperComparisonAllowed"])
        self.assertEqual(card["longVolHurdle"]["status"], "eligible-for-paper-comparison")

    def test_normalized_outcome_subtracts_modeled_friction(self) -> None:
        outcome = normalized_outcome(closed_ticket("t1"))
        self.assertEqual(outcome["grossR"], 0.5)
        self.assertLess(outcome["netREstimate"], outcome["grossR"])
        self.assertFalse(outcome["frictionRealized"])

    def test_plain_straddle_name_is_treated_as_long_vol(self) -> None:
        self.assertTrue(is_long_vol({"strategy": "Straddle"}))
        card = decision_card(
            {
                "ticker": "XYZ",
                "strategy": "Straddle",
                "price": 100,
                "ivRank": 20,
                "forecastRealizedMovePct": 15,
                "schwabOptions": {"atmImpliedMovePct": 0.12},
                "estimatedMaxLoss": 100,
                "greekSummary": {
                    "netDelta": 0,
                    "netGamma": 0.1,
                    "netTheta": -0.1,
                    "netVega": 0.2,
                    "greeksComplete": True,
                },
            }
        )
        self.assertEqual(card["profitPlan"][0], "review at +0.5R")

    def test_long_vol_high_premium_remains_shadow_only(self) -> None:
        item = {
            "ticker": "XYZ",
            "price": 100.0,
            "ivRank": 25.0,
            "forecastRealizedMovePct": 30.0,
            "daysUntilEarnings": 5,
            "schwabOptions": {"atmImpliedMovePct": 0.22, "atmSpreadPct": 0.10},
            "strikePlan": {
                "strategy": "LONG_STRADDLE",
                "estimatedMaxLoss": 500.0,
                "greekSummary": {
                    "netDelta": 0.0,
                    "netGamma": 0.1,
                    "netTheta": -0.2,
                    "netVega": 0.3,
                    "greeksComplete": True,
                },
            },
        }
        card = decision_card(item, account_nlv=5000)

        self.assertFalse(card["paperComparisonAllowed"])
        self.assertEqual(card["longVolHurdle"]["status"], "shadow-only-high-implied-move")
        self.assertIn(
            "implied-move-above-20pct",
            card["longVolHurdle"]["deskEvidenceGuards"],
        )

    def test_long_vol_size_guard_uses_account_nlv(self) -> None:
        item = {
            "ticker": "XYZ",
            "price": 100.0,
            "ivRank": 25.0,
            "forecastRealizedMovePct": 15.0,
            "schwabOptions": {"atmImpliedMovePct": 0.12, "atmSpreadPct": 0.10},
            "strikePlan": {
                "strategy": "LONG_STRADDLE",
                "estimatedMaxLoss": 1300.0,
                "greekSummary": {
                    "netDelta": 0.0,
                    "netGamma": 0.1,
                    "netTheta": -0.2,
                    "netVega": 0.3,
                    "greeksComplete": True,
                },
            },
        }
        card = decision_card(item, account_nlv=5000)

        self.assertFalse(card["paperComparisonAllowed"])
        self.assertIn("long-vol-size-above-25pct-nlv", card["missingFields"])


class AnalyticsControlTests(unittest.TestCase):
    def test_expectancy_keeps_paper_and_shadow_separate(self) -> None:
        payload = build_expectancy_ledger(
            paper={"items": [closed_ticket("p1")]},
            shadow={"items": [closed_ticket("s1", pnl=-50.0)]},
        )
        self.assertEqual(payload["counts"]["paper"], 1)
        self.assertEqual(payload["counts"]["shadow"], 1)
        self.assertFalse(any(row["promotionEvidenceEligible"] for row in payload["families"]))

    def test_dte_analysis_is_observational(self) -> None:
        payload = build_dte_policy_analysis(
            paper={"items": [closed_ticket("p1")]},
            shadow={"items": []},
        )
        self.assertTrue(payload["reviewAt21Dte"])
        self.assertFalse(payload["observationalExitComparison"]["causalClaimAllowed"])
        self.assertEqual(payload["counts"]["records"], 1)

    def test_behavior_flags_loser_holding_bias(self) -> None:
        winners = [
            closed_ticket(f"w{i}", ticker=f"W{i}", pnl=50, reviewed_at="2026-05-03T00:00:00-06:00")
            for i in range(3)
        ]
        losers = [
            closed_ticket(f"l{i}", ticker=f"L{i}", pnl=-50, reviewed_at="2026-05-20T00:00:00-06:00")
            for i in range(3)
        ]
        payload = build_trading_behavior_audit(
            paper={"items": winners + losers},
            shadow={"items": []},
            nlv_history={date(2026, 5, 1): 1000.0},
            decisions=[],
        )
        self.assertTrue(payload["dispositionEffect"]["watch"])
        self.assertEqual(payload["verdict"], "disposition-watch")

    def test_behavior_excludes_blocked_paper_tickets_from_turnover(self) -> None:
        blocked = closed_ticket("blocked")
        blocked["status"] = "paper-blocked"
        staged = closed_ticket("staged")
        staged["status"] = "paper-staged"
        payload = build_trading_behavior_audit(
            paper={"items": [blocked, staged]},
            shadow={"items": []},
            nlv_history={date(2026, 5, 1): 1000.0},
            decisions=[],
        )
        self.assertEqual(payload["turnover"]["days"][0]["capitalAtRiskDollars"], 100.0)


class RiskControlTests(unittest.TestCase):
    def test_process_breach_stops_new_entries(self) -> None:
        ledger = {
            "items": [
                {
                    "ticketId": "open-1",
                    "ticker": "XYZ",
                    "strategy": "CALL_DEBIT_SPREAD",
                    "status": "paper-staged",
                    "estimatedMaxLoss": 100,
                    "outcome": {"status": "open"},
                }
            ]
        }
        payload = build_process_compliance(ledger=ledger, mtm={})
        self.assertFalse(payload["newPaperEntriesAllowed"])
        self.assertEqual(payload["verdict"], "stop-new-paper-entries")

    def test_portfolio_heat_combines_related_miners(self) -> None:
        account = {
            "netLiquidatingValue": 1000,
            "positions": [
                {"symbol": "IREN", "assetType": "EQUITY", "markValue": 250},
                {"symbol": "HIVE", "assetType": "EQUITY", "markValue": 200},
            ],
        }
        payload = build_portfolio_heat(
            account=account,
            ledger={"items": []},
            director={},
            conviction={},
        )
        top = payload["themes"][0]
        self.assertEqual(top["theme"], "digital-infrastructure-miners")
        self.assertEqual(top["pctOfNlv"], 45.0)
        self.assertEqual(payload["verdict"], "high-theme-heat")

    def test_wheel_requires_share_lot_or_assignment_cash(self) -> None:
        account = {
            "totalCash": 600,
            "positions": [{"symbol": "HIVE", "assetType": "EQUITY", "qty": 50}],
        }
        options = {
            "generatedAt": "2026-06-22T00:00:00-06:00",
            "status": "ok",
            "rows": [
                {
                    "symbol": "HIVE",
                    "underlyingPrice": 4.25,
                    "contracts": [
                        {
                            "symbol": "HIVE_P4",
                            "putCall": "PUT",
                            "daysToExpiration": 35,
                            "expirationDate": "2026-07-17",
                            "strikePrice": 4.0,
                            "delta": -0.25,
                            "bid": 0.25,
                            "ask": 0.30,
                            "openInterest": 500,
                            "volume": 20,
                        }
                    ],
                }
            ]
        }
        with patch(
            "inferno_wheel_shadow.local_now",
            return_value=datetime(2026, 6, 22, 12, 0, tzinfo=ZoneInfo("America/Denver")),
        ):
            payload = build_wheel_shadow(account=account, options=options)
        row = payload["rows"][0]
        self.assertFalse(row["coveredCallEligible"])
        self.assertEqual(row["verdict"], "shadow-candidate")
        self.assertFalse(payload["paperStageAllowed"])


if __name__ == "__main__":
    unittest.main()
