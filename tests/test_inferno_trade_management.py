"""Contract tests for inferno_trade_management.

Pinned invariants:
  - Module is research-only, promotable=False, authorityChanged=False.
  - Strategy taxonomy: LONG_STRADDLE/STRANGLE/CALL/PUT -> lane-a;
    PUT_CREDIT/CALL_CREDIT/IRON_CONDOR -> lane-b-credit;
    CALL_DEBIT/PUT_DEBIT -> lane-b-debit; anything else -> unknown.
  - Lane A profit ladder triggers at exact thresholds:
      +0.50 of debit -> take-profit-1
      +1.00 of debit -> take-profit-2
      +2.00 of debit -> take-profit-3
      -0.50 of debit -> stop-loss
  - Lane A pre-event-exit fires when daysUntilEarnings <= 1.
  - Lane A hard time-stop fires at DTE <= 2 regardless.
  - Lane A flat-time-stop fires at DTE <= 3 only when |pct| <= 0.10.
  - Lane B credit close-at-50%-of-max fires at exactly +0.50 of max profit.
  - Lane B credit late-cycle trim (+0.25 of max) only fires when DTE <= 7.
  - Lane B credit stop fires when PnL <= -1.0 * credit_collected.
  - Lane B debit ladder: +0.50 max -> tp1; +0.80 max -> tp2.
  - Lane B debit stop fires when playbookPctOfDebit <= -0.50.
  - awaiting-data verdict fires when MTM data is absent but no time-rule
    triggers.
  - Module NEVER mutates the ledger.
"""

from __future__ import annotations

import copy
import unittest
from datetime import date, datetime, timezone

import inferno_trade_management as tm


TODAY = date(2026, 5, 27)
NOW = datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)


def _ticket(
    *,
    ticket_id: str = "t-1",
    ticker: str = "MOD",
    strategy: str = "CALL_DEBIT_SPREAD",
    expiration: str = "2026-06-18",
    days_until_earnings: int | None = 7,
    entry_limit: float = 3.50,
    estimated_max_loss: float = 350.0,
    estimated_max_profit=650.0,
    estimated_credit: float | None = None,
    outcome_status: str = "open",
) -> dict:
    return {
        "ticketId": ticket_id,
        "ticker": ticker,
        "strategy": strategy,
        "expiration": expiration,
        "daysUntilEarnings": days_until_earnings,
        "entryLimit": entry_limit,
        "estimatedMaxLoss": estimated_max_loss,
        "estimatedMaxProfit": estimated_max_profit,
        "strikePlan": {"estimatedCredit": estimated_credit} if estimated_credit else None,
        "outcome": {"status": outcome_status},
    }


def _mark(
    *,
    fetch_status: str = "ok",
    playbook_pct_of_debit: float | None = None,
    pnl_dollars: float | None = None,
    pct_of_max_profit: float | None = None,
) -> dict:
    return {
        "fetchStatus": fetch_status,
        "playbookPctOfDebit": playbook_pct_of_debit,
        "unrealizedPnlDollars": pnl_dollars,
        "unrealizedPnlPctOfMaxProfit": pct_of_max_profit,
    }


# ──────────────────────── taxonomy + helpers ──────────────────────────


class StrategyLaneTests(unittest.TestCase):
    def test_long_vol_maps_to_lane_a(self) -> None:
        for s in ("LONG_STRADDLE", "LONG_STRANGLE", "LONG_CALL", "LONG_PUT"):
            self.assertEqual(tm._strategy_lane(s), "lane-a")

    def test_credit_spreads_map_to_lane_b_credit(self) -> None:
        for s in ("PUT_CREDIT_SPREAD", "CALL_CREDIT_SPREAD", "IRON_CONDOR"):
            self.assertEqual(tm._strategy_lane(s), "lane-b-credit")

    def test_debit_spreads_map_to_lane_b_debit(self) -> None:
        for s in ("CALL_DEBIT_SPREAD", "PUT_DEBIT_SPREAD", "VERTICAL_DEBIT_SPREAD"):
            self.assertEqual(tm._strategy_lane(s), "lane-b-debit")

    def test_unknown_strategy_falls_back(self) -> None:
        self.assertEqual(tm._strategy_lane("RATIO_BACKSPREAD"), "unknown")
        self.assertEqual(tm._strategy_lane(None), "unknown")
        self.assertEqual(tm._strategy_lane(""), "unknown")


# ──────────────────────── Lane A verdict triggers ─────────────────────


