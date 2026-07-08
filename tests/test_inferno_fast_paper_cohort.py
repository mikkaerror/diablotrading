from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

import inferno_fast_paper_cohort as fast


MOUNTAIN = ZoneInfo("America/Denver")
NOW = datetime(2026, 6, 18, 18, 0, tzinfo=MOUNTAIN)


def candidate(ticker: str, strategy: str, loss: float, score: int = 4) -> dict:
    return {
        "ticker": ticker,
        "strategy": strategy,
        "maxLoss": loss,
        "bootstrapScore": score,
        "readiness": 90,
        "failedGates": ["dteOk"],
        "item": {
            "ticker": ticker,
            "setupRec": "Straddle",
            "generatedAt": NOW.isoformat(),
            "price": 100,
            "daysUntilEarnings": 30,
            "riskVerdict": {"passed": True, "blocks": [], "metrics": {"maxLossDollars": loss}},
            "strikePlan": {
                "strategy": strategy,
                "expiration": "2026-07-17",
                "estimatedDebit": loss / 100,
                "estimatedMaxLoss": loss,
                "estimatedMaxProfit": "uncapped",
                "legs": [
                    {
                        "symbol": f"{ticker}C",
                        "instruction": "BUY_TO_OPEN",
                        "bid": 1.0,
                        "ask": loss / 100,
                        "mid": 1.5,
                    }
                ],
            },
        },
    }


def strike_item(ticker: str, strategy: str, loss: float) -> dict:
    item = candidate(ticker, strategy, loss)["item"]
    return {**item, "ok": True}


def bootstrap(tickers: list[tuple[str, int]]) -> dict:
    return {
        "proposals": [
            {
                "ticker": ticker,
                "score": score,
                "readiness": 90,
                "failedGates": [],
                "liveQualityYet": False,
            }
            for ticker, score in tickers
        ]
    }


class MarketCalendarTests(unittest.TestCase):
    def test_juneteenth_and_weekend_roll_to_monday(self) -> None:
        self.assertFalse(fast.is_market_session(date(2026, 6, 19)))
        self.assertEqual(fast.next_market_session(date(2026, 6, 18)), date(2026, 6, 22))


class SlateSelectionTests(unittest.TestCase):
    def test_maximizes_count_inside_daily_risk_cap(self) -> None:
        candidates = [
            candidate("A", "LONG_STRANGLE", 469, 4),
            candidate("B", "LONG_STRANGLE", 440, 4),
            candidate("C", "LONG_STRADDLE", 370, 4),
            candidate("D", "CALL_DEBIT_SPREAD", 80, 3),
            candidate("E", "CALL_DEBIT_SPREAD", 260, 3),
        ]
        selected = fast.choose_daily_slate(candidates, capacity=5, daily_risk_cap=1500)
        self.assertEqual(len(selected), 4)
        self.assertLessEqual(sum(item["maxLoss"] for item in selected), 1500)
        self.assertGreaterEqual(len({item["strategy"] for item in selected}), 2)

    def test_fast_entries_are_never_promotion_eligible(self) -> None:
        entry = fast.build_fast_entry(candidate("A", "LONG_STRANGLE", 400), now=NOW)
        self.assertFalse(entry["promotionEligible"])
        self.assertFalse(entry["promotable"])
        self.assertFalse(entry["liveTradingAllowed"])
        self.assertFalse(entry["brokerSubmitAllowed"])
        self.assertEqual(entry["evidenceCohort"], "exploratory-fast")

    def test_same_day_cycle_tops_off_inside_remaining_daily_cap(self) -> None:
        existing = fast.build_fast_entry(candidate("A", "LONG_STRANGLE", 1400), now=NOW)
        ledger = {"items": [existing]}
        payload, updated = fast.build_fast_paper_cohort(
            now=NOW,
            ledger_override=ledger,
            bootstrap_override=bootstrap([("B", 5), ("C", 4)]),
            strike_plan_override={
                "items": [
                    strike_item("B", "CALL_DEBIT_SPREAD", 80),
                    strike_item("C", "LONG_STRANGLE", 160),
                ]
            },
            target_trades=5,
        )

        self.assertEqual(payload["counts"]["selectedToday"], 1)
        self.assertEqual(payload["selectedSlate"][0]["ticker"], "B")
        self.assertEqual(payload["riskBudget"]["openedTodayMaxLoss"], 1400.0)
        self.assertEqual(payload["riskBudget"]["remainingDailyMaxLoss"], 100.0)
        self.assertEqual(len(fast.open_items(updated)), 2)
        self.assertTrue(all(not item["promotionEligible"] for item in payload["selectedSlate"]))

    def test_backlog_keeps_priceable_candidates_that_do_not_fit_today(self) -> None:
        existing = fast.build_fast_entry(candidate("A", "LONG_STRANGLE", 1450), now=NOW)
        payload, updated = fast.build_fast_paper_cohort(
            now=NOW,
            ledger_override={"items": [existing]},
            bootstrap_override=bootstrap([("B", 5)]),
            strike_plan_override={"items": [strike_item("B", "LONG_STRANGLE", 120)]},
            target_trades=5,
        )

        self.assertEqual(payload["counts"]["selectedToday"], 0)
        self.assertEqual([item["ticker"] for item in payload["backlogSlate"]], ["B"])
        self.assertEqual(payload["backlogSlate"][0]["promotionEligible"], False)
        self.assertEqual(len(fast.open_items(updated)), 1)