class LaneATriggerTests(unittest.TestCase):
    def _assess_long_vol(self, *, pct, dte, dte_earn=7) -> str:
        ticket = _ticket(
            ticker="PL",
            strategy="LONG_STRANGLE",
            expiration=(TODAY.fromordinal(TODAY.toordinal() + dte)).isoformat(),
            days_until_earnings=dte_earn,
            entry_limit=5.0,
            estimated_max_loss=500.0,
            estimated_max_profit="uncapped",
        )
        mark = _mark(playbook_pct_of_debit=pct)
        return tm.assess_ticket(ticket, mark=mark, today=TODAY)["verdict"]

    def test_take_profit_1_at_50_pct(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=0.50, dte=20), "take-profit-1")

    def test_take_profit_2_at_100_pct(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=1.00, dte=20), "take-profit-2")

    def test_take_profit_3_at_200_pct_runner(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=2.00, dte=20), "take-profit-3")

    def test_stop_loss_at_minus_50_pct(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=-0.50, dte=20), "stop-loss")

    def test_just_under_take_profit_holds(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=0.49, dte=20), "hold")

    def test_just_above_stop_holds(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=-0.49, dte=20), "hold")

    def test_pre_event_exit_fires_at_earnings_eve(self) -> None:
        # Even a wining ticket exits before earnings by default.
        self.assertEqual(
            self._assess_long_vol(pct=0.10, dte=20, dte_earn=1), "pre-event-exit"
        )

    def test_hard_time_stop_fires_at_dte_2(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=0.40, dte=2), "time-stop")

    def test_flat_time_stop_fires_at_dte_3_with_flat_position(self) -> None:
        # |pct| <= 0.10 counts as flat
        self.assertEqual(self._assess_long_vol(pct=0.05, dte=3), "time-stop")

    def test_flat_time_stop_does_not_fire_when_position_not_flat(self) -> None:
        self.assertEqual(self._assess_long_vol(pct=0.30, dte=3), "hold")

    def test_awaiting_data_when_mark_missing(self) -> None:
        ticket = _ticket(strategy="LONG_STRANGLE", days_until_earnings=10)
        out = tm.assess_ticket(ticket, mark=None, today=TODAY)
        self.assertEqual(out["verdict"], "awaiting-data")


# ──────────────────────── Lane B credit verdict triggers ──────────────


class LaneBCreditTriggerTests(unittest.TestCase):
    def _assess(self, *, pct_max, dte, pnl_dollars=None, credit=1.10) -> str:
        ticket = _ticket(
            ticker="PL",
            strategy="PUT_CREDIT_SPREAD",
            expiration=(TODAY.fromordinal(TODAY.toordinal() + dte)).isoformat(),
            entry_limit=1.10,
            estimated_max_loss=90.0,
            estimated_max_profit=110.0,
            estimated_credit=credit,
        )
        mark = _mark(pct_of_max_profit=pct_max, pnl_dollars=pnl_dollars)
        return tm.assess_ticket(ticket, mark=mark, today=TODAY)["verdict"]

    def test_close_at_50_pct_of_max_profit(self) -> None:
        self.assertEqual(self._assess(pct_max=0.50, dte=20), "take-profit-1")

    def test_just_under_50_pct_holds(self) -> None:
        self.assertEqual(self._assess(pct_max=0.49, dte=20), "hold")

    def test_late_cycle_trim_at_25_pct_when_dte_under_7(self) -> None:
        self.assertEqual(self._assess(pct_max=0.30, dte=6), "take-profit-2")

    def test_late_cycle_trim_does_not_fire_outside_window(self) -> None:
        # 25% of max but more than 7 days out -> hold
        self.assertEqual(self._assess(pct_max=0.30, dte=10), "hold")

    def test_force_close_at_t_minus_3_profitable(self) -> None:
        self.assertEqual(self._assess(pct_max=0.10, dte=3), "take-profit-3")

    def test_force_close_at_t_minus_3_not_profitable(self) -> None:
        self.assertEqual(self._assess(pct_max=-0.10, dte=3), "time-stop")

    def test_stop_loss_at_minus_credit_collected(self) -> None:
        # credit = 1.10/share -> 110 credit_dollars; -1.0 * 110 = -110 trigger.
        self.assertEqual(
            self._assess(pct_max=-0.5, dte=20, pnl_dollars=-110.0, credit=1.10),
            "stop-loss",
        )

    def test_just_above_stop_holds(self) -> None:
        self.assertEqual(
            self._assess(pct_max=-0.4, dte=20, pnl_dollars=-100.0, credit=1.10),
            "hold",
        )

    def test_awaiting_data_when_price_fields_none(self) -> None:
        ticket = _ticket(
            strategy="PUT_CREDIT_SPREAD",
            expiration=(TODAY.fromordinal(TODAY.toordinal() + 20)).isoformat(),
            estimated_credit=1.10,
        )
        mark = _mark()  # all None
        out = tm.assess_ticket(ticket, mark=mark, today=TODAY)
        self.assertEqual(out["verdict"], "awaiting-data")


# ──────────────────────── Lane B debit verdict triggers ───────────────


class LaneBDebitTriggerTests(unittest.TestCase):
    def _assess(self, *, pct_max=None, pct_debit=None, dte=20) -> str:
        ticket = _ticket(
            strategy="CALL_DEBIT_SPREAD",
            expiration=(TODAY.fromordinal(TODAY.toordinal() + dte)).isoformat(),
            entry_limit=3.50,
            estimated_max_loss=350.0,
            estimated_max_profit=650.0,
        )
        mark = _mark(playbook_pct_of_debit=pct_debit, pct_of_max_profit=pct_max)
        return tm.assess_ticket(ticket, mark=mark, today=TODAY)["verdict"]

    def test_trim_half_at_50_pct_of_max(self) -> None:
        self.assertEqual(self._assess(pct_max=0.50, dte=20), "take-profit-1")

    def test_close_at_80_pct_of_max(self) -> None:
        self.assertEqual(self._assess(pct_max=0.80, dte=20), "take-profit-2")

    def test_stop_loss_at_minus_50_pct_of_debit(self) -> None:
        self.assertEqual(
            self._assess(pct_max=0.0, pct_debit=-0.50, dte=20), "stop-loss"
        )

    def test_hard_time_stop_at_dte_2(self) -> None:
        self.assertEqual(self._assess(pct_max=0.10, dte=2), "time-stop")

    def test_awaiting_data_when_price_fields_none(self) -> None:
        self.assertEqual(self._assess(pct_max=None, pct_debit=None, dte=20), "awaiting-data")


# ──────────────────────── build + render + invariants ─────────────────


class BuildTests(unittest.TestCase):
    def test_research_only_invariants(self) -> None:
        payload = tm.build_trade_management(
            now=NOW, ledger_override={"items": []}, mtm_override={"marksByTicketId": {}}
        )
        self.assertEqual(payload["stage"], tm.TRADE_MANAGEMENT_STAGE)
        self.assertTrue(payload["researchOnly"])
        self.assertFalse(payload["promotable"])
        self.assertFalse(payload["authorityChanged"])
        self.assertEqual(payload["openPositionCount"], 0)
        self.assertEqual(payload["verdict"], "no-open-positions")

    def test_does_not_mutate_ledger(self) -> None:
        ledger = {"items": [_ticket()]}
        ledger_snapshot = copy.deepcopy(ledger)
        tm.build_trade_management(
            now=NOW,
            ledger_override=ledger,
            mtm_override={"marksByTicketId": {}},
        )
        self.assertEqual(ledger, ledger_snapshot)

    def test_verdict_counts_aggregate(self) -> None:
        # Build two open tickets: one with mark (data), one without (awaiting).
        t1 = _ticket(ticket_id="t1", strategy="CALL_DEBIT_SPREAD")
        t2 = _ticket(ticket_id="t2", strategy="LONG_STRANGLE", days_until_earnings=10)
        ledger = {"items": [t1, t2]}
        marks = {
            "t1": _mark(pct_of_max_profit=0.60),  # take-profit-1
        }
        payload = tm.build_trade_management(
            now=NOW,
            ledger_override=ledger,
            mtm_override={"marksByTicketId": marks},
        )
        self.assertEqual(payload["openPositionCount"], 2)
        self.assertEqual(payload["verdictCounts"]["take-profit-1"], 1)
        self.assertEqual(payload["verdictCounts"]["awaiting-data"], 1)
        # actionable excludes hold + awaiting-data
        self.assertEqual(payload["actionableCount"], 1)
        self.assertEqual(payload["verdict"], "actions-recommended")

    def test_overall_verdict_awaiting_data_when_no_price_data(self) -> None:
        ledger = {"items": [_ticket(ticket_id="t1", strategy="CALL_DEBIT_SPREAD")]}
        payload = tm.build_trade_management(
            now=NOW,
            ledger_override=ledger,
            mtm_override={"marksByTicketId": {}},
        )
        self.assertEqual(payload["actionableCount"], 0)
        self.assertEqual(payload["verdictCounts"]["awaiting-data"], 1)
        self.assertEqual(payload["verdict"], "awaiting-data")

    def test_text_renderer_includes_required_sections(self) -> None:
        t1 = _ticket(ticket_id="t1")
        ledger = {"items": [t1]}
        payload = tm.build_trade_management(
            now=NOW,
            ledger_override=ledger,
            mtm_override={"marksByTicketId": {"t1": _mark(pct_of_max_profit=0.60)}},
        )
        text = tm.trade_management_text(payload)
        for required in (
            "Inferno Trade Management",
            "Generated:",
            "Overall verdict:",
            "Open positions:",
            "Per-position recommendations:",
            "Reminders:",
        ):
            self.assertIn(required, text)

    def test_skips_non_open_tickets(self) -> None:
        ledger = {
            "items": [
                _ticket(ticket_id="t1", outcome_status="open"),
                _ticket(ticket_id="t2", outcome_status="closed"),
                _ticket(ticket_id="t3", outcome_status="not-opened"),
            ]
        }
        payload = tm.build_trade_management(
            now=NOW,
            ledger_override=ledger,
            mtm_override={"marksByTicketId": {}},
        )
        self.assertEqual(payload["openPositionCount"], 1)


if __name__ == "__main__":
    unittest.main()