class ExitTests(unittest.TestCase):
    def test_conservative_exit_uses_bid_for_long_and_ask_for_short(self) -> None:
        mark = {
            "perLeg": [
                {"instruction": "BUY_TO_OPEN", "currentBid": 3.0, "currentAsk": 3.2},
                {"instruction": "SELL_TO_OPEN", "currentBid": 1.0, "currentAsk": 1.2},
            ]
        }
        self.assertEqual(fast.conservative_exit_value(mark), 180.0)

    def test_due_ticket_waits_for_later_session_quote(self) -> None:
        entry = fast.build_fast_entry(candidate("A", "LONG_STRANGLE", 400), now=NOW)
        ledger = {"items": [entry]}
        stale_quote_ms = int(datetime(2026, 6, 18, 15, 30, tzinfo=fast.EASTERN).timestamp() * 1000)
        mtm = {
            "marksByTicketId": {
                entry["ticketId"]: {
                    "fetchStatus": "ok",
                    "perLeg": [
                        {
                            "instruction": "BUY_TO_OPEN",
                            "currentBid": 4.5,
                            "currentAsk": 4.7,
                            "quoteTimeInLong": stale_quote_ms,
                        }
                    ],
                }
            }
        }
        monday = datetime(2026, 6, 22, 15, 30, tzinfo=MOUNTAIN)
        updated, closed, pending = fast.close_due_entries(ledger, mtm, now=monday)
        self.assertEqual(closed, [])
        self.assertTrue(pending)
        self.assertEqual(updated["items"][0]["outcome"]["status"], "open")

    def test_due_ticket_closes_with_fresh_quote(self) -> None:
        entry = fast.build_fast_entry(candidate("A", "LONG_STRANGLE", 400), now=NOW)
        ledger = {"items": [entry]}
        fresh_quote_ms = int(datetime(2026, 6, 22, 15, 30, tzinfo=fast.EASTERN).timestamp() * 1000)
        mtm = {
            "marksByTicketId": {
                entry["ticketId"]: {
                    "fetchStatus": "ok",
                    "perLeg": [
                        {
                            "instruction": "BUY_TO_OPEN",
                            "currentBid": 4.5,
                            "currentAsk": 4.7,
                            "quoteTimeInLong": fresh_quote_ms,
                        }
                    ],
                }
            }
        }
        monday = datetime(2026, 6, 22, 15, 30, tzinfo=MOUNTAIN)
        updated, closed, pending = fast.close_due_entries(ledger, mtm, now=monday)
        self.assertEqual(closed, [entry["ticketId"]])
        self.assertEqual(pending, [])
        outcome = updated["items"][0]["outcome"]
        self.assertEqual(outcome["status"], "closed")
        self.assertEqual(outcome["estimatedPnl"], 50.0)


if __name__ == "__main__":
    unittest.main()
